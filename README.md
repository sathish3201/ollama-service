# ollama-service

A small local web service that wraps [Ollama](https://ollama.com) behind an
OpenAI-compatible REST API and an [MCP](https://modelcontextprotocol.io)
server, gated by an API key — so other projects (your RAG notebook, an MCP
client like Claude Code, or any HTTP client) can call your local model the
same way they'd call OpenAI or Anthropic's API.

## What this is (and isn't)

- **The model runs on your machine.** Ollama and `phi3:mini` stay local —
  this repo does not upload weights or host inference anywhere.
- **GitHub hosts the source code only.** Pushing this repo to GitHub does
  *not* make the service reachable from the internet. GitHub has no
  general-purpose server hosting (Pages is static-only). To make this
  reachable from elsewhere, deploy the `Dockerfile` to an actual host
  (a VPS, Render, Railway, Fly.io, etc.) that also has Ollama running
  and the model pulled.
- **API-key auth mirrors the OpenAI/Anthropic pattern** — pass your key
  as `Authorization: Bearer <key>`, same shape as those SDKs — but this
  key is one you generate yourself and only protects *this* service.

## Layout

| File | Purpose |
|---|---|
| `app.py` | FastAPI service. `/v1/chat/completions` (OpenAI-compatible) + `/health`. |
| `mcp_server.py` | MCP server exposing an `ask_local_model` tool that calls `app.py`. |
| `requirements.txt` | Python dependencies. |
| `.env.example` | Template for required environment variables. |
| `Dockerfile` | Container image for the FastAPI service (Ollama runs separately). |

## Setup

1. **Ollama must already be running with a model pulled:**
   ```
   ollama serve
   ollama pull phi3:mini
   ```

2. **Install dependencies** (using your existing Anaconda Python):
   ```
   pip install -r requirements.txt
   ```

3. **Create your `.env`:**
   ```
   cp .env.example .env
   ```
   Generate a real key and paste it into `.env`:
   ```
   python -c "import secrets; print('sk-local-' + secrets.token_hex(24))"
   ```
   **Never commit `.env`** — it's already in `.gitignore`.

4. **Run the FastAPI service:**
   ```
   # Windows PowerShell — load .env into the session first
   Get-Content .env | ForEach-Object {
       if ($_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2]) }
   }
   uvicorn app:app --host 0.0.0.0 --port 8000
   ```

5. **Check it's alive:**
   ```
   curl http://localhost:8000/health
   ```

## Using it from your RAG notebook

Same pattern as pointing at Ollama directly, but now through your service
with API-key auth — swap the `OpenAI(...)` client init in
`demo_chatbot_basics.ipynb`:

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-local-...",             # the key from your .env
    base_url="http://localhost:8000/v1"  # your service, not Ollama directly
)

response = client.chat.completions.create(
    model="phi3:mini",
    messages=[{"role": "user", "content": "What is an embedding?"}],
)
print(response.choices[0].message.content)
```

## Using it as an MCP server

Register `mcp_server.py` with an MCP client (stdio transport). It requires
`SERVICE_API_KEY` and `SERVICE_URL` in its environment, and the FastAPI
service from step 4 above must already be running.

```
python mcp_server.py
```

The exposed tool is `ask_local_model(prompt, model="phi3:mini")`.

## Deploying somewhere reachable (optional, beyond "push to GitHub")

If you actually want this callable from outside your machine:

1. Provision a host that can run both Ollama and this container (a small
   VPS with a few GB RAM at minimum; `phi3:mini` is CPU-friendly).
2. Install Ollama there, `ollama pull phi3:mini`.
3. Build and run this Dockerfile on the same host, pointing
   `OLLAMA_BASE_URL` at `http://localhost:11434` (or wherever Ollama
   listens on that host).
4. Put a reverse proxy (e.g. Caddy, nginx) with TLS in front of port 8000
   if this needs to be public — don't expose it raw over HTTP with only
   the API key for protection.

GitHub Actions can automate *steps 3–4* (build the image, push to a
registry, redeploy) as CI/CD — but the model itself still needs to run on
a real, always-on host you control. GitHub Actions runners are ephemeral
and are not a substitute for that host.
