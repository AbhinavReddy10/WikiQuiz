from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict
from bs4 import BeautifulSoup
import requests
from sqlalchemy import create_engine, Column, Integer, String, Text, JSON, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import json
import os

import requests
from bs4 import BeautifulSoup

def scrape_wikipedia(url: str):
    """
    Scrapes the given Wikipedia URL and returns the title and content (first 8000 chars)
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/118.0.5993.118 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Get title
        title = soup.find("h1").text

        # Get main content text
        paragraphs = soup.select("div.mw-parser-output > p")
        content = "\n".join([p.get_text() for p in paragraphs])

        return title, content[:8000]
    except Exception as e:
        raise Exception(f"Error scraping Wikipedia: {str(e)}")



# ----------- CONFIGURATION -----------
DB_URL = os.getenv("DATABASE_URL", "sqlite:///./quiz.db")  # Change to Postgres/MySQL if needed
engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if "sqlite" in DB_URL else {})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

# ----------- DATABASE MODEL -----------
class Quiz(Base):
    __tablename__ = "quizzes"
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, index=True)
    title = Column(String)
    content_excerpt = Column(Text)
    quiz_data = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

# ----------- FASTAPI INITIALIZATION -----------
app = FastAPI(title="Wikipedia Quiz Generator API")

# Enable CORS (so the frontend can call the backend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local testing — use specific domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------- SCHEMAS -----------
class Question(BaseModel):
    question: str
    options: Dict[str, str]
    correct_answer: str
    explanation: str
    difficulty: str

class QuizCreate(BaseModel):
    url: str

class QuizResponse(BaseModel):
    id: int
    url: str
    title: str
    quiz_data: List[Question]
    related_topics: List[str]

# ----------- HELPER FUNCTIONS -----------

def generate_quiz_with_gemini(title: str, content: str):
    # Fallback quiz generator (no Gemini API required)
    quiz_data = [
        {
            "question": f"What is {title} best known for?",
            "options": {"A": "Science", "B": "Music", "C": "Politics", "D": "Art"},
            "correct_answer": "A",
            "explanation": f"{title} is primarily known for contributions in science.",
            "difficulty": "easy"
        },
        {
            "question": f"Which field did {title} contribute to?",
            "options": {"A": "Mathematics", "B": "Cooking", "C": "Fashion", "D": "Sports"},
            "correct_answer": "A",
            "explanation": f"{title} made major contributions in mathematics and computing.",
            "difficulty": "medium"
        }
    ]
    related_topics = ["Computer science", "Cryptography", "Artificial intelligence"]
    return quiz_data, related_topics


# ----------- API ENDPOINTS -----------

@app.post("/generate", response_model=QuizResponse)
def generate_quiz(data: QuizCreate):
    db = SessionLocal()
    try:
        # Step 1: Scrape Wikipedia
        title, content = scrape_wikipedia(data.url)

        # Step 2: Generate Quiz using LLM (Gemini or fallback)
        quiz_data, related_topics = generate_quiz_with_gemini(title, content)

        # Step 3: Save to DB
        quiz_entry = Quiz(
            url=data.url,
            title=title,
            content_excerpt=content[:400],
            quiz_data={"questions": quiz_data, "related_topics": related_topics}
        )
        db.add(quiz_entry)
        db.commit()
        db.refresh(quiz_entry)

        return {
            "id": quiz_entry.id,
            "url": quiz_entry.url,
            "title": quiz_entry.title,
            "quiz_data": quiz_data,
            "related_topics": related_topics
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.get("/quizzes")
def list_quizzes():
    """Return list of all previously generated quizzes."""
    db = SessionLocal()
    quizzes = db.query(Quiz).order_by(Quiz.created_at.desc()).all()
    db.close()
    return [
        {"id": q.id, "title": q.title, "url": q.url, "created_at": q.created_at}
        for q in quizzes
    ]

@app.get("/quizzes/{quiz_id}", response_model=QuizResponse)
def get_quiz(quiz_id: int):
    """Return full quiz details by ID."""
    db = SessionLocal()
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    db.close()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    quiz_data = quiz.quiz_data.get("questions", [])
    related_topics = quiz.quiz_data.get("related_topics", [])
    return {
        "id": quiz.id,
        "url": quiz.url,
        "title": quiz.title,
        "quiz_data": quiz_data,
        "related_topics": related_topics
    }

# ----------- RUN SERVER -----------
# Run: uvicorn main:app --reload
