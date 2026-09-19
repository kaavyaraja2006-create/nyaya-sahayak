# Demo

1. `python3 build.py app` (only if you changed `src/`), then `cd backend && npm start`, open http://127.0.0.1:8000.
2. Sign up, create a case, add documents and a transcript, add the authorities you rely on, run the analysis.
3. Open a claim → source passage → evidence → potential conflict → Compare sources → review with a comment → Audit trail → Reports (PDF/JSON/CSV).
4. Sign out and back in: everything is still there.

There is no built-in case. `tests/e2e-data/` holds fictional files used only by the tests and the MCP demo; you can upload them to try the flow.
