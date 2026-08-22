"""§45 item 3 — unauthorized account access is denied at the tool/data layer."""
import pytest

from app.security.auth import resolve_user_context, AuthorizationError
from app.tools import structured as tools_structured


def test_agent_rohit_can_access_own_scope(db_path):
    ctx = resolve_user_context("agent_rohit")  # scoped to ACCT-001, ACCT-003
    account = tools_structured.get_account(db_path, ctx, "ACCT-001")
    assert account["account_id"] == "ACCT-001"


def test_agent_rohit_denied_out_of_scope_account(db_path):
    ctx = resolve_user_context("agent_rohit")  # NOT scoped to ACCT-002
    with pytest.raises(AuthorizationError):
        tools_structured.get_account(db_path, ctx, "ACCT-002")


def test_agent_rohit_denied_out_of_scope_order(db_path):
    """ORD-2001 belongs to ACCT-002 — rohit must not be able to fetch it,
    even by guessing/supplying the order_id directly (the check happens
    after lookup, keyed off the order's real account_id, not any account_id
    the model might have claimed)."""
    ctx = resolve_user_context("agent_rohit")
    with pytest.raises(AuthorizationError):
        tools_structured.get_order(db_path, ctx, "ORD-2001")


def test_manager_sees_all_accounts(db_path):
    ctx = resolve_user_context("manager_priya")
    for account_id in ("ACCT-001", "ACCT-002", "ACCT-003", "ACCT-004"):
        assert tools_structured.get_account(db_path, ctx, account_id) is not None


def test_cross_account_aggregate_requires_manager_role(db_path):
    rohit_ctx = resolve_user_context("agent_rohit")
    with pytest.raises(AuthorizationError):
        tools_structured.find_high_severity_or_sla_risk_tickets(db_path, rohit_ctx)

    manager_ctx = resolve_user_context("manager_priya")
    result = tools_structured.find_high_severity_or_sla_risk_tickets(db_path, manager_ctx)
    assert isinstance(result, list)
