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
* REST API (`docs/API.md`), SQLite persistence (`docs/DATABASE.md`), JWT auth with logout revocation and login throttling, per-user isolation on every route, tool and file.
* Uploads: type is checked by extension **and** content, size-limited, filenames sanitised, paths built server-side; originals, extracted text and reports stored under `uploads/{user}/{case}/…` with a SHA-256.
* Background analysis with real agent run records; crash recovery marks interrupted runs honestly.
* Gemini on the server: key only in the environment, per-user consent, PII masking, quote-grounded claims only (`docs/AGENTS.md`).
* A real MCP stdio server with the 7 tools (`docs/MCP.md`) and a demo client (`cd backend && npm run demo`).

## Tests (`./run-tests.sh`)
* `tests/core.test.js` — 18 engine tests. `backend/tests/api.test.js` — 32 API/MCP/persistence/crash tests (Node's built-in runner).
* `tests/e2e.py` — 74 browser checks in standalone mode and 76 against the running backend (Python + Playwright + Chromium).
* Not tested: Docker files; Gemini against the live service (mocked only); third-party MCP clients.

## Honest scope
* **Not FastAPI / React / SQLAlchemy / Pydantic / the MCP SDK.** The build environment had no network, so none could be installed. The backend is Node (built-in `node:sqlite`), the UI is plain JavaScript, and MCP is implemented directly against the protocol. Porting the API layer to FastAPI is possible (services and tool contracts are the seams) but has not been done.
* Default analysis is rule-based and heuristic; it can miss or over-flag. Times are compared within a single day. Text-layer PDFs only (no OCR). PII masking is basic. Credentials are not verified. Password reset by email needs a mail service and is not included.
* One process holds all cases in memory and SQLite is the store: fine for a demo or small team, not large multi-tenant use. Plain HTTP only. The session token is kept in `sessionStorage`.
* `tests/fixtures` and `tests/e2e-data` contain fictional material used only by tests and the MCP demo.

Layout: `dist/` built app · `backend/` server, MCP server, tests · `src/` engine (00–10), provider (06), UI (20–28), CSS · `docs/` · `build.py` (`python3 build.py app|engine|core`).
