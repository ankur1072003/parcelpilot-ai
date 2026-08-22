"""
Server-side authorization. This is the ONLY place account-scope decisions
are made. Tools call check_account_access() themselves — they never trust
an account_id or role supplied by the model or the frontend as authoritative;
those are only used to LOOK UP the real, server-held UserContext.

Do not add a code path where a tool accepts account_scope or role as a
parameter and treats it as ground truth. UserContext is always resolved
from a session store keyed by an opaque session token, not from request body.
"""
from dataclasses import dataclass


class AuthorizationError(Exception):
    """Raised when a user attempts to access data/action outside their scope."""
    pass


@dataclass(frozen=True)
class UserContext:
    user_id: str
    role: str                      # support_agent | support_manager | admin
    permitted_account_ids: tuple    # empty tuple + role in (support_manager, admin) => all accounts


# --- Demo session store -----------------------------------------------------
# In production this would be a real session/auth backend. For the assessment
# this is a small, explicit, server-side table — the frontend can only ask
# "log in as X"; it can never assert a role or account list directly.

_DEMO_USERS = {
    "agent_rohit": UserContext(
        user_id="agent_rohit",
        role="support_agent",
        permitted_account_ids=("ACCT-001", "ACCT-003"),  # scoped to specific accounts
    ),
    "agent_maya": UserContext(
        user_id="agent_maya",
        role="support_agent",
        permitted_account_ids=("ACCT-002", "ACCT-004"),
    ),
    "manager_priya": UserContext(
        user_id="manager_priya",
        role="support_manager",
        permitted_account_ids=(),  # empty + manager/admin role => sees all accounts
    ),
}


def resolve_user_context(demo_user_id: str) -> UserContext:
    ctx = _DEMO_USERS.get(demo_user_id)
    if ctx is None:
        raise AuthorizationError(f"Unknown user: {demo_user_id}")
    return ctx


def has_account_access(ctx: UserContext, account_id: str) -> bool:
    if ctx.role in ("support_manager", "admin"):
        return True
    return account_id in ctx.permitted_account_ids


def require_account_access(ctx: UserContext, account_id: str) -> None:
    if not has_account_access(ctx, account_id):
        raise AuthorizationError(
            f"User {ctx.user_id} is not authorized for account {account_id}."
        )


def require_role(ctx: UserContext, allowed_roles: tuple) -> None:
    if ctx.role not in allowed_roles:
        raise AuthorizationError(
            f"User {ctx.user_id} (role={ctx.role}) is not permitted to perform this operation."
        )
