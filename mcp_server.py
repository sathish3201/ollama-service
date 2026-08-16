"""
MCP server exposing the local Ollama model as a tool.

Wraps the same FastAPI service (app.py) that must already be running,
so MCP clients (e.g. Claude Code, via `claude mcp add`) can call the
local model as a tool named `ask_local_model`.

Run standalone for a quick check:
    python mcp_server.py

Register with an MCP client (stdio transport) pointing at this script.
Requires the FastAPI service (app.py) to be running and SERVICE_API_KEY
set in the environment.
"""

import os

import httpx
from mcp.server.fastmcp import FastMCP

SERVICE_URL = os.environ.get("SERVICE_URL", "http://localhost:8000")
API_KEY = os.environ.get("SERVICE_API_KEY")
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "phi3:mini")

if not API_KEY:
    raise RuntimeError(
        "SERVICE_API_KEY environment variable is not set. "
        "It must match the key app.py was started with."
    )

mcp = FastMCP("local-ollama")


@mcp.tool()
async def ask_local_model(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """
    Ask the locally-running Ollama model a question.

    Args:
        prompt: The question or instruction to send to the model.
        model: Which local model to use (default: phi3:mini).
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {"Authorization": f"Bearer {API_KEY}"}

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{SERVICE_URL}/v1/chat/completions", json=payload, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    mcp.run(transport="stdio")
