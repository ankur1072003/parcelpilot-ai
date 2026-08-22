import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.data.db import ingest_xlsx_to_sqlite
from app.retrieval.index import build_document_index


@pytest.fixture(scope="session")
def db_path():
    path = REPO_ROOT / "data" / "parcelpilot.db"
    if not path.exists():
        ingest_xlsx_to_sqlite(
            str(REPO_ROOT / "data" / "raw" / "ParcelPilot_Assessment_Data.xlsx"), str(path)
        )
    return str(path)


@pytest.fixture(scope="session")
def index_path():
    path = REPO_ROOT / "data" / "doc_index.pkl"
    if not path.exists():
        build_document_index(
            str(REPO_ROOT / "data" / "raw"),
            str(REPO_ROOT / "config" / "document_registry.yaml"),
            str(path),
        )
    return str(path)


@pytest.fixture
def actions_db_path():
    """Fresh, isolated SQLite file per test so action-state tests don't interfere."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name
