# NyayaSahayak

Source-traceable, human-in-the-loop legal evidence analysis. **Evidence. Context. Traceability.**
It organises case documents and hearing transcripts into claims, evidence, potential conflicts, authority passages and citation checks, and puts every finding under human review with an audit trail. It never decides guilt, innocence, liability, credibility, admissibility or outcome.

## Two ways to run it (same app, same engine)

**A. With the backend (recommended: real accounts, SQLite, stored files, server-side Gemini key)**
```bash
cd backend && npm start          # Node 22.13+, no npm install needed
# open http://127.0.0.1:8000
```
Optional: `GEMINI_API_KEY=… npm start` (see `.env.example`). Data lives in `backend/data/` (override with `DATA_DIR`).
Docker: `cp .env.example .env && docker compose up --build` (untested in the build environment; put an HTTPS proxy in front for anything beyond local use).

**B. Standalone (no server)** — open `dist/index.html` from disk. Everything runs and is stored in your browser; nothing is shared or synced. An optional Gemini key can be added in Settings (or `dist/config.js`, see `dist/config.example.js`) and is then used directly from the browser.

The app ships with **no built-in case data and no legal authorities**. You add the authorities you rely on (Authorities → Add); retrieval and citation audit use only those.

## What the backend provides
* REST API (`docs/API.md`), SQLite persistence (`docs/DATABASE.md`), JWT auth with logout revocation and login throttling, **case-based access control** on every route, tool and file (see below).
* Uploads: type is checked by extension **and** content, size-limited, filenames sanitised, paths built server-side; originals, extracted text and reports stored under `uploads/{case}/…` with a SHA-256 (databases from the first release, which used `uploads/{user}/{case}/…`, still resolve).
* Background analysis with real agent run records; crash recovery marks interrupted runs honestly.
* Gemini on the server: key only in the environment, per-user consent, PII masking, quote-grounded claims only (`docs/AGENTS.md`).
* A real MCP stdio server with the 7 tools (`docs/MCP.md`) and a demo client (`cd backend && npm run demo`).

## Court workflow, public pages and lawyer marketplace (server mode)
* **Roles and case access.** A case has one judge, any number of lawyers and one court stenographer. Only those people (and the workspace creator for personal cases) can open it. The **stenographer sees a hearing-only view**: case header, hearings, transcripts and document names, plus uploads; no claims, evidence, findings, audit, reports or document text. Everyone else, and a case that does not exist, gets the same `403 FORBIDDEN`, so case IDs cannot be probed.
* **Lawyer sign-in by one-time code.** Lawyers register with a State Bar Council enrolment number and mobile number and sign in with enrolment number + registered mobile + a 6-digit code (5 min, single use, hashed at rest, attempt- and rate-limited, identical responses for unknown numbers). Set `SMS_WEBHOOK_URL` (and `SMS_WEBHOOK_TOKEN`) to deliver codes by your SMS gateway; with none set, codes are written to the server log (development only, refused when `NODE_ENV=production`).
* **Stenographer workflow.** Court desk → open or pick a case → *Start hearing* (choose judge and lawyers) → a large typing area that autosaves on the server (conflict-safe across tabs) → *Generate transcript* → formatted output beside it; upload a transcript file instead if you prefer. Case, hearing, judge, lawyers and stenographer IDs are recorded together and audited.
* **Public case tracking.** `#/track` (no sign-in): enter a Case ID to see title, court, status, upcoming hearings and history. The case must be switched on by the judge / stenographer / case owner, and only hearings marked public appear. Never documents, transcripts, people or the audit trail.
* **Find a lawyer.** `#/find-lawyer` (no sign-in): describe the case and see verified lawyers ranked by a transparent rule-based score (practice area is a hard requirement; court, city, experience, court-recorded cases and budget add points; blank fields never count against anyone) with the reasons shown. Optional AI re-ranking sends only a PII-masked description and can add nothing. Lawyer facts come only from their own profile and from hearings recorded on this platform; nothing is invented. Clients (a separate account type) send a request; contact details stay hidden until the lawyer accepts, and then a private conversation opens between the two people only.
* **Verification.** Accounts whose e-mail is listed in `ADMIN_EMAILS` see *Verify lawyers*. Only verified lawyers who choose to be listed appear in the directory. This is a manual check against the Bar Council register; nothing is verified automatically.
* In the standalone file build the court workflow (cases, assignment, hearings, transcripts) runs in the browser; OTP sign-in, public tracking, find-a-lawyer, requests and chat need the server and say so.

## Optional demo data (fictional)
The app ships empty on purpose. To try every screen, fill a **fresh** data folder once:
```bash
cd backend
DATA_DIR=./demo-data npm run seed                                  # prints the demo accounts and links
DATA_DIR=./demo-data ADMIN_EMAILS=admin@demo.example npm start     # then open http://127.0.0.1:8000
```
(Windows PowerShell: `$env:DATA_DIR="./demo-data"; npm run seed` then `$env:ADMIN_EMAILS="admin@demo.example"; npm start`.) It creates a judge, a stenographer, three lawyers (one left unverified), two clients and an admin, all with password `Demo@12345`; two cases with documents, an analysis, hearings (one recorded with a transcript, some upcoming, one private), public tracking, lawyer profiles, a pending request and an accepted request with chat. Every name is invented. The seed is server-mode only; the standalone file build stays empty.

## Tests (`./run-tests.sh`)
* `frontend/tests/core.test.js` — 18 engine tests. `backend/tests/api.test.js` — 32 API/MCP/persistence/crash tests. `backend/tests/workflow.test.js` — 44 tests: OTP, case authorization, hearings, drafts, public tracking, marketplace, chat, and a sweep of **every route** with URLs and IDs changed by hand (Node's built-in runner).
* `frontend/tests/e2e.py` — 74 browser checks in standalone mode and the same flow against the running backend; `e2e_standalone_court.py` — court workflow in the standalone build; `e2e_workflow.py` — 66 checks for lawyer OTP sign-in, the stenographer workspace, case-based access in the UI, public tracking, find-a-lawyer, requests and chat (Python + Playwright + Chromium).
* Not tested: Docker files; Gemini against the live service (mocked only); third-party MCP clients.

## Honest scope
* **Not FastAPI / React / SQLAlchemy / Pydantic / the MCP SDK.** The build environment had no network, so none could be installed. The backend is Node (built-in `node:sqlite`), the UI is plain JavaScript, and MCP is implemented directly against the protocol. Porting the API layer to FastAPI is possible (services and tool contracts are the seams) but has not been done.
* Default analysis is rule-based and heuristic; it can miss or over-flag. Times are compared within a single day. Text-layer PDFs only (no OCR). PII masking is basic. Credentials are checked only by a manual administrator step (see Verification). Password reset by email needs a mail service and is not included.
* One process holds all cases in memory and SQLite is the store: fine for a demo or small team, not large multi-tenant use. Plain HTTP only. The session token is kept in `sessionStorage`.
* `tests/fixtures` and `tests/e2e-data` contain fictional material used only by tests and the MCP demo.

Layout: `dist/` built app · `backend/` server, MCP server, tests · `frontend/src/` engine (00–11), provider (06), UI (20–30), CSS · `docs/` · `build.py` (`python3 build.py app|engine|core`).
