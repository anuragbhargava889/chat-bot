FROM python:3.11-slim

WORKDIR /app

# System deps: build tools for chromadb/sentence-transformers native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer cache)
COPY requirements.txt requirements-anthropic.txt requirements-groq.txt \
     requirements-openai.txt requirements-ollama.txt ./

# Install base + all provider packages so the image works with any LLM_PROVIDER
RUN pip install --no-cache-dir \
    -r requirements.txt \
    langchain-anthropic>=0.3.0 \
    langchain-groq>=0.2.0 \
    langchain-openai>=0.2.0 \
    langchain-ollama>=0.2.0 \
    gunicorn

# Copy application code
COPY . .

# ChromaDB and PDF volumes — these paths are overridable via env vars
VOLUME ["/app/chroma_db", "/app/pdfs"]

EXPOSE 5000

# Gunicorn with threading for SSE streaming
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--worker-class", "gthread", \
     "--workers", "2", "--threads", "4", "--timeout", "120", "app:app"]
