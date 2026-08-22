"""
§45 items 1 & 2 — the two example questions plus one additional record,
proven by driving the real tools in the same sequence the agent must use.
This does not test the LLM's tool-selection (that needs a live API key —
see README/ARCHITECTURE limitations), but it proves the DATA and TOOL LAYER
can support a correct answer, which is the part that must never be faked.

Reference time: dataset snapshot 2026-08-16 11:00 +05:30 (from workbook README).
"""
from datetime import datetime

import pytest

from app.security.auth import resolve_user_context
from app.tools import structured as tools_structured
from app.tools import documents as tools_documents
from app.reliability.authority import resolve_source_conflicts

# All timestamps in the workbook are stored as naive local time (Asia/Kolkata,
# per the README sheet) — there is no UTC offset in the source data, so the
# reference time is kept naive too rather than mixing aware/naive datetimes.
SNAPSHOT_TIME = datetime(2026, 8, 16, 11, 0)


def test_example_1_northstar_cancellation_fee_ord1001(db_path, index_path):
    """
    Assessment example: 'Can Northstar cancel ORD-1001 without a cancellation
    fee? Explain why.'  Ground truth: YES — Northstar's Enterprise Agreement
    explicitly overrides the default SOP fee, regardless of elapsed time.
    """
    ctx = resolve_user_context("manager_priya")  # sees all accounts

    order = tools_structured.get_order(db_path, ctx, "ORD-1001")
    assert order["account_id"] == "ACCT-001"
    assert order["status"] == "BOOKED"

    account = tools_structured.get_account(db_path, ctx, order["account_id"])
    assert account["account_name"] == "Northstar Logistics"

    doc_hits = tools_documents.search_documents(
        index_path, "cancellation fee BOOKED shipment", customer_id="ACCT-001", top_k=5
    )
    resolution = resolve_source_conflicts(doc_hits, account_id="ACCT-001")

    winner = resolution["winning_source"]
    assert winner is not None
    assert winner.source_id == "doc_agreement_acct_001"  # customer agreement wins (rank 1)
    assert "no cancellation fee" in winner.text.lower()

    # the SOP is present as evidence but must not be the winning source
    overridden_ids = [e.source_id for e in resolution["overridden_sources"]]
    assert "doc_cancellation_sop_v4" in overridden_ids


def test_example_2_lumenworks_late_pickup_service_credit(db_path, index_path):
    """
    Assessment example: 'A pickup is three hours late because of carrier
    fault. Should I get a service credit?' Applied to ORD-2002 (LumenWorks):
    pickup is ~4.5 hours late at the dataset snapshot, carrier at fault.
    LumenWorks' agreement sets a 4-hour threshold / fixed INR 300 credit,
    which overrides the SOP default (2-hour threshold / up to INR 500).
    """
    ctx = resolve_user_context("manager_priya")

    order = tools_structured.get_order(db_path, ctx, "ORD-2002")
    assert order["account_id"] == "ACCT-002"
    assert order["carrier_fault"] == 1
    assert order["customer_fault"] == 0

    delay_hours = tools_structured.calculate_pickup_delay_hours(order, SNAPSHOT_TIME)
    assert delay_hours is not None and delay_hours > 4.0

    doc_hits = tools_documents.search_documents(
        index_path, "failed pickup service credit delay threshold",
        customer_id="ACCT-002", top_k=5,
    )
    resolution = resolve_source_conflicts(doc_hits, account_id="ACCT-002")
    winner = resolution["winning_source"]
    assert winner.source_id == "doc_agreement_acct_002"
    assert "300" in winner.text  # fixed INR 300 credit clause


def test_additional_record_beacon_retail_within_30min_cancellation(db_path, index_path):
    """
    Generalization check (§45 item 2): ORD-3001, Beacon Retail (ACCT-003),
    NO customer agreement in the pack -> default SOP applies. Cancellation
    was requested within 30 minutes of booking -> no fee under the SOP.
    """
    ctx = resolve_user_context("manager_priya")

    order = tools_structured.get_order(db_path, ctx, "ORD-3001")
    assert order["account_id"] == "ACCT-003"

    account = tools_structured.get_account(db_path, ctx, "ACCT-003")
    assert account["contract_file"] is None  # confirmed: no custom agreement

    minutes_to_cancel_request = (
        (datetime.fromisoformat(order["cancellation_requested_at"])
         - datetime.fromisoformat(order["booked_at"])).total_seconds() / 60.0
    )
    assert minutes_to_cancel_request <= 30

    doc_hits = tools_documents.search_documents(
        index_path, "cancellation fee within 30 minutes of booking",
        customer_id="ACCT-003", top_k=5,
    )
    resolution = resolve_source_conflicts(doc_hits, account_id="ACCT-003")
    winner = resolution["winning_source"]
    # no agreement exists for ACCT-003, so the current SOP must be the winner
    assert winner.source_id == "doc_cancellation_sop_v4"
