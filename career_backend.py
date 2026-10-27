# imports
from __future__ import annotations

import csv
import hashlib
import json
import operator
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph


# Path and Environment

# Base directory configuration for resolving relative paths safely
base_dir = Path(__file__).resolve().parent
pdf_path = base_dir / "samples.pdf"
chroma_dir = base_dir / "chroma_db"

# CSV files for recording anonymous user sessions and feedback during evaluations 
log_path = base_dir / "anonymous_interaction_log.csv"
interview_log_path = base_dir / "anonymous_interview_practice_log.csv"
feedback_log_path = base_dir / "anonymous_feedback_log.csv"
evaluation_summary_path = base_dir / "evaluation_summary.json"

# LLM Configuration (fallback to gpt4o-mini and text-embedding-3-small)
chat_model = os.getenv("career_chat_model", "gpt-4o-mini")
embedding_model = os.getenv("career_embedding_model", "text-embedding-3-small")

# Estimated model cost in pounds per 1 million tokens.
# Change this value if your model price changes.
ESTIMATED_COST_PER_1M_TOKENS_GBP = float(
    os.getenv("career_estimated_cost_per_1m_tokens_gbp", "0.47")
)


def require_openai_key() -> None:
    """Stop early with a helpful error if the API key is missing."""
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Set it before running, for example: "
            "export OPENAI_API_KEY='your-key-here'"
        )

# Enforce API key presence before initializing LangChain objects
require_openai_key()

# Core LLM Instances
llm = ChatOpenAI(model=chat_model, temperature=0.2, max_tokens=200)
interview_llm = ChatOpenAI(model=chat_model, temperature=0.2, max_tokens=260)
embeddings = OpenAIEmbeddings(model=embedding_model)


# RAG Retriever Initialisation
def ensure_directory_writable(path: Path) -> None:
    """
    Chroma has to update its local database on startup.
    Directories copied from another machine can arrive without write permission,
    which makes that startup fail before the API can serve any request.
    """
    if not path.exists():
        return

    targets = [path, *path.rglob("*")]
    for target in targets:
        if os.access(target, os.W_OK):
            continue
        target.chmod(target.stat().st_mode | 0o700)


def build_or_load_retriever():
    """
    Builds a persistent ChromaDB retriever from samples.pdf.
    If the database already exists, it loads it instead of re-embedding the PDF.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"Could not find {pdf_path}. Keep samples.pdf beside this file.")

    ensure_directory_writable(chroma_dir)

    if chroma_dir.exists() and any(chroma_dir.iterdir()):
        #Load existing local vectorstore
        vectorstore = Chroma(
            persist_directory=str(chroma_dir),
            embedding_function=embeddings,
            collection_name="career_advisor_docs",
        )
    else:
        # Process and chunk the source PDF file
        loader = PyPDFLoader(str(pdf_path))
        raw_documents = loader.load()

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=700,
            chunk_overlap=120,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        documents = splitter.split_documents(raw_documents)

        # Store chunk embeddings persistently
        vectorstore = Chroma.from_documents(
            documents=documents,
            embedding=embeddings,
            persist_directory=str(chroma_dir),
            collection_name="career_advisor_docs",
        )

    # Returns top 2 most mathematically similar text chunks
    return vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 2},
    )


retriever = build_or_load_retriever()


# LangGraph Core Workflow Definitions
class CareerChatState(TypedDict, total=False):
    """Shared state passed between LangGraph nodes."""

    messages: Annotated[list, operator.add]
    current_question: str
    rewritten_question: str
    context: List[Document]
    retrieval_grade: str
    answer: str
    retry_count: int
    used_rewritten_query: bool
    retrieved_sources: List[str]

# Guardrails, tone expectations, data schemes, and edge-cases instructions for CareerPath (Prompt Engineering)
SYSTEM_PROMPT = """
You are CareerPath, a career advisor chatbot prototype for University of Northampton students.

