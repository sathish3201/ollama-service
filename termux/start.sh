#!/data/data/com.termux/files/usr/bin/bash
# Run this INSIDE Termux on your Android phone, AFTER setup.sh has
# completed and you've added your ngrok authtoken.
#
# Starts llama.cpp's OpenAI-compatible server + an ngrok tunnel.
#
# IMPORTANT — keeping this alive:
#   Android will kill Termux if it goes to the background without a
#   "wake lock". Before running this, in a SEPARATE Termux session run:
#       termux-wake-lock
#   This prevents Android's battery optimizer from killing the process.
#   Also: in Termux's Android app settings, disable battery optimization
#   for Termux itself, or Android may still kill it after a while.
set -e

MODEL_PATH=~/models/Phi-3-mini-4k-instruct-q4.gguf
SERVICE_API_KEY="${SERVICE_API_KEY:-sk-local-7a79296a92b11ca6bfef66a86afc1a39f67c59380af5fcfc}"
PORT=8080

if [ ! -f "$MODEL_PATH" ]; then
  echo "Model not found at $MODEL_PATH — run setup.sh first."
  exit 1
fi

echo "=== Starting llama.cpp server on port $PORT ==="
echo "(This exposes an OpenAI-compatible /v1/chat/completions endpoint,"
echo " but llama-server has NO built-in API key check — that's what"
echo " the ngrok basic-auth flag below adds.)"

cd ~/llama.cpp
./build/bin/llama-server \
  -m "$MODEL_PATH" \
  --port "$PORT" \
  --host 0.0.0.0 \
  -c 4096 \
  &
LLAMA_PID=$!

echo "Waiting for llama-server to be ready..."
until curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; do
  sleep 1
done
echo "llama-server is ready (PID $LLAMA_PID)."

echo "=== Starting ngrok tunnel with basic-auth protection ==="
echo "(llama-server itself has no API key check, so ngrok's basic-auth"
echo " is what protects this endpoint from being open to the internet.)"
ngrok http "$PORT" --basic-auth="apikey:${SERVICE_API_KEY}" --log=stdout
