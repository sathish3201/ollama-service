# Running the model directly on your Android phone (Termux)

This is a genuinely different setup from the laptop version — it runs
`llama.cpp` (not Ollama, which doesn't officially support Android) inside
Termux, with a quantized GGUF model, exposed via ngrok.

## Which model?

| Model | Size | Multimodal? | Notes |
|---|---|---|---|
| **Gemma 3 1B** (default) | ~815 MB | No (text-only) | Recommended for phones — noticeably lighter on RAM, storage, and battery, still capable for RAG-style Q&A. |
| Phi-3-mini | ~2.3 GB | No (text-only) | Larger, more capable, but meaningfully heavier to run on a phone. |
| SmolVLM2-500M | ~546 MB | **Yes** (image + video frames) | The multimodal option that actually fits a 4GB-RAM phone. Ungated — no HF token needed. See "Multimodal: images, video, and PDFs" below. |

Pass `MODEL=phi3` or `MODEL=smolvlm2` to both scripts to switch (must match
between `setup.sh` and `start.sh`):

```bash
MODEL=phi3 bash setup.sh
MODEL=phi3 bash start.sh

# or:
MODEL=smolvlm2 bash setup.sh
MODEL=smolvlm2 bash start.sh
```

**Gemma 3 4B and other larger vision models are not included here** —
they need ~4GB of download and ~5GB of RAM at runtime, which doesn't fit
a phone with 4GB RAM or less. SmolVLM2-500M is the realistic multimodal
option at that budget.

## Read this before you start

- **Install Termux from F-Droid or GitHub releases — not the Play Store
  version** (outdated, broken). You said you already have it installed;
  double check it's the maintained build.
- **This will use real battery and generate heat**, though noticeably
  less with Gemma 3 1B than with the larger Phi-3-mini. Expect faster
  battery drain than idle either way while the model is active.
- **Android WILL try to kill this in the background** unless you take
  the wake-lock and battery-optimization steps below. This is the
  biggest practical risk to "always on."
- **Auth is different here than on the laptop setup.** `llama-server`
  (llama.cpp's built-in OpenAI-compatible server) has **no API key
  check of its own** — so this setup uses ngrok's `--basic-auth` flag
  instead. Clients authenticate with **HTTP Basic Auth**
  (`username:apikey`, `password:<your key>`), not a `Bearer` token like
  the FastAPI/laptop version used.

## Setup (run in Termux, on your phone)

**Gemma's GGUF repo on Hugging Face is gated**, so you need a token before
running setup:

1. Visit https://huggingface.co/google/gemma-3-1b-it-qat-q4_0-gguf while
   logged in and click **"Agree and access repository"** (one-time).
2. Create a read token at https://huggingface.co/settings/tokens.
3. Export it in Termux before running setup:
   ```bash
   export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx
   ```

Without this, `setup.sh` fails with `401 Unauthorized` when downloading
the model. (If you use `MODEL=phi3` instead, Phi-3-mini's repo isn't
gated, so `HF_TOKEN` isn't required in that case.)

```bash
bash setup.sh
```

This installs build tools, compiles llama.cpp for your phone's ARM
architecture, downloads the quantized model (**Gemma 3 1B, ~815MB, by
default** — do this on Wi-Fi), and installs ngrok.

**ngrok runs inside an Ubuntu proot** (`proot-distro`), not directly in
Termux — on some devices the plain Termux binary fails with
`error: "ngrok" has unexpected e_type: 2` because ngrok's Linux build
doesn't run reliably under Termux's Bionic/Android userland. `setup.sh`
installs `proot-distro`, an Ubuntu rootfs, and ngrok inside it
automatically. Ubuntu shares Termux's network namespace, so ngrok there
can still reach `llama-server` on `127.0.0.1`.

Add your ngrok authtoken (free — get it from
https://dashboard.ngrok.com/get-started/your-authtoken) **inside the
Ubuntu proot**:

```bash
proot-distro login ubuntu -- ngrok config add-authtoken <YOUR_TOKEN>
```

## Keeping it alive in the background

Before starting the server, in Termux run:

```bash
termux-wake-lock
```

This tells Android not to suspend Termux's CPU while it's backgrounded.
Additionally, in **Android Settings → Apps → Termux → Battery**, set
battery optimization to **"Unrestricted"** (not "Optimized"). Without
both of these, Android will very likely kill the process after a few
minutes of screen-off time.

## Start the server + tunnel

```bash
bash start.sh
```

This starts `llama-server` on port 8080, then opens an ngrok tunnel with
basic-auth protection. Watch the output for a line like:

```
url=https://something-random.ngrok-free.dev
```

That's your public URL — it changes each time ngrok restarts unless you
claim a static free domain.

## Calling it from your notebook / any client

Because auth is HTTP Basic (not Bearer) here, the `OpenAI()` client needs
a small adjustment vs. the laptop version:

```python
from openai import OpenAI
import httpx

client = OpenAI(
    api_key="unused",  # llama-server doesn't check this field itself
    base_url="https://your-phone-tunnel.ngrok-free.dev/v1",
    http_client=httpx.Client(auth=("apikey", "sk-local-...")),  # HTTP Basic Auth
)

response = client.chat.completions.create(
    model="gemma3-1b",  # llama-server ignores the model name (only one loaded)
    messages=[{"role": "user", "content": "What is RAG?"}],
)
print(response.choices[0].message.content)
```

## Multimodal: images, video, and PDFs (MODEL=smolvlm2)

SmolVLM2-500M understands **images** (and video frames, since it's the
"Video-Instruct" variant) — it does not read raw video files or PDFs
directly. Nothing in the llama.cpp / GGUF ecosystem does that today.
The trick is turning video/PDF into images first, then sending those.

`setup.sh` installs `ffmpeg` and `poppler` (for `pdftoppm`) for exactly
this.

**PDF → images:**
```bash
pdftoppm -jpeg -r 150 document.pdf page
# produces page-1.jpg, page-2.jpg, ...
```

**Video → frames:** (grab one frame every 2 seconds, adjust `fps` as needed)
```bash
ffmpeg -i video.mp4 -vf fps=1/2 frame-%03d.jpg
```

**Sending an image to the model** — base64-encode it and send as an
`image_url` content block in the OpenAI-compatible chat endpoint:

```bash
python3 -c "
import base64, json
img = base64.b64encode(open('page-1.jpg','rb').read()).decode()
print(json.dumps({
    'model': 'smolvlm2',
    'messages': [{
        'role': 'user',
        'content': [
            {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{img}'}},
            {'type': 'text', 'text': 'Summarize this page.'}
        ]
    }]
}))" > /tmp/req.json

curl -s -u apikey:sk-local-... \
  http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d @/tmp/req.json
```

For a multi-page PDF or multi-frame video, loop over the extracted
images and call the endpoint once per image (SmolVLM2-500M handles one
image well; feeding it many at once will strain the RAM budget). To
summarize a whole document/video, ask it to summarize each
page/frame individually, then feed those summaries back into the model
as plain text for a final combined summary.

## Running the laptop and phone at the same time

Nothing stops both being up simultaneously — they're independent
services with independent ngrok URLs. You'd just point different
clients at whichever URL is currently live, the same way you'd pick
between two API providers. There's no built-in failover between them;
your application code would need to try one, then the other, if you
want that.
