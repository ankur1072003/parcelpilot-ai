"""
§45 item 4 — current-vs-deprecated policy.
§45 item 6 — historical ticket resolution never becomes authoritative.
"""
from app.tools import documents as tools_documents
from app.reliability.authority import resolve_source_conflicts, Evidence
from app.security.auth import resolve_user_context
from app.tools import structured as tools_structured


def test_deprecated_policy_never_beats_current_policy(index_path):
    """Both v2 (deprecated) and v3 (current) mention response-time targets;
    the deprecated doc is retrievable (not hidden) but must never win."""
    hits = tools_documents.search_documents(
        index_path, "P1 P2 P3 response time targets Enterprise Growth Standard",
        top_k=10,
    )
    filenames = {h.filename for h in hits}
    assert "02_Support_Policy_v2_DEPRECATED.pdf" in filenames, (
        "sanity check: deprecated doc should still be retrievable as evidence"
    )

    resolution = resolve_source_conflicts(hits, account_id=None)
    winner = resolution["winning_source"]
    assert winner is not None
    assert winner.status != "deprecated"
    assert winner.source_id == "doc_support_policy_v3"

    overridden_ids = [e.source_id for e in resolution["overridden_sources"]]
    assert "doc_support_policy_v2" in overridden_ids


def test_historical_ticket_resolution_is_context_only_not_authoritative(db_path):
    """
    TKT-450: historical_resolution field says a INR 250 fee applied after
    30 minutes for Northstar — this directly contradicts Northstar's real
    agreement (no fee, ever, before pickup). The historical resolution must
    never be treated as a 'source' that can win a conflict.
    """
    ctx = resolve_user_context("manager_priya")
    ticket = tools_structured.get_ticket(db_path, ctx, "TKT-450")
    assert ticket["historical_resolution"] is not None
    assert "250" in ticket["historical_resolution"]

    # Simulate treating the historical resolution as evidence alongside the
    # real agreement, to prove the resolver still excludes it from winning.
    agreement_evidence = Evidence(
        source_id="doc_agreement_acct_001", filename="05_...pdf", status="active",
        authority_rank=1, text="Northstar may cancel with no fee...",
        customer_scope="ACCT-001",
    )
    historical_evidence = Evidence(
        source_id="ticket_TKT-450", filename=None, status="historical_ticket",
        authority_rank=5, text=ticket["historical_resolution"], customer_scope="ACCT-001",
    )
    resolution = resolve_source_conflicts([agreement_evidence, historical_evidence], "ACCT-001")
    assert resolution["winning_source"].source_id == "doc_agreement_acct_001"
    assert any(e.source_id == "ticket_TKT-450" for e in resolution["historical_context"])
    assert all(e.source_id != "ticket_TKT-450" for e in [resolution["winning_source"]])
