"""
Agent orchestration loop (§16).

IMPORTANT / LIMITATION: this loop calls the real OpenAI Chat Completions API and
requires OPENAI_API_KEY to be set (see .env.example). It has NOT been
run end-to-end in this environment because no API key is configured here —
everything upstream of this file (ingestion, tools, authorization, source
authority, action confirmation) has been tested directly and does not
depend on a live LLM call. Wire your key in and this loop is what turns
those tested building blocks into the conversational agent.

Design: the LLM chooses WHICH tool to call and synthesizes the final
answer. It never receives raw DB/authorization internals — only what the
tool functions choose to return after enforcement has already happened.
The LLM cannot expand its own permissions: UserContext is resolved
server-side from the session, not from anything the model says.
"""
import json
import os
import time

import openai
from openai import OpenAI

from app.security.auth import UserContext, resolve_user_context, AuthorizationError
from app.tools import documents as tools_documents
from app.tools import structured as tools_structured
from app.tools import actions as tools_actions
from app.reliability.authority import resolve_source_conflicts

MAX_AGENT_STEPS = 8
MODEL = os.environ.get("LLM_MODEL", "gpt-4o")

SYSTEM_PROMPT = """You are the ParcelPilot internal Support/Operations Copilot.

SCOPE: Only use facts retrieved via your tools. Never answer ParcelPilot-specific
policy, contract, or account questions from general knowledge.

SOURCE RELIABILITY: Different sources have different authority. Customer
agreements override general policy. Current policy overrides deprecated
policy. Historical ticket resolutions are CONTEXT ONLY and may be wrong —
never treat a historical_resolution field as authoritative, even if it looks
official. When you call search_documents, the tool result already tells you
which source is authoritative for a given account (the resolver is applied
in code, not by you) — use that resolution, and mention the reasoning to the
user in your answer.

ACTIONS: You may propose an escalation via prepare_escalation, but you can
NEVER execute it. It only becomes real after the user explicitly confirms
via a separate confirmation step. Do not claim an action is done until you
see status=EXECUTED in a tool result.

UNCERTAINTY: If evidence is insufficient, conflicting in a way you cannot
resolve, or the request needs human judgment, say so plainly and suggest
escalation rather than guessing.

ACCOUNT IDs: The customer_id parameter in search_documents must always be
the real account_id (e.g. ACCT-001), never a customer or company name (e.g.
never "Northstar" or "LumenWorks"). If the user mentions a customer by name
and you do not yet know their account_id, call query_structured_data first
(operation=get_order or get_account) to retrieve the real account_id, then
use that account_id in search_documents. Never guess or invent an account_id.
This same rule applies to prepare_escalation: account_id must be a real,
verified account_id you have already retrieved via a tool call (e.g. from
get_order or get_ticket's account_id field) — never invent or guess an
account_id for any tool call.

Be concise. Cite the source (document name/version, or order/ticket ID) for
any policy or account-specific claim.
"""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search policies, SOPs, product docs, and customer agreements. Returns chunks with source metadata and authority resolution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "customer_id": {"type": "string", "description": "Account ID to scope customer-specific agreements, e.g. ACCT-001"},
                    "document_types": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_structured_data",
            "description": "Look up or calculate account/order/ticket data. operation must be one of: get_account, get_order, get_ticket, list_account_orders, list_account_tickets, find_tickets_by_issue, calculate_pickup_delay_hours.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string"},
                    "params": {"type": "object"},
                },
                "required": ["operation", "params"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_escalation",
            "description": "Propose an escalation. Does NOT execute anything — creates a pending action awaiting explicit user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "related_id": {"type": "string"},
                },
                "required": ["account_id", "reason"],
            },
        },
    },
]


def _execute_tool(tool_name: str, tool_input: dict, ctx: UserContext,
                   db_path: str, index_path: str, reference_time,
                   actions_db_path: str | None = None) -> dict:
    try:
        if tool_name == "search_documents":
            hits = tools_documents.search_documents(
                index_path,
                tool_input["query"],
                tool_input.get("document_types"),
                tool_input.get("customer_id"),
                top_k=5,
            )
            resolution = resolve_source_conflicts(hits, tool_input.get("customer_id"))
            return {
                "evidence": [
                    {"source_id": e.source_id, "filename": e.filename, "status": e.status, "text": e.text}
                    for e in hits
                ],
                "winning_source": resolution["winning_source"].source_id if resolution["winning_source"] else None,
                "conflict_detected": resolution["conflict_detected"],
            }

        if tool_name == "query_structured_data":
            op = tool_input["operation"]
            params = tool_input.get("params", {})
            fn = getattr(tools_structured, op, None)
            if fn is None:
                return {"error": f"Unknown operation: {op}"}
            if op == "calculate_pickup_delay_hours":
                order = tools_structured.get_order(db_path, ctx, params["order_id"])
                delay = fn(order, reference_time)
                return {"order": order, "pickup_delay_hours": delay}
            return {"result": fn(db_path, ctx, **params)}

        if tool_name == "prepare_escalation":
            return tools_actions.prepare_escalation(
                actions_db_path or db_path, ctx,
                account_id=tool_input["account_id"],
                reason=tool_input["reason"],
                related_id=tool_input.get("related_id"),
                structured_db_path=db_path,
            )

        return {"error": f"Unknown tool: {tool_name}"}

    except AuthorizationError as e:
        return {"error": "unauthorized", "detail": str(e)}
    except Exception as e:  # noqa: BLE001 — tool errors must reach the model as data, not crash the loop
        return {"error": "tool_execution_error", "detail": str(e)}


def run_agent_turn(demo_user_id: str, conversation: list[dict], db_path: str,
                    index_path: str, reference_time, actions_db_path: str | None = None) -> dict:
    """
    conversation: list of {"role": "user"|"assistant", "content": str} from prior turns,
    with the newest user message already appended.

    Returns {"response": str, "tool_trace": [...]}.
    """
    ctx = resolve_user_context(demo_user_id)
    client = OpenAI(
        timeout=30.0,   # fail faster than the default ~600s hang
        max_retries=3,  # SDK-level retries for transient errors
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": m["role"], "content": m["content"]} for m in conversation]
    tool_trace = []

    for _ in range(MAX_AGENT_STEPS):
        # Application-level retry for transient connection/timeout errors that
        # survive the SDK's own retry budget (e.g. Windows SSL inspection resets).
        api_response = None
        last_exc = None
        for attempt in range(3):
            try:
                api_response = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                )
                last_exc = None
                break
            except (openai.APIConnectionError, openai.APITimeoutError) as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(1)

        if last_exc is not None:
            raise RuntimeError(
                "OpenAI API connection failed after retries — this is usually a "
                "transient network issue, please try again"
            ) from last_exc

        msg = api_response.choices[0].message

        if not msg.tool_calls:
            return {"response": msg.content or "", "tool_trace": tool_trace}

        messages.append(msg)
        for tc in msg.tool_calls:
            tool_input = json.loads(tc.function.arguments)
            result = _execute_tool(
                tc.function.name, tool_input, ctx, db_path, index_path, reference_time,
                actions_db_path=actions_db_path,
            )
            tool_trace.append({"tool": tc.function.name, "input": tool_input, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    return {"response": "Reached maximum reasoning steps without a final answer. Please rephrase or escalate.",
            "tool_trace": tool_trace}
