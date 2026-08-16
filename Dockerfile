FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py mcp_server.py ./

# SERVICE_API_KEY, OLLAMA_BASE_URL, DEFAULT_MODEL are read from the
# environment at runtime — pass them with `docker run -e ...` or a
# compose file. This image does NOT bundle Ollama or a model; it only
# runs the FastAPI wrapper. Ollama must be reachable at OLLAMA_BASE_URL
# (e.g. running on the Docker host, or as a sibling container).
EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
