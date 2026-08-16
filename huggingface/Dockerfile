# Dockerfile for deploying to Hugging Face Spaces (Docker SDK, free CPU tier).
#
# Bundles Ollama + the FastAPI wrapper (app.py) into ONE container, since
# HF Spaces runs a single container per Space — unlike the local setup
# where Ollama and app.py run as separate processes.
#
# Free tier: 2 vCPU, 16GB RAM — enough for phi3:mini (2.2GB).

FROM python:3.12-slim

# --- Install Ollama ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://ollama.com/install.sh | sh

# --- Python dependencies for the FastAPI wrapper ---
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py start.sh ./
RUN chmod +x start.sh

# Hugging Face Spaces requires the app to listen on port 7860.
# app.py itself doesn't hardcode a port — start.sh passes it via uvicorn's --port flag.
ENV PORT=7860
ENV OLLAMA_BASE_URL=http://localhost:11434
ENV DEFAULT_MODEL=phi3:mini

# HF Spaces containers run as a non-root user by convention; Ollama's
# installer needs a writable home for model storage.
ENV OLLAMA_MODELS=/app/.ollama/models
RUN mkdir -p /app/.ollama/models && chmod -R 777 /app/.ollama

EXPOSE 7860

CMD ["./start.sh"]
