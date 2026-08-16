#!/bin/bash
# Starts Ollama in the background, waits for it to be ready, pulls the
# default model if not already present, then starts the FastAPI wrapper
# in the foreground (so the container stays alive as long as it runs).
set -e

echo "Starting Ollama server..."
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama's API to respond before doing anything else.
echo "Waiting for Ollama to be ready..."
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
  sleep 1
done
echo "Ollama is ready."

# Pull the model if it isn't already present in the persisted volume.
if ! ollama list | grep -q "${DEFAULT_MODEL}"; then
  echo "Pulling model: ${DEFAULT_MODEL} (first run only — this can take a few minutes)"
  ollama pull "${DEFAULT_MODEL}"
else
  echo "Model ${DEFAULT_MODEL} already present."
fi

echo "Starting FastAPI service on port ${PORT}..."
exec uvicorn app:app --host 0.0.0.0 --port "${PORT}"
