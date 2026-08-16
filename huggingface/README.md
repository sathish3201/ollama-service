---
title: Ollama RAG Service
emoji: 🦙
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# Ollama RAG Service (Hugging Face Space)

A free, publicly-reachable OpenAI-compatible API backed by a local Ollama
model (`phi3:mini`), running entirely inside this Space's container.

## Endpoints

- `GET /health` — unauthenticated health check
- `POST /v1/chat/completions` — OpenAI-compatible chat completions.
  Requires `Authorization: Bearer <SERVICE_API_KEY>`.

## Required Space secret

Set this in **Settings → Variables and secrets** on this Space (not in
this file, and never committed to git):

| Name | Value |
|---|---|
| `SERVICE_API_KEY` | Your own generated key (see the parent repo's README) |

## Notes on the free tier

- **2 vCPU / 16GB RAM** — enough headroom for `phi3:mini` (2.2GB).
- The Space **sleeps after a period of inactivity** on the free tier and
  cold-starts on the next request. The first request after a sleep will
  be slow because `start.sh` re-pulls/verifies the model.
- Public Spaces are, by definition, reachable by anyone with the URL —
  the `SERVICE_API_KEY` check in `app.py` is what actually protects the
  `/v1/chat/completions` endpoint. Keep the key secret and out of any
  public repo.
