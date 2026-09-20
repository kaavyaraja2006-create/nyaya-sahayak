# Agents

Each agent has a name, purpose, declared tools, status, warnings, `requires_review`, and writes a run record (`agent_runs`): input/output summary, duration, tool calls, error. One failing agent does not stop the pipeline.

Order: Document → Transcript → Claim → Evidence → Conflict → Legal Research → Citation Audit → Report (the orchestrator is `runAnalysis`; its record is the analysis object).

* **Claim Agent** is the only LLM-capable stage. With Gemini enabled, the model must return a verbatim quote and a paragraph id; the quote is located in the source text and anything that cannot be found is discarded. On any failure that document falls back to the rules engine and the run is marked *degraded*.
* Conflicts compare event times and locations across sources within a single day. Signals (support / conflict / uncertainty, 0–100) are workflow signals, not probabilities.
* Authorities come only from the user's library. Citation results: `POTENTIALLY_RELEVANT`, `WEAK_RELEVANCE`, `MISSING_CITATION`, `UNRESOLVED`; never "verified".

## Python agent pipeline (`agents/`)

A separate, self-contained set of five source-grounded agents, wired by a
minimal LangGraph `StateGraph` in `agents/graph/`:

`START → CaseUnderstanding → EvidenceConflict → AuthorityCitation → CounterArgument → RiskReviewReport → END`

* One strongly typed shared state (`NyayaSahayakState`). No router, no supervisor, no sixth agent.
* Each stage receives only the structured output it needs, as the object the previous agent produced — provenance is never re-typed or re-asserted.
* Uncertainty is preserved: `UNVERIFIED`, `SOURCE_NOT_FOUND`, `NO_CONTRARY_SOURCE_FOUND` and `REQUIRES_HUMAN_REVIEW` reach the report unchanged.
* A stage that fails leaves its result `None` and is recorded `FAILED` in `stage_log`; the report then declares the stage missing rather than reporting no issues.
* `CounterArgumentAgent` returns `NO_CONTRARY_SOURCE_FOUND` rather than inventing opposition. `RiskReviewReportAgent` aggregates only — its `HIGH`/`MEDIUM`/`LOW` levels come from the deterministic rules in `risk_rules.py`, and every risk item traces `Risk → Finding → Claim → Source`.

Tests: `backend/tests/test_*_agent.py` and `backend/tests/test_graph.py`.
