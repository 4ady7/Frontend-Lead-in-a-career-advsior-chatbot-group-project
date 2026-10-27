"""FastAPI bridge for the CareerPath frontend."""

# imports 
from pydantic import BaseModel
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from career_backend import (
    chat_with_bot,
    grade_interview_answer,
    start_interview_practice,
    log_user_feedback,
)

# Create the FastAPI application instance
app = FastAPI(title="CareerPath Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # fine for local prototype; restrict this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request model for the chat endpoint
class ChatRequest(BaseModel):
    user_text: str
    thread_id: str = "student-001"
    degree: str | None = None
    interests: str | None = None


class ChatResponse(BaseModel):
    answer: str

# Request model used when starting interview practice
class InterviewStartRequest(BaseModel):
    thread_id: str = "student-001"
    degree: str | None = None
    interests: str | None = None
    target_role: str | None = None
    participant_id: str | None = None

# Response model returned after starting interview practice
class InterviewStartResponse(BaseModel):
    message: str
    question: str
    question_index: int
    total_questions: int
    complete: bool

# Request model used when the user submits an interview answer
class InterviewAnswerRequest(BaseModel):
    thread_id: str = "student-001"
    question_index: int
    question: str
    user_answer: str
    degree: str | None = None
    interests: str | None = None
    target_role: str | None = None
    participant_id: str | None = None

# Response model returned after grading an interview answer
class InterviewAnswerResponse(BaseModel):
    message: str
    score: int
    strengths: str
    improvements: str
    model_answer: str
    feedback: str
    question: str
    question_index: int
    total_questions: int
    complete: bool

# Request model for saving user feedback about the system
class FeedbackRequest(BaseModel):
    thread_id: str = "student-001"
    helpfulness: int
    clarity: int
    relevance: int
    trust: int
    comment: str | None = ""
    participant_id: str | None = None
    task_label: str | None = None

# Response model confirming whether feedback was saved
class FeedbackResponse(BaseModel):
    status: str

#health check route to confirm the backend is running
@app.get("/")
def health_check():
    return {"status": "ok", "message": "CareerPath backend is running"}

# Chat route used by the frontend to send a user message to the bot
@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    profile_context = ""
    if request.degree or request.interests:
        profile_context = (
            f"Student profile: degree={request.degree or 'not provided'}, "
            f"interests={request.interests or 'not provided'}. "
        )

    answer = chat_with_bot(
        profile_context + request.user_text,
        thread_id=request.thread_id,
    )
    return ChatResponse(answer=answer)

# Route for starting a new interview-practice session
@app.post("/interview/start", response_model=InterviewStartResponse)
def interview_start(request: InterviewStartRequest):
    return start_interview_practice(
        thread_id=request.thread_id,
        degree=request.degree or "",
        interests=request.interests or "",
        target_role=request.target_role or "",
    )

# Route for submitting and grading an interview answer
@app.post("/interview/answer", response_model=InterviewAnswerResponse)
def interview_answer(request: InterviewAnswerRequest):
    return grade_interview_answer(
        thread_id=request.thread_id,
        participant_id=request.participant_id,
        question_index=request.question_index,
        question=request.question,
        user_answer=request.user_answer,
        degree=request.degree or "",
        interests=request.interests or "",
        target_role=request.target_role or "",
    )

# Route for collecting user feedback about the chatbot or interview tool
@app.post("/feedback", response_model=FeedbackResponse)
def feedback(request: FeedbackRequest):
    log_user_feedback(
        thread_id=request.thread_id,
        helpfulness=request.helpfulness,
        clarity=request.clarity,
        relevance=request.relevance,
        trust=request.trust,
        comment=request.comment or "",
        participant_id=request.participant_id,
        task_label=request.task_label,
    )

    return FeedbackResponse(status="saved")

