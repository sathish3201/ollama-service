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

# Default: Gemma 3 1B (~815MB, lighter and faster on phones, text-only).
# Must match whatever you passed to setup.sh, e.g.:  MODEL=phi3 bash start.sh
#   MODEL=phi3      -> phi-3-mini, text-only, ~2.3GB
#   MODEL=smolvlm2  -> SmolVLM2-500M, multimodal (image + video frames), ~546MB
MODEL="${MODEL:-gemma3-1b}"
MMPROJ_PATH=""
if [ "$MODEL" = "gemma3-1b" ]; then
  MODEL_PATH=~/models/gemma-3-1b-it-q4_0.gguf
elif [ "$MODEL" = "phi3" ]; then
  MODEL_PATH=~/models/Phi-3-mini-4k-instruct-q4.gguf
elif [ "$MODEL" = "smolvlm2" ]; then
  MODEL_PATH=~/models/SmolVLM2-500M-Video-Instruct-Q8_0.gguf
  MMPROJ_PATH=~/models/mmproj-SmolVLM2-500M-Video-Instruct-Q8_0.gguf
else
  echo "Unknown MODEL='$MODEL' — expected 'gemma3-1b', 'phi3', or 'smolvlm2'"
  exit 1
fi

SERVICE_API_KEY="${SERVICE_API_KEY:-sk-local-7a79296a92b11ca6bfef66a86afc1a39f67c59380af5fcfc}"
PORT=8080

if [ ! -s "$MODEL_PATH" ]; then
  echo "Model missing or empty at $MODEL_PATH — run setup.sh first (with the same MODEL=... value)."
  echo "(An empty file usually means a previous download failed partway — delete it and re-run setup.sh.)"
  exit 1
fi
if [ -n "$MMPROJ_PATH" ] && [ ! -s "$MMPROJ_PATH" ]; then
  echo "mmproj file missing or empty at $MMPROJ_PATH — run setup.sh first (with the same MODEL=... value)."
  exit 1
fi

echo "=== Starting llama.cpp server on port $PORT ==="
echo "(This exposes an OpenAI-compatible /v1/chat/completions endpoint."
echo " --api-key makes llama-server check for 'Authorization: Bearer"
echo " <key>' itself, matching the laptop/FastAPI setup — so both"
echo " backends can share the same auth scheme and the same LOCAL_MODEL_*"
echo " env vars on Render, regardless of which one is currently up.)"

cd ~/llama.cpp
if [ -n "$MMPROJ_PATH" ]; then
  ./build/bin/llama-server \
    -m "$MODEL_PATH" \
    --mmproj "$MMPROJ_PATH" \
    --port "$PORT" \
    --host 0.0.0.0 \
    -c 4096 \
    --parallel 1 \
    --api-key "$SERVICE_API_KEY" \
    &
else
  ./build/bin/llama-server \
    -m "$MODEL_PATH" \
    --port "$PORT" \
    --host 0.0.0.0 \
    -c 4096 \
    --parallel 1 \
    --api-key "$SERVICE_API_KEY" \
    &
fi
LLAMA_PID=$!

echo "Waiting for llama-server to be ready..."
until curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; do
  sleep 1
done
echo "llama-server is ready (PID $LLAMA_PID)."

echo "=== Starting ngrok tunnel ==="
echo "(No ngrok-side auth needed anymore — llama-server's --api-key"
echo " above now enforces Bearer auth itself.)"
echo "(ngrok runs inside the Ubuntu proot — see setup.sh — since it can"
echo " fail with 'unexpected e_type' when run directly under Termux."
echo " Ubuntu shares Termux's network namespace, so 127.0.0.1:$PORT"
echo " here reaches the llama-server we just started above.)"
proot-distro login ubuntu -- ngrok http "$PORT" --log=stdout