Rules:
- Answer using the supplied UON/student careers context whenever possible.
- If no relevant UON/student careers context is supplied, give general careers guidance and clearly avoid presenting it as official University of Northampton policy.
- Answer in two or three sentences, unless the question explicitly asks for more detail.
- Be supportive, direct, practical, and student-friendly.
- Use inclusive, respectful, and non-judgemental language.
- Do not make assumptions about a student’s gender, age, nationality, disability, ethnicity, religion, financial background, caring responsibilities, work experience, or visa status.
- Give guidance that supports different student circumstances, including home students, international students, disabled students, mature students, commuting students, students with caring responsibilities, and students from different socio-economic backgrounds.
- Where relevant, mention accessible alternatives such as flexible work, remote options, part-time opportunities, university support services, reasonable adjustments, and official careers support.
- Avoid stereotypes about degrees, industries, cultures, genders, or types of work.
- Be transparent about uncertainty and avoid overconfident advice when the evidence is weak. If confidence is low, say so clearly.
- Do not invent University of Northampton services, policies, web links, deadlines, eligibility rules, contact details, or procedures. If the supplied context does not confirm something, say that the student should check the official University of Northampton source, Student Futures, or the appropriate university service.
- Do not request unnecessary personal or sensitive information.
- Do not ask a follow-up question by default.
- First give the best useful answer possible using the information already provided.
- Only ask one short follow-up question if the answer would be unsafe, impossible, or highly inaccurate without more detail.
- When details are missing, make a reasonable assumption, state it briefly, and give general guidance.
- End responses with an optional prompt where useful, such as "You can tell me your course or target role if you'd like more tailored advice." Do not end every response with a question.
- Always finish the final sentence completely. Do not stop mid-sentence, mid-word, or after an unfinished phrase.
- If the answer is getting too long, shorten it earlier so the response still ends with a complete sentence.
- Do not pretend to be a qualified careers advisor.
- For important career, visa, legal, medical, financial, wellbeing, or personal decisions, advise the student to check with an appropriate human professional or official university service.
- Do not mention Student Futures in every answer.
- Only suggest contacting Student Futures when:
  1. the question is outside the chatbot’s knowledge or retrieved context,
  2. the chatbot cannot give a confident answer,
  3. the user asks for official university support,
  4. the issue involves important career, visa, legal, medical, financial, wellbeing, or personal circumstances,
  5. the user needs human review, personalised professional judgement, or official confirmation.
- For normal career questions such as CV tips, interview preparation, job search advice, career ideas, skills development, or placement guidance, answer directly first without referring the student to Student Futures.
- If a hand-off is needed, briefly explain why and say that Student Futures or an appropriate university service can provide official support.
- If a student describes serious distress, harm, discrimination, harassment, or a safeguarding concern: respond with care and warmth, avoid treating it as a careers question, and signpost them to university wellbeing, safeguarding, or emergency support services.
- Keep answers clear and structured.
""".strip()

def latest_human_message(messages: list) -> str:
    """Returns the latest user message from LangGraph's message list."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message.content
        if isinstance(message, dict) and message.get("role") in {"user", "human"}:
            return message.get("content", "")
    return ""


def extract_question(state: CareerChatState) -> dict:
    question = latest_human_message(state.get("messages", []))
    return {
        "current_question": question,
        "rewritten_question": "",
        "retry_count": state.get("retry_count", 0),
    }


def get_document_sources(docs: Optional[List[Document]]) -> List[str]:
    """Return compact source labels for retrieved documents without storing full text."""
    sources: List[str] = []
    for doc in docs or []:
        source = Path(str(doc.metadata.get("source", "samples.pdf"))).name
        page = doc.metadata.get("page")
        page_text = f":p{page + 1}" if isinstance(page, int) else ""
        sources.append(f"{source}{page_text}")
    return sources


def retrieve_documents(state: CareerChatState) -> dict:
    query = state.get("rewritten_question") or state.get("current_question", "")
    docs = retriever.invoke(query)
    return {
        "context": docs,
        "used_rewritten_query": bool(state.get("rewritten_question")),
        "retrieved_sources": get_document_sources(docs),
    }


