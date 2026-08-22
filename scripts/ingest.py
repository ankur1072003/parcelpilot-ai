"""
Ingestion entrypoint. Safe to rerun — drops and recreates tables/index each time.

Usage:
    python scripts/ingest.py
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.data.db import ingest_xlsx_to_sqlite  # noqa: E402
from app.retrieval.index import build_document_index  # noqa: E402


def main():
    xlsx_path = REPO_ROOT / "data" / "raw" / "ParcelPilot_Assessment_Data.xlsx"
    db_path = REPO_ROOT / "data" / "parcelpilot.db"
    registry_path = REPO_ROOT / "config" / "document_registry.yaml"
    pdf_dir = REPO_ROOT / "data" / "raw"
    index_path = REPO_ROOT / "data" / "doc_index.pkl"

    print(f"[1/2] Ingesting structured data from {xlsx_path.name} -> {db_path.name}")
    summary = ingest_xlsx_to_sqlite(str(xlsx_path), str(db_path))
    for table, count in summary.items():
        print(f"      {table}: {count} rows")

    print(f"[2/2] Building document retrieval index from {pdf_dir}")
    doc_summary = build_document_index(str(pdf_dir), str(registry_path), str(index_path))
    print(f"      indexed {doc_summary['num_chunks']} chunks from {doc_summary['num_documents']} documents")

    print("Ingestion complete.")


if __name__ == "__main__":
    main()
