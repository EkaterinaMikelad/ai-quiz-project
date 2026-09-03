import os
import json
from typing import List, Literal
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey, select

DATABASE_URL = "sqlite+aiosqlite:///quiz.db"
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class QuizModel(Base):
    __tablename__ = "quizzes"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    shuffle_questions = Column(Boolean, default=True)
    shuffle_answers = Column(Boolean, default=True)
    questions = relationship("QuestionModel", back_populates="quiz", cascade="all, delete-orphan", lazy="selectin")

class QuestionModel(Base):
    __tablename__ = "questions"
    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id", ondelete="CASCADE"))
    question_text = Column(Text, nullable=False)
    question_type = Column(String(50), default="single")
    time_limit = Column(Integer, default=30)
    quiz = relationship("QuizModel", back_populates="questions")
    answers = relationship("AnswerModel", back_populates="question", cascade="all, delete-orphan", lazy="selectin")

class AnswerModel(Base):
    __tablename__ = "answers"
    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"))
    answer_text = Column(Text, nullable=False)
    is_correct = Column(Boolean, default=False)
    question = relationship("QuestionModel", back_populates="answers")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

# Официальный базовый URL для интеграции с DeepSeek API
ai_client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY", "sk-862f7ab763da4e30b734838515604500"),
    base_url="https://api.deepseek.com/v1"
)

class AIAnswer(BaseModel):
    answer_text: str
    is_correct: bool

class AIQuestion(BaseModel):
    question_text: str
    question_type: Literal["single", "multiple"]
    time_limit: int = 30
    answers: List[AIAnswer]

class AIGeneratedQuiz(BaseModel):
    title: str
    description: str
    questions: List[AIQuestion]

app = FastAPI(title="Joyteka Clone: DeepSeek Integrated Engine")

@app.on_event("startup")
async def startup_event():
    await init_db()

class QuizGenerationRequest(BaseModel):
    prompt: str = Field(..., example="География России для 6 класса")
    num_questions: int = Field(default=5, ge=1, le=15)

@app.post("/quiz/generate")
async def generate_and_save_quiz(payload: QuizGenerationRequest, db: AsyncSession = Depends(get_db)):
    try:
        system_instruction = (
            "Ты — профессиональный методист образовательных квизов. "
            "Сгенерируй квиз и верни ТОЛЬКО чистый JSON-объект, строго соответствующий следующей схеме: "
            f"{json.dumps(AIGeneratedQuiz.model_json_schema(), ensure_ascii=False)}. "
            "Не пиши никаких вступлений, пояснений или markdown-разметки типа ```json."
        )
        
        response = await ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"Тема квиза: {payload.prompt}. Количество вопросов: {payload.num_questions}"}
            ],
            temperature=0.7
        )
        
        raw_json = response.choices.message.content.strip()
        quiz_data = AIGeneratedQuiz.model_validate_json(raw_json)
        
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка генерации нейросетью: {str(e)}")

    try:
        new_quiz = QuizModel(
            title=quiz_data.title,
            description=quiz_data.description,
            shuffle_questions=True,
            shuffle_answers=True
        )
        db.add(new_quiz)
        await db.flush()
        
        formatted_questions = []
        for q in quiz_data.questions:
            new_question = QuestionModel(
                quiz_id=new_quiz.id,
                question_text=q.question_text,
                question_type=q.question_type,
                time_limit=q.time_limit
            )
            db.add(new_question)
            await db.flush()
            
            formatted_answers = []
            for a in q.answers:
                new_answer = AnswerModel(
                    question_id=new_question.id,
                    answer_text=a.answer_text,
                    is_correct=a.is_correct
                )
                db.add(new_answer)
                formatted_answers.append({
                    "answer_text": a.answer_text,
                    "is_correct": a.is_correct
                })
                
            formatted_questions.append({
                "question_text": q.question_text,
                "answers": formatted_answers
            })
                
        await db.commit()
        
        return {
            "status": "success",
            "quiz_id": new_quiz.id,
            "title": new_quiz.title,
            "questions": formatted_questions
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения в БД: {str(e)}")

@app.get("/quiz/{quiz_id}")
async def get_quiz(quiz_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(QuizModel).where(QuizModel.id == quiz_id))
    quiz = result.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Квиз не найден")
    
    return {
        "title": quiz.title,
        "description": quiz.description,
        "questions": [
            {
                "question_text": q.question_text,
                "answers": [
                    {"answer_text": a.answer_text, "is_correct": a.is_correct}
                    for a in q.answers
                ]
            }
            for q in quiz.questions
        ]
    }
