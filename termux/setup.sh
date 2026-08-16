#!/data/data/com.termux/files/usr/bin/bash
# Run this INSIDE Termux on your Android phone.
#
# Sets up a local, OpenAI-compatible LLM server on the phone itself using
# llama.cpp (compiled for Android/ARM) + a small GGUF model + ngrok for
# public access. No cloud host, no laptop required once this is running.
#
# Usage (from Termux):
#   bash setup.sh
set -e

echo "=== Step 1: Update Termux packages ==="
pkg update -y && pkg upgrade -y

echo "=== Step 2: Install build tools + git + cmake + wget ==="
pkg install -y git cmake golang wget clang make

echo "=== Step 3: Grant storage access (needed to save the model file) ==="
termux-setup-storage || true

echo "=== Step 4: Clone and build llama.cpp ==="
cd ~
if [ ! -d "llama.cpp" ]; then
  git clone https://github.com/ggerganov/llama.cpp.git
fi
cd llama.cpp
cmake -B build
cmake --build build --config Release -j"$(nproc)"

echo "=== Step 5: Download phi-3-mini GGUF (quantized, ~2.3GB) ==="
mkdir -p ~/models
cd ~/models
if [ ! -f "Phi-3-mini-4k-instruct-q4.gguf" ]; then
  wget -O Phi-3-mini-4k-instruct-q4.gguf \
    "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf"
fi

echo "=== Step 6: Install ngrok ==="
pkg install -y ngrok || {
  echo "ngrok not in pkg repo — installing manually"
  ARCH=$(uname -m)
  cd ~
  wget -O ngrok.tgz "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz"
  tar -xzf ngrok.tgz
  mv ngrok "$PREFIX/bin/"
}

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "1. Run: ngrok config add-authtoken <YOUR_NGROK_TOKEN>"
echo "   (get your token from https://dashboard.ngrok.com/get-started/your-authtoken)"
echo "2. Run: bash start.sh"