def format_docs(docs: Optional[List[Document]]) -> str:
    if not docs:
        return "No relevant UON career context was retrieved."

    formatted = []
    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source", "samples.pdf")
        page = doc.metadata.get("page")
        page_text = f", page {page + 1}" if isinstance(page, int) else ""
        formatted.append(f"[Source {i}: {source}{page_text}]\n{doc.page_content}")
    return "\n\n".join(formatted)


def grade_documents(state: CareerChatState) -> dict:
    """
    Grades whether the retrieved documents are good enough.
    This prevents the bot from confidently answering from weak context.
    """
    question = state.get("current_question", "")
    context = format_docs(state.get("context", []))

    prompt = f"""
Decide whether the context is relevant to the student's question.

Student question: {question}

Retrieved context:
{context}

Reply with only one word: good or poor.
""".strip()

    result = llm.invoke([HumanMessage(content=prompt)]).content.strip().lower()
    grade = "good" if "good" in result else "poor"
    return {"retrieval_grade": grade}


def rewrite_query(state: CareerChatState) -> dict:
    """Rewrites vague questions so retrieval has a second chance."""
    question = state.get("current_question", "")
    history = state.get("messages", [])[-6:]

    prompt = f"""
Rewrite this student career question for searching UON careers support documents.
Keep it short and specific.

Conversation history: {history}
Original question: {question}

Rewritten search query:
""".strip()

    rewritten = llm.invoke([HumanMessage(content=prompt)]).content.strip()
    return {
        "rewritten_question": rewritten,
        "retry_count": state.get("retry_count", 0) + 1,
    }


def route_after_grading(state: CareerChatState) -> str:
    """Conditional edge: generate if context is good; otherwise rewrite and retry once."""
    if state.get("retrieval_grade") == "good":
        return "generate"
    if state.get("retry_count", 0) >= 1:
        return "generate"
    return "rewrite"


def generate_response(state: CareerChatState) -> dict:
    question = state.get("current_question", "")
    context = format_docs(state.get("context", []))
    retrieval_grade = state.get("retrieval_grade", "unknown")

    user_prompt = f"""
Retrieved context quality: {retrieval_grade}

Context:
{context}

Student question:
{question}

Write the final answer for the student.
""".strip()

    # Keep only recent conversation turns to reduce token cost while preserving memory.
    recent_messages = state.get("messages", [])[-8:]
    messages = [SystemMessage(content=SYSTEM_PROMPT), *recent_messages, HumanMessage(content=user_prompt)]

    response = llm.invoke(messages)
    answer = response.content

    return {
        "answer": answer,
        "messages": [AIMessage(content=answer)],
    }


# LangGraph State Machine Compilation
builder = StateGraph(CareerChatState)

# Append funcional needs to make the framework structure
builder.add_node("extract_question", extract_question)
builder.add_node("retrieve_documents", retrieve_documents)
builder.add_node("grade_documents", grade_documents)
builder.add_node("rewrite_query", rewrite_query)
builder.add_node("generate_response", generate_response)

# Map directional graph flow
builder.add_edge(START, "extract_question")
builder.add_edge("extract_question", "retrieve_documents")
builder.add_edge("retrieve_documents", "grade_documents")
builder.add_conditional_edges(
    "grade_documents",
    route_after_grading,
    {"generate": "generate_response", "rewrite": "rewrite_query"},
)
builder.add_edge("rewrite_query", "retrieve_documents")
builder.add_edge("generate_response", END)

# Configure thread checkpointers for state persistence across sessions
memory = MemorySaver()
career_graph = builder.compile(checkpointer=memory)


# Metrics and Evaluation Logging Utilities
def anonymise_thread_id(thread_id: str) -> str:
    """
    Store a stable anonymous thread identifier instead of the raw thread ID.
    This keeps evaluation rows linkable without storing names, emails, or student IDs.
    """
    salt = os.getenv("career_log_salt", "careerpath-local-evaluation")
    return hashlib.sha256(f"{salt}:{thread_id}".encode("utf-8")).hexdigest()[:16]


def estimate_word_count(text: str) -> int:
    """Small helper for rough response length analysis without token dependencies."""
    return len((text or "").split())

