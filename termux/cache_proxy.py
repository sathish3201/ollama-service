"""
Caching proxy in front of llama-server, for the Termux/phone setup.

llama-server has no response caching of its own — every request re-runs
inference, even for an identical question or the same image sent twice
(a real cost on a phone: slower answers, more battery/heat). This proxy
sits between ngrok and llama-server: it checks a local SQLite cache for
an identical request (same model/messages/temperature/max_tokens,
images included since they're embedded as base64 inside `messages`)
before forwarding to llama-server, and stores the response after a
cache miss. Same approach as app.py's cache on the laptop side.

Auth (--api-key on llama-server) still happens on llama-server itself —
this proxy forwards the Authorization header through unchanged rather
than re-implementing the check, so start.sh's existing SERVICE_API_KEY
flow doesn't need to change.

Run:
    uvicorn cache_proxy:app --host 0.0.0.0 --port 8081

Then point ngrok at THIS port (8081), not llama-server's port (8080)
directly — see start.sh.
"""

import hashlib
import json
import os
import sqlite3
import time

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

LLAMA_SERVER_URL = os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080")

CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "true").lower() != "false"
CACHE_PATH = os.environ.get("CACHE_PATH", "cache.sqlite3")


def _init_cache_db() -> None:
    conn = sqlite3.connect(CACHE_PATH)
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


def _cache_key(body: dict) -> str:
    # Cache on exactly what determines the model's output: model,
    # messages (text AND any embedded base64 images), temperature,
    # max_tokens. Two requests with the same image bytes produce the
    # same base64 string, so image content is naturally covered here
    # without any special-casing.
    payload = {
        "model": body.get("model"),
        "messages": body.get("messages"),
        "temperature": body.get("temperature"),
        "max_tokens": body.get("max_tokens"),
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

app = FastAPI(title="llama-server caching proxy", version="1.0.0")


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{LLAMA_SERVER_URL}/health")
            resp.raise_for_status()
        return {"status": "ok", "llama_server_reachable": True, "cache_enabled": CACHE_ENABLED}
    except httpx.HTTPError:
        return {"status": "degraded", "llama_server_reachable": False, "cache_enabled": CACHE_ENABLED}


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Checks the cache, then forwards to llama-server on a miss (which does its own --api-key check)."""
    body = await request.json()

    cache_key = await run_in_threadpool(_cache_key, body)
    cached = await run_in_threadpool(_cache_get, cache_key)
    if cached is not None:
        return JSONResponse(cached, headers={"X-Cache": "HIT"})

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(
                f"{LLAMA_SERVER_URL}/v1/chat/completions",
                json=body,
                headers={"Authorization": authorization} if authorization else {},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"llama-server request failed: {exc}") from exc

    if resp.status_code != 200:
        # Pass through llama-server's own error (401 from a bad key,
        # 400 from a malformed request, etc.) without caching it.
        return JSONResponse(resp.json() if resp.content else {}, status_code=resp.status_code)

    result = resp.json()
    answer = result.get("choices", [{}])[0].get("message", {}).get("content", "")

    # Only cache real answers — an empty completion (e.g. a small model
    # emitting an early stop token on some prompts) shouldn't get
    # permanently cached as "the" answer to that question.
    if answer:
        await run_in_threadpool(_cache_put, cache_key, result)

    return JSONResponse(result, headers={"X-Cache": "MISS"})
