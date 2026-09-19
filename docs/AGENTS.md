# Agents

Each agent has a name, purpose, declared tools, status, warnings, `requires_review`, and writes a run record (`agent_runs`): input/output summary, duration, tool calls, error. One failing agent does not stop the pipeline.

Order: Document → Transcript → Claim → Evidence → Conflict → Legal Research → Citation Audit → Report (the orchestrator is `runAnalysis`; its record is the analysis object).

* **Claim Agent** is the only LLM-capable stage. With Gemini enabled, the model must return a verbatim quote and a paragraph id; the quote is located in the source text and anything that cannot be found is discarded. On any failure that document falls back to the rules engine and the run is marked *degraded*.
* Conflicts compare event times and locations across sources within a single day. Signals (support / conflict / uncertainty, 0–100) are workflow signals, not probabilities.
* Authorities come only from the user's library. Citation results: `POTENTIALLY_RELEVANT`, `WEAK_RELEVANCE`, `MISSING_CITATION`, `UNRESOLVED`; never "verified".