def estimate_token_count(text: str) -> int:
    """
    Roughly estimate token usage from text.

    This is not exact, but it gives a useful evaluation estimate.
    A common approximation is 1 word ≈ 1.3 tokens.
    """
    return max(1, int(estimate_word_count(text) * 1.3))

def estimate_cost_gbp(estimated_tokens: int) -> float:
    """
    Estimate API cost from estimated token usage in pounds.

    Formula:
    estimated cost = estimated tokens / 1,000,000 * cost per 1M tokens in GBP
    """
    return round((estimated_tokens / 1_000_000) * ESTIMATED_COST_PER_1M_TOKENS_GBP, 6)


def log_interaction(
    *,
    thread_id: str,
    user_text: str,
    result: Dict[str, Any],
    latency_ms: int,
    participant_id: Optional[str] = None,
    task_label: Optional[str] = None,
) -> None:
    """
    Anonymous granular logging for evaluation.

    No names, emails, student IDs, or raw thread IDs are stored. The log captures
    enough data to evaluate retrieval quality, retry behaviour, and response quality.
    """
    answer = result.get("answer", "")
    context_docs = result.get("context", []) or []
    file_exists = log_path.exists()

    estimated_user_tokens = estimate_token_count(user_text)
    estimated_answer_tokens = estimate_token_count(answer)
    estimated_total_tokens = estimated_user_tokens + estimated_answer_tokens
    estimated_cost_gbp = estimate_cost_gbp(estimated_total_tokens)

    fieldnames = [
        "timestamp_utc",
        "anonymous_thread_id",
        "participant_id",
        "task_label",
        "chat_model",
        "embedding_model",
        "user_text",
        "answer",
        "retrieval_grade",
        "retry_count",
        "used_rewritten_query",
        "rewritten_question",
        "retrieved_sources",
        "retrieved_doc_count",
        "answer_word_count",
        "estimated_user_tokens",
        "estimated_answer_tokens",
        "estimated_total_tokens",
        "estimated_cost_gbp",
        "latency_ms",
    ]

    with log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds"),
                "anonymous_thread_id": anonymise_thread_id(thread_id),
                "participant_id": participant_id or "",
                "task_label": task_label or "",
                "chat_model": chat_model,
                "embedding_model": embedding_model,
                "user_text": user_text,
                "answer": answer,
                "retrieval_grade": result.get("retrieval_grade", "unknown"),
                "retry_count": result.get("retry_count", 0),
                "used_rewritten_query": result.get("used_rewritten_query", False),
                "rewritten_question": result.get("rewritten_question", ""),
                "retrieved_sources": " | ".join(result.get("retrieved_sources", [])),
                "retrieved_doc_count": len(context_docs),
                "answer_word_count": estimate_word_count(answer),
                "estimated_user_tokens": estimated_user_tokens,
                "estimated_answer_tokens": estimated_answer_tokens,
                "estimated_total_tokens": estimated_total_tokens,
                "estimated_cost_gbp": estimated_cost_gbp,
                "latency_ms": latency_ms,
                                
            }
        )


def log_user_feedback(
    *,
    thread_id: str,
    helpfulness: int,
    clarity: int,
    relevance: int,
    trust: int,
    comment: str = "",
    participant_id: Optional[str] = None,
    task_label: Optional[str] = None,
) -> None:
    """
    Save anonymous participant ratings after a test conversation.

    Ratings should use a 1-5 scale:
    1 = very poor, 5 = excellent.
    """
    ratings = {
        "helpfulness": helpfulness,
        "clarity": clarity,
        "relevance": relevance,
        "trust": trust,
    }
    for name, value in ratings.items():
        if not isinstance(value, int) or not 1 <= value <= 5:
            raise ValueError(f"{name} must be an integer from 1 to 5")

    file_exists = feedback_log_path.exists()
    fieldnames = [
        "timestamp_utc",
        "anonymous_thread_id",
        "participant_id",
        "task_label",
        "helpfulness",
        "clarity",
        "relevance",
        "trust",
        "comment",
    ]

    with feedback_log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds"),
                "anonymous_thread_id": anonymise_thread_id(thread_id),
                "participant_id": participant_id or "",
                "task_label": task_label or "",
                "helpfulness": helpfulness,
                "clarity": clarity,
                "relevance": relevance,
                "trust": trust,
                "comment": comment,
            }
        )

