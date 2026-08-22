# Architecture Note

## 1. System Overview

An internal copilot for ParcelPilot's support/operations team. It answers questions that
require combining unstructured evidence (policies, SOPs, customer agreements, product docs)
with structured records (accounts, orders, tickets), and can propose — but never itself
execute — state-changing actions like escalations.

## 2. Agent Design

A single explicit tool-calling loop (`backend/app/agent/orchestrator.py`) against the Claude
Messages API, capped at `MAX_AGENT_STEPS=8`. The LLM's responsibilities: understand intent,
choose which tool(s) to call, synthesize a final answer from tool results, and communicate
uncertainty. Everything else — authorization, source precedence, action execution, SQL
parameterization — is deterministic code the LLM cannot influence, because tool results are
the *only* channel through which the model sees data, and those results are produced after
enforcement has already run.

## 3. Tool Design

- `search_documents`: read-only, customer-scope filtered, returns metadata-rich chunks plus
  a pre-computed authority resolution.
- `query_structured_data`: a fixed allowlist of named operations (`get_account`, `get_order`,
  `calculate_pickup_delay_hours`, …) — never raw SQL. Each function independently re-checks
  authorization using the record's real `account_id`, not any account_id the caller supplied.
- `prepare_escalation` / `confirm_action`: a two-step state machine. The model can only ever
  call `prepare_escalation`; only a separate, explicit HTTP call with a literal `action_id`
  can move it to `EXECUTED`.

## 4. Document Handling

Each PDF is extracted with `pdfplumber`, then chunked on the numbered section headers that
every supplied document actually uses (`"1. Scope and source precedence"`, etc.), with a
paragraph-split fallback. Metadata (`document_type`, `version`, `status`, `effective_date`,
`customer_scope`, `authority_rank`) comes from `config/document_registry.yaml`, populated
by directly reading each PDF rather than inferring fields. A TF-IDF vector is built over the
23 resulting chunks; citations (`source_id`, `filename`) travel with every retrieved chunk
through the whole pipeline.

## 5. Structured Data Handling

`scripts/ingest.py` loads the 3 real sheets (`accounts`, `orders`, `tickets`) into SQLite
with their real column names, using pandas/openpyxl only at ingestion time. All runtime
reads go through small, named, parameterized functions in `backend/app/data/db.py` — there
is no code path from user or model input to a raw SQL string.

## 6. Access Control

Enforced in `backend/app/security/auth.py` + re-checked inside every tool function in
`backend/app/tools/structured.py` and `backend/app/tools/actions.py`. `UserContext` (role,
permitted account IDs) is resolved server-side from a demo session table keyed by
`demo_user_id` — never trusted from the request body's `account_id`/`role` fields, and
never from anything the model outputs. Verified with 5 authorization tests, including one
that attempts to fetch an order belonging to an out-of-scope account directly by ID.

## 7. Source Reliability

`backend/app/reliability/authority.py` implements a fixed precedence
(agreement > current policy/SOP > current product docs > deprecated policy > historical
ticket) as ranked, comparable data (`authority_rank`), not as prompt language. Historical
ticket resolutions are excluded from the "applicable sources" set entirely and surfaced
separately as context — they structurally cannot become the `winning_source`.

## 8. Conflict Resolution

`resolve_source_conflicts()` filters retrieved evidence to what's applicable to the account
in question (excluding another customer's agreement), ranks the rest by authority, and
returns the winner plus which sources it overrode. `detect_conflicting_evidence()` flags
when multiple authority tiers are present at all, which the agent is instructed to mention
in its answer. Real test case: Support Policy v2 (deprecated) and v3 (current) both discuss
response-time targets for the same plans with different numbers — v3 always wins, and v2
remains retrievable (not hidden) so the agent can explain why it was excluded if asked.

## 9. Confirmation Gating

State-changing actions are separated into "propose" and "execute" as two different API
calls with a persisted `PENDING_CONFIRMATION` row in between. This exists because an LLM
producing a plausible-sounding "I've escalated this" is indistinguishable from one that
actually did, unless the actual write is gated behind something the model cannot itself
supply — a real, separate confirmation call with the literal `action_id`. Tested for:
no execution on prepare, cancel prevents execution, and duplicate/replayed confirmation
on an already-`EXECUTED` action is rejected with a 409.

## 10. Proactive Issue Detection

Implemented as simple keyword clustering over open tickets (`backend/app/main.py:ops_insights`),
matched against the two real known issues in the Product Ops Guide (KI-208 bulk-upload
failures, KI-211 webhook delay) plus generic P1-shaped patterns (outage language, security
language). This is rule-based rather than ML because the dataset (7 tickets) does not
justify statistical clustering, and rule-based logic is easier to test, explain, and trust
in a support-ops context where false positives have a real cost.

## 11. Major Technical Trade-Offs

- **SQLite over a hosted RDBMS:** the dataset is static and small (4 accounts, 6 orders,
  7 tickets). SQLite gives real parameterized querying, easy test isolation (a fresh temp
  file per test), and zero deployment/infra risk, at the cost of not being what a production
  ParcelPilot system would actually run on long-term (see PRODUCT.md).
- **TF-IDF over embeddings:** at 23 chunks, an embedding-based vector store adds a network
  dependency and infra surface without a measurable retrieval-quality gain, and this
  environment has no reachable embeddings API. Explicitly called out as the first thing to
  swap if the document corpus grows.
- **A single explicit tool loop over LangGraph:** the state machine here — search, look up,
  propose, wait for confirmation — is simple enough that a graph framework's main benefit
  (managing complex branching state) isn't needed, while its cost (another abstraction layer
  to explain in a 5-minute demo) is real.
- **Authorization re-checked per-function, not only at the API boundary:** because tool
  functions are also what a future internal script or batch job would call directly, correct
  behavior can't depend on FastAPI middleware alone.
