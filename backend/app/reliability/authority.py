"""
Source authority ranking and conflict detection/resolution.

This module is the enforcement point for §9/§10 of the master prompt:
precedence must live in code, not only in a prompt instruction. The agent
calls these functions on retrieved evidence; it does not decide precedence
itself.

Authority order (lower rank = wins):
  1 = customer-specific agreement
  2 = current policy / current SOP
  3 = current product documentation
  4 = deprecated policy
  5 = historical ticket resolution (context only, never authoritative)
"""
from dataclasses import dataclass, field


HISTORICAL_TICKET_RANK = 5


@dataclass
class Evidence:
    source_id: str
    filename: str
    status: str            # current | deprecated | active | historical_ticket
    authority_rank: int
    text: str
    customer_scope: str | None = None


def rank_source_authority(evidence_list: list[Evidence]) -> list[Evidence]:
    """Sort evidence by authority, most authoritative first."""
    return sorted(evidence_list, key=lambda e: e.authority_rank)


def get_applicable_sources(evidence_list: list[Evidence], account_id: str | None) -> list[Evidence]:
    """
    Filter out documents that are scoped to a DIFFERENT customer than the
    one being discussed. Documents with customer_scope=None apply generally.
    Historical tickets are never treated as applicable "sources" for a rule —
    they are surfaced separately as context only (see detect_conflicting_evidence).
    """
    applicable = []
    for e in evidence_list:
        if e.status == "historical_ticket":
            continue
        if e.customer_scope is not None and e.customer_scope != account_id:
            continue
        applicable.append(e)
    return applicable


def detect_conflicting_evidence(evidence_list: list[Evidence]) -> bool:
    """
    Naive but explicit conflict signal: true if there's more than one
    non-historical source and their authority ranks differ (i.e. a
    lower-authority source exists alongside a higher-authority one that
    could plausibly disagree). Real conflict *content* detection (do the two
    texts actually disagree) is left to the LLM synthesis step, but it must
    always be told which source wins if it does — that part is deterministic.
    """
    applicable = [e for e in evidence_list if e.status != "historical_ticket"]
    ranks = {e.authority_rank for e in applicable}
    return len(ranks) > 1


def resolve_source_conflicts(evidence_list: list[Evidence], account_id: str | None) -> dict:
    """
    Returns a structured resolution the agent must use verbatim when
    constructing its final answer:
      {
        "winning_source": Evidence | None,
        "overridden_sources": [Evidence, ...],
        "historical_context": [Evidence, ...],   # never authoritative
        "conflict_detected": bool,
      }
    """
    applicable = get_applicable_sources(evidence_list, account_id)
    ranked = rank_source_authority(applicable)
    historical = [e for e in evidence_list if e.status == "historical_ticket"]

    return {
        "winning_source": ranked[0] if ranked else None,
        "overridden_sources": ranked[1:] if len(ranked) > 1 else [],
        "historical_context": historical,
        "conflict_detected": detect_conflicting_evidence(applicable),
    }
