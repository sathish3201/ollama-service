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

| Path | Purpose |
|---|---|
| `app.py` | FastAPI service. `/v1/chat/completions` (OpenAI-compatible) + `/health`. |
| `mcp_server.py` | MCP server exposing an `ask_local_model` tool that calls `app.py`. |
| `requirements.txt` | Python dependencies. |
| `.env.example` | Template for required environment variables. |
| `Dockerfile` | Container image for the FastAPI service (Ollama runs separately). |
| `huggingface/` | Variant for deploying to Hugging Face Spaces — bundles Ollama + `app.py` into one container. **Requires a paid Space (Docker SDK is not on HF's free tier as of this writing).** See `huggingface/README.md`. |
| `termux/` | Variant for running the model directly on an Android phone via Termux + llama.cpp, with ngrok for public access. Genuinely free, but battery/background-kill tradeoffs apply. See `termux/README.md`. |

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
   > If port 8000 is already taken by something else on your machine
   > (check with `netstat -ano | findstr :8000`), just pick a free one,
   > e.g. `--port 8001`, and use that port in every example below.

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

## Making it publicly reachable — free, via ngrok

Pushing this repo to GitHub does **not** put the service on the internet
(see above) — but you don't need a paid cloud host either. A free tunnel
gives your already-running local service a public HTTPS URL, at the cost
of only working while this machine and the tunnel process stay up.

1. **Install ngrok** and authenticate once:
   ```
   ngrok config add-authtoken <YOUR_TOKEN>
   ```
   Get a free token from https://dashboard.ngrok.com/get-started/your-authtoken.

2. **With the FastAPI service already running** (step 4 above), start a
   tunnel pointed at the same port:
   ```
   ngrok http 8001
   ```
   ngrok prints a public URL, e.g.:
   ```
   url=https://bovine-cylinder-onboard.ngrok-free.dev
   ```
   This URL is **random and changes every time you restart ngrok**,
   unless you claim a static free domain from the ngrok dashboard.

3. **Verify end-to-end** (replace the URL and key with your own):
   ```bash
   curl https://bovine-cylinder-onboard.ngrok-free.dev/health

   curl -X POST https://bovine-cylinder-onboard.ngrok-free.dev/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer sk-local-..." \
     -d '{"model":"phi3:mini","messages":[{"role":"user","content":"Say hello in 5 words."}],"max_tokens":30}'
   ```

4. **Point any client at the tunnel URL** the same way you would at
   `localhost` — just swap `base_url`:
   ```python
   client = OpenAI(
       api_key="sk-local-...",
       base_url="https://bovine-cylinder-onboard.ngrok-free.dev/v1"
   )
   ```

**Reality check:** this only works while Ollama, `app.py`, and `ngrok`
are all running on this machine. Close the laptop or kill any of those
three processes and the URL stops responding. For a setup that doesn't
depend on a laptop staying on, see `termux/README.md` (runs the model on
an Android phone instead) — with its own tradeoffs (battery drain,
Android backgrounding the process unless configured not to).

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
