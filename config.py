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

# Anthropic Claude API
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')

# LLM used for intent routing, entity extraction, and response generation.
# claude-haiku-4-5 for fast classification calls; claude-opus-4-7 for richer answers.
LLM_FAST  = os.getenv('LLM_FAST',  'claude-haiku-4-5')
LLM_SMART = os.getenv('LLM_SMART', 'claude-opus-4-7')
