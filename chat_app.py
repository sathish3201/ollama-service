"""
Standalone multimodal chat app: text + images + PDFs + DOCX, served to a
phone browser (or any browser) as a small web UI + installable PWA.

Deliberately separate from app.py (which powers the live nexoria-website
widget on port 8001) so nothing here can affect that production endpoint.
Same local Ollama instance, different port, different process.

Run:
    uvicorn chat_app:app --host 0.0.0.0 --port 8002

Then open http://<this-machine's-LAN-IP>:8002/ in your phone's browser
(same WiFi), or point ngrok at 8002 for access from anywhere.
"""

import base64
import io
import json
import os
import time
import uuid

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

API_KEY = os.environ.get("SERVICE_API_KEY")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
# This service only hosts TEXT chat (phi3:mini / gemma3:1b / qwen2.5:3b) —
# no vision model is pulled into Ollama on the laptop. Image/PDF file
# uploads are still accepted here (converted to image_url blocks below) so
# the request shape is uniform, but sending one to a text-only model will
# just get ignored or produce a confused answer. The web UI is
# responsible for routing file-attached messages to the phone/smolvlm2
# backend instead — see webui/index.html's pickBackendFor().
DEFAULT_TEXT_MODEL = os.environ.get("DEFAULT_MODEL", "phi3:mini")

# Models actually pulled into this laptop's Ollama that do NOT understand
# images (see ollama list). Sending an image_url block to one of these
# doesn't error cleanly server-side — Ollama's /api/chat 404s in a way
# that looks like a routing bug rather than "wrong model for this input".
# Reject it here instead, with a message that names the actual problem.
TEXT_ONLY_MODELS = {"phi3:mini", "gemma3:1b", "qwen2.5:3b"}

if not API_KEY:
    raise RuntimeError(
        "SERVICE_API_KEY environment variable is not set. "
        "Copy .env.example to .env, fill in a key, and load it before starting."
    )

app = FastAPI(title="Local Multimodal Chat", version="1.0.0")

# Browser calls this directly (fetch from the phone's page) — allow any
# origin serving the page itself; this is a personal-use local service,
# not a public multi-tenant API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _check_api_key(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# File -> model-consumable content conversion
#
# The vision model only understands images (as base64 data URLs) and plain
# text — it cannot read PDF/DOCX bytes directly. Convert here, server-side,
# so the phone just uploads the raw file.
# ---------------------------------------------------------------------------

MAX_PDF_PAGES = 10  # guard against a huge PDF turning into 200 image calls


def _image_to_data_url(image_bytes: bytes, mime: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _pdf_to_image_data_urls(pdf_bytes: bytes) -> list[str]:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_count = min(doc.page_count, MAX_PDF_PAGES)
        urls = []
        for i in range(page_count):
            page = doc.load_page(i)
            # 150 DPI is enough for a vision model to read text; higher
            # just costs more tokens/RAM for no real accuracy gain here.
            pix = page.get_pixmap(dpi=150)
            urls.append(_image_to_data_url(pix.tobytes("jpeg"), "image/jpeg"))
        return urls
    finally:
        doc.close()


def _docx_to_text(docx_bytes: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(docx_bytes))
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


async def _file_to_content_blocks(upload: UploadFile) -> list[dict]:
    """Convert one uploaded file into OpenAI-style content blocks."""
    data = await upload.read()
    filename = upload.filename or "file"
    content_type = upload.content_type or ""
    lower_name = filename.lower()

    if content_type.startswith("image/") or lower_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        mime = content_type or "image/jpeg"
        return [{"type": "image_url", "image_url": {"url": _image_to_data_url(data, mime)}}]

    if content_type == "application/pdf" or lower_name.endswith(".pdf"):
        image_urls = await run_in_threadpool_sync(_pdf_to_image_data_urls, data)
        blocks = [{"type": "text", "text": f"[Attached PDF: {filename}, {len(image_urls)} page(s) shown as images below]"}]
        blocks += [{"type": "image_url", "image_url": {"url": u}} for u in image_urls]
        return blocks

    if lower_name.endswith(".docx"):
        text = await run_in_threadpool_sync(_docx_to_text, data)
        return [{"type": "text", "text": f"[Attached document: {filename}]\n\n{text}"}]

    if lower_name.endswith((".txt", ".md", ".csv")):
        return [{"type": "text", "text": f"[Attached file: {filename}]\n\n{data.decode('utf-8', errors='replace')}"}]

    raise HTTPException(status_code=415, detail=f"Unsupported file type: {filename}")


async def run_in_threadpool_sync(fn, *args):
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(fn, *args)


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
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
    model: str = Form(...),
    message: str = Form(""),
    history: str = Form("[]"),
    files: list[UploadFile] = File(default=[]),
    authorization: str | None = Header(default=None),
):
    """
    Multipart chat endpoint: text message + optional file uploads (images,
    PDFs, DOCX) in one request. `history` is a JSON-encoded list of prior
    {role, content} turns (content as plain text — the client keeps only
    text history to avoid resending large images every turn).
    """
    _check_api_key(authorization)

    try:
        prior_messages = json.loads(history)
    except json.JSONDecodeError:
        prior_messages = []

    content_blocks: list[dict] = []
    if message.strip():
        content_blocks.append({"type": "text", "text": message})
    for f in files:
        content_blocks += await _file_to_content_blocks(f)

    if not content_blocks:
        raise HTTPException(status_code=400, detail="Empty message with no files")

    has_image = any(b["type"] == "image_url" for b in content_blocks)
    if has_image and model in TEXT_ONLY_MODELS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{model}' can't understand images (text-only model on this laptop backend). "
                "Route image/PDF messages to the phone's vision backend (smolvlm2) instead — "
                "check that its ngrok tunnel is up and reachable."
            ),
        )

    messages = prior_messages + [{"role": "user", "content": content_blocks}]

    # Ollama's /api/chat accepts OpenAI-style content blocks for
    # multimodal-capable models: text blocks are concatenated, image_url
    # data-URL blocks are decoded into the model's native `images` field.
    ollama_messages = []
    for m in messages:
        if isinstance(m["content"], str):
            ollama_messages.append({"role": m["role"], "content": m["content"]})
            continue
        text_parts = []
        images = []
        for block in m["content"]:
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "image_url":
                url = block["image_url"]["url"]
                # data:image/jpeg;base64,<data>
                images.append(url.split(",", 1)[1])
        ollama_messages.append(
            {"role": m["role"], "content": "\n".join(text_parts), "images": images or None}
        )

    payload = {"model": model, "messages": ollama_messages, "stream": False}

    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Ollama request failed: {exc}") from exc

    data = resp.json()
    answer = data.get("message", {}).get("content", "")

    return JSONResponse(
        {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "created": int(time.time()),
            "model": model,
            "reply": answer,
            "usage": {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
        }
    )


# ---------------------------------------------------------------------------
# Static web UI (chat page + PWA shell)
# ---------------------------------------------------------------------------

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "webui")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.get("/manifest.json")
async def manifest():
    return FileResponse(os.path.join(_STATIC_DIR, "manifest.json"))


@app.get("/sw.js")
async def service_worker():
    return FileResponse(os.path.join(_STATIC_DIR, "sw.js"), media_type="application/javascript")
