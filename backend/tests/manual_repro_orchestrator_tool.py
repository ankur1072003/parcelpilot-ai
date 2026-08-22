import sys
sys.path.insert(0, ".")
from datetime import datetime
from app.security.auth import resolve_user_context
from app.agent.orchestrator import _execute_tool

ctx = resolve_user_context("agent_rohit")
result = _execute_tool(
    "prepare_escalation",
    {"account_id": "ACCT-001", "reason": "test", "related_id": "TKT-501"},
    ctx, "../data/parcelpilot.db", "../data/doc_index.pkl", datetime(2026, 8, 16, 11, 0)
)
print("RESULT:", result)
