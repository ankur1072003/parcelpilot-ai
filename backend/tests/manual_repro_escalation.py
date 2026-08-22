import sys
sys.path.insert(0, ".")
from app.security.auth import resolve_user_context
from app.tools import actions as tools_actions

ctx = resolve_user_context("agent_rohit")
print("Calling prepare_escalation directly...")
result = tools_actions.prepare_escalation(
    "../data/actions.db", ctx,
    account_id="ACCT-001",
    reason="Northstar total shipment-creation outage (TKT-501)",
    related_id="TKT-501",
    structured_db_path="../data/parcelpilot.db",
)
print("SUCCESS:", result)
