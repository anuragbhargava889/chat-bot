import os
import re
from config import PDF_DIR

try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

_all_chunks: list[str] = []
_chunk_sources: list[str] = []


def load_pdfs():
    global _all_chunks, _chunk_sources
    _all_chunks = []
    _chunk_sources = []

    if not os.path.exists(PDF_DIR):
        os.makedirs(PDF_DIR, exist_ok=True)
        return

    for filename in sorted(os.listdir(PDF_DIR)):
        if not filename.lower().endswith(".pdf"):
            continue
        filepath = os.path.join(PDF_DIR, filename)
        text = _extract_text(filepath)
        if text:
            for chunk in _chunk_text(text):
                _all_chunks.append(chunk)
                _chunk_sources.append(filename)


def _extract_text(filepath: str) -> str:
    if not HAS_PYPDF2:
        return ""
    try:
        text_parts = []
        with open(filepath, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                part = page.extract_text()
                if part:
                    text_parts.append(part)
        return "\n".join(text_parts)
    except Exception:
        return ""


def _chunk_text(text: str, chunk_size: int = 600, overlap: int = 100) -> list[str]:
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


def answer_from_pdfs(question: str) -> str:
    if not _all_chunks:
        load_pdfs()

    if not _all_chunks:
        return (
            "No PDF documents are loaded in the library yet. "
            "Please add PDF files to the `pdfs/` directory and ask an admin to reload."
        )

    if HAS_SKLEARN:
        return _tfidf_answer(question)
    return _keyword_answer(question)


def _tfidf_answer(question: str) -> str:
    try:
        corpus = _all_chunks + [question]
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        matrix = vectorizer.fit_transform(corpus)
        sims = cosine_similarity(matrix[-1], matrix[:-1])[0]
        best = int(np.argmax(sims))
        if sims[best] < 0.08:
            return "I could not find a relevant answer in the PDF library for your question."
        return f"**Source: {_chunk_sources[best]}**\n\n{_all_chunks[best]}"
    except Exception:
        return _keyword_answer(question)


def _keyword_answer(question: str) -> str:
    keywords = set(re.sub(r"[^\w\s]", "", question.lower()).split())
    best_score, best_chunk, best_source = 0, None, None
    for chunk, source in zip(_all_chunks, _chunk_sources):
        score = len(keywords & set(chunk.lower().split()))
        if score > best_score:
            best_score, best_chunk, best_source = score, chunk, source
    if best_chunk:
        return f"**Source: {best_source}**\n\n{best_chunk}"
    return "I could not find a relevant answer in the PDF library for your question."


def get_pdf_list() -> list[str]:
    if not os.path.exists(PDF_DIR):
        return []
    return sorted(f for f in os.listdir(PDF_DIR) if f.lower().endswith(".pdf"))


# Pre-load on import so first query is fast
load_pdfs()
