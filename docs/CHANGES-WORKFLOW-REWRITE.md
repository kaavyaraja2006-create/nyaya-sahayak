# Court workflow, public pages and lawyer marketplace: what changed

All eight phases are implemented in the Node backend, the shared engine and the browser UI.

## Access model
* `caseAccess(user, case)` → `full` (assigned judge, assigned lawyers, personal-workspace creator), `hearing` (assigned stenographer) or none. Missing and forbidden cases both return `403 FORBIDDEN`.
* The stenographer gets case header, hearings, transcripts, document names and uploads only. `backend/src/views.js` builds each caller's view.

## Auth
* Lawyers: enrolment number + registered mobile + 6-digit code (`backend/src/otp.js`). Signup requires both; password login is refused for lawyers. Codes: 5 min, single use, HMAC-hashed at rest, attempt and rate limited, identical responses for unknown numbers.
* New roles: Court stenographer, Client. Clients cannot open case files.
* `ADMIN_EMAILS` accounts verify lawyers (`#/verification`).

## Features
* Case → Judge → Lawyer(s) → Stenographer → Hearing model; hearing state machine; stenographer "Start hearing" records all ids and audits it.
* Transcript workspace: large autosaving typing area (conflict-safe), generated transcript output, upload with progress.
* Public case tracking (`#/track`), find-a-lawyer (`#/find-lawyer`), requests, private chat, lawyer profile.

## Files
New: `backend/src/{otp,views,marketplace,errors}.js`, `frontend/src/{11-hearings,29-ui-court,30-ui-public}.js`, `backend/tests/workflow.test.js`, `frontend/tests/{e2e_workflow,e2e_standalone_court}.py`.
Changed: `backend/src/{server,db,config}.js`, `frontend/src/{02-auth,05-services,07-agents,20..23,27,28}*.js`, `style.css`, `build.py`, docs, `run-tests.sh`, `.env.example`.

## Behaviour changes to know about
* Case/document ids you cannot access return `403` (was `404`).
* Files are stored under `uploads/{case}/…` (old `uploads/{user}/{case}/…` still resolves).
* Database changes are applied automatically at start-up; see `docs/DATABASE.md`.

## Not done / limits
* Lawyer verification is a manual administrator step; nothing is checked against the Bar Council register automatically.
* SMS delivery needs your gateway (`SMS_WEBHOOK_URL`); without it codes go to the server log (development only).
* The FastAPI folder (`backend/app`) is the earlier non-functional skeleton and was left untouched.
* Docker files remain untested.
* Databases from the earlier prototype (different schema) are set aside automatically (renamed to `*.incompatible-<time>.db`, never deleted); the two shipped copies are kept under `backend/legacy-db/`.
