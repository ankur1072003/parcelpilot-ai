"""
FastAPI application. Run with:
    uvicorn app.main:app --reload --port 8000

LIMITATION: /api/chat calls the live agent orchestrator, which requires
OPENAI_API_KEY. Without it, /api/chat will return a 500 — every other
endpoint (login, actions, ops insights) works without a key since they only
touch the deterministic tool/data layer.
"""
import os
import sys
import yaml
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"
sys.path.insert(0, str(REPO_ROOT / "backend"))

load_dotenv(dotenv_path=REPO_ROOT / ".env")

from app.security.auth import resolve_user_context, AuthorizationError
from app.tools import actions as tools_actions
from app.tools import structured as tools_structured

def _resolve_path(env_var_name: str, default_relative_path: str) -> str:
    raw = os.environ.get(env_var_name)
    if raw:
        p = Path(raw)
        return str(p if p.is_absolute() else (REPO_ROOT / p).resolve())
    return str((REPO_ROOT / default_relative_path).resolve())


DB_PATH = _resolve_path("DATABASE_PATH", "data/parcelpilot.db")
ACTIONS_DB_PATH = _resolve_path("ACTIONS_DATABASE_PATH", "data/actions.db")
INDEX_PATH = _resolve_path("VECTOR_STORE_PATH", "data/doc_index.pkl")

with open(REPO_ROOT / "config" / "document_registry.yaml") as f:
    _registry = yaml.safe_load(f)
REFERENCE_TIME = datetime.fromisoformat(_registry["dataset_snapshot_time"]).replace(tzinfo=None)

app = FastAPI(title="ParcelPilot Ops Copilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo only — restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    demo_user_id: str
    conversation: list[dict]  # [{"role": "user"|"assistant", "content": str}, ...]


class ConfirmRequest(BaseModel):
    demo_user_id: str
    confirm: bool


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/whoami")
def whoami(demo_user_id: str):
    try:
        ctx = resolve_user_context(demo_user_id)
    except AuthorizationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return {
        "user_id": ctx.user_id,
        "role": ctx.role,
        "permitted_account_ids": list(ctx.permitted_account_ids) or "ALL",
    }


@app.post("/api/chat")
def chat(req: ChatRequest):
    from app.agent.orchestrator import run_agent_turn  # imported lazily: needs API key at call time
    try:
        return run_agent_turn(req.demo_user_id, req.conversation, DB_PATH, INDEX_PATH, REFERENCE_TIME,
                              actions_db_path=ACTIONS_DB_PATH)
    except AuthorizationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/actions/{action_id}")
def get_action(action_id: str):
    action = tools_actions.get_action(ACTIONS_DB_PATH, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="No such action")
    return action


@app.post("/api/actions/{action_id}/confirm")
def confirm_action(action_id: str, req: ConfirmRequest):
    try:
        ctx = resolve_user_context(req.demo_user_id)
        return tools_actions.confirm_action(ACTIONS_DB_PATH, ctx, action_id, req.confirm)
    except AuthorizationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except tools_actions.ActionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/ops/insights")
def ops_insights(demo_user_id: str):
    """Problem 1: Proactive Issue Detection — manager/admin only (enforced in the tool layer)."""
    try:
        ctx = resolve_user_context(demo_user_id)
        open_tickets = tools_structured.find_high_severity_or_sla_risk_tickets(DB_PATH, ctx)
    except AuthorizationError as e:
        raise HTTPException(status_code=403, detail=str(e))

    # simple rule-based clustering (§12) — repeated subject keywords across accounts
    from collections import defaultdict
    clusters = defaultdict(list)
    for t in open_tickets:
        key = None
        subject = (t.get("subject") or "").lower()
        if "bulk upload" in subject or "csv" in subject:
            key = "Bulk upload / CSV failures (matches known issue KI-208)"
        elif "booked" in subject and "pickup" in subject:
            key = "Shipment stuck showing BOOKED after pickup (matches known issue KI-211)"
        elif "shipment creation" in subject or "500" in subject:
            key = "Shipment creation failures (possible P1 outage)"
        elif "api key" in subject or "security" in subject:
            key = "Security-sensitive report (possible P1 escalation)"
        if key:
            clusters[key].append(t["ticket_id"])

    insights = [
        {"title": title, "affected_tickets": ids, "ticket_count": len(ids)}
        for title, ids in clusters.items()
    ]
    return {"insights": insights, "reference_time": REFERENCE_TIME.isoformat()}


@app.get("/")
def serve_frontend():
    return FileResponse(str(FRONTEND_DIR / "index.html"))
