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

echo "=== Step 5: Download model GGUF ==="
mkdir -p ~/models
cd ~/models

# Default: Gemma 3 1B (~815MB) — much lighter than phi3-mini, the
# recommended choice for phones. Set MODEL=phi3 to pull the larger
# phi-3-mini (~2.3GB) instead, e.g.:  MODEL=phi3 bash setup.sh
MODEL="${MODEL:-gemma3-1b}"

if [ "$MODEL" = "gemma3-1b" ]; then
  # Gemma repos on Hugging Face are gated: you must (1) accept the
  # license at https://huggingface.co/google/gemma-3-1b-it-qat-q4_0-gguf
  # while logged in, and (2) pass a token here, or the download gets a
  # 401 Unauthorized. Get a token from https://huggingface.co/settings/tokens
  # and export it before running this script:  export HF_TOKEN=hf_xxx
  if [ -z "$HF_TOKEN" ]; then
    echo "ERROR: HF_TOKEN is not set."
    echo "Gemma's GGUF repo is gated — export a Hugging Face token first:"
    echo "  export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx"
    echo "(create one at https://huggingface.co/settings/tokens, and make"
    echo " sure you've clicked 'Agree and access repository' at"
    echo " https://huggingface.co/google/gemma-3-1b-it-qat-q4_0-gguf)"
    exit 1
  fi
  if [ ! -f "gemma-3-1b-it-q4_0.gguf" ]; then
    wget --header="Authorization: Bearer $HF_TOKEN" \
      -O gemma-3-1b-it-q4_0.gguf \
      "https://huggingface.co/google/gemma-3-1b-it-qat-q4_0-gguf/resolve/main/gemma-3-1b-it-q4_0.gguf"
  fi
elif [ "$MODEL" = "phi3" ]; then
  if [ ! -f "Phi-3-mini-4k-instruct-q4.gguf" ]; then
    wget -O Phi-3-mini-4k-instruct-q4.gguf \
      "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf"
  fi
else
  echo "Unknown MODEL='$MODEL' — expected 'gemma3-1b' or 'phi3'"
  exit 1
fi

echo "=== Step 6: Install ngrok (inside an Ubuntu proot) ==="
# ngrok's Linux binary doesn't run reliably directly under Termux's
# Bionic/Android userland on some devices (fails with
# `unexpected e_type: 2`). Running it inside a proot-distro Ubuntu
# (a real glibc ARM64 userland) avoids that. Ubuntu shares Termux's
# network namespace, so ngrok there can still reach llama-server via
# localhost.
pkg install -y proot-distro
if ! proot-distro list 2>/dev/null | grep -q "ubuntu.*installed"; then
  proot-distro install ubuntu
fi

proot-distro login ubuntu -- bash -c '
  set -e
  apt update -y
  apt install -y wget tar ca-certificates
  if ! command -v ngrok >/dev/null 2>&1; then
    cd /tmp
    wget -O ngrok.tgz "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz"
    tar -xzf ngrok.tgz
    mv ngrok /usr/local/bin/
    chmod +x /usr/local/bin/ngrok
  fi
  ngrok version
'

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "1. Run: proot-distro login ubuntu -- ngrok config add-authtoken <YOUR_NGROK_TOKEN>"
echo "   (get your token from https://dashboard.ngrok.com/get-started/your-authtoken)"
echo "2. Run: bash start.sh"
