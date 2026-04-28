"""
PDF handler — loads PDFs, embeds them with sentence-transformers, stores
chunks in ChromaDB, and exposes semantic search via query_pdfs().
"""
import os
import re

import chromadb
from sentence_transformers import SentenceTransformer

try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

from config import PDF_DIR, CHROMA_DIR

COLLECTION_NAME = "pdf_library"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"   # 80 MB, fast, good quality

_embed_model: SentenceTransformer | None = None
_chroma_client: chromadb.PersistentClient | None = None
_collection = None


# ── internal helpers ──────────────────────────────────────────────────────────

def _embed_model_instance() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    return _embed_model


def _get_collection():
    global _chroma_client, _collection
    if _chroma_client is None:
        os.makedirs(CHROMA_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    if _collection is None:
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def _extract_text(filepath: str) -> str:
    if not HAS_PYPDF2:
        return ""
    try:
        parts: list[str] = []
        with open(filepath, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
        return "\n".join(parts)
    except Exception:
        return ""


def _chunk_text(text: str, chunk_size: int = 600) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) <= chunk_size:
            current += " " + sentence
        else:
            if current.strip():
                chunks.append(current.strip())
            current = sentence
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if len(c) > 40]


# ── public API ────────────────────────────────────────────────────────────────

def load_pdfs() -> int:
    """
    (Re-)index all PDFs in PDF_DIR into ChromaDB.
    Drops the existing collection first so stale chunks are removed.
    Returns the number of chunks embedded.
    """
    global _collection

    os.makedirs(PDF_DIR, exist_ok=True)

    # Drop and recreate so reloads are idempotent
    client = _chroma_client or chromadb.PersistentClient(path=CHROMA_DIR)
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    _collection = None

    collection = _get_collection()
    pdf_files = [f for f in os.listdir(PDF_DIR) if f.lower().endswith(".pdf")]
    if not pdf_files:
        return 0

    model = _embed_model_instance()
    all_ids, all_docs, all_metas = [], [], []

    for filename in sorted(pdf_files):
        text = _extract_text(os.path.join(PDF_DIR, filename))
        if not text:
            continue
        for i, chunk in enumerate(_chunk_text(text)):
            all_ids.append(f"{filename}__chunk_{i}")
            all_docs.append(chunk)
            all_metas.append({"source": filename, "chunk_idx": i})

    if not all_docs:
        return 0

    # Embed in batches so large libraries don't OOM
    batch_size = 64
    for i in range(0, len(all_docs), batch_size):
        b_ids   = all_ids[i : i + batch_size]
        b_docs  = all_docs[i : i + batch_size]
        b_metas = all_metas[i : i + batch_size]
        embeddings = model.encode(b_docs, show_progress_bar=False).tolist()
        collection.upsert(ids=b_ids, documents=b_docs, metadatas=b_metas, embeddings=embeddings)

    return len(all_docs)


def query_pdfs(question: str, top_k: int = 3) -> list[dict]:
    """
    Semantic search over embedded PDF chunks.
    Returns a list of dicts: {text, source, score}.
    Score is cosine similarity (higher = more relevant).
    """
    collection = _get_collection()
    if collection.count() == 0:
        return []

    model = _embed_model_instance()
    q_emb = model.encode([question], show_progress_bar=False).tolist()
    n = min(top_k, collection.count())

    results = collection.query(query_embeddings=q_emb, n_results=n)
    chunks: list[dict] = []
    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        chunks.append({"text": doc, "source": meta["source"], "score": round(1.0 - dist, 4)})

    return chunks


def get_pdf_list() -> list[str]:
    if not os.path.exists(PDF_DIR):
        return []
    return sorted(f for f in os.listdir(PDF_DIR) if f.lower().endswith(".pdf"))


# Pre-load on import so first query is fast
load_pdfs()
