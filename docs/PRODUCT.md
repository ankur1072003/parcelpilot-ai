# Product Note

## Additional Client Problem: Proactive Issue Detection

Chosen because it complements the internal-copilot direction directly: the same open-ticket
data the chatbot already reads can be surfaced to a manager as a standing view, without
waiting for someone to ask the right question. A purely reactive chatbot only helps once
a specific person asks a specific question — it can't tell a manager "these five tickets
are actually one incident."

### Current Implementation

`GET /api/ops/insights` (manager/admin only, enforced at the tool layer) clusters open
tickets by subject/keyword against the two real known issues in the Product Ops Guide and
generic outage/security patterns. On the real dataset this surfaces 4 clusters from 5 open
tickets, correctly separating the bulk-upload complaint (matches KI-208) from the
stuck-BOOKED-status complaint (matches KI-211) from the outage and security reports.

### Product Value

- Lets a manager triage by *pattern* instead of ticket-by-ticket, catching a systemic issue
  (e.g., "3 customers hit the same bulk-upload bug") before it becomes 20 separate tickets.
- Connects directly to the Product Ops Guide's known-issues list, so a manager sees "this
  matches KI-208, here's the workaround" instead of re-diagnosing from scratch.
- Keeps false-positive cost low by staying rule-based and explainable rather than a black-box
  anomaly score a manager has to learn to trust.

### What I Would Build Next

**P0**
- Production authentication/SSO (demo auth is intentionally mocked)
- A broader automated test suite beyond the 6 non-negotiable cases (10–20 scenarios per the
  original spec), covering more of the dataset's edge cases (e.g., DELIVERED-order
  cancellation attempts, manager-approval threshold on credits over ₹1,000)
- Real ticket-system integration so `prepare_escalation`/`confirm_action` writes to an actual
  system instead of a local audit table

**P1**
- Replace keyword clustering with embedding-based similarity once the ticket volume justifies it
- A feedback loop where an agent can flag "this answer was wrong," feeding back into the
  document registry or a correction log
- Better source-governance workflow for updating `document_registry.yaml` when a policy changes,
  so metadata can't silently drift from the real file the way the original master-guide/
  planning-package review (earlier in this project's history) found structural drift between
  documentation and actual assets
- Streaming responses in the chat UI

**P2**
- Customer-facing assistant (the other assessment-permitted direction), scoped per-account
- Analytics dashboards beyond the single Ops Insights view
- Multiple LLM provider support

### Intentionally Left Out

- Production SSO, carrier API integrations, a hosted/managed vector database, sophisticated
  ML-based anomaly detection, and an enterprise observability stack — each would add real
  infrastructure risk and setup time without improving correctness on this dataset size, and
  each is a straightforward drop-in later without restructuring what's here.
- A customer-facing chatbot variant — the internal-copilot direction was chosen up front
  (see ARCHITECTURE.md) and building both within the deadline would have diluted testing
  depth on either.

### Success Metric

**Primary: percentage of support cases the copilot resolves correctly without requiring
human rework** (i.e., an agent doesn't have to correct, re-answer, or reverse an action the
copilot took). This balances usefulness (it has to actually answer, not just punt to a
human) against trust (a wrong answer that looks confident is worse than an honest
escalation) — which is exactly the tension ParcelPilot described as its core concern.

Secondary metrics worth tracking alongside it: escalation precision (proportion of
escalations a manager agrees were warranted), citation correctness (does the cited source
actually say what the answer claims), and unauthorized-access attempt rate (should be zero,
and any non-zero value is a security incident, not a UX metric).
