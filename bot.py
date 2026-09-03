import os
import asyncio
import aiohttp
import json
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import CommandStart

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8746007140:AAHLkwSt0ltOm7ddVTbKENSXqGcBERoYsvU")
API_URL = os.getenv("API_URL", "http://localhost:8000")

bot = Bot(token=TOKEN)
dp = Dispatcher()

class QuizStates(StatesGroup):
    waiting_for_topic = State()
    playing = State()

def get_answers_keyboard(questions: list, question_idx: int) -> InlineKeyboardMarkup:
    question = questions[question_idx]
    buttons = []
    for ans_idx, ans in enumerate(question["answers"]):
        callback_data = f"quiz_{question_idx}_{ans_idx}"
        buttons.append([InlineKeyboardButton(text=ans["answer_text"], callback_data=callback_data)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Привет, {message.from_user.full_name}! 🚀\n"
        f"Добро пожаловать в ИИ-конструктор интерактивных квизов.\n\n"
        f"Напишите мне **тему**, на которую вы хотите сгенерировать уникальный тест (например: *География России 6 класс* или *История космонавтики*):"
    )
    await state.set_state(QuizStates.waiting_for_topic)

@dp.message(QuizStates.waiting_for_topic)
async def generate_quiz_request(message: Message, state: FSMContext):
    topic = message.text
    waiting_msg = await message.answer("⏳ *DeepSeek генерирует ваш квиз...* Это займет около 10-15 секунд.", parse_mode="Markdown")
    
    async with aiohttp.ClientSession() as session:
        try:
            payload = {"prompt": topic, "num_questions": 5}
            async with session.post(f"{API_URL}/quiz/generate", json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    questions = data["questions"]
                    
                    await state.update_data(questions=questions, current_question=0, score=0)
                    await waiting_msg.delete()
                    
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🎮 Начать игру", callback_data="start_generated_quiz")]
                    ])
                    await message.answer(f"✅ Квиз по теме «{data['title']}» успешно создан!", reply_markup=keyboard)
                    await state.set_state(QuizStates.playing)
                else:
                    await waiting_msg.edit_text(f"❌ Ошибка сервера бэкенда: статус {response.status}")
        except Exception as e:
            await waiting_msg.edit_text(f"❌ Не удалось связаться с бэкендом: {str(e)}")

@dp.callback_query(QuizStates.playing, F.data == "start_generated_quiz")
async def start_quiz_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_data = await state.get_data()
    questions = user_data["questions"]
    
    question = questions[0]
    await callback.message.answer(
        text=f"❓ **Вопрос 1 из {len(questions)}**:\n\n{question['question_text']}",
        reply_markup=get_answers_keyboard(questions, 0),
        parse_mode="Markdown"
    )
    await callback.message.delete()

@dp.callback_query(QuizStates.playing, F.data.startswith("quiz_"))
async def handle_answer(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    _, q_idx_str, ans_idx_str = callback.data.split("_")
    q_idx = int(q_idx_str)
    ans_idx = int(ans_idx_str)
    
    user_data = await state.get_data()
    questions = user_data["questions"]
    current_score = user_data.get("score", 0)
    
    question = questions[q_idx]
    selected_answer = question["answers"][ans_idx]
    
    if selected_answer["is_correct"]:
        current_score += 1
        await callback.message.answer("🎯 **Правильно!**", parse_mode="Markdown")
    else:
        correct_ans = next(a for a in question["answers"] if a["is_correct"])
        await callback.message.answer(
            f"❌ **Неверно.**\nПравильный ответ: *{correct_ans['answer_text']}*", 
            parse_mode="Markdown"
        )
        
    next_q_idx = q_idx + 1
    
    if next_q_idx < len(questions):
        await state.update_data(current_question=next_q_idx, score=current_score)
        next_question = questions[next_q_idx]
        await callback.message.answer(
            text=f"❓ **Вопрос {next_q_idx + 1} из {len(questions)}**:\n\n{next_question['question_text']}",
            reply_markup=get_answers_keyboard(questions, next_q_idx),
            parse_mode="Markdown"
        )
    else:
        await callback.message.answer(
            text=f"🏆 **Квиз завершен!**\n\nВаш результат: *{current_score}* из *{len(questions)}* правильных ответов.",
            parse_mode="Markdown"
        )
        await state.clear()
        
    await callback.message.delete()

async def main():
    print("Бот успешно запущен и готов к работе...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
