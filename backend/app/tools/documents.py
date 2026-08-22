"""
Tool 1 — search_documents.

Read-only, no authorization concerns beyond customer-scoping (a document
scoped to one customer's agreement should not leak into another customer's
answer). Account-level authorization for STRUCTURED data lives in
tools/structured.py; this tool only filters documents by customer_scope.
"""
from app.retrieval.index import search_documents as _search_documents
from app.reliability.authority import Evidence


def search_documents(index_path: str, query: str, document_types: list[str] | None = None,
                      customer_id: str | None = None, top_k: int = 5) -> list[Evidence]:
    raw_results = _search_documents(index_path, query, document_types, customer_id, top_k)
    return [
        Evidence(
            source_id=r["source_id"],
            filename=r["filename"],
            status=r["status"],
            authority_rank=r["authority_rank"],
            text=r["text"],
            customer_scope=r["customer_scope"],
        )
        for r in raw_results
    ]
