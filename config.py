import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'chatbot_db'),
    'port': int(os.getenv('DB_PORT', 3306)),
}

PDF_DIR = os.getenv('PDF_DIR', os.path.join(os.path.dirname(__file__), 'pdfs'))
SECRET_KEY = os.getenv('SECRET_KEY', 'change-this-secret-key-in-production')

# Vector database — ChromaDB persists embeddings here so re-loading PDFs
# is fast after the first run.
CHROMA_DIR = os.getenv('CHROMA_DIR', os.path.join(os.path.dirname(__file__), 'chroma_db'))

# Ollama LLM configuration — install Ollama from https://ollama.com
# then run: ollama pull llama3.1
OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
LLM_MODEL   = os.getenv('LLM_MODEL',   'llama3.1')
