# Database (SQLite, `DATA_DIR/nyayasahayak.db`)

Tables: `users, cases, documents, transcripts, claims, evidence, claim_evidence, claim_links, conflicts, authorities, authority_links, citations, findings, reviews, audit_events, agent_runs, tool_calls, reports, counters, revoked_tokens`.

* Child tables have `(case_id, id)` keys (IDs like `C-01` are per case) and cascade on case delete. `authorities` are per user.
* Columns follow the product spec (e.g. `claims.claim_text, source_document_id, page, line_start, line_end, timestamp, status, support_strength, conflict_strength, uncertainty`); each row also stores the complete object in `data` (JSON) and its array position in `seq`.
* Passwords: `users.password_hash` = `pbkdf2$salt$hash` (PBKDF2-SHA256, 120k iterations). Reviews and audit events are append-only from the API.
* Files: originals in `uploads/{user}/{case}/documents|transcripts`, extracted text in `extracted/`, reports in `reports/`. The database holds relative paths and a SHA-256 of each original.
* On start-up any analysis left "running" by a crash is marked failed and an `ANALYSIS_INTERRUPTED` audit event is written.
