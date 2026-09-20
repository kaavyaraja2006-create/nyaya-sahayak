# Architecture

```mermaid
flowchart TD
  U[Reviewer] --> W[Web app (dist/index.html)]
  W -- REST /api + JWT --> S[API server (backend/src/server.js)]
  S --> E[Engine services: ownership-checked case, document, claim, review, report logic]
  E --> A[Agent pipeline: document, transcript, claim, evidence, conflict, legal research, citation audit, report]
  A --> T[Controlled tool layer: 7 tools]
  E --> DB[(SQLite)]
  S --> F[(uploads/{case}/documents · transcripts · extracted · reports)]
  A -. claim extraction only, optional .-> G[Gemini API]
  M[MCP server (stdio)] --> T
  C[Any MCP client] --> M
```

* **One engine, two hosts.** `src/00–10` is the analysis engine (extraction, conflicts, authority retrieval, citation audit, review, audit, reports). The browser bundle runs it locally when you open `dist/index.html` from disk; the server runs the *same* code when the page is served by the backend. Behaviour is identical and both are covered by tests.
* **The server is authoritative in server mode.** The browser sends bytes and decisions; the server parses files, runs agents, writes SQLite, stores originals and reports. The browser keeps only an in-memory cache and does not persist case data locally.
* **Access is enforced in the service layer** (`caseAccess(user, case)` → `full` | `hearing` | none, used by `ownedCase`), so it applies to REST calls, agents and MCP tools alike. `full` = assigned judge, assigned lawyers, and the creator of a personal workspace case; `hearing` = the assigned stenographer (header, hearings, transcripts, document metadata, uploads). Not-found and not-allowed are indistinguishable (both `403 FORBIDDEN`). `backend/src/views.js` decides what each level receives (`snapshot`), and what the public may see (`publicCase`).
* **Court workflow** lives in `frontend/src/11-hearings.js` (hearing state machine, start/end, transcript generation). `backend/src/otp.js` (lawyer sign-in codes) and `backend/src/marketplace.js` (profiles, rule-based matching, requests, private messages) sit beside the server; both use the same SQLite store.
* **Persistence.** The engine works on whole-case objects. `db.js` loads them at start and writes changed cases back in one transaction; each row keeps its columns for querying plus the full object in `data`. See DATABASE.md.
* **Limits.** One process, one in-memory copy of all cases (fine for a team or a demo, not for large multi-tenant use). The engine is a singleton per process. No TLS (use a proxy). Login throttling is in memory.
