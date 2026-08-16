# Running the model directly on your Android phone (Termux)

This is a genuinely different setup from the laptop version — it runs
`llama.cpp` (not Ollama, which doesn't officially support Android) inside
Termux, with a quantized Phi-3-mini GGUF model, exposed via ngrok.

## Read this before you start

- **Install Termux from F-Droid or GitHub releases — not the Play Store
  version** (outdated, broken). You said you already have it installed;
  double check it's the maintained build.
- **This will use real battery and generate heat.** Running a ~4GB model
  continuously is genuinely demanding for a phone. Expect noticeably
  faster battery drain while it's active.
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

```bash
bash setup.sh
```

This installs build tools, compiles llama.cpp for your phone's ARM
architecture, downloads the quantized Phi-3-mini model (~2.3GB — do this
on Wi-Fi), and installs ngrok.

Then add your ngrok authtoken (free — get it from
https://dashboard.ngrok.com/get-started/your-authtoken):

```bash
ngrok config add-authtoken <YOUR_TOKEN>
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
    model="phi3-mini",  # llama-server ignores the model name (only one loaded)
    messages=[{"role": "user", "content": "What is RAG?"}],
)
print(response.choices[0].message.content)
```

## Running the laptop and phone at the same time

Nothing stops both being up simultaneously — they're independent
services with independent ngrok URLs. You'd just point different
clients at whichever URL is currently live, the same way you'd pick
between two API providers. There's no built-in failover between them;
your application code would need to try one, then the other, if you
want that.
