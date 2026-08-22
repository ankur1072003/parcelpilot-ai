"""
Document ingestion + retrieval.

Trade-off (documented in ARCHITECTURE.md): we use a local TF-IDF index rather
than an embedding-based vector store. The corpus is 6 short documents
(~20-30 chunks total) — at this scale a managed/embedding vector DB adds
infra risk without adding retrieval quality, and this sandbox has no network
path to an embeddings API. TF-IDF over these documents is easy to test,
easy to explain in the demo, and swappable later (see PRODUCT.md "what's next").
"""
import pickle
import re
from pathlib import Path

import pdfplumber
import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def _extract_pdf_text(path: str) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _chunk_text(text: str, filename: str) -> list[dict]:
    """
    Split on numbered section headers (e.g. "1. Scope and source precedence"),
    which is how every supplied document is actually structured. Falls back to
    paragraph splitting if no numbered headers are found.
    """
    section_pattern = re.compile(r"(?m)^(\d+\.\s+.+)$")
    matches = list(section_pattern.finditer(text))

    chunks = []
    if matches:
        # preamble before first numbered section (title/status/effective lines)
        preamble = text[: matches[0].start()].strip()
        if preamble:
            chunks.append(preamble)
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunks.append(text[start:end].strip())
    else:
        chunks = [p.strip() for p in text.split("\n\n") if p.strip()]

    return [{"chunk_id": f"{filename}::chunk{i}", "text": c} for i, c in enumerate(chunks) if c]


def build_document_index(pdf_dir: str, registry_path: str, index_path: str) -> dict:
    with open(registry_path) as f:
        registry = yaml.safe_load(f)

    registry_by_filename = {d["filename"]: d for d in registry["documents"]}

    all_chunks = []  # list of dicts: chunk_id, text, metadata
    for filename, meta in registry_by_filename.items():
        pdf_path = Path(pdf_dir) / filename
        if not pdf_path.exists():
            raise FileNotFoundError(f"Registry references {filename} but it was not found in {pdf_dir}")
        text = _extract_pdf_text(str(pdf_path))
        chunks = _chunk_text(text, filename)
        for c in chunks:
            all_chunks.append({
                "chunk_id": c["chunk_id"],
                "text": c["text"],
                "filename": filename,
                "document_type": meta["document_type"],
                "version": meta.get("version"),
                "status": meta["status"],
                "effective_date": meta.get("effective_date"),
                "customer_scope": meta.get("customer_scope"),
                "authority_rank": meta["authority_rank"],
                "source_id": meta["source_id"],
            })

    texts = [c["text"] for c in all_chunks]
    vectorizer = TfidfVectorizer(stop_words="english")
    matrix = vectorizer.fit_transform(texts)

    with open(index_path, "wb") as f:
        pickle.dump({"chunks": all_chunks, "vectorizer": vectorizer, "matrix": matrix}, f)

    return {"num_chunks": len(all_chunks), "num_documents": len(registry_by_filename)}


def search_documents(index_path: str, query: str, document_types: list[str] | None = None,
                      customer_id: str | None = None, top_k: int = 5) -> list[dict]:
    with open(index_path, "rb") as f:
        idx = pickle.load(f)

    chunks, vectorizer, matrix = idx["chunks"], idx["vectorizer"], idx["matrix"]

    # filter candidates first (document_types / customer scope), then rank
    candidate_idxs = []
    for i, c in enumerate(chunks):
        if document_types and c["document_type"] not in document_types:
            continue
        if customer_id and c["customer_scope"] not in (None, customer_id):
            # a customer-scoped document belonging to a DIFFERENT customer is excluded
            continue
        candidate_idxs.append(i)

    if not candidate_idxs:
        return []

    q_vec = vectorizer.transform([query])
    sims = cosine_similarity(q_vec, matrix[candidate_idxs]).flatten()

    ranked = sorted(zip(candidate_idxs, sims), key=lambda x: x[1], reverse=True)[:top_k]

    results = []
    for i, score in ranked:
        c = chunks[i]
        results.append({
            "chunk_id": c["chunk_id"],
            "text": c["text"],
            "filename": c["filename"],
            "document_type": c["document_type"],
            "version": c["version"],
            "status": c["status"],
            "effective_date": c["effective_date"],
            "customer_scope": c["customer_scope"],
            "authority_rank": c["authority_rank"],
            "source_id": c["source_id"],
            "relevance_score": float(score),
        })
    return results
