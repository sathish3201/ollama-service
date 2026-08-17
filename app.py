"""
Local Ollama web service with OpenAI-compatible API and API-key auth.

Wraps a local Ollama instance so any client that speaks the OpenAI
chat-completions format (openai python package, curl, your RAG notebook)
can call it exactly like the real OpenAI/Anthropic API — just point
base_url at this service and pass your generated API key.

Run:
    uvicorn app:app --host 0.0.0.0 --port 8000

This process must run on a machine that also has Ollama running
(``ollama serve``, default http://localhost:11434) with the model
pulled (e.g. ``ollama pull phi3:mini``).
"""

import hashlib
import json
import os
import sqlite3
import time
import uuid

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

API_KEY = os.environ.get("SERVICE_API_KEY")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "phi3:mini")

# Response cache: identical requests (same model/messages/temperature/max_tokens)
# are served from disk instead of re-running inference. Persists across
# restarts (SQLite file), since the phone backend restarts often (battery
# kills, manual restarts). Set CACHE_ENABLED=false to disable.
CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "true").lower() != "false"
CACHE_PATH = os.environ.get("CACHE_PATH", "cache.sqlite3")


def _init_cache_db() -> None:
    conn = sqlite3.connect(CACHE_PATH)
    # WAL mode lets a read (cache lookup) proceed without blocking on a
    # concurrent write (cache write from another request) — matters here
    # since multiple chat requests can be in flight at once.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS response_cache (
            cache_key TEXT PRIMARY KEY,
            response_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def _cache_key(body: "ChatCompletionRequest") -> str:
    payload = {
        "model": body.model,
        "messages": [m.model_dump() for m in body.messages],
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
    }
    canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cache_get(cache_key: str) -> dict | None:
    if not CACHE_ENABLED:
        return None
    conn = sqlite3.connect(CACHE_PATH)
    row = conn.execute(
        "SELECT response_json FROM response_cache WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    conn.close()
    return json.loads(row[0]) if row else None


def _cache_put(cache_key: str, response: dict) -> None:
    if not CACHE_ENABLED:
        return
    conn = sqlite3.connect(CACHE_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO response_cache (cache_key, response_json, created_at) VALUES (?, ?, ?)",
        (cache_key, json.dumps(response), time.time()),
    )
    conn.commit()
    conn.close()


if CACHE_ENABLED:
    _init_cache_db()

# Comma-separated list of origins allowed to call this service directly
# from a browser (e.g. a static site with no backend, like a GitHub Pages
# portfolio). Not needed for server-to-server callers (e.g. an Express
# backend) — CORS only applies to browser-originated requests.
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]

if not API_KEY:
    raise RuntimeError(
        "SERVICE_API_KEY environment variable is not set. "
        "Copy .env.example to .env, fill in a key, and load it before starting."
    )

app = FastAPI(title="Local Ollama Service", version="1.0.0")

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["POST", "GET"],
        allow_headers=["Content-Type", "Authorization"],
    )


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = DEFAULT_MODEL
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False


def _check_api_key(authorization: str | None) -> None:
    """Validate the Bearer token against SERVICE_API_KEY."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health")
async def health():
    """Unauthenticated health check — confirms this service and Ollama are both up."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
        return {"status": "ok", "ollama_reachable": True, "models": models}
    except httpx.HTTPError:
        return {"status": "degraded", "ollama_reachable": False, "models": []}


@app.post("/v1/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    authorization: str | None = Header(default=None),
):
    """OpenAI-compatible chat completions endpoint, backed by local Ollama."""
    _check_api_key(authorization)

    cache_key = _cache_key(body)
    cached = await run_in_threadpool(_cache_get, cache_key)
    if cached is not None:
        return cached

    ollama_payload = {
        "model": body.model,
        "messages": [m.model_dump() for m in body.messages],
        "stream": False,
        "options": {"temperature": body.temperature},
    }
    if body.max_tokens is not None:
        ollama_payload["options"]["num_predict"] = body.max_tokens

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=ollama_payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Ollama request failed: {exc}") from exc

    data = resp.json()
    answer = data.get("message", {}).get("content", "")

    # Shape the response like the OpenAI SDK expects, so
    # `response.choices[0].message.content` keeps working unchanged.
    result = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
            "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
        },
    }

    # Only cache real answers — an empty completion (e.g. the model
    # emitting an early stop token on some prompts) shouldn't get
    # permanently cached as "the" answer to that question.
    if answer:
        await run_in_threadpool(_cache_put, cache_key, result)

    return result