# Interview Practice Component

# Fixed structural sequence of graduate questions used to test interview candidate readiness
INTERVIEW_QUESTIONS = [
    "Tell me about yourself and why this role interests you.",
    "Describe a time you worked in a team to solve a problem.",
    "Tell me about a challenge or setback and how you handled it.",
    "Give an example of a skill from your course or experience that would help you in this role.",
    "Why should this employer choose you over another candidate?",
]


def build_interview_focus(degree: str = "", interests: str = "", target_role: str = "") -> str:
    """Create a short, non-sensitive interview context string for coaching."""
    parts = []
    if degree:
        parts.append(f"degree: {degree}")
    if interests:
        parts.append(f"interests: {interests}")
    if target_role:
        parts.append(f"target role: {target_role}")
    return "; ".join(parts) if parts else "general student graduate/internship interview"


def start_interview_practice(
    *,
    thread_id: str = "student-001",
    degree: str = "",
    interests: str = "",
    target_role: str = "",
) -> Dict[str, Any]:
    """Start a structured interview simulation."""
    focus = build_interview_focus(degree, interests, target_role)
    question = INTERVIEW_QUESTIONS[0]

    intro = (
        "Interview practice started. I’ll ask 5 common student/graduate interview questions. "
        "Answer each one like you would in a real interview, then I’ll score it and give feedback.\n\n"
        f"Focus: {focus}\n\n"
        f"Question 1/5: {question}"
    )

    return {
        "message": intro,
        "question": question,
        "question_index": 1,
        "total_questions": len(INTERVIEW_QUESTIONS),
        "complete": False,
    }


def _parse_interview_json(raw_text: str) -> Dict[str, Any]:
    """Parse JSON feedback from the LLM, with a safe fallback for malformed output."""
    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw_text[start:end])
    except json.JSONDecodeError:
        pass

    # Safe fallback configuration schema in the event of parsing failures
    return {
        "score": 3,
        "strengths": "You gave a usable answer and attempted to address the question.",
        "improvements": "Add one specific example, explain your action clearly, and finish with the result or what you learned.",
        "model_answer": "Use the STAR structure: situation, task, action, result. Keep it specific and link it back to the role.",
        "feedback": raw_text.strip() or "Your answer needs more detail and a clearer example.",
    }


def log_interview_practice(
    *,
    thread_id: str,
    question_index: int,
    question: str,
    user_answer: str,
    score: int,
    strengths: str,
    improvements: str,
    participant_id: Optional[str] = None,
    target_role: str = "",
) -> None:
    """Anonymous logging for the dedicated interview-practice feature."""
    file_exists = interview_log_path.exists()

    fieldnames = [
        "timestamp_utc",
        "anonymous_thread_id",
        "participant_id",
        "target_role",
        "question_index",
        "question",
        "user_answer",
        "score",
        "strengths",
        "improvements",
        "answer_word_count",
    ]

    with interview_log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerow(
            {
                "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds"),
                "anonymous_thread_id": anonymise_thread_id(thread_id),
                "participant_id": participant_id or "",
                "target_role": target_role,
                "question_index": question_index,
                "question": question,
                "user_answer": user_answer,
                "score": score,
                "strengths": strengths,
                "improvements": improvements,
                "answer_word_count": estimate_word_count(user_answer),
            }
        )


