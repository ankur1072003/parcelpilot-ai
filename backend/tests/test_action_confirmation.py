"""§45 item 5 — a state-changing action cannot execute without an explicit,
separate confirmation call, cannot be double-executed, and honors cancel."""
import pytest

from app.security.auth import resolve_user_context, AuthorizationError
from app.tools import actions as tools_actions


def test_prepare_does_not_execute(actions_db_path, db_path):
    ctx = resolve_user_context("agent_rohit")
    result = tools_actions.prepare_escalation(
        actions_db_path, ctx, account_id="ACCT-001",
        reason="Northstar reports total shipment-creation outage (TKT-501)",
        related_id="TKT-501",
        structured_db_path=db_path,
    )
    assert result["status"] == "PENDING_CONFIRMATION"

    stored = tools_actions.get_action(actions_db_path, result["action_id"])
    assert stored["status"] == "PENDING_CONFIRMATION"
    assert stored["executed_at"] is None


def test_explicit_confirmation_executes(actions_db_path, db_path):
    ctx = resolve_user_context("agent_rohit")
    prepared = tools_actions.prepare_escalation(
        actions_db_path, ctx, account_id="ACCT-001", reason="test", related_id=None,
        structured_db_path=db_path,
    )
    confirmed = tools_actions.confirm_action(actions_db_path, ctx, prepared["action_id"], confirm=True)
    assert confirmed["status"] == "EXECUTED"


def test_cancel_prevents_execution(actions_db_path, db_path):
    ctx = resolve_user_context("agent_rohit")
    prepared = tools_actions.prepare_escalation(
        actions_db_path, ctx, account_id="ACCT-001", reason="test", related_id=None,
        structured_db_path=db_path,
    )
    result = tools_actions.confirm_action(actions_db_path, ctx, prepared["action_id"], confirm=False)
    assert result["status"] == "CANCELLED"

    with pytest.raises(tools_actions.ActionError):
        tools_actions.confirm_action(actions_db_path, ctx, prepared["action_id"], confirm=True)


def test_duplicate_confirmation_does_not_double_execute(actions_db_path, db_path):
    ctx = resolve_user_context("agent_rohit")
    prepared = tools_actions.prepare_escalation(
        actions_db_path, ctx, account_id="ACCT-001", reason="test", related_id=None,
        structured_db_path=db_path,
    )
    tools_actions.confirm_action(actions_db_path, ctx, prepared["action_id"], confirm=True)

    with pytest.raises(tools_actions.ActionError):
        tools_actions.confirm_action(actions_db_path, ctx, prepared["action_id"], confirm=True)


def test_cannot_prepare_escalation_for_unauthorized_account(actions_db_path, db_path):
    ctx = resolve_user_context("agent_rohit")  # not scoped to ACCT-002
    with pytest.raises(AuthorizationError):
        tools_actions.prepare_escalation(
            actions_db_path, ctx, account_id="ACCT-002", reason="test", related_id=None,
            structured_db_path=db_path,
        )
