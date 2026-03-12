# """StudyBuddy API - FastAPI app with OpenAI and Supabase."""

# import asyncio
# import json
# from contextlib import asynccontextmanager

# from fastapi import FastAPI, HTTPException, Request
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.responses import StreamingResponse
# from pydantic import BaseModel

# from auth.clerk import get_email_from_token
# from config import get_settings
# from services.ai import generate_answer, stream_answer
# from db.supabase import (
#     get_conversation,
#     get_first_question_per_conversation,
#     get_messages,
#     get_or_create_user,
#     get_supabase,
#     list_conversations,
#     save_qa,
# )


# class AskRequest(BaseModel):
#     question: str
#     conversation_id: str | None = None


# class AskResponse(BaseModel):
#     answer: str
#     conversation_id: str | None = None


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     settings = get_settings()
#     if not settings.openai_configured:
#         print("Warning: OPENAI_API_KEY not set. Answer generation will return a placeholder.")
#     yield


# app = FastAPI(
#     title="StudyBuddy API",
#     description="AI-powered study assistant",
#     version="0.1.0",
#     lifespan=lifespan,
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=[
#         "http://localhost:3000",
#         "http://127.0.0.1:3000",
#     ],
#     allow_origin_regex=r"https://.*\.vercel\.app",
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


# def _get_email(request: Request) -> str:
#     """Extract and validate user email from Clerk JWT. Raises 401 if missing/invalid."""
#     auth = request.headers.get("Authorization")
#     email = get_email_from_token(auth)
#     if not email:
#         raise HTTPException(
#             status_code=401,
#             detail="Missing or invalid Authorization. Sign in and send Bearer token.",
#         )
#     return email


# @app.get("/")
# def root():
#     """So opening the Render URL in a browser shows API is up (GET / used to 404)."""
#     return {
#         "service": "StudyBuddy API",
#         "health": "GET /health",
#         "ask": "POST /api/ask with JSON body {\"question\": \"...\", \"conversation_id\": \"...\"?}",
#         "conversations": "GET /api/conversations",
#         "messages": "GET /api/conversations/{id}/messages",
#     }


# @app.get("/health")
# def health():
#     return {"status": "ok"}


# @app.post("/api/ask", response_model=AskResponse)
# async def ask(req: AskRequest, request: Request):
#     """Generate an answer for the given question. Requires Authorization: Bearer <Clerk JWT>. Stores in Supabase with user/conversation/message schema."""
#     question = (req.question or "").strip()
#     if not question:
#         raise HTTPException(status_code=400, detail="question is required")
#     email = _get_email(request)
#     answer = await generate_answer(question)
#     conversation_id = save_qa(
#         email=email,
#         question=question,
#         answer=answer,
#         conversation_id=req.conversation_id,
#     )
#     return AskResponse(answer=answer, conversation_id=conversation_id)


# async def _stream_ask_async(question: str, email: str, conversation_id: str | None):
#     """Async generator for SSE: run sync stream in thread, yield SSE lines from queue."""
#     q: asyncio.Queue[str] = asyncio.Queue()

#     def run_stream() -> None:
#         full: list[str] = []
#         for chunk, done in stream_answer(question):
#             if chunk:
#                 full.append(chunk)
#                 q.put_nowait(json.dumps({"content": chunk}))
#             if done:
#                 break
#         answer = "".join(full)
#         cid = save_qa(email=email, question=question, answer=answer, conversation_id=conversation_id)
#         q.put_nowait(json.dumps({"done": True, "conversation_id": cid}))

#     loop = asyncio.get_event_loop()
#     loop.run_in_executor(None, run_stream)
#     while True:
#         data = await q.get()
#         yield f"data: {data}\n\n"
#         try:
#             if json.loads(data).get("done"):
#                 break
#         except Exception:
#             pass


# @app.post("/api/ask/stream")
# async def ask_stream(req: AskRequest, request: Request):
#     """Stream answer chunks via SSE. Requires Bearer token. Sends conversation_id in final event."""
#     question = (req.question or "").strip()
#     if not question:
#         raise HTTPException(status_code=400, detail="question is required")
#     email = _get_email(request)
#     return StreamingResponse(
#         _stream_ask_async(question, email, req.conversation_id),
#         media_type="text/event-stream",
#         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
#     )


# @app.get("/api/conversations")
# def api_list_conversations(request: Request):
#     """List current user's conversations (newest first). Requires Bearer token."""
#     email = _get_email(request)
#     if not get_supabase():
#         return []
#     user_id = get_or_create_user(email)
#     if not user_id:
#         return []
#     items = list_conversations(user_id)
#     cids = [str(c["id"]) for c in items]
#     titles = get_first_question_per_conversation(cids)
#     return [
#         {
#             "id": str(c["id"]),
#             "created_at": c["created_at"],
#             "title": titles.get(str(c["id"])) or "New chat",
#         }
#         for c in items
#     ]


# @app.get("/api/conversations/{conversation_id}/messages")
# def api_get_messages(conversation_id: str, request: Request):
#     """Get messages for a conversation. Requires Bearer token; conversation must belong to user."""
#     email = _get_email(request)
#     user_id = get_or_create_user(email)
#     if not user_id:
#         return []
#     conv = get_conversation(conversation_id)
#     if not conv or str(conv["user_id"]) != str(user_id):
#         raise HTTPException(status_code=404, detail="Conversation not found")
#     messages = get_messages(conversation_id)
#     return [
#         {
#             "id": str(m["id"]),
#             "question": m["question"],
#             "answer": m["answer"],
#             "created_at": m["created_at"],
#         }
#         for m in messages
#     ]


"""CompareKaro API — Product comparison agent with FastAPI."""

import asyncio
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth.clerk import get_email_from_token
from config import get_settings
from db.supabase import (
    get_conversation,
    get_first_question_per_conversation,
    get_messages,
    get_or_create_user,
    get_supabase,
    list_conversations,
    save_qa,
)
from services.ai import generate_answer, stream_answer
from agent.compare_agent import (
    clean_user_input,
    compare_products_async,
    compare_products_stream,
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    conversation_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    conversation_id: str | None = None


class CompareRequest(BaseModel):
    query: str                          # product name OR URLs
    conversation_id: str | None = None


class CompareResponse(BaseModel):
    result: str
    conversation_id: str | None = None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.openai_configured:
        print("⚠️  OPENAI_API_KEY not set.")
    if not settings.serpapi_api_key:
        print("⚠️  SERPAPI_API_KEY not set — comparison agent won't work.")
    yield


app = FastAPI(
    title="CompareKaro API",
    description="AI-powered product comparison across Amazon & Flipkart",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _get_email(request: Request) -> str:
    auth = request.headers.get("Authorization")
    # DEV_MODE: skip Clerk auth for local testing — remove before production
    if os.getenv("DEV_MODE", "").lower() == "true" and not auth:
        return "dev@localhost"
    email = get_email_from_token(auth)
    if not email:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization.")
    return email


def _is_compare_intent(cleaned_text: str) -> bool:
    """True if the user is asking to compare products on Amazon/Flipkart."""
    if not cleaned_text or len(cleaned_text.strip()) < 3:
        return False
    lower = cleaned_text.lower()
    has_compare = "compare" in lower
    has_platform = "flipkart" in lower or "amazon" in lower
    return bool(has_compare and has_platform)


# ---------------------------------------------------------------------------
# Root & Health
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {
        "service": "CompareKaro API",
        "version": "1.0.0",
        "endpoints": {
            "health": "GET /health",
            "compare": "POST /api/compare",
            "compare_stream": "POST /api/compare/stream",
            "ask": "POST /api/ask",
            "ask_stream": "POST /api/ask/stream",
            "conversations": "GET /api/conversations",
            "messages": "GET /api/conversations/{id}/messages",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Compare endpoints (primary feature)
# ---------------------------------------------------------------------------

@app.post("/api/compare", response_model=CompareResponse)
async def compare(req: CompareRequest, request: Request):
    """Run the comparison agent. Non-streaming."""
    query = clean_user_input((req.query or "").strip())
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    email = _get_email(request)
    result = await compare_products_async(query)

    conversation_id = save_qa(
        email=email,
        question=f"[Compare] {query}",
        answer=result,
        conversation_id=req.conversation_id,
    )
    return CompareResponse(result=result, conversation_id=conversation_id)


async def _stream_compare_sse(query: str, email: str, conversation_id: str | None):
    """Wrap sync compare streamer into async SSE generator."""
    q: asyncio.Queue[str] = asyncio.Queue()

    def _run() -> None:
        full: list[str] = []
        for chunk, done in compare_products_stream(query):
            if chunk:
                full.append(chunk)
                q.put_nowait(json.dumps({"content": chunk}))
            if done:
                break
        answer = "".join(full)
        cid = save_qa(
            email=email,
            question=f"[Compare] {query}",
            answer=answer,
            conversation_id=conversation_id,
        )
        q.put_nowait(json.dumps({"done": True, "conversation_id": cid}))

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run)

    while True:
        data = await q.get()
        yield f"data: {data}\n\n"
        try:
            if json.loads(data).get("done"):
                break
        except Exception:
            pass


@app.post("/api/compare/stream")
async def compare_stream(req: CompareRequest, request: Request):
    """Stream comparison results via SSE."""
    query = clean_user_input((req.query or "").strip())
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    email = _get_email(request)
    return StreamingResponse(
        _stream_compare_sse(query, email, req.conversation_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Ask endpoints (chat / study assistant — kept for backward compat)
# ---------------------------------------------------------------------------

@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest, request: Request):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    email = _get_email(request)
    cleaned = clean_user_input(question)
    if _is_compare_intent(cleaned):
        answer = await compare_products_async(cleaned)
        conversation_id = save_qa(
            email=email, question=f"[Compare] {cleaned}", answer=answer,
            conversation_id=req.conversation_id,
        )
        return AskResponse(answer=answer, conversation_id=conversation_id)
    answer = await generate_answer(question)
    conversation_id = save_qa(
        email=email, question=question, answer=answer,
        conversation_id=req.conversation_id,
    )
    return AskResponse(answer=answer, conversation_id=conversation_id)


async def _stream_ask_sse(question: str, email: str, conversation_id: str | None):
    q: asyncio.Queue[str] = asyncio.Queue()

    def _run() -> None:
        full: list[str] = []
        for chunk, done in stream_answer(question):
            if chunk:
                full.append(chunk)
                q.put_nowait(json.dumps({"content": chunk}))
            if done:
                break
        answer = "".join(full)
        cid = save_qa(
            email=email, question=question, answer=answer,
            conversation_id=conversation_id,
        )
        q.put_nowait(json.dumps({"done": True, "conversation_id": cid}))

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run)

    while True:
        data = await q.get()
        yield f"data: {data}\n\n"
        try:
            if json.loads(data).get("done"):
                break
        except Exception:
            pass


@app.post("/api/ask/stream")
async def ask_stream(req: AskRequest, request: Request):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    email = _get_email(request)
    cleaned = clean_user_input(question)
    if _is_compare_intent(cleaned):
        return StreamingResponse(
            _stream_compare_sse(cleaned, email, req.conversation_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return StreamingResponse(
        _stream_ask_sse(question, email, req.conversation_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Conversation endpoints
# ---------------------------------------------------------------------------

@app.get("/api/conversations")
def api_list_conversations(request: Request):
    email = _get_email(request)
    if not get_supabase():
        return []
    user_id = get_or_create_user(email)
    if not user_id:
        return []
    items = list_conversations(user_id)
    cids = [str(c["id"]) for c in items]
    titles = get_first_question_per_conversation(cids)
    return [
        {
            "id": str(c["id"]),
            "created_at": c["created_at"],
            "title": titles.get(str(c["id"])) or "New chat",
        }
        for c in items
    ]


@app.get("/api/conversations/{conversation_id}/messages")
def api_get_messages(conversation_id: str, request: Request):
    email = _get_email(request)
    user_id = get_or_create_user(email)
    if not user_id:
        return []
    conv = get_conversation(conversation_id)
    if not conv or str(conv["user_id"]) != str(user_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = get_messages(conversation_id)
    return [
        {
            "id": str(m["id"]),
            "question": m["question"],
            "answer": m["answer"],
            "created_at": m["created_at"],
        }
        for m in messages
    ]