def grade_interview_answer(
    *,
    question_index: int,
    question: str,
    user_answer: str,
    thread_id: str = "student-001",
    degree: str = "",
    interests: str = "",
    target_role: str = "",
    participant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Score one interview answer and return feedback plus the next question."""
    focus = build_interview_focus(degree, interests, target_role)

    prompt = f"""
You are an interview coach for University of Northampton students.
Assess this practice interview answer fairly and constructively.

Student context: {focus}
Question {question_index}: {question}
Student answer: {user_answer}

Score the answer from 1 to 5 using this rubric:
- structure: clear STAR or logical answer
- relevance: answers the question and links to the role
- evidence: includes a specific example or detail
- confidence: sounds clear and professional

Return only valid JSON with exactly these keys:
{{
  "score": 3,
  "strengths": "one short sentence",
  "improvements": "one short sentence",
  "model_answer": "a stronger example answer in 2-4 sentences",
  "feedback": "brief supportive feedback in 2-3 sentences"
}}
""".strip()

    raw = interview_llm.invoke([HumanMessage(content=prompt)]).content
    feedback = _parse_interview_json(raw)

    try:
        score = int(feedback.get("score", 3))
    except (TypeError, ValueError):
        score = 3

    score = max(1, min(5, score))

    strengths = str(feedback.get("strengths", "You gave a relevant answer."))
    improvements = str(feedback.get("improvements", "Add a specific example and result."))
    model_answer = str(feedback.get("model_answer", "Use STAR: situation, task, action, result."))
    feedback_text = str(feedback.get("feedback", "Good attempt. Add more evidence and link it to the role."))

    log_interview_practice(
        thread_id=thread_id,
        participant_id=participant_id,
        target_role=target_role,
        question_index=question_index,
        question=question,
        user_answer=user_answer,
        score=score,
        strengths=strengths,
        improvements=improvements,
    )

    next_index = question_index + 1
    complete = next_index > len(INTERVIEW_QUESTIONS)
    next_question = "" if complete else INTERVIEW_QUESTIONS[next_index - 1]

    message = (
        f"Score: {score}/5\n\n"
        f"Strength: {strengths}\n"
        f"Improve: {improvements}\n\n"
        f"Example stronger answer:\n{model_answer}\n\n"
        f"{feedback_text}"
    )

    if complete:
        message += "\n\nInterview practice complete. Review your scores and try again after improving your examples."
    else:
        message += f"\n\nQuestion {next_index}/{len(INTERVIEW_QUESTIONS)}: {next_question}"

    return {
        "message": message,
        "score": score,
        "strengths": strengths,
        "improvements": improvements,
        "model_answer": model_answer,
        "feedback": feedback_text,
        "question": next_question,
        "question_index": next_index,
        "total_questions": len(INTERVIEW_QUESTIONS),
        "complete": complete,
    }




# Report Compilation Utilities

def _safe_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _average(values: List[int]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def build_evaluation_summary() -> Dict[str, Any]:
    """
    Create a compact summary 

    This helps assess retrieval quality, retry frequency, response length,
    latency, and participant feedback after the 10-person evaluation.
    """
    summary: Dict[str, Any] = {
        "interaction_log_path": str(log_path),
        "feedback_log_path": str(feedback_log_path),
        "interview_log_path": str(interview_log_path),
        "total_interactions": 0,
        "unique_anonymous_threads": 0,
        "retrieval_grade_counts": {},
        "retry_rate_percent": 0.0,
        "rewrite_rate_percent": 0.0,
        "average_latency_ms": None,
        "average_answer_word_count": None,
        "feedback_count": 0,
        "average_feedback": {},
        "interview_practice_count": 0,
        "average_interview_score": None,
        "interview_question_counts": {},
        "total_estimated_user_tokens": 0,
        "total_estimated_answer_tokens": 0,
        "total_estimated_tokens": 0,
        "average_estimated_tokens_per_interaction": None,
        "total_estimated_cost_gbp": 0.0,
        "average_estimated_cost_per_interaction_gbp": None,
        
    }

    # Process conversational logs
    if log_path.exists():
        with log_path.open("r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        summary["total_interactions"] = len(rows)
        summary["unique_anonymous_threads"] = len({row.get("anonymous_thread_id", "") for row in rows if row.get("anonymous_thread_id")})
        grade_counts = Counter(row.get("retrieval_grade", "unknown") for row in rows)
        summary["retrieval_grade_counts"] = dict(grade_counts)
        if rows:
            retry_rows = [row for row in rows if _safe_int(row.get("retry_count", "0")) > 0]
            rewritten_rows = [row for row in rows if str(row.get("used_rewritten_query", "")).lower() == "true"]
            total_user_tokens = sum(_safe_int(row.get("estimated_user_tokens", "0")) for row in rows)
            total_answer_tokens = sum(_safe_int(row.get("estimated_answer_tokens", "0")) for row in rows)
            total_tokens = sum(_safe_int(row.get("estimated_total_tokens", "0")) for row in rows)

            total_estimated_cost = sum(
                float(row.get("estimated_cost_gbp", "0") or 0)
                for row in rows
            )

            summary["retry_rate_percent"] = round((len(retry_rows) / len(rows)) * 100, 2)
            summary["rewrite_rate_percent"] = round((len(rewritten_rows) / len(rows)) * 100, 2)
            summary["average_latency_ms"] = _average([_safe_int(row.get("latency_ms", "0")) for row in rows])
            summary["average_answer_word_count"] = _average([_safe_int(row.get("answer_word_count", "0")) for row in rows])
            summary["total_estimated_user_tokens"] = total_user_tokens
            summary["total_estimated_answer_tokens"] = total_answer_tokens
            summary["total_estimated_tokens"] = total_tokens
            summary["average_estimated_tokens_per_interaction"] = round(total_tokens / len(rows), 2)
            summary["total_estimated_cost_gbp"] = round(total_estimated_cost, 6)
            summary["average_estimated_cost_per_interaction_gbp"] = round(
                total_estimated_cost / len(rows),
                6,
            )
            


    # Process user feedback logs
    if feedback_log_path.exists():
        with feedback_log_path.open("r", newline="", encoding="utf-8") as f:
            feedback_rows = list(csv.DictReader(f))
        summary["feedback_count"] = len(feedback_rows)
        for field in ["helpfulness", "clarity", "relevance", "trust"]:
            summary["average_feedback"][field] = _average([_safe_int(row.get(field, "0")) for row in feedback_rows])

    # Process mock interview logs
    interview_rows = []
    if interview_log_path.exists():
        with interview_log_path.open("r", newline="", encoding="utf-8") as f:
            interview_rows = list(csv.DictReader(f))

    summary["interview_practice_count"] = len(interview_rows)
    summary["average_interview_score"] = _average(
        [_safe_int(row.get("score", "0")) for row in interview_rows]
    )
    summary["interview_question_counts"] = dict(
        Counter(row.get("question_index", "unknown") for row in interview_rows)
    )
    
    with evaluation_summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


# External Application Wrapper Interface
def chat_with_bot(
    user_text: str,
    thread_id: str = "student-001",
    *,
    participant_id: Optional[str] = None,
    task_label: Optional[str] = None,
) -> str:
    """
    Main function used by the notebook and FastAPI app.

    The same thread_id keeps memory across messages.
    A different thread_id starts a separate conversation.
    participant_id can be something anonymous like P01, P02, etc.
    task_label can be something like CV, interview, career_path, or internship.
    """
    config = {"configurable": {"thread_id": thread_id}}
    start_time = time.perf_counter()

    # Fire conversational state machine rup step
    result = career_graph.invoke(
        {"messages": [HumanMessage(content=user_text)]},
        config=config,
    )
    latency_ms = int((time.perf_counter() - start_time) * 1000)
    answer = result.get("answer", "Sorry, I could not generate an answer.")

    # Record data metrics downstream asynchronously
    log_interaction(
        thread_id=thread_id,
        user_text=user_text,
        result=result,
        latency_ms=latency_ms,
        participant_id=participant_id,
        task_label=task_label,
    )
    return answer

# Terminal interactive loop iterface
if __name__ == "__main__":
    print("CareerPath backend ready. Type 'quit' to stop.")
    print("Type 'summary' to create evaluation_summary.json.\n")
    tid = "terminal-demo"
    while True:
        user = input("You: ").strip()
        if user.lower() in {"quit", "exit"}:
            break
        if user.lower() == "summary":
            summary = build_evaluation_summary()
            print(json.dumps(summary, indent=2), "\n")
            continue
        print("Bot:", chat_with_bot(user, thread_id=tid, participant_id="terminal", task_label="manual_test"), "\n")