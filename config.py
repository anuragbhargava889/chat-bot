import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'chatbot_db'),
    'port': int(os.getenv('DB_PORT', 3306)),
}


def get_db_uri() -> str:
    """SQLAlchemy connection URI for LangChain SQLDatabase."""
    c = DB_CONFIG
    return (
        f"mysql+mysqlconnector://{quote_plus(c['user'])}:{quote_plus(c['password'])}"
        f"@{c['host']}:{c['port']}/{c['database']}"
    )

PDF_DIR = os.getenv('PDF_DIR', os.path.join(os.path.dirname(__file__), 'pdfs'))
SECRET_KEY = os.getenv('SECRET_KEY', 'change-this-secret-key-in-production')

# Vector database — ChromaDB persists embeddings here so re-loading PDFs
# is fast after the first run.
CHROMA_DIR = os.getenv('CHROMA_DIR', os.path.join(os.path.dirname(__file__), 'chroma_db'))

# LLM provider configuration
# LLM_PROVIDER: ollama | openai | anthropic | groq
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'ollama')
LLM_MODEL    = os.getenv('LLM_MODEL',    'llama3.1')
LLM_API_KEY  = os.getenv('LLM_API_KEY',  '')
# LLM_BASE_URL: required for ollama; optional override for openai-compatible endpoints.
# Intentionally no default here — the ollama default is applied inside get_llm() only.
LLM_BASE_URL = os.getenv('LLM_BASE_URL', '')


def get_llm():
    """Return a LangChain chat model based on LLM_PROVIDER in .env."""
    provider = LLM_PROVIDER.lower()

    if provider == 'ollama':
        # Fall back to OLLAMA_HOST for backward compatibility, then to localhost.
        base_url = LLM_BASE_URL or os.getenv('OLLAMA_HOST', 'http://localhost:11434')
        from langchain_ollama import ChatOllama
        return ChatOllama(model=LLM_MODEL, base_url=base_url, temperature=0)

    if provider == 'openai':
        from langchain_openai import ChatOpenAI
        kwargs = dict(model=LLM_MODEL, api_key=LLM_API_KEY, temperature=0)
        if LLM_BASE_URL:
            kwargs['base_url'] = LLM_BASE_URL
        return ChatOpenAI(**kwargs)

    if provider == 'anthropic':
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=LLM_MODEL, api_key=LLM_API_KEY, temperature=0)

    if provider == 'groq':
        from langchain_groq import ChatGroq
        return ChatGroq(model=LLM_MODEL, api_key=LLM_API_KEY, temperature=0)

    raise ValueError(
        f"Unsupported LLM_PROVIDER={provider!r}. "
        "Choose one of: ollama, openai, anthropic, groq"
    )
