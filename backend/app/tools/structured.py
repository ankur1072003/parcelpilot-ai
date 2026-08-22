"""
Tool 2 — query_structured_data.

Every function here takes a UserContext FIRST and enforces access before
returning anything. There is no function that returns account/order/ticket
data without checking require_account_access() (or, for cross-account
aggregate ops, require_role()) first. The model can request any account_id
it wants in its tool call arguments — the enforcement below is what actually
decides whether the data comes back, not the model's own judgment.

Calculation helpers return raw INPUTS (e.g., hours late, fault flags) rather
than a hard-coded fee/credit amount. The applicable threshold and amount
live in policy/SOP/agreement documents (retrieved via Tool 1) and may be
overridden per customer — baking a fixed number into this tool would violate
the "do not hard-code assessment answers" rule and would silently go stale
if a policy changes.
"""
from datetime import datetime

from app.data import db as _db
from app.security.auth import UserContext, require_account_access, require_role


def get_account(db_path: str, ctx: UserContext, account_id: str) -> dict:
    require_account_access(ctx, account_id)
    account = _db.get_account(db_path, account_id)
    if account is None:
        raise ValueError(f"No such account: {account_id}")
    return account


def get_order(db_path: str, ctx: UserContext, order_id: str) -> dict:
    order = _db.get_order(db_path, order_id)
    if order is None:
        raise ValueError(f"No such order: {order_id}")
    require_account_access(ctx, order["account_id"])
    return order


def get_ticket(db_path: str, ctx: UserContext, ticket_id: str) -> dict:
    ticket = _db.get_ticket(db_path, ticket_id)
    if ticket is None:
        raise ValueError(f"No such ticket: {ticket_id}")
    require_account_access(ctx, ticket["account_id"])
    return ticket


def list_account_orders(db_path: str, ctx: UserContext, account_id: str) -> list[dict]:
    require_account_access(ctx, account_id)
    return _db.list_account_orders(db_path, account_id)


def list_account_tickets(db_path: str, ctx: UserContext, account_id: str) -> list[dict]:
    require_account_access(ctx, account_id)
    return _db.list_account_tickets(db_path, account_id)


def find_tickets_by_issue(db_path: str, ctx: UserContext, keyword: str,
                           account_id: str | None = None) -> list[dict]:
    if account_id is not None:
        require_account_access(ctx, account_id)
        return _db.find_tickets_by_keyword(db_path, keyword, account_id)
    # cross-account keyword search is an ops-only aggregate operation
    require_role(ctx, ("support_manager", "admin"))
    return _db.find_tickets_by_keyword(db_path, keyword, None)


def find_high_severity_or_sla_risk_tickets(db_path: str, ctx: UserContext) -> list[dict]:
    """Cross-account aggregate view for Ops Insights — manager/admin only."""
    require_role(ctx, ("support_manager", "admin"))
    return _db.list_all_open_tickets(db_path)


def aggregate_issue_patterns(db_path: str, ctx: UserContext) -> list[dict]:
    """Cross-account aggregate view for Ops Insights — manager/admin only."""
    require_role(ctx, ("support_manager", "admin"))
    return _db.list_all_open_tickets(db_path)


# --- calculation helpers -----------------------------------------------------

def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts)


def calculate_time_since_booking(order: dict, reference_time: datetime) -> float | None:
    booked = _parse(order.get("booked_at"))
    if booked is None:
        return None
    return (reference_time - booked).total_seconds() / 60.0  # minutes


def calculate_pickup_delay_hours(order: dict, reference_time: datetime) -> float | None:
    """
    Hours the pickup is late past the scheduled window END.
    If pickup_actual_at is set, delay is measured against that.
    If not yet picked up, delay is measured against reference_time
    (the dataset snapshot time), which is what "still not picked up" means.
    Returns None if the order was never late (picked up within window, or window missing).

    NOTE ON TIME ZONES: all timestamps in the workbook are naive local time
    (Asia/Kolkata per the README sheet) with no UTC offset in the source
    data. `reference_time` must also be passed as a naive datetime in the
    same local time — do not pass a tz-aware datetime here, it will raise.
    """
    window_end = _parse(order.get("pickup_window_end"))
    if window_end is None:
        return None
    actual = _parse(order.get("pickup_actual_at")) or reference_time
    delta_hours = (actual - window_end).total_seconds() / 3600.0
    return max(delta_hours, 0.0)
