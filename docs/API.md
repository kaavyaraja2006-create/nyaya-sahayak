# REST API

Base path `/api`. JSON in and out. Protected routes need `Authorization: Bearer <jwt>`. Errors: `{ "error": { "code", "message", "errors"? } }`. Case IDs look like `NS-2026-001`. Another user's case always returns `404 CASE_NOT_FOUND`.

| Method & path | Purpose |
|---|---|
| `GET /health` | status (public, no secrets) |
| `POST /auth/signup` · `POST /auth/login` | returns `{ token, expiresInMinutes, user }` (login is throttled; generic error) |
| `POST /auth/logout` · `GET /auth/me` | revoke token · current user |
| `POST /auth/mcp-token` | 24 h token scoped to the MCP server only |
| `GET /sync` | user, all case snapshots and authority library (used by the web app) |
| `GET/POST /cases` · `GET/PUT/DELETE /cases/:id` · `POST /cases/:id/archive` | case CRUD; `GET /cases/:id/snapshot` returns the full case |
| `GET/POST /cases/:id/documents` · `PUT/DELETE …/documents/:docId` · `GET …/documents/:docId/file` | upload `{filename, contentBase64}` (pdf/docx/txt/md, ≤ `MAX_UPLOAD_MB`), change category, remove, download the original |
| `GET/POST /cases/:id/transcripts` | `{filename, contentBase64}` or `{text}`, plus `hearingDate`, `hearingNumber` |
| `POST /cases/:id/analyze` → `202 {run_id}` · `GET /cases/:id/analysis` | background run; poll for real agent-run records |
| `GET /cases/:id/agent-runs` · `…/claims` · `…/claims/:claimId` · `GET /claims/:claimId?case_id=` | agents and claims (detail includes evidence, conflicts, authorities, citations) |
| `GET /cases/:id/evidence` · `GET /evidence/:eid?case_id=` · `…/conflicts` · `…/authorities` · `…/citations` · `…/findings` | analysis outputs |
| `POST /cases/:id/findings/:fid/review` · `POST /claims/:claimId/review` (`case_id` in body) · `POST …/findings/:fid/open` | human review `{action: accept\|reject\|modify\|verify\|comment, comment, modifiedText}`; never overwrites the AI finding |
| `GET /cases/:id/reviews` · `GET /cases/:id/audit` | review records and audit events |
| `GET/POST /cases/:id/report` · `GET /cases/:id/reports/:rid/pdf` | preview JSON; generate + store PDF/JSON; download PDF |
| `GET/POST /authorities` · `DELETE /authorities/:id` · `GET /authorities/search?q=` | the user's own authority library (the app ships with none) |
| `GET /search?q=` | global search |
| `GET /mcp/tools` · `POST /mcp/call` | the tool layer over HTTP, as the caller |
| `GET /ai/status` · `PUT /ai/settings` · `POST /ai/test` | per-user Gemini consent/mask/model; the key never leaves the server |

## Court workflow, public pages and marketplace (added in this release)
Access: `full` = judge / assigned lawyers / personal-workspace creator; `hearing` = assigned stenographer. Everyone else: `403 FORBIDDEN`, identical for missing and forbidden cases. Case-scoped routes below marked *(hearing)* are open to the stenographer; the rest of the case routes above are `full` only.

| Route | Purpose |
|---|---|
| `POST /auth/signup` | lawyers must send `registrationNumber` (enrolment) and `phone`; the response is `{requiresOtp, challengeId, …}` with no session |
| `POST /auth/lawyer/otp/request` `{enrollmentNumber, mobile}` (public) | sends a code; same response whether or not the pair exists |
| `POST /auth/lawyer/otp/verify` `{challengeId, otp}` (public) | returns the session token; codes are single use |
| `POST /auth/login` | refused with `LAWYER_OTP_REQUIRED` for lawyer accounts |
| `PUT /cases/:id/assignment` *(hearing)* `{judgeId?, stenographerId?, lawyerIds?}` · `POST /cases/:id/leave` | who is on the case (judge/stenographer set by court staff only) |
| `PUT /cases/:id/public` *(hearing)* `{enabled, title, summary}` | switch public tracking on/off (managers only) |
| `GET/POST /cases/:id/hearings` · `GET/PUT /cases/:id/hearings/:hid` · `POST …/status` · `POST …/end` *(hearing)* | schedule, edit, adjourn/cancel, end |
| `POST /cases/:id/hearings/start` `{hearingId?, judgeId, lawyerIds, title?}` *(stenographer)* | starts a hearing and records case+hearing+judge+lawyers+stenographer |
| `GET/PUT /cases/:id/hearings/:hid/draft` `{text, baseRev}` *(assigned stenographer)* | autosaved typing area; `409 DRAFT_CONFLICT` if changed elsewhere |
| `POST /cases/:id/hearings/:hid/transcript` `{text}` *(assigned stenographer)* | create or revise the hearing's transcript document |
| `GET /hearings/active` · `GET /directory/:kind` (judges, lawyers, stenographers) | the caller's active hearing; who can be assigned (no contact details; not for clients) |
| `GET /public/cases/:id` (no sign-in, rate limited) | public status and hearing dates only |
| `POST /public/lawyers/match` (no sign-in, rate limited) · `GET /public/lawyers/:id` | rule-based matching with per-criterion reasons; optional `aiConsent` |
| `GET/PUT /lawyer/profile` · `GET /admin/lawyers` · `POST /admin/lawyers/:id/verify` | a lawyer's own profile; verification (accounts in `ADMIN_EMAILS`) |
| `POST/GET /requests` · `GET /requests/:id` · `POST /requests/:id/decision` | client → lawyer requests; contact details appear only after `ACCEPTED` |
| `GET/POST /requests/:id/messages` | private chat, only after acceptance and only for the two participants |
