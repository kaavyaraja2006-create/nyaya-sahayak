# Database (SQLite, `DATA_DIR/nyayasahayak.db`)

Tables: `users, cases, documents, transcripts, claims, evidence, claim_evidence, claim_links, conflicts, authorities, authority_links, citations, findings, reviews, audit_events, agent_runs, tool_calls, reports, counters, revoked_tokens`.

* Child tables have `(case_id, id)` keys (IDs like `C-01` are per case) and cascade on case delete. `authorities` are per user.
* Columns follow the product spec (e.g. `claims.claim_text, source_document_id, page, line_start, line_end, timestamp, status, support_strength, conflict_strength, uncertainty`); each row also stores the complete object in `data` (JSON) and its array position in `seq`.
* Passwords: `users.password_hash` = `pbkdf2$salt$hash` (PBKDF2-SHA256, 120k iterations). Reviews and audit events are append-only from the API.
* Files: originals in `uploads/{case}/documents|transcripts` (older databases: `uploads/{user}/{case}/…`, still read), extracted text in `extracted/`, reports in `reports/`. The database holds relative paths and a SHA-256 of each original.
* On start-up any analysis left "running" by a crash is marked failed and an `ANALYSIS_INTERRUPTED` audit event is written.

## Court workflow, OTP and marketplace tables (added in this release)
Applied idempotently on start-up (`migrate()` adds columns; `CREATE TABLE IF NOT EXISTS` adds tables). Existing databases keep working; cases saved before assignments existed get their creator assigned to the matching slot.
* `users` + `mobile_verified`, `verified`, `verified_at`, `profile` (JSON: practice areas, city, courts, fees, listed). `cases` + `judge_id`, `stenographer_id`.
* `case_lawyers(case_id, lawyer_id, seq)`; `hearings(case_id, id, seq, judge_id, stenographer_id, scheduled_at, status, title, is_public, started_at, ended_at, data)`; `hearing_lawyers(case_id, hearing_id, lawyer_id)`.
* `hearing_drafts(case_id, hearing_id, body, rev, updated_at, updated_by)` — the stenographer's live typing area; `rev` gives conflict detection between tabs.
* `otp_challenges(id, user_id, purpose, code_hash, salt, created_at, expires_at, attempts, consumed_at, invalidated_at, ip)` — only an HMAC of the code is stored.
* `lawyer_requests(id, client_id, lawyer_id, status, case_type, city, court, budget_min, budget_max, description, match_score, match_reasons, ai_used, decision_note, created_at, decided_at)`; `messages(id, request_id, sender_id, body, created_at)`; `message_reads(request_id, user_id, last_id)`.
* A database file created by the (non-functional) FastAPI skeleton is detected and refused with a clear message rather than misread.
