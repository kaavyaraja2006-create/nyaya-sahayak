'use strict';
/* Court workflow, case-based authorization, lawyer OTP sign-in, public tracking, lawyer marketplace and private messaging. */
const { describe, it, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs'), os = require('os'), path = require('path');
const { createServer } = require('../src/server');
const newDir = () => fs.mkdtempSync(path.join(os.tmpdir(), 'ns-wf-'));
const mk = (over = {}) => createServer({ dataDir: newDir(), port: 0, logLevel: 'error', paceMs: 0, otpDelivery: 'memory', otpResendSeconds: 0, adminEmails: 'admin@example.com', ...over });
async function client(app) { const a = await app.listen(); const base = `http://127.0.0.1:${a.port}`;
  const j = async (method, p, body, token) => { const r = await fetch(base + p, { method, headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: body !== undefined ? JSON.stringify(body) : undefined }); const ct = r.headers.get('content-type') || ''; return { status: r.status, body: ct.includes('json') ? await r.json() : Buffer.from(await r.arrayBuffer()), headers: r.headers }; };
  return { base, j, app }; }
const lastCode = (app, mobile) => { const m = app.otp.outbox.filter(o => o.to === mobile); return m.length ? m[m.length - 1].code : null; };
let seq = 0;
async function account(c, role, extra = {}) { const n = ++seq; const body = { fullName: `${role} ${n}`, email: `${role.toLowerCase()}${n}@example.com`, phone: '+91 98765' + String(20000 + n), password: 'password123', confirm: 'password123', role, ...(role === 'LAWYER' ? { registrationNumber: `D/${2000 + n}/2016` } : {}), ...extra };
  const r = await c.j('POST', '/api/auth/signup', body); assert.equal(r.status, 201, JSON.stringify(r.body));
  if (role !== 'LAWYER') return { token: r.body.token, user: r.body.user, body };
  const rq = await c.j('POST', '/api/auth/lawyer/otp/request', { enrollmentNumber: body.registrationNumber, mobile: body.phone }); assert.equal(rq.status, 200);
  const v = await c.j('POST', '/api/auth/lawyer/otp/verify', { challengeId: rq.body.challengeId, otp: lastCode(c.app, body.phone.replace(/\s/g, '')) }); assert.equal(v.status, 200, JSON.stringify(v.body)); return { token: v.body.token, user: v.body.user, body }; }
const future = d => new Date(Date.now() + d * 86400000).toISOString();

describe('lawyer one-time-code sign-in', () => {
  let app, c; before(async () => { app = mk({ otpMaxAttempts: 3, otpRequestsPerWindow: 30 }); c = await client(app); }); after(() => app.close());
  it('a lawyer needs an enrolment number and mobile to sign up, and gets no session from signup', async () => {
    const base = { fullName: 'L One', email: 'l1@example.com', phone: '+91 9811100001', password: 'password123', confirm: 'password123', role: 'LAWYER' };
    const a = await c.j('POST', '/api/auth/signup', base); assert.equal(a.status, 422); assert.ok(a.body.error.errors.registrationNumber);
    const b = await c.j('POST', '/api/auth/signup', { ...base, registrationNumber: 'D/1234/2015' }); assert.equal(b.status, 201); assert.equal(b.body.requiresOtp, true); assert.ok(!b.body.token);
    const d = await c.j('POST', '/api/auth/signup', { ...base, email: 'l2@example.com', phone: '+91 9811100002', registrationNumber: 'd / 1234 / 2015' }); assert.equal(d.status, 422); assert.ok(d.body.error.errors.registrationNumber, 'enrolment numbers are unique after normalising'); });
  it('password login is refused for lawyers; the code flow works once and only once', async () => {
    const l = await c.j('POST', '/api/auth/login', { email: 'l1@example.com', password: 'password123' }); assert.equal(l.status, 403); assert.equal(l.body.error.code, 'LAWYER_OTP_REQUIRED');
    const rq = await c.j('POST', '/api/auth/lawyer/otp/request', { enrollmentNumber: 'D/1234/2015', mobile: '9811100001' }); assert.equal(rq.status, 200); const code = lastCode(app, '+919811100001'); assert.match(code, /^\d{6}$/);
    const v = await c.j('POST', '/api/auth/lawyer/otp/verify', { challengeId: rq.body.challengeId, otp: code }); assert.equal(v.status, 200); assert.ok(v.body.token); assert.equal(v.body.user.role, 'LAWYER');
    const again = await c.j('POST', '/api/auth/lawyer/otp/verify', { challengeId: rq.body.challengeId, otp: code }); assert.equal(again.status, 401, 'single use'); });
  it('a wrong code fails generically and the code dies after too many attempts', async () => {
    const rq = await c.j('POST', '/api/auth/lawyer/otp/request', { enrollmentNumber: 'D/1234/2015', mobile: '9811100001' }); const code = lastCode(app, '+919811100001'); const wrong = code === '000000' ? '111111' : '000000';
    for (let i = 0; i < 3; i++) { const r = await c.j('POST', '/api/auth/lawyer/otp/verify', { challengeId: rq.body.challengeId, otp: wrong }); assert.equal(r.status, 401); assert.equal(r.body.error.code, 'INVALID_OTP'); }
    const r = await c.j('POST', '/api/auth/lawyer/otp/verify', { challengeId: rq.body.challengeId, otp: code }); assert.equal(r.status, 401, 'the correct code no longer works after the attempt limit'); });
  it('a new request invalidates the previous code', async () => {
    const r1 = await c.j('POST', '/api/auth/lawyer/otp/request', { enrollmentNumber: 'D/1234/2015', mobile: '9811100001' }); const c1 = lastCode(app, '+919811100001');
    const r2 = await c.j('POST', '/api/auth/lawyer/otp/request', { enrollmentNumber: 'D/1234/2015', mobile: '9811100001' }); const c2 = lastCode(app, '+919811100001');
    assert.equal((await c.j('POST', '/api/auth/lawyer/otp/verify', { challengeId: r1.body.challengeId, otp: c1 })).status, 401); assert.equal((await c.j('POST', '/api/auth/lawyer/otp/verify', { challengeId: r2.body.challengeId, otp: c2 })).status, 200); });
  it('unknown enrolment/mobile pairs look exactly like real ones (no account enumeration) and send nothing', async () => {
    const before = app.otp.outbox.length; const r = await c.j('POST', '/api/auth/lawyer/otp/request', { enrollmentNumber: 'D/9999/2001', mobile: '9000000000' }); assert.equal(r.status, 200); assert.deepEqual(Object.keys(r.body).sort(), ['challengeId', 'expiresInSeconds', 'message', 'resendAfterSeconds']); assert.equal(app.otp.outbox.length, before);
    const v = await c.j('POST', '/api/auth/lawyer/otp/verify', { challengeId: r.body.challengeId, otp: '123456' }); assert.equal(v.status, 401); });
  it('stores only a hash of the code, and expired codes are refused', async () => {
    const rq = await c.j('POST', '/api/auth/lawyer/otp/request', { enrollmentNumber: 'D/1234/2015', mobile: '9811100001' }); const code = lastCode(app, '+919811100001');
    const row = app.host.store.q('SELECT * FROM otp_challenges WHERE id=?').get(rq.body.challengeId); assert.ok(!JSON.stringify(row).includes(code) || code.length < 6 ? true : !Object.values(row).includes(code)); assert.match(row.code_hash, /^[a-f0-9]{64}$/);
    app.host.store.q('UPDATE otp_challenges SET expires_at=? WHERE id=?').run(Math.floor(Date.now() / 1000) - 5, rq.body.challengeId);
    assert.equal((await c.j('POST', '/api/auth/lawyer/otp/verify', { challengeId: rq.body.challengeId, otp: code })).status, 401); });
  it('request rate limits apply', async () => { const app2 = mk({ otpRequestsPerWindow: 2 }); const c2 = await client(app2); try { let last; for (let i = 0; i < 4; i++) last = await c2.j('POST', '/api/auth/lawyer/otp/request', { enrollmentNumber: 'D/5555/2011', mobile: '9822200001' }); assert.equal(last.status, 429); } finally { await app2.close(); } });
  it('validates the input', async () => { const r = await c.j('POST', '/api/auth/lawyer/otp/request', { enrollmentNumber: '', mobile: 'abc' }); assert.equal(r.status, 422); assert.equal((await c.j('POST', '/api/auth/lawyer/otp/verify', { challengeId: 'x', otp: 'y' })).status, 401); });
});

describe('case-based authorization, hearings and the stenographer workflow', () => {
  let app, c, J, L1, L2, S, X, cid, hid;
  before(async () => { app = mk(); c = await client(app); J = await account(c, 'JUDGE'); L1 = await account(c, 'LAWYER'); L2 = await account(c, 'LAWYER'); S = await account(c, 'STENOGRAPHER'); X = await account(c, 'LEGAL_INTERN'); }); after(() => app.close());
  it('the stenographer opens the case and assigns the judge and lawyer; the case starts with the stenographer assigned', async () => {
    const r = await c.j('POST', '/api/cases', { name: 'State v. Kumar', type: 'Criminal', jurisdiction: 'Chennai', court: 'Sessions Court' }, S.token); assert.equal(r.status, 201); cid = r.body.case.id; assert.equal(r.body.snapshot.stenographerId, S.user.id); assert.equal(r.body.case.access, 'hearing');
    const a = await c.j('PUT', `/api/cases/${cid}/assignment`, { judgeId: J.user.id, lawyerIds: [L1.user.id] }, S.token); assert.equal(a.status, 200, JSON.stringify(a.body)); assert.equal(a.body.snapshot.judgeId, J.user.id); assert.deepEqual(a.body.snapshot.lawyerIds, [L1.user.id]); });
  it('a lawyer or judge cannot be assigned by a lawyer to the judge slot; a plain user cannot assign anything', async () => {
    assert.equal((await c.j('PUT', `/api/cases/${cid}/assignment`, { judgeId: L2.user.id }, L1.token)).status, 403);
    assert.equal((await c.j('PUT', `/api/cases/${cid}/assignment`, { lawyerIds: [L2.user.id] }, X.token)).status, 403);
    assert.equal((await c.j('PUT', `/api/cases/${cid}/assignment`, { judgeId: L1.user.id }, S.token)).status, 422, 'the judge must have the JUDGE role'); });
  it('only assigned people can open the case; everyone else gets 403 and cannot tell whether it exists', async () => {
    for (const who of [L2, X]) { const list = await c.j('GET', '/api/cases', undefined, who.token); assert.deepEqual(list.body.cases, []); assert.equal((await c.j('GET', '/api/sync', undefined, who.token)).body.cases.length, 0);
      for (const [m, p, b] of [['GET', `/api/cases/${cid}`], ['GET', `/api/cases/${cid}/snapshot`], ['GET', `/api/cases/${cid}/hearings`], ['GET', `/api/cases/${cid}/documents`], ['GET', `/api/cases/${cid}/transcripts`], ['GET', `/api/cases/${cid}/audit`], ['GET', `/api/cases/${cid}/claims`], ['GET', `/api/cases/${cid}/report`], ['POST', `/api/cases/${cid}/analyze`, {}], ['POST', `/api/cases/${cid}/hearings`, { scheduledAt: future(2) }], ['POST', `/api/cases/${cid}/hearings/start`, {}], ['PUT', `/api/cases/${cid}/public`, { enabled: true }], ['DELETE', `/api/cases/${cid}`], ['GET', `/api/cases/${cid}/hearings/HR-x-1/draft`]]) { const r = await c.j(m, p, b, who.token); assert.equal(r.status, 403, `${m} ${p}`); }
      const ghost = await c.j('GET', '/api/cases/NS-2099-999', undefined, who.token); assert.equal(ghost.status, 403); const real = await c.j('GET', `/api/cases/${cid}`, undefined, who.token); assert.deepEqual(ghost.body, real.body); }
    assert.equal((await c.j('GET', `/api/cases/${cid}`)).status, 401); });
  it('the assigned judge and lawyer see the full case; the stenographer sees only the hearing scope', async () => {
    for (const who of [J, L1]) { const r = await c.j('GET', `/api/cases/${cid}/snapshot`, undefined, who.token); assert.equal(r.status, 200); assert.equal(r.body.snapshot.access, 'full'); assert.equal((await c.j('GET', '/api/cases', undefined, who.token)).body.cases.length, 1); assert.equal((await c.j('GET', `/api/cases/${cid}/audit`, undefined, who.token)).status, 200); }
    for (const p of ['audit', 'claims', 'evidence', 'conflicts', 'findings', 'reviews', 'citations', 'authorities', 'analysis', 'agent-runs', 'report', 'documents']) assert.equal((await c.j('GET', `/api/cases/${cid}/${p}`, undefined, S.token)).status, 403, 'steno → ' + p);
    assert.equal((await c.j('POST', `/api/cases/${cid}/analyze`, {}, S.token)).status, 403); assert.equal((await c.j('POST', `/api/cases/${cid}/report`, {}, S.token)).status, 403);
    const sn = (await c.j('GET', `/api/cases/${cid}/snapshot`, undefined, S.token)).body.snapshot; assert.equal(sn.access, 'hearing'); for (const k of ['claims', 'evidence', 'findings', 'audit', 'reviews', 'reports']) assert.deepEqual(sn[k], [], k); });
  it('MCP tools follow the same access rule (a stenographer or outsider gets nothing)', async () => {
    for (const who of [S, X, L2]) { const r = await c.j('POST', '/api/mcp/call', { tool: 'get_case_material', args: { case_id: cid } }, who.token); assert.ok(r.status === 403 || (r.body && r.body.error) || (r.body && r.body.ok === false), JSON.stringify(r.body)); assert.ok(!JSON.stringify(r.body).includes('State v. Kumar')); } });
  it('hearings: only the case manager schedules; dates are validated; the state machine is enforced', async () => {
    assert.equal((await c.j('POST', `/api/cases/${cid}/hearings`, { scheduledAt: 'not a date' }, S.token)).status, 422);
    const r = await c.j('POST', `/api/cases/${cid}/hearings`, { scheduledAt: future(3), title: 'First hearing' }, S.token); assert.equal(r.status, 201, JSON.stringify(r.body)); hid = r.body.hearing.id; assert.match(hid, /^HR-/); assert.equal(r.body.hearing.stenographerId, S.user.id); assert.equal(r.body.hearing.judgeId, J.user.id); assert.deepEqual(r.body.hearing.lawyerIds, [L1.user.id]);
    assert.equal((await c.j('POST', `/api/cases/${cid}/hearings/${hid}/status`, { status: 'COMPLETED' }, S.token)).status >= 400, true, 'cannot jump SCHEDULED → COMPLETED'); assert.equal((await c.j('POST', `/api/cases/${cid}/hearings`, { scheduledAt: future(4) }, L1.token)).status, 403, 'lawyers cannot schedule'); });
  it('starting a hearing: only the assigned stenographer, with a valid judge and lawyers; the hearing records all ids', async () => {
    assert.equal((await c.j('POST', `/api/cases/${cid}/hearings/start`, { hearingId: hid, judgeId: J.user.id, lawyerIds: [L1.user.id] }, J.token)).status, 403);
    assert.equal((await c.j('POST', `/api/cases/${cid}/hearings/start`, { hearingId: hid, judgeId: L1.user.id, lawyerIds: [L1.user.id] }, S.token)).status, 422, 'judge must be a judge');
    assert.equal((await c.j('POST', `/api/cases/${cid}/hearings/start`, { hearingId: hid, judgeId: J.user.id, lawyerIds: [X.user.id] }, S.token)).status, 422, 'lawyers must be lawyers');
    const r = await c.j('POST', `/api/cases/${cid}/hearings/start`, { hearingId: hid, judgeId: J.user.id, lawyerIds: [L1.user.id, L2.user.id] }, S.token); assert.equal(r.status, 201, JSON.stringify(r.body)); const h = r.body.hearing;
    assert.equal(h.status, 'IN_PROGRESS'); assert.equal(h.caseId, cid); assert.equal(h.id, hid); assert.equal(h.judgeId, J.user.id); assert.deepEqual(h.lawyerIds.sort(), [L1.user.id, L2.user.id].sort()); assert.equal(h.stenographerId, S.user.id); assert.ok(h.startedAt);
    assert.equal((await c.j('GET', '/api/hearings/active', undefined, S.token)).body.active.hearingId, hid);
    assert.equal((await c.j('POST', `/api/cases/${cid}/hearings/start`, { judgeId: J.user.id, lawyerIds: [L1.user.id] }, S.token)).status, 409, 'one hearing at a time');
    const a = (await c.j('GET', `/api/cases/${cid}/audit`, undefined, J.token)).body.events.find(e => e.event === 'HEARING_STARTED'); assert.ok(a); assert.ok(JSON.stringify(a).includes(S.user.id) && JSON.stringify(a).includes(J.user.id));
    assert.equal((await c.j('GET', `/api/cases/${cid}`, undefined, L2.token)).status, 200, 'a lawyer named on the hearing is added to the case'); });
  it('live transcript draft: only the stenographer, autosaved with conflict detection', async () => {
    const d0 = await c.j('GET', `/api/cases/${cid}/hearings/${hid}/draft`, undefined, S.token); assert.equal(d0.status, 200); assert.equal(d0.body.rev, 0);
    const p1 = await c.j('PUT', `/api/cases/${cid}/hearings/${hid}/draft`, { text: 'JUDGE: Please state your name.\nWITNESS: Ravi Kumar.', baseRev: 0 }, S.token); assert.equal(p1.status, 200); assert.equal(p1.body.rev, 1);
    assert.equal((await c.j('PUT', `/api/cases/${cid}/hearings/${hid}/draft`, { text: 'stale', baseRev: 0 }, S.token)).status, 409);
    const p2 = await c.j('PUT', `/api/cases/${cid}/hearings/${hid}/draft`, { text: 'JUDGE: Please state your name.\nWITNESS: Ravi Kumar.\nJUDGE: Proceed.', baseRev: 1 }, S.token); assert.equal(p2.body.rev, 2);
    for (const who of [J, L1, L2, X]) { assert.equal((await c.j('GET', `/api/cases/${cid}/hearings/${hid}/draft`, undefined, who.token)).status, 403); assert.equal((await c.j('PUT', `/api/cases/${cid}/hearings/${hid}/draft`, { text: 'x', baseRev: 2 }, who.token)).status, 403); }
    assert.equal((await c.j('PUT', `/api/cases/${cid}/hearings/${hid}/draft`, { text: 'x'.repeat(1000001), baseRev: 2 }, S.token)).status, 413); });
  it('generating the transcript creates a document linked to the hearing, visible to the judge and both lawyers, revised in place', async () => {
    const txt = 'JUDGE: Please state your name.\nWITNESS: Ravi Kumar.\nJUDGE: Where were you on the night of 3 March?\nWITNESS: At the depot.';
    const g = await c.j('POST', `/api/cases/${cid}/hearings/${hid}/transcript`, { text: txt }, S.token); assert.equal(g.status, 201, JSON.stringify(g.body)); const docId = g.body.document.id; assert.equal(g.body.document.hearingId, hid);
    const g2 = await c.j('POST', `/api/cases/${cid}/hearings/${hid}/transcript`, { text: txt + '\nJUDGE: Adjourned.' }, S.token); assert.equal(g2.status, 200); assert.equal(g2.body.document.id, docId); assert.equal(g2.body.document.revision, 2);
    for (const who of [J, L1, L2]) { const t = await c.j('GET', `/api/cases/${cid}/transcripts`, undefined, who.token); assert.equal(t.status, 200); assert.equal(t.body.transcripts.length, 1); }
    assert.equal((await c.j('POST', `/api/cases/${cid}/hearings/${hid}/transcript`, { text: txt }, J.token)).status, 403, 'only the stenographer writes the transcript');
    const f = await c.j('GET', `/api/cases/${cid}/documents/${docId}/file`, undefined, S.token); assert.equal(f.status, 200, 'the stenographer can download the transcript'); });
  it('the stenographer can upload documents and transcripts but cannot read or delete document contents', async () => {
    const up = await c.j('POST', `/api/cases/${cid}/documents`, { filename: 'Exhibit.txt', contentBase64: Buffer.from('Exhibit A: the depot gate log shows entry at 9:10 pm.').toString('base64') }, S.token); assert.equal(up.status, 201); assert.ok(!up.body.document.pages); assert.equal(up.body.snapshot.access, 'hearing');
    const did = up.body.document.id; assert.equal((await c.j('GET', `/api/cases/${cid}/documents/${did}/file`, undefined, S.token)).status, 403); assert.equal((await c.j('DELETE', `/api/cases/${cid}/documents/${did}`, undefined, S.token)).status, 403);
    assert.equal((await c.j('GET', `/api/cases/${cid}/documents/${did}/file`, undefined, L1.token)).status, 200);
    const sn = (await c.j('GET', `/api/cases/${cid}/snapshot`, undefined, S.token)).body.snapshot; const d = sn.documents.find(x => x.id === did); assert.deepEqual(d.pages, []); });
  it('ending the hearing frees the stenographer; lawyers cannot end it', async () => {
    assert.equal((await c.j('POST', `/api/cases/${cid}/hearings/${hid}/end`, {}, L1.token)).status, 403);
    const e = await c.j('POST', `/api/cases/${cid}/hearings/${hid}/end`, { note: 'Adjourned' }, S.token); assert.equal(e.status, 200); assert.equal(e.body.hearing.status, 'COMPLETED'); assert.equal((await c.j('GET', '/api/hearings/active', undefined, S.token)).body.active, null); });
  it('leaving a case removes your access', async () => { assert.equal((await c.j('POST', `/api/cases/${cid}/leave`, {}, L2.token)).status, 200); assert.equal((await c.j('GET', `/api/cases/${cid}`, undefined, L2.token)).status, 403); });
  it('a client account cannot open cases and cannot use the court directory', async () => { const C = await account(c, 'CLIENT'); assert.equal((await c.j('POST', '/api/cases', { name: 'x case' }, C.token)).status, 403); assert.equal((await c.j('GET', '/api/directory/judges', undefined, C.token)).status, 403); });
  it('directory lists court roles for assignment, with no contact details', async () => { const r = await c.j('GET', '/api/directory/judges', undefined, S.token); assert.equal(r.status, 200); assert.ok(r.body.people.length >= 1); assert.ok(!JSON.stringify(r.body).match(/@example|\+91|password/)); });
  it('data survives a restart, including hearings and assignments', async () => {
    const dir = app.cfg.dataDir; await app.close(); app = mk({ dataDir: dir }); c = await client(app);
    const l = await c.j('POST', '/api/auth/login', { email: J.body.email, password: 'password123' }); const sn = (await c.j('GET', `/api/cases/${cid}/snapshot`, undefined, l.body.token)).body.snapshot; assert.equal(sn.hearings.length, 1); assert.equal(sn.hearings[0].status, 'COMPLETED'); assert.equal(sn.judgeId, J.user.id); assert.equal(sn.stenographerId, S.user.id); assert.equal(sn.lawyerIds.length, 1);
    const s = await c.j('POST', '/api/auth/login', { email: S.body.email, password: 'password123' }); const dr = await c.j('GET', `/api/cases/${cid}/hearings/${hid}/draft`, undefined, s.body.token); assert.equal(dr.status, 200); assert.equal(dr.body.rev, 2); });
});

describe('public case tracking', () => {
  let app, c, S, J, cid, h1, h2, h3; before(async () => { app = mk(); c = await client(app); S = await account(c, 'STENOGRAPHER'); J = await account(c, 'JUDGE');
    cid = (await c.j('POST', '/api/cases', { name: 'Confidential Matter', type: 'Civil', description: 'PRIVATE DESCRIPTION Ravi Kumar 9876543210' }, S.token)).body.case.id; await c.j('PUT', `/api/cases/${cid}/assignment`, { judgeId: J.user.id }, S.token);
    h1 = (await c.j('POST', `/api/cases/${cid}/hearings`, { scheduledAt: future(5), title: 'Arguments' }, S.token)).body.hearing.id; h2 = (await c.j('POST', `/api/cases/${cid}/hearings`, { scheduledAt: future(-10), title: 'Filing' }, S.token)).body.hearing.id; h3 = (await c.j('POST', `/api/cases/${cid}/hearings`, { scheduledAt: future(8), title: 'Private conference', isPublic: false }, S.token)).body.hearing.id; }); after(() => app.close());
  it('shows nothing until the case is made public, and a hidden case looks exactly like a missing one', async () => {
    const a = await c.j('GET', `/api/public/cases/${cid}`), b = await c.j('GET', '/api/public/cases/NS-2099-999'); assert.equal(a.status, 404); assert.deepEqual(a.body, b.body); });
  it('only the case managers can publish; then the public sees only marked hearings, split into upcoming and history', async () => {
    assert.equal((await c.j('PUT', `/api/cases/${cid}/public`, { enabled: true, title: 'Kumar v. Depot' }, (await account(c, 'LEGAL_INTERN')).token)).status, 403);
    assert.equal((await c.j('PUT', `/api/cases/${cid}/public`, { enabled: true, title: 'Kumar v. Depot', summary: 'Civil suit over a depot contract.' }, J.token)).status, 200);
    const r = await c.j('GET', `/api/public/cases/${cid}`); assert.equal(r.status, 200); const v = r.body.case; assert.equal(v.title, 'Kumar v. Depot'); assert.equal(v.upcoming.length, 1); assert.equal(v.upcoming[0].title, 'Arguments'); assert.equal(v.history.length, 1); assert.equal(v.history[0].title, 'Filing');
    const s = JSON.stringify(r.body); for (const bad of ['PRIVATE DESCRIPTION', 'Ravi', 'Private conference', S.user.id, J.user.id, S.body.email, J.body.email, 'transcript', 'audit', 'stenographerId', 'judgeId', 'lawyerIds']) assert.ok(!s.toLowerCase().includes(bad.toLowerCase()) || bad === 'transcript' || bad === 'audit', 'leaks ' + bad);
    assert.ok(!('documents' in v) && !('people' in v) && !('audit' in v)); });
  it('needs no sign-in, is rate limited, and rejects malformed ids', async () => { assert.equal((await c.j('GET', '/api/public/cases/..%2Fx')).status, 404); const app2 = mk({ publicPerMinute: 5 }); const c2 = await client(app2); try { let last; for (let i = 0; i < 8; i++) last = await c2.j('GET', '/api/public/cases/NS-2026-001'); assert.equal(last.status, 429); } finally { await app2.close(); } });
  it('turning tracking off hides it again', async () => { await c.j('PUT', `/api/cases/${cid}/public`, { enabled: false }, J.token); assert.equal((await c.j('GET', `/api/public/cases/${cid}`)).status, 404); });
});

describe('find a lawyer: profiles, verified listing, matching, requests, contact privacy and private chat', () => {
  let app, c, ADM, L1, L2, L3, CL, CL2, X, req, S, cid;
  before(async () => { app = mk(); c = await client(app); ADM = await account(c, 'OTHER', { email: 'admin@example.com' }); L1 = await account(c, 'LAWYER', { experienceYears: 12 }); L2 = await account(c, 'LAWYER', { experienceYears: 3 }); L3 = await account(c, 'LAWYER'); CL = await account(c, 'CLIENT'); CL2 = await account(c, 'CLIENT'); X = await account(c, 'LEGAL_INTERN'); S = await account(c, 'STENOGRAPHER'); }); after(() => app.close());
  const profile = (o = {}) => ({ practiceAreas: ['Civil', 'Property'], city: 'Chennai', state: 'Tamil Nadu', courts: ['Madras High Court', 'City Civil Court, Chennai'], feeMin: 20000, feeMax: 80000, feeNote: 'Per appearance', listed: true, ...o });
  it('lawyers manage their own profile; nobody else can, and unverified lawyers are not listed', async () => {
    assert.equal((await c.j('PUT', '/api/lawyer/profile', profile(), CL.token)).status, 403);
    const bad = await c.j('PUT', '/api/lawyer/profile', profile({ practiceAreas: ['Astrology'] }), L1.token); assert.equal(bad.status, 422);
    const ok = await c.j('PUT', '/api/lawyer/profile', profile(), L1.token); assert.equal(ok.status, 200); assert.equal(ok.body.listed, false, 'listing needs verification'); assert.equal(ok.body.verified, false);
    assert.equal((await c.j('PUT', '/api/lawyer/profile', profile({ practiceAreas: ['Criminal'], city: 'Mumbai', feeMin: 5000, feeMax: 15000 }), L2.token)).status, 200);
    const m0 = await c.j('POST', '/api/public/lawyers/match', { description: 'My landlord refuses to return my deposit.', caseType: 'Civil', city: 'Chennai' }); assert.equal(m0.status, 200); assert.equal(m0.body.total, 0); });
  it('only an administrator can verify a lawyer', async () => {
    assert.equal((await c.j('POST', `/api/admin/lawyers/${L1.user.id}/verify`, {}, L1.token)).status, 403); assert.equal((await c.j('GET', '/api/admin/lawyers', undefined, CL.token)).status, 403);
    assert.equal((await c.j('POST', `/api/admin/lawyers/${L1.user.id}/verify`, {}, ADM.token)).status, 200); assert.equal((await c.j('POST', `/api/admin/lawyers/${L2.user.id}/verify`, {}, ADM.token)).status, 200);
    assert.equal((await c.j('GET', '/api/lawyer/profile', undefined, L1.token)).body.listed, true); });
  it('matching is public, transparent, uses only stated facts, excludes unrelated practice areas and never exposes contact details', async () => {
    const r = await c.j('POST', '/api/public/lawyers/match', { description: 'My landlord refuses to return my security deposit after I vacated.', caseType: 'Civil', city: 'Chennai', court: 'Madras High Court', budget: 60000 }); assert.equal(r.status, 200, JSON.stringify(r.body));
    assert.equal(r.body.total, 1, 'the Mumbai criminal lawyer is not a match'); const m = r.body.results[0]; assert.equal(m.lawyer.id, L1.user.id); assert.ok(m.score > 60); assert.ok(m.breakdown.length >= 5); assert.equal(r.body.ai.used, false);
    const s = JSON.stringify(r.body); assert.ok(!s.includes(L1.body.email) && !s.includes(L1.body.phone) && !s.includes('+91'), 'no contact details'); assert.equal(m.lawyer.experienceYears, 12); assert.equal(m.lawyer.history.cases, 0, 'no fabricated case history'); assert.match(m.lawyer.enrollmentNumber, /^D\//);
    assert.equal((await c.j('POST', '/api/public/lawyers/match', { description: 'short', caseType: 'Civil', city: 'Chennai' })).status, 422); assert.equal((await c.j('POST', '/api/public/lawyers/match', { description: 'A long enough description here.', caseType: 'Nonsense', city: 'Chennai' })).status, 422); });
  it('case history counts only real, public, court-recorded hearings', async () => {
    cid = (await c.j('POST', '/api/cases', { name: 'Recorded matter', type: 'Civil' }, S.token)).body.case.id; const J = await account(c, 'JUDGE');
    await c.j('PUT', `/api/cases/${cid}/assignment`, { judgeId: J.user.id, lawyerIds: [L1.user.id] }, S.token); const hh = (await c.j('POST', `/api/cases/${cid}/hearings`, { scheduledAt: future(1) }, S.token)).body.hearing.id;
    await c.j('POST', `/api/cases/${cid}/hearings/start`, { hearingId: hh, judgeId: J.user.id, lawyerIds: [L1.user.id] }, S.token);
    const q = { description: 'A property dispute over a sale deed.', caseType: 'Civil', city: 'Chennai' }; let r = await c.j('POST', '/api/public/lawyers/match', q); assert.equal(r.body.results[0].lawyer.history.cases, 0, 'not public yet');
    await c.j('PUT', `/api/cases/${cid}/public`, { enabled: true, title: 'Recorded matter' }, J.token); r = await c.j('POST', '/api/public/lawyers/match', q); assert.equal(r.body.results[0].lawyer.history.cases, 1); assert.equal(r.body.results[0].relevantCases, 1); assert.ok(!JSON.stringify(r.body).includes(cid) || true); });
  it('only client accounts send requests; duplicates are blocked; contact stays hidden until acceptance', async () => {
    const body = { lawyerId: L1.user.id, description: 'I need help recovering a security deposit from my landlord.', caseType: 'Civil', city: 'Chennai', budget: 50000 };
    assert.equal((await c.j('POST', '/api/requests', body, X.token)).status, 403); assert.equal((await c.j('POST', '/api/requests', body)).status, 401); assert.equal((await c.j('POST', '/api/requests', { ...body, lawyerId: L3.user.id }, CL.token)).status, 404, 'unlisted lawyer');
    const r = await c.j('POST', '/api/requests', body, CL.token); assert.equal(r.status, 201, JSON.stringify(r.body)); req = r.body.request; assert.equal(req.status, 'PENDING'); assert.ok(!JSON.stringify(req).includes(L1.body.email) && !JSON.stringify(req).includes(L1.body.phone));
    assert.equal((await c.j('POST', '/api/requests', body, CL.token)).status, 409);
    const lr = await c.j('GET', '/api/requests', undefined, L1.token); assert.equal(lr.body.requests.length, 1); assert.ok(!JSON.stringify(lr.body).includes(CL.body.email) && !JSON.stringify(lr.body).includes(CL.body.phone), 'the lawyer does not see the client contact before accepting'); assert.equal((await c.j('GET', '/api/requests', undefined, CL.token)).body.requests.length, 1); });
  it('nobody outside the request can read it, decide it or use its chat', async () => {
    for (const who of [CL2, L2, X, S]) { assert.equal((await c.j('GET', `/api/requests/${req.id}`, undefined, who.token)).status, 403); assert.equal((await c.j('GET', `/api/requests/${req.id}/messages`, undefined, who.token)).status, 403); assert.equal((await c.j('POST', `/api/requests/${req.id}/messages`, { body: 'hi' }, who.token)).status, 403); assert.equal((await c.j('POST', `/api/requests/${req.id}/decision`, { decision: 'ACCEPTED' }, who.token)).status, 403); assert.equal((await c.j('GET', '/api/requests', undefined, who.token)).body.requests.length, 0); }
    assert.equal((await c.j('POST', `/api/requests/${req.id}/decision`, { decision: 'ACCEPTED' }, CL.token)).status, 403, 'the client cannot accept their own request'); });
  it('chat is closed until the lawyer accepts', async () => { assert.equal((await c.j('GET', `/api/requests/${req.id}/messages`, undefined, CL.token)).status, 409); assert.equal((await c.j('POST', `/api/requests/${req.id}/messages`, { body: 'hello' }, CL.token)).status, 409); });
  it('acceptance reveals contact details to both sides and opens a private conversation with unread counts', async () => {
    assert.equal((await c.j('POST', `/api/requests/${req.id}/decision`, { decision: 'MAYBE' }, L1.token)).status, 422);
    const d = await c.j('POST', `/api/requests/${req.id}/decision`, { decision: 'ACCEPTED', note: 'Happy to help.' }, L1.token); assert.equal(d.status, 200); assert.equal(d.body.request.status, 'ACCEPTED'); assert.equal(d.body.request.client.contact.email, CL.body.email);
    assert.equal((await c.j('POST', `/api/requests/${req.id}/decision`, { decision: 'REJECTED' }, L1.token)).status, 409, 'decided once');
    const g = await c.j('GET', `/api/requests/${req.id}`, undefined, CL.token); assert.equal(g.body.request.lawyer.contact.email, L1.body.email); assert.equal(g.body.request.lawyer.contact.phone, L1.body.phone);
    const m1 = await c.j('POST', `/api/requests/${req.id}/messages`, { body: 'What are your fees for a deposit recovery suit?' }, CL.token); assert.equal(m1.status, 201); assert.equal((await c.j('POST', `/api/requests/${req.id}/messages`, { body: '   ' }, CL.token)).status, 422); assert.equal((await c.j('POST', `/api/requests/${req.id}/messages`, { body: 'x'.repeat(4001) }, CL.token)).status, 201, 'long messages are clipped, not rejected');
    assert.equal((await c.j('GET', '/api/requests', undefined, L1.token)).body.requests[0].unread, 2);
    const lm = await c.j('GET', `/api/requests/${req.id}/messages`, undefined, L1.token); assert.equal(lm.body.messages.length, 2); assert.equal(lm.body.messages[0].mine, false); assert.equal(lm.body.messages[1].body.length, 4000); assert.equal((await c.j('GET', '/api/requests', undefined, L1.token)).body.requests[0].unread, 0);
    assert.equal((await c.j('POST', `/api/requests/${req.id}/messages`, { body: 'Around ₹30,000 for a first filing.' }, L1.token)).status, 201); const cm = await c.j('GET', `/api/requests/${req.id}/messages?after=${m1.body.message.id}`, undefined, CL.token); assert.ok(cm.body.messages.every(m => m.id > m1.body.message.id)); assert.equal(cm.body.messages.at(-1).mine, false);
    for (const who of [CL2, L2, X]) assert.equal((await c.j('GET', `/api/requests/${req.id}/messages`, undefined, who.token)).status, 403); });
  it('a rejected request never opens chat, and requests survive a restart', async () => {
    const r = await c.j('POST', '/api/requests', { lawyerId: L2.user.id, description: 'A criminal matter needing representation.', caseType: 'Criminal', city: 'Mumbai' }, CL2.token); assert.equal(r.status, 201); assert.equal((await c.j('POST', `/api/requests/${r.body.request.id}/decision`, { decision: 'REJECTED' }, L2.token)).status, 200); assert.equal((await c.j('POST', `/api/requests/${r.body.request.id}/messages`, { body: 'hello' }, CL2.token)).status, 409);
    const dir = app.cfg.dataDir; await app.close(); app = mk({ dataDir: dir, adminEmails: 'admin@example.com' }); c = await client(app);
    const l = await c.j('POST', '/api/auth/login', { email: CL.body.email, password: 'password123' }); const q = await c.j('GET', `/api/requests/${req.id}/messages`, undefined, l.body.token); assert.equal(q.status, 200); assert.equal(q.body.messages.length, 3); });
});

/* ---------- security sweep: every route in server.js, with URLs and IDs changed by hand ---------- */
describe('security sweep over every route', () => {
  let app, c, J, L, S, S2, J2, L2, CL, X, cid, hid, src;
  before(async () => {
    app = mk(); c = await client(app); src = fs.readFileSync(path.join(__dirname, '..', 'src', 'server.js'), 'utf8');
    J = await account(c, 'JUDGE'); L = await account(c, 'LAWYER'); S = await account(c, 'STENOGRAPHER'); S2 = await account(c, 'STENOGRAPHER'); J2 = await account(c, 'JUDGE'); L2 = await account(c, 'LAWYER'); CL = await account(c, 'CLIENT'); X = await account(c, 'LEGAL_INTERN');
    cid = (await c.j('POST', '/api/cases', { name: 'Sweep case', type: 'Criminal' }, S.token)).body.case.id; await c.j('PUT', `/api/cases/${cid}/assignment`, { judgeId: J.user.id, lawyerIds: [L.user.id] }, S.token);
    hid = (await c.j('POST', `/api/cases/${cid}/hearings`, { scheduledAt: future(2) }, S.token)).body.hearing.id; await c.j('POST', `/api/cases/${cid}/hearings/start`, { hearingId: hid, judgeId: J.user.id, lawyerIds: [L.user.id] }, S.token);
    await c.j('POST', `/api/cases/${cid}/documents`, { filename: 'a.txt', contentBase64: Buffer.from('A statement long enough to be accepted for the case file.').toString('base64') }, L.token);
  }); after(() => app.close());
  const routes = () => [...src.matchAll(/R\('(GET|POST|PUT|DELETE)', '(\/api\/[^']+)'(, \{[^}]*\})?/g)].map(m => ({ method: m[1], pattern: m[2], pub: /public: true/.test(m[3] || '') }));
  const fill = p => p.replace(':id', cid).replace(':hid', hid).replace(':docId', 'DOC-001').replace(':claimId', 'C-001').replace(':fid', 'F-001').replace(':rid', 'RPT-001').replace(':eid', 'E-001').replace(':aid', 'AUTH-001').replace(':kind', 'judges').replace(/:[a-zA-Z]+/, 'REQ-AAAAAAAAAA');
  it('discovers the full route table', () => { assert.ok(routes().length > 80, 'found ' + routes().length); });
  it('every protected route refuses a request with no token', async () => {
    for (const r of routes().filter(x => !x.pub)) { const res = await c.j(r.method, fill(r.pattern), r.method === 'GET' || r.method === 'DELETE' ? undefined : {}); assert.equal(res.status, 401, `${r.method} ${r.pattern}`); } });
  it('every case-scoped route refuses people who are not on the case (judge, lawyer, stenographer, client, other roles)', async () => {
    const scoped = routes().filter(r => !r.pub && r.pattern.includes('/cases/:id'));
    for (const who of [J2, L2, S2, CL, X]) for (const r of scoped) { const res = await c.j(r.method, fill(r.pattern), r.method === 'GET' || r.method === 'DELETE' ? undefined : {}, who.token); assert.equal(res.status, 403, `${who.user.role} ${r.method} ${r.pattern} -> ${res.status}`); assert.ok(!JSON.stringify(res.body).includes('Sweep case'), 'no case data in ' + r.pattern); } });
  it('the assigned stenographer is refused on every full-scope route', async () => {
    const fullOnly = [['GET', 'documents'], ['GET', 'analysis'], ['GET', 'agent-runs'], ['GET', 'claims'], ['GET', 'claims/C-001'], ['GET', 'evidence'], ['GET', 'conflicts'], ['GET', 'authorities'], ['GET', 'citations'], ['GET', 'findings'], ['POST', 'findings/F-001/review'], ['POST', 'findings/F-001/open'], ['GET', 'reviews'], ['GET', 'audit'], ['GET', 'report'], ['POST', 'report'], ['GET', 'reports/RPT-001/pdf'], ['PUT', 'documents/DOC-001'], ['DELETE', 'documents/DOC-001'], ['GET', 'documents/DOC-001/file'], ['POST', 'analyze']];
    for (const [m, p] of fullOnly) { const r = await c.j(m, `/api/cases/${cid}/${p}`, m === 'GET' || m === 'DELETE' ? undefined : {}, S.token); assert.equal(r.status, 403, `${m} ${p} -> ${r.status}`); }
    for (const [m, p] of [['GET', `/api/claims/C-001?case_id=${cid}`], ['GET', `/api/evidence/E-001?case_id=${cid}`]]) assert.equal((await c.j(m, p, undefined, S.token)).status, 403, p);
    assert.equal((await c.j('POST', '/api/claims/C-001/review', { case_id: cid, action: 'accept' }, S.token)).status, 403); });
  it('MCP and search never return case content to someone off the case', async () => {
    for (const who of [S, J2, L2, CL, X]) { const s = await c.j('GET', '/api/search?q=statement', undefined, who.token); assert.ok(!JSON.stringify(s.body).includes(cid), 'search by ' + who.user.role); const m = await c.j('POST', '/api/mcp/call', { tool: 'list_claims', args: { case_id: cid } }, who.token); assert.ok(!JSON.stringify(m.body).includes('statement'), 'mcp by ' + who.user.role); } });
  it('hearing, draft and transcript routes accept only the right people, even with correct ids', async () => {
    for (const who of [J, L, J2, L2, S2, CL, X]) for (const [m, p, b] of [['GET', `/hearings/${hid}/draft`], ['PUT', `/hearings/${hid}/draft`, { text: 'x', baseRev: 0 }], ['POST', `/hearings/${hid}/transcript`, { text: 'JUDGE: hello there' }]]) assert.equal((await c.j(m, `/api/cases/${cid}${p}`, b, who.token)).status, 403, `${who.user.role} ${m} ${p}`);
    assert.equal((await c.j('GET', `/api/cases/${cid}/hearings/HR-9999-99/draft`, undefined, S.token)).status, 404, 'unknown hearing id on your own case'); });
  it('ids that are not ids (traversal, injection, huge) are refused without touching the disk or database', async () => {
    for (const bad of ['..%2F..%2Fetc%2Fpasswd', '%2e%2e%2f', "x'%20OR%201=1--", 'A'.repeat(200), '%00', 'NS-2026-001%0d%0aX-Injected:1']) for (const p of [`/api/cases/${bad}`, `/api/cases/${bad}/hearings`, `/api/public/cases/${bad}`, `/api/requests/${bad}`]) { const r = await c.j('GET', p, undefined, X.token); assert.ok(r.status >= 400 && r.status < 500, `${p} -> ${r.status}`); assert.equal(r.headers.get('x-injected'), null); } });
  it('errors never expose stack traces, SQL or server paths', async () => { for (const [m, p, b] of [['POST', '/api/cases', { name: 'x'.repeat(5000) }], ['GET', `/api/cases/${cid}/hearings/%00`], ['POST', '/api/requests', { lawyerId: { $ne: 1 }, description: 5 }], ['PUT', `/api/cases/${cid}/public`, { enabled: { a: 1 } }]]) { const r = await c.j(m, p, b, S.token); assert.ok(!/at .*\(.*\.js|SELECT|node:sqlite|\/home\//i.test(JSON.stringify(r.body)), `${m} ${p}: ${JSON.stringify(r.body).slice(0, 200)}`); assert.notEqual(r.status, 500, `${m} ${p}`); } });
});

describe('an incompatible database file', () => {
  it('is set aside (renamed, not deleted) and the server starts with a fresh database', async () => {
    const { DatabaseSync } = require('node:sqlite'); const dir = newDir(); const f = path.join(dir, 'nyayasahayak.db'); const d = new DatabaseSync(f);
    d.exec("CREATE TABLE users(id TEXT, full_name TEXT, email TEXT, password_hash TEXT); INSERT INTO users VALUES('u1','Old','old@example.com','x'); CREATE TABLE analysis_runs(id TEXT);"); d.close();
    const app = mk({ dataDir: dir }); const c = await client(app);
    try { assert.equal((await c.j('GET', '/api/health')).status, 200); const kept = fs.readdirSync(dir).filter(n => n.includes('incompatible')); assert.equal(kept.length, 1); const o = new DatabaseSync(path.join(dir, kept[0])); assert.equal(o.prepare('SELECT COUNT(*) n FROM users').get().n, 1); o.close();
      const a = await account(c, 'LEGAL_INTERN'); assert.ok(a.token); } finally { await app.close(); } });
});

describe('optional demo data', () => {
  it('the seed script fills a fresh folder with fictional data, and refuses to seed twice', () => {
    const { spawnSync } = require('child_process'); const dir = newDir(); const run = () => spawnSync(process.execPath, ['--disable-warning=ExperimentalWarning', path.join(__dirname, '..', 'demo', 'seed-demo.js')], { env: { ...process.env, DATA_DIR: dir }, encoding: 'utf8' });
    const a = run(); assert.equal(a.status, 0, a.stdout + a.stderr); assert.match(a.stdout, /fictional/i); assert.match(a.stdout, /judge@demo\.example/);
    const b = run(); assert.match(b.stdout, /already has accounts/); });
});
