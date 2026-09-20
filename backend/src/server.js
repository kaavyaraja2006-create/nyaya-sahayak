'use strict';
/* NyayaSahayak API server. Node 22+, no third-party packages.
   Layers: HTTP → routes (this file) → engine services (dist/engine.js, ownership-checked) → SQLite (db.js). */
const http = require('http'), fs = require('fs'), path = require('path'), crypto = require('crypto');
const { load } = require('./config'); const { Host } = require('./engine-host');
const { signJwt, verifyJwt, loadSecret, Throttle, safeJoin, safeName } = require('./security');
const { ApiError } = require('./errors'); const { OtpService, OtpError } = require('./otp'); const { makeViews } = require('./views'); const { makeMarketplace } = require('./marketplace');
const ID_RE = /^[A-Za-z0-9._-]{1,48}$/;
const MIME = { pdf: 'application/pdf', docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', txt: 'text/plain', md: 'text/plain' };

function createServer(over = {}) {
  const cfg = load(over); const LV = { debug: 10, info: 20, warn: 30, error: 40 };
  const log = (level, msg, f = {}) => { if ((LV[level] || 20) >= (LV[cfg.logLevel] || 20)) process.stdout.write(JSON.stringify({ ts: new Date().toISOString(), level, msg, ...f }) + '\n'); };
  const secret = loadSecret(cfg); const host = new Host(cfg, log); const N = host.N; const throttle = new Throttle(cfg.loginMaxFailures, cfg.loginWindowMs);
  fs.mkdirSync(cfg.uploadsDir, { recursive: true });
  const running = new Set();
  const views = makeViews(host, cfg); const otp = new OtpService(cfg, host.store, secret, log); const market = makeMarketplace(host, cfg, views, log); const pubThrottle = new Throttle(cfg.publicPerMinute, 60000);

  /* ---------- helpers ---------- */
  const pub = views.pub;
  const clone = o => JSON.parse(JSON.stringify(o));
  const issue = (u, scp = 'access', minutes = cfg.tokenMinutes) => { const now = Math.floor(Date.now() / 1000); return signJwt({ sub: u.id, iat: now, exp: now + minutes * 60, jti: crypto.randomBytes(12).toString('hex'), scp }, secret); };
  function mapError(e) {
    if (e instanceof ApiError) return e;
    if (e instanceof OtpError) return new ApiError(e.status, e.code, e.message, e.extra);
    const c = e && e.code;
    /* a case that does not exist and one you may not open are answered identically, so case ids cannot be probed */
    if (c === 'CASE_NOT_FOUND' || c === 'PERMISSION_DENIED') return new ApiError(403, 'FORBIDDEN', 'You do not have access to this case.');
    if (c === 'FORBIDDEN_ROLE') return new ApiError(403, c, e.message);
    if (c === 'BAD_STATE' || c === 'ALREADY_ACTIVE') return new ApiError(409, c, e.message);
    if (c === 'FILE_TOO_LARGE') return new ApiError(413, c, e.message);
    if (c === 'VALIDATION' || c === 'VALIDATION_ERROR') return new ApiError(422, 'VALIDATION_ERROR', e.message, e.errors ? { errors: e.errors } : undefined);
    if (c === 'ARCHIVED' || c === 'ALREADY_RUNNING') return new ApiError(409, c, e.message);
    if (c === 'NO_MATERIAL') return new ApiError(422, c, e.message);
    if (c === 'UNAUTHENTICATED') return new ApiError(401, c, e.message);
    if (typeof c === 'string' && /_NOT_FOUND$/.test(c)) return new ApiError(404, c, e.message);
    if (typeof c === 'string' && c.startsWith('AI_')) return new ApiError(502, c, e.message);
    log('error', 'unhandled', { message: e && e.message, stack: String(e && e.stack || '').split('\n').slice(0, 3).join(' | ') });
    return new ApiError(500, 'INTERNAL_ERROR', 'The server could not complete this request.');
  }
  const denied = () => new ApiError(403, 'FORBIDDEN', 'You do not have access to this case.');
  /* scope 'full' (default) = judge / lawyer / workspace owner; 'hearing' = also the assigned stenographer */
  const own = (ctx, cid, scope = 'full') => { if (!ID_RE.test(cid)) throw denied(); return host.as(ctx.user.id, N => scope === 'full' ? N.CaseSvc.get(ctx.user.id, cid) : N.CaseSvc.getAny(ctx.user.id, cid)); };
  const summary = (ctx, C) => views.summary(ctx.user, C);
  const snap = (ctx, cid) => views.snapshot(ctx.user, host.as(ctx.user.id, N => N.CaseSvc.getAny(ctx.user.id, cid)));
  const caseDir = cid => safeJoin(cfg.uploadsDir, cid);
  /* files live under uploads/{case}/…; databases written by the first release stored them under uploads/{creator}/{case}/… and still resolve */
  const resolveStored = (C, rel) => { const abs = safeJoin(cfg.uploadsDir, rel); const ok = [caseDir(C.id), safeJoin(cfg.uploadsDir, C.userId, C.id)].some(r => abs.startsWith(r + path.sep)); if (!ok) throw new ApiError(404, 'DOC_NOT_FOUND', 'Document not found.'); return abs; };
  const requireRole = (ctx, ...roles) => { if (!roles.includes(ctx.user.role)) throw new ApiError(403, 'FORBIDDEN_ROLE', 'Your account type cannot do this.'); };
  const rate = ctx => { if (pubThrottle.blocked(ctx.ip)) throw new ApiError(429, 'TOO_MANY_REQUESTS', 'Too many requests. Wait a minute and try again.'); pubThrottle.fail(ctx.ip); };
  const run = (ctx, fn) => { try { return host.as(ctx.user.id, fn); } finally { try { host.flush(); } catch (e) { log('error', 'persist_failed', { message: e.message }); } } };
  const fileLike = (buf, name) => ({ name, size: buf.length, arrayBuffer: async () => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), text: async () => buf.toString('utf8') });

  /* Stores an uploaded document / transcript. The stenographer (hearing scope) may add both; nobody else's rights change.
     Files are stored under uploads/{case}/… so every person assigned to the case reads the same copy. */
  async function ingest(ctx, cid, body, kind) {
    const C0 = own(ctx, cid, 'hearing'); const b = body || {}; let buf, name, ext; const uid = ctx.user.id;
    /* hearing association: explicit hearingId, otherwise the stenographer's active hearing on this case */
    let hearingId = b.hearingId ? String(b.hearingId) : null; if (hearingId && !ID_RE.test(hearingId)) throw new ApiError(422, 'VALIDATION_ERROR', 'That hearing is not valid.');
    if (!hearingId) { const a = host.as(uid, N => N.HearingSvc.active(uid)); if (a && a.caseId === cid) hearingId = a.hearingId; }
    if (hearingId && kind === 'transcript') { const h = (C0.hearings || []).find(x => x.id === hearingId); if (!h) throw new ApiError(422, 'VALIDATION_ERROR', 'That hearing does not belong to this case.'); if (h.stenographerId !== uid) throw denied(); }
    if (b.contentBase64 != null) {
      name = String(b.filename || ''); if (!name || name.length > 255) throw new ApiError(422, 'VALIDATION_ERROR', 'filename is required.', { errors: { filename: 'Provide a file name.' } });
      ext = (name.split('.').pop() || '').toLowerCase(); if (!MIME[ext]) throw new ApiError(415, 'UNSUPPORTED_FILE', 'Unsupported file type. Use PDF, DOCX or TXT.');
      const s = String(b.contentBase64); if (s.length > cfg.maxUploadBytes * 1.4 + 16 || !/^[A-Za-z0-9+/=\s]*$/.test(s)) throw new ApiError(413, 'FILE_TOO_LARGE', 'The file is larger than the upload limit or not valid base64.');
      buf = Buffer.from(s, 'base64'); if (!buf.length) throw new ApiError(422, 'EMPTY_FILE', 'The file is empty.'); if (buf.length > cfg.maxUploadBytes) throw new ApiError(413, 'FILE_TOO_LARGE', `The file is larger than the ${Math.round(cfg.maxUploadBytes / 1048576)} MB limit.`);
      if (ext === 'pdf' && buf.subarray(0, 5).toString('latin1') !== '%PDF-') throw new ApiError(415, 'UNSUPPORTED_FILE', 'The file content is not a PDF.');
      if (ext === 'docx' && !(buf[0] === 0x50 && buf[1] === 0x4b)) throw new ApiError(415, 'UNSUPPORTED_FILE', 'The file content is not a DOCX.');
      if ((ext === 'txt' || ext === 'md') && buf.subarray(0, 4096).includes(0)) throw new ApiError(415, 'UNSUPPORTED_FILE', 'The file does not look like plain text.');
    } else if (typeof b.text === 'string' && kind === 'transcript') {
      if (b.text.trim().length < 10) throw new ApiError(422, 'VALIDATION_ERROR', 'Paste the transcript text.', { errors: { text: 'Paste the transcript text.' } }); if (b.text.length > 2000000) throw new ApiError(413, 'FILE_TOO_LARGE', 'The transcript is too long.');
      buf = Buffer.from(b.text, 'utf8'); name = String(b.filename || 'Pasted transcript.txt'); ext = 'txt';
    } else throw new ApiError(422, 'VALIDATION_ERROR', 'Send contentBase64 with filename, or text for a transcript.');
    const parsed = await N.parseFile(fileLike(buf, name)); if (!parsed.ok) throw new ApiError(422, 'PARSE_ERROR', parsed.error);
    return run(ctx, N => {
      const d = N.DocSvc.add(uid, cid, { filename: name, text: parsed.text, mime: parsed.mime, size: buf.length, extractor: parsed.extractor, extractNote: parsed.note || '', kind, hearingId, category: b.category && kind === 'document' ? String(b.category) : undefined, hearingDate: b.hearingDate ? String(b.hearingDate).slice(0, 10) : null, hearingNumber: b.hearingNumber ? String(b.hearingNumber).slice(0, 20) : null });
      store_file(cid, kind === 'transcript' ? 'transcripts' : 'documents', d, name, buf, parsed.text); const Cn = N.CaseSvc.getAny(uid, cid); Cn.updatedAt = new Date().toISOString();
      log('info', 'document_uploaded', { case: cid, doc: d.id, bytes: buf.length });
      const access = N.caseAccess(ctx.user, Cn); const meta = access === 'full' ? clone({ ...d, pages: undefined }) : { id: d.id, kind: d.kind, filename: d.filename, category: d.category, status: d.status, pageCount: d.pageCount, uploadedAt: d.uploadedAt, hearingId: d.hearingId, statementCount: d.statementCount };
      return { document: meta, snapshot: views.snapshot(ctx.user, Cn) };
    });
  }
  function store_file(cid, sub, d, name, buf, text) {
    const rel = path.join(cid, sub, `${d.id}_${safeName(name)}`); const abs = safeJoin(cfg.uploadsDir, rel); fs.mkdirSync(path.dirname(abs), { recursive: true }); fs.writeFileSync(abs, buf, { mode: 0o640 });
    const ex = safeJoin(cfg.uploadsDir, cid, 'extracted', `${d.id}.txt`); fs.mkdirSync(path.dirname(ex), { recursive: true }); fs.writeFileSync(ex, text || '');
    d.storagePath = rel.split(path.sep).join('/'); d.sha256 = crypto.createHash('sha256').update(buf).digest('hex');
  }

  /* ---------- route table ---------- */
  const routes = []; const R = (method, pattern, opts, fn) => { if (typeof opts === 'function') { fn = opts; opts = {}; } const keys = []; const re = new RegExp('^' + pattern.replace(/:([a-zA-Z_]+)/g, (_, k) => { keys.push(k); return '([^/]+)'; }) + '/?$'); routes.push({ method, re, keys, opts, fn }); };

  R('GET', '/api/health', { public: true }, () => ({ status: 'ok', service: 'nyayasahayak', version: '1.0.0', storage: 'sqlite', ai: { provider: cfg.geminiKey ? 'gemini+rules' : 'local-rules', configured: !!cfg.geminiKey } }));

  /* auth */
  const lawyerKey = u => `${N.normEnroll(u.registrationNumber)}|${N.normPhone(u.phone)}`;
  R('POST', '/api/auth/signup', { public: true }, async ctx => {
    const r = await N.signup(ctx.body || {}); N.setSession(null); if (!r.ok) throw new ApiError(422, 'VALIDATION_ERROR', 'Please correct the highlighted fields.', { errors: r.errors }); host.flush();
    log('info', 'signup', { user: r.user.id, role: r.user.role });
    /* lawyers do not get a session from signup: the first sign-in proves control of the registered mobile number */
    if (r.user.role === 'LAWYER') { let c = null, sent = true; try { c = await otp.request({ user: r.user, key: lawyerKey(r.user), ip: ctx.ip, mobile: N.normPhone(r.user.phone) }); } catch (e) { sent = false; log('warn', 'signup_otp_failed', { code: e && e.code }); }
      return { status: 201, body: { requiresOtp: true, otpSent: sent, ...(c || {}), user: pub(r.user), message: sent ? 'Account created. Enter the one-time code sent to your registered mobile number.' : 'Account created, but the one-time code could not be sent. Use “Send code” on the sign-in page.' } }; }
    return { status: 201, body: { token: issue(r.user), expiresInMinutes: cfg.tokenMinutes, user: pub(r.user) } };
  });
  R('POST', '/api/auth/login', { public: true }, async ctx => {
    const email = String((ctx.body || {}).email || '').trim().toLowerCase(); const key = ctx.ip + '|' + email;
    if (throttle.blocked(key)) throw new ApiError(429, 'TOO_MANY_ATTEMPTS', 'Too many failed sign-in attempts. Try again later.');
    const r = await N.login(email, String((ctx.body || {}).password || '')); N.setSession(null);
    if (!r.ok) { throttle.fail(key); log('warn', 'login_failed', { ip: ctx.ip }); throw new ApiError(401, 'INVALID_CREDENTIALS', 'Invalid email or password.'); }
    if (r.user.role === 'LAWYER') { throttle.clear(key); throw new ApiError(403, 'LAWYER_OTP_REQUIRED', 'Lawyers sign in with their State Bar Council enrolment number, registered mobile number and a one-time code.'); }
    throttle.clear(key); return { token: issue(r.user), expiresInMinutes: cfg.tokenMinutes, user: pub(r.user) };
  });
  /* lawyer sign-in: enrolment number + registered mobile → one-time code by SMS → session */
  R('POST', '/api/auth/lawyer/otp/request', { public: true }, async ctx => {
    const b = ctx.body || {}; const enr = N.normEnroll(b.enrollmentNumber), mob = N.normPhone(b.mobile);
    if (!N.validEnroll(enr) || !mob) throw new ApiError(422, 'VALIDATION_ERROR', 'Enter your enrolment number and registered mobile number.', { errors: { ...(N.validEnroll(enr) ? {} : { enrollmentNumber: 'Enter your State Bar Council enrolment number.' }), ...(mob ? {} : { mobile: 'Enter the mobile number registered with your Bar Council.' }) } });
    const user = host.DB.users.find(u => u.role === 'LAWYER' && N.normEnroll(u.registrationNumber) === enr && N.normPhone(u.phone) === mob) || null;
    const c = await otp.request({ user, key: `${enr}|${mob}`, ip: ctx.ip, mobile: mob }); log('info', 'otp_requested', { ip: ctx.ip, known: !!user });
    return { ...c, message: 'If these details match a registered lawyer, a one-time code has been sent to the registered mobile number.' };
  });
  R('POST', '/api/auth/lawyer/otp/verify', { public: true }, ctx => {
    const b = ctx.body || {}; const { userId } = otp.verify({ challengeId: b.challengeId, code: b.otp, ip: ctx.ip }); const user = host.DB.users.find(u => u.id === userId);
    if (!user || user.role !== 'LAWYER') throw new OtpError(401, 'INVALID_OTP', 'That code is not valid or has expired. Request a new code.');
    if (!user.mobileVerified) { user.mobileVerified = true; user.updatedAt = new Date().toISOString(); host.flush(); }
    log('info', 'lawyer_login', { user: user.id }); return { token: issue(user), expiresInMinutes: cfg.tokenMinutes, user: pub(user) };
  });
  R('POST', '/api/auth/logout', ctx => { host.store.revoke(ctx.claims.jti, ctx.claims.exp); return { ok: true }; });
  R('GET', '/api/auth/me', ctx => ({ user: pub(ctx.user) }));
  R('POST', '/api/auth/mcp-token', ctx => ({ token: issue(ctx.user, 'mcp', 24 * 60), note: 'Set as NS_MCP_TOKEN for backend/mcp-server.js. Valid for 24 hours; scoped to the MCP server only.' }));

  /* whole-account snapshot used by the web client: only cases this user may open, each cut down to what their role may see */
  R('GET', '/api/sync', ctx => run(ctx, N => ({ user: pub(ctx.user), cases: N.CaseSvc.listAny(ctx.user.id).map(C => views.snapshot(ctx.user, C)), authorities: clone(N.AuthSvc.list(ctx.user.id)) })));

  /* cases */
  R('GET', '/api/cases', ctx => run(ctx, N => ({ cases: N.CaseSvc.listAny(ctx.user.id).map(C => summary(ctx, C)) })));
  R('POST', '/api/cases', ctx => run(ctx, N => { const C = N.CaseSvc.create(ctx.user.id, ctx.body || {}); return { status: 201, body: { case: summary(ctx, C), snapshot: views.snapshot(ctx.user, C) } }; }));
  R('GET', '/api/cases/:id', ctx => { const C = own(ctx, ctx.params.id, 'hearing'); return { case: summary(ctx, C) }; });
  R('GET', '/api/cases/:id/snapshot', ctx => { own(ctx, ctx.params.id, 'hearing'); return { snapshot: snap(ctx, ctx.params.id) }; });
  R('PUT', '/api/cases/:id', ctx => run(ctx, N => { own(ctx, ctx.params.id, 'hearing'); const C = N.CaseSvc.update(ctx.user.id, ctx.params.id, ctx.body || {}); return { case: summary(ctx, C), snapshot: views.snapshot(ctx.user, C) }; }));
  R('POST', '/api/cases/:id/archive', ctx => run(ctx, N => { own(ctx, ctx.params.id, 'hearing'); const C = N.CaseSvc.archive(ctx.user.id, ctx.params.id, (ctx.body || {}).archived !== false); return { case: summary(ctx, C), snapshot: views.snapshot(ctx.user, C) }; }));
  R('DELETE', '/api/cases/:id', ctx => run(ctx, N => { const C = own(ctx, ctx.params.id, 'hearing'); const owner = C.userId; N.CaseSvc.remove(ctx.user.id, ctx.params.id); for (const d of [caseDir(C.id), safeJoin(cfg.uploadsDir, owner, C.id)]) { try { fs.rmSync(d, { recursive: true, force: true }); } catch (e) {} } return { ok: true }; }));
  /* people on the case */
  R('PUT', '/api/cases/:id/assignment', ctx => run(ctx, N => { own(ctx, ctx.params.id, 'hearing'); const b = ctx.body || {}; const o = {}; ['judgeId', 'stenographerId', 'lawyerIds'].forEach(k => { if (k in b) o[k] = b[k]; }); const C = N.CaseSvc.assign(ctx.user.id, ctx.params.id, o); return { snapshot: views.snapshot(ctx.user, C) }; }));
  R('POST', '/api/cases/:id/leave', ctx => run(ctx, N => { own(ctx, ctx.params.id, 'hearing'); N.CaseSvc.leave(ctx.user.id, ctx.params.id); return { ok: true }; }));
  R('PUT', '/api/cases/:id/public', ctx => run(ctx, N => { own(ctx, ctx.params.id, 'hearing'); const b = ctx.body || {}; const o = {}; ['enabled', 'title', 'summary'].forEach(k => { if (k in b) o[k] = b[k]; }); const C = N.CaseSvc.setPublic(ctx.user.id, ctx.params.id, o); return { snapshot: views.snapshot(ctx.user, C), preview: views.publicCase(C.id) }; }));

  /* documents and transcripts */
  R('GET', '/api/cases/:id/documents', ctx => run(ctx, N => ({ documents: N.CaseSvc.get(ctx.user.id, ctx.params.id).documents.filter(d => d.kind === 'document').map(d => clone({ ...d, pages: undefined })) })));
  R('POST', '/api/cases/:id/documents', async ctx => ({ status: 201, body: await ingest(ctx, ctx.params.id, ctx.body, 'document') }));
  R('GET', '/api/cases/:id/transcripts', ctx => run(ctx, N => ({ transcripts: N.CaseSvc.getAny(ctx.user.id, ctx.params.id).documents.filter(d => d.kind === 'transcript').map(d => clone({ ...d, pages: undefined })) })));
  R('POST', '/api/cases/:id/transcripts', async ctx => ({ status: 201, body: await ingest(ctx, ctx.params.id, ctx.body, 'transcript') }));
  R('PUT', '/api/cases/:id/documents/:docId', ctx => run(ctx, N => { N.DocSvc.setCategory(ctx.user.id, ctx.params.id, ctx.params.docId, String((ctx.body || {}).category || '')); return { snapshot: snap(ctx, ctx.params.id) }; }));
  R('DELETE', '/api/cases/:id/documents/:docId', ctx => run(ctx, N => { N.DocSvc.remove(ctx.user.id, ctx.params.id, ctx.params.docId); return { snapshot: snap(ctx, ctx.params.id) }; }));
  R('GET', '/api/cases/:id/documents/:docId/file', { raw: true }, ctx => {
    const C = own(ctx, ctx.params.id, 'hearing'); const acc = host.as(ctx.user.id, N => N.caseAccess(ctx.user, C)); const d = C.documents.find(x => x.id === ctx.params.docId); if (!d || !d.storagePath) throw new ApiError(404, 'DOC_NOT_FOUND', 'Document not found.'); if (acc !== 'full' && d.kind !== 'transcript') throw denied();
    const abs = resolveStored(C, d.storagePath); if (!fs.existsSync(abs)) throw new ApiError(404, 'DOC_NOT_FOUND', 'The stored file is missing.');
    const ext = (d.filename.split('.').pop() || '').toLowerCase(); return { raw: fs.readFileSync(abs), type: MIME[ext] || 'application/octet-stream', name: safeName(d.filename) };
  });

  /* hearings: Case → Judge → Lawyer(s) → Stenographer → Hearing */
  R('GET', '/api/hearings/active', ctx => run(ctx, N => ({ active: N.HearingSvc.active(ctx.user.id) })));
  R('GET', '/api/cases/:id/hearings', ctx => run(ctx, N => ({ hearings: clone(N.HearingSvc.list(ctx.user.id, ctx.params.id)) })));
  R('POST', '/api/cases/:id/hearings', ctx => run(ctx, N => { own(ctx, ctx.params.id, 'hearing'); const h = N.HearingSvc.schedule(ctx.user.id, ctx.params.id, ctx.body || {}); return { status: 201, body: { hearing: clone(h), snapshot: snap(ctx, ctx.params.id) } }; }));
  R('POST', '/api/cases/:id/hearings/start', ctx => run(ctx, N => { own(ctx, ctx.params.id, 'hearing'); const b = ctx.body || {}; const h = N.HearingSvc.start(ctx.user.id, ctx.params.id, { hearingId: b.hearingId ? String(b.hearingId) : undefined, judgeId: b.judgeId, lawyerIds: b.lawyerIds, title: b.title }); return { status: 201, body: { hearing: clone(h), snapshot: snap(ctx, ctx.params.id) } }; }));
  R('GET', '/api/cases/:id/hearings/:hid', ctx => run(ctx, N => ({ hearing: clone(N.HearingSvc.get(ctx.user.id, ctx.params.id, ctx.params.hid)) })));
  R('PUT', '/api/cases/:id/hearings/:hid', ctx => run(ctx, N => { own(ctx, ctx.params.id, 'hearing'); const b = ctx.body || {}; const o = {}; ['scheduledAt', 'title', 'isPublic', 'publicNote'].forEach(k => { if (k in b) o[k] = b[k]; }); const h = N.HearingSvc.update(ctx.user.id, ctx.params.id, ctx.params.hid, o); return { hearing: clone(h), snapshot: snap(ctx, ctx.params.id) }; }));
  R('POST', '/api/cases/:id/hearings/:hid/status', ctx => run(ctx, N => { own(ctx, ctx.params.id, 'hearing'); const b = ctx.body || {}; const r = N.HearingSvc.setStatus(ctx.user.id, ctx.params.id, ctx.params.hid, String(b.status || ''), { scheduledAt: b.scheduledAt, nextDate: b.nextDate, note: b.note }); return { hearing: clone(r.hearing), next: r.next ? clone(r.next) : null, snapshot: snap(ctx, ctx.params.id) }; }));
  R('POST', '/api/cases/:id/hearings/:hid/end', ctx => run(ctx, N => { own(ctx, ctx.params.id, 'hearing'); const h = N.HearingSvc.end(ctx.user.id, ctx.params.id, ctx.params.hid, { note: (ctx.body || {}).note }); return { hearing: clone(h), snapshot: snap(ctx, ctx.params.id) }; }));
  /* the stenographer's typing area is saved on the server as they type, so a refresh or a crashed browser loses nothing */
  const writable = (ctx, cid, hid) => host.as(ctx.user.id, N => { const C = N.CaseSvc.getAny(ctx.user.id, cid); const h = (C.hearings || []).find(x => x.id === hid); if (!h) throw new ApiError(404, 'HEARING_NOT_FOUND', 'No hearing was found for the supplied hearing_id.'); if (h.stenographerId !== ctx.user.id) throw denied(); return { C, h, can: N.HearingSvc.canWriteTranscript(ctx.user.id, C, h) }; });
  R('GET', '/api/cases/:id/hearings/:hid/draft', ctx => { const { C, h } = writable(ctx, ctx.params.id, ctx.params.hid); const r = host.store.q('SELECT body,rev,updated_at FROM hearing_drafts WHERE case_id=? AND hearing_id=?').get(C.id, h.id); return { text: r ? r.body : '', rev: r ? r.rev : 0, updatedAt: r ? r.updated_at : null }; });
  R('PUT', '/api/cases/:id/hearings/:hid/draft', ctx => {
    const { C, h, can } = writable(ctx, ctx.params.id, ctx.params.hid); if (!can) throw new ApiError(409, 'BAD_STATE', 'Drafts can be saved while the hearing is in progress or after it has ended.');
    const b = ctx.body || {}; const text = String(b.text == null ? '' : b.text); if (text.length > N.DRAFT_MAX_CHARS) throw new ApiError(413, 'FILE_TOO_LARGE', 'The transcript is too long.');
    const cur = host.store.q('SELECT rev FROM hearing_drafts WHERE case_id=? AND hearing_id=?').get(C.id, h.id); const base = Number(b.baseRev) || 0; if (cur && base !== cur.rev) throw new ApiError(409, 'DRAFT_CONFLICT', 'This transcript was changed elsewhere (another tab or device). Reload to see the latest text.', { rev: cur.rev });
    const rev = (cur ? cur.rev : 0) + 1, t = new Date().toISOString(); host.store.q('INSERT INTO hearing_drafts(case_id,hearing_id,body,rev,updated_at,updated_by) VALUES(?,?,?,?,?,?) ON CONFLICT(case_id,hearing_id) DO UPDATE SET body=excluded.body,rev=excluded.rev,updated_at=excluded.updated_at,updated_by=excluded.updated_by').run(C.id, h.id, text, rev, t, ctx.user.id);
    return { rev, savedAt: t, chars: text.length };
  });
  R('POST', '/api/cases/:id/hearings/:hid/transcript', ctx => {
    const { C, h, can } = writable(ctx, ctx.params.id, ctx.params.hid); if (!can) throw new ApiError(409, 'BAD_STATE', 'A transcript can be generated while the hearing is in progress or after it has ended.');
    const text = String((ctx.body || {}).text || ''); const oldDoc = h.transcriptDocId;
    return run(ctx, N => { const d = N.HearingSvc.generateTranscript(ctx.user.id, C.id, h.id, text); const buf = Buffer.from(text, 'utf8');
      store_file(C.id, 'transcripts', d, `Hearing ${h.number} transcript.txt`, buf, text); N.CaseSvc.getAny(ctx.user.id, C.id).updatedAt = new Date().toISOString();
      return { status: oldDoc ? 200 : 201, body: { document: { id: d.id, filename: d.filename, statementCount: d.statementCount, status: d.status, revision: d.revision || 1, hearingId: h.id }, snapshot: snap(ctx, C.id) } }; });
  });

  /* directory of registered court roles, for choosing who to assign to a case */
  R('GET', '/api/directory/:kind', ctx => {
    if (ctx.user.role === 'CLIENT') throw new ApiError(403, 'FORBIDDEN_ROLE', 'Your account type cannot do this.');
    const role = { judges: 'JUDGE', lawyers: 'LAWYER', stenographers: 'STENOGRAPHER' }[ctx.params.kind]; if (!role) throw new ApiError(404, 'NOT_FOUND', 'Not found.'); const q = String(ctx.query.q || '').trim().toLowerCase();
    const list = host.DB.users.filter(u => u.role === role && (!q || u.fullName.toLowerCase().includes(q) || String(u.registrationNumber || '').toLowerCase().includes(q))).map(u => ({ ...views.person(u), city: (u.profile || {}).city || '' })).sort((a, b) => (b.verified - a.verified) || a.name.localeCompare(b.name)).slice(0, 50);
    return { people: list };
  });

  /* ---------- public (no sign-in) ---------- */
  R('GET', '/api/public/cases/:id', { public: true }, ctx => { rate(ctx); const id = ctx.params.id; const v = ID_RE.test(id) ? views.publicCase(id) : null; if (!v) throw new ApiError(404, 'CASE_NOT_FOUND', 'No public case was found with that Case ID. It may not exist, or its owner has not made it public.'); return { case: v }; });
  R('POST', '/api/public/lawyers/match', { public: true }, async ctx => { rate(ctx); return await market.match(ctx.body || {}); });
  R('GET', '/api/public/lawyers/:id', { public: true }, ctx => { rate(ctx); const u = ID_RE.test(ctx.params.id) ? host.DB.users.find(x => x.id === ctx.params.id) : null; if (!u || !market.isListed(u)) throw new ApiError(404, 'LAWYER_NOT_FOUND', 'That lawyer is not available.'); return { lawyer: market.publicLawyer(u, true) }; });

  /* lawyer's own marketplace profile, and the verification desk (accounts listed in ADMIN_EMAILS only) */
  R('GET', '/api/lawyer/profile', ctx => { requireRole(ctx, 'LAWYER'); return { profile: ctx.user.profile || {}, experienceYears: ctx.user.experienceYears == null ? null : ctx.user.experienceYears, verified: !!ctx.user.verified, listed: market.isListed(ctx.user) }; });
  R('PUT', '/api/lawyer/profile', ctx => { requireRole(ctx, 'LAWYER'); market.saveProfile(ctx.user, ctx.body || {}); return { profile: ctx.user.profile || {}, experienceYears: ctx.user.experienceYears == null ? null : ctx.user.experienceYears, verified: !!ctx.user.verified, listed: market.isListed(ctx.user), user: pub(ctx.user) }; });
  const adminOnly = ctx => { if (!views.isAdmin(ctx.user)) throw new ApiError(403, 'FORBIDDEN_ROLE', 'Only a verification administrator can do this.'); };
  R('GET', '/api/admin/lawyers', ctx => { adminOnly(ctx); return { lawyers: host.DB.users.filter(u => u.role === 'LAWYER').map(u => ({ id: u.id, name: u.fullName, enrollmentNumber: u.registrationNumber, phone: u.phone, verified: !!u.verified, verifiedAt: u.verifiedAt || null, createdAt: u.createdAt })) }; });
  R('POST', '/api/admin/lawyers/:id/verify', ctx => { adminOnly(ctx); const u = host.DB.users.find(x => x.id === ctx.params.id && x.role === 'LAWYER'); if (!u) throw new ApiError(404, 'USER_NOT_FOUND', 'Lawyer not found.'); const v = (ctx.body || {}).verified !== false; u.verified = v; u.verifiedAt = v ? new Date().toISOString() : null; u.updatedAt = new Date().toISOString(); host.flush(); log('info', 'lawyer_verification', { admin: ctx.user.id, lawyer: u.id, verified: v }); return { id: u.id, verified: v }; });

  /* requests to lawyers and the private conversation that opens once one is accepted */
  R('POST', '/api/requests', ctx => ({ status: 201, body: { request: market.createRequest(ctx.user, ctx.body || {}) } }));
  R('GET', '/api/requests', ctx => ({ requests: market.listRequests(ctx.user) }));
  R('GET', '/api/requests/:id', ctx => ({ request: market.getRequest(ctx.user, ctx.params.id) }));
  R('POST', '/api/requests/:id/decision', ctx => { requireRole(ctx, 'LAWYER'); return { request: market.decide(ctx.user, ctx.params.id, ctx.body || {}) }; });
  R('GET', '/api/requests/:id/messages', ctx => ({ messages: market.messages(ctx.user, ctx.params.id, ctx.query.after) }));
  R('POST', '/api/requests/:id/messages', ctx => ({ status: 201, body: { message: market.postMessage(ctx.user, ctx.params.id, ctx.body || {}) } }));

  /* analysis: returns immediately; agents run in the background and write real run records */
  R('POST', '/api/cases/:id/analyze', ctx => {
    own(ctx, ctx.params.id); if (running.has(ctx.params.id)) throw new ApiError(409, 'ALREADY_RUNNING', 'Analysis is already running for this case.');
    return run(ctx, N => { const uid = ctx.user.id, cid = ctx.params.id; const p = N.runAnalysis(uid, cid, { paceMs: cfg.paceMs }); const C = N.CaseSvc.get(uid, cid); const runId = C.analysis && C.analysis.id; running.add(cid);
      p.then(a => log('info', 'analysis_done', { case: cid, status: a.status }), e => log('error', 'analysis_failed', { case: cid, message: e.message })).finally(() => { running.delete(cid); host.flush(); });
      return { status: 202, body: { run_id: runId, status: 'running' } }; });
  });
  R('GET', '/api/cases/:id/analysis', ctx => run(ctx, N => { const C = N.CaseSvc.get(ctx.user.id, ctx.params.id); const A = C.analysis; return { analysis: clone(A), case_status: C.status, agent_runs: A ? clone(C.agentRuns.filter(r => r.analysisId === A.id)) : [], tool_calls: clone(C.toolCalls.slice(-60)) }; }));
  R('GET', '/api/cases/:id/agent-runs', ctx => run(ctx, N => ({ agent_runs: clone(N.CaseSvc.get(ctx.user.id, ctx.params.id).agentRuns) })));

  /* claims / evidence / conflicts / authorities / citations */
  R('GET', '/api/cases/:id/claims', ctx => run(ctx, N => { const C = N.CaseSvc.get(ctx.user.id, ctx.params.id); return { claims: C.claims.map(c => ({ ...clone(c), status: N.claimStatus(C, c) })) }; }));
  const claimOf = (N, ctx, cid, id) => { const C = N.CaseSvc.get(ctx.user.id, cid); const c = N.ClaimSvc.get(ctx.user.id, cid, id); return { C, c }; };
  R('GET', '/api/cases/:id/claims/:claimId', ctx => run(ctx, N => { const { C, c } = claimOf(N, ctx, ctx.params.id, ctx.params.claimId); return { claim: { ...clone(c), status: N.claimStatus(C, c) }, evidence: clone(N.ClaimSvc.evidenceFor(ctx.user.id, C.id, c.id)), conflicts: clone(N.ClaimSvc.conflictsFor(ctx.user.id, C.id, c.id)), authorities: clone(C.authorityLinks.filter(l => l.claimId === c.id)), citations: clone(C.citations.filter(x => x.claimId === c.id)) }; }));
  R('GET', '/api/claims/:claimId', ctx => { const cid = ctx.query.case_id; if (!cid) throw new ApiError(422, 'VALIDATION_ERROR', 'case_id is required.'); return run(ctx, N => { const { C, c } = claimOf(N, ctx, cid, ctx.params.claimId); return { claim: { ...clone(c), status: N.claimStatus(C, c) } }; }); });
  R('GET', '/api/cases/:id/evidence', ctx => run(ctx, N => { const C = N.CaseSvc.get(ctx.user.id, ctx.params.id); return { evidence: clone(C.evidence), relationships: clone(C.relationships) }; }));
  R('GET', '/api/evidence/:eid', ctx => { const cid = ctx.query.case_id; if (!cid) throw new ApiError(422, 'VALIDATION_ERROR', 'case_id is required.'); return run(ctx, N => { const C = N.CaseSvc.get(ctx.user.id, cid); const e = C.evidence.find(x => x.id === ctx.params.eid); if (!e) throw Object.assign(new N.ServiceError('EVIDENCE_NOT_FOUND', 'No evidence was found for the supplied evidence_id.')); return { evidence: clone(e), relationships: clone(C.relationships.filter(r => r.evidenceId === e.id)) }; }); });
  R('GET', '/api/cases/:id/conflicts', ctx => run(ctx, N => ({ conflicts: clone(N.CaseSvc.get(ctx.user.id, ctx.params.id).conflicts) })));
  R('GET', '/api/cases/:id/authorities', ctx => run(ctx, N => { const C = N.CaseSvc.get(ctx.user.id, ctx.params.id); N.useLibrary(ctx.user.id); return { links: clone(C.authorityLinks), authorities: clone(N.AuthSvc.list(ctx.user.id)) }; }));
  R('GET', '/api/cases/:id/citations', ctx => run(ctx, N => ({ citations: clone(N.CaseSvc.get(ctx.user.id, ctx.params.id).citations) })));
  R('GET', '/api/cases/:id/findings', ctx => run(ctx, N => { const C = N.CaseSvc.get(ctx.user.id, ctx.params.id); return { findings: C.findings.map(f => ({ ...clone(f), status: N.findingStatus(C, f) })) }; }));

  /* the user's authority library (the app ships with none) */
  R('GET', '/api/authorities', ctx => run(ctx, N => ({ authorities: clone(N.AuthSvc.list(ctx.user.id)) })));
  R('POST', '/api/authorities', ctx => run(ctx, N => ({ status: 201, body: { authority: clone(N.AuthSvc.add(ctx.user.id, ctx.body || {})) } })));
  R('DELETE', '/api/authorities/:aid', ctx => run(ctx, N => { N.AuthSvc.remove(ctx.user.id, ctx.params.aid); return { ok: true }; }));
  R('GET', '/api/authorities/search', ctx => run(ctx, N => { N.useLibrary(ctx.user.id); return { results: N.searchAuthorities(String(ctx.query.q || ''), Math.min(20, Number(ctx.query.limit) || 5)) }; }));

  /* human review: never overwrites the AI finding, always writes review + audit rows */
  const doReview = (ctx, cid, fid, body) => run(ctx, N => { const b = body || {}; const rv = N.ReviewSvc.save(ctx.user.id, cid, fid, { action: b.action, comment: b.comment, modifiedText: b.modifiedText }); return { review: clone(rv), snapshot: views.snapshot(ctx.user, N.CaseSvc.get(ctx.user.id, cid)) }; });
  R('POST', '/api/cases/:id/findings/:fid/review', ctx => ({ status: 201, body: doReview(ctx, ctx.params.id, ctx.params.fid, ctx.body) }));
  R('POST', '/api/cases/:id/findings/:fid/open', ctx => run(ctx, N => { N.ReviewSvc.open(ctx.user.id, ctx.params.id, ctx.params.fid); return { ok: true }; }));
  R('POST', '/api/claims/:claimId/review', ctx => { const cid = (ctx.body || {}).case_id; if (!cid) throw new ApiError(422, 'VALIDATION_ERROR', 'case_id is required.'); const f = run(ctx, N => { const C = N.CaseSvc.get(ctx.user.id, cid); const fin = N.claimFinding(C, ctx.params.claimId); if (!fin) throw new N.ServiceError('CLAIM_NOT_FOUND', 'No claim was found for the supplied claim_id.'); return fin.id; }); return { status: 201, body: doReview(ctx, cid, f, ctx.body) }; });
  R('GET', '/api/cases/:id/reviews', ctx => run(ctx, N => ({ reviews: clone(N.CaseSvc.get(ctx.user.id, ctx.params.id).reviews) })));
  R('GET', '/api/cases/:id/audit', ctx => run(ctx, N => ({ events: clone(N.AuditSvc.list(ctx.user.id, ctx.params.id)) })));

  /* reports */
  R('GET', '/api/cases/:id/report', ctx => run(ctx, N => ({ report: N.buildReport(N.CaseSvc.get(ctx.user.id, ctx.params.id), ctx.user) })));
  R('POST', '/api/cases/:id/report', ctx => run(ctx, N => {
    const { rec, report } = N.ReportSvc.generate(ctx.user.id, ctx.params.id); const dir = safeJoin(cfg.uploadsDir, ctx.params.id, 'reports'); fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, rec.id + '.pdf'), Buffer.from(N.reportToPDF(report))); fs.writeFileSync(path.join(dir, rec.id + '.json'), JSON.stringify(report, null, 2)); rec.filePath = `${ctx.params.id}/reports/${rec.id}.pdf`;
    return { status: 201, body: { report_id: rec.id, report, pdf_url: `/api/cases/${ctx.params.id}/reports/${rec.id}/pdf`, snapshot: views.snapshot(ctx.user, N.CaseSvc.get(ctx.user.id, ctx.params.id)) } };
  }));
  R('GET', '/api/cases/:id/reports/:rid/pdf', { raw: true }, ctx => { const C = own(ctx, ctx.params.id); if (!ID_RE.test(ctx.params.rid)) throw new ApiError(404, 'REPORT_NOT_FOUND', 'Report not found.'); const rec = C.reports.find(r => r.id === ctx.params.rid); if (!rec) throw new ApiError(404, 'REPORT_NOT_FOUND', 'Report not found.'); let abs = safeJoin(cfg.uploadsDir, C.id, 'reports', rec.id + '.pdf'); if (!fs.existsSync(abs)) abs = safeJoin(cfg.uploadsDir, C.userId, C.id, 'reports', rec.id + '.pdf'); if (!fs.existsSync(abs)) throw new ApiError(404, 'REPORT_NOT_FOUND', 'The report file is missing.'); return { raw: fs.readFileSync(abs), type: 'application/pdf', name: `${C.id}-${rec.id}.pdf` }; });

  /* search, MCP tool layer over HTTP, AI settings */
  R('GET', '/api/search', ctx => run(ctx, N => { N.useLibrary(ctx.user.id); return { results: N.searchAll(ctx.user.id, String(ctx.query.q || '')) }; }));
  R('GET', '/api/mcp/tools', ctx => ({ server: 'nyayasahayak', tools: N.MCP_TOOL_NAMES.map(n => ({ name: n, purpose: N.MCP.tools[n].purpose, input: N.MCP.tools[n].input })) }));
  R('POST', '/api/mcp/call', ctx => run(ctx, N => { const b = ctx.body || {}; return N.mcpCall(String(b.tool || ''), b.args || {}, { userId: ctx.user.id }); }));
  R('GET', '/api/ai/status', ctx => { const s = host.userSettings(ctx.user.id); return { provider: cfg.geminiKey && s.consent ? 'gemini+rules' : 'local-rules', keyConfiguredOnServer: !!cfg.geminiKey, model: s.model || cfg.geminiModel, consent: !!s.consent, mask: s.mask !== false, note: 'The API key lives only in the server environment and is never sent to the browser.' }; });
  R('PUT', '/api/ai/settings', ctx => { const b = ctx.body || {}; if (b.model != null && !/^[A-Za-z0-9._\-]{3,60}$/.test(String(b.model))) throw new ApiError(422, 'VALIDATION_ERROR', 'Enter a valid model name.'); host.setUserSettings(ctx.user.id, { consent: !!b.consent, mask: b.mask !== false, model: b.model ? String(b.model) : undefined }); return { ok: true }; });
  R('POST', '/api/ai/test', async ctx => { if (!cfg.geminiKey) throw new ApiError(400, 'AI_NOT_CONFIGURED', 'No Gemini API key is configured on the server.'); const ok = await host.as(ctx.user.id, N => N.geminiGenerate('Return the JSON object {"ok": true}.', { type: 'OBJECT', properties: { ok: { type: 'BOOLEAN' } }, required: ['ok'] }, { cfg: N.aiConfig(), timeoutMs: 20000 })); return { ok: !!(ok && ok.ok) }; });

  /* ---------- HTTP plumbing ---------- */
  const csp = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'";
  function baseHeaders(req, res) {
    res.setHeader('X-Content-Type-Options', 'nosniff'); res.setHeader('X-Frame-Options', 'DENY'); res.setHeader('Referrer-Policy', 'no-referrer'); res.setHeader('Cache-Control', 'no-store');
    const o = req.headers.origin; if (o && cfg.corsOrigins.includes(o)) { res.setHeader('Access-Control-Allow-Origin', o); res.setHeader('Vary', 'Origin'); res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type'); res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS'); }
  }
  const send = (res, status, body) => { const s = JSON.stringify(body); res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(s) }); res.end(s); };
  const readBody = req => new Promise((resolve, reject) => { const max = cfg.maxUploadBytes * 1.4 + 65536; let n = 0, over = false; const chunks = []; req.on('data', c => { n += c.length; if (over) { if (n > max * 4) req.destroy(); return; } if (n > max) { over = true; chunks.length = 0; } else chunks.push(c); }); req.on('end', () => over ? reject(new ApiError(413, 'PAYLOAD_TOO_LARGE', 'The request body is too large.')) : resolve(Buffer.concat(chunks))); req.on('error', reject); });

  const server = http.createServer(async (req, res) => {
    const t0 = Date.now(); const rid = crypto.randomBytes(6).toString('hex'); baseHeaders(req, res); res.setHeader('X-Request-Id', rid);
    const url = new URL(req.url, 'http://x'); const ip = req.socket.remoteAddress || '';
    try {
      if (req.method === 'OPTIONS') { res.writeHead(204); return res.end(); }
      if (!url.pathname.startsWith('/api/')) {
        if ((url.pathname === '/' || url.pathname === '/index.html') && req.method === 'GET') { if (!fs.existsSync(cfg.staticFile)) return send(res, 404, { error: { code: 'NOT_FOUND', message: 'The web app has not been built.' } }); const html = fs.readFileSync(cfg.staticFile); res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Content-Security-Policy': csp, 'Content-Length': html.length }); return res.end(html); }
        if (url.pathname === '/config.js' && req.method === 'GET') { res.writeHead(200, { 'Content-Type': 'application/javascript; charset=utf-8' }); return res.end('// Server mode: no browser-side configuration. The Gemini key stays in the server environment.\n'); }
        return send(res, 404, { error: { code: 'NOT_FOUND', message: 'Not found.' } });
      }
      const route = routes.find(r => r.method === req.method && r.re.test(url.pathname));
      if (!route) { const other = routes.some(r => r.re.test(url.pathname)); throw new ApiError(other ? 405 : 404, other ? 'METHOD_NOT_ALLOWED' : 'NOT_FOUND', other ? 'Method not allowed.' : 'Not found.'); }
      const m = url.pathname.match(route.re); const params = {}; route.keys.forEach((k, i) => { params[k] = decodeURIComponent(m[i + 1]); });
      const ctx = { req, ip, params, query: Object.fromEntries(url.searchParams), body: null, user: null, claims: null };
      if (!route.opts.public) {
        const h = String(req.headers.authorization || ''); if (!h.startsWith('Bearer ')) throw new ApiError(401, 'UNAUTHENTICATED', 'Sign in to continue.');
        let claims; try { claims = verifyJwt(h.slice(7), secret); } catch (e) { throw new ApiError(401, 'UNAUTHENTICATED', 'Your session is invalid or has expired. Sign in again.'); }
        if (claims.scp !== 'access' || host.store.isRevoked(claims.jti)) throw new ApiError(401, 'UNAUTHENTICATED', 'Your session is invalid or has expired. Sign in again.');
        const user = host.DB.users.find(u => u.id === claims.sub); if (!user) throw new ApiError(401, 'UNAUTHENTICATED', 'Your session is invalid or has expired. Sign in again.'); ctx.user = user; ctx.claims = claims;
      }
      if (req.method === 'POST' || req.method === 'PUT') { const raw = await readBody(req); if (raw.length) { if (!/json/i.test(req.headers['content-type'] || '')) throw new ApiError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Send application/json.'); try { ctx.body = JSON.parse(raw.toString('utf8')); } catch (e) { throw new ApiError(400, 'BAD_JSON', 'The request body is not valid JSON.'); } if (ctx.body === null || typeof ctx.body !== 'object' || Array.isArray(ctx.body)) throw new ApiError(400, 'BAD_JSON', 'The request body must be a JSON object.'); } }
      let out = await route.fn(ctx); let status = 200;
      if (out && out.raw) { res.writeHead(200, { 'Content-Type': out.type, 'Content-Length': out.raw.length, 'Content-Disposition': `attachment; filename="${out.name}"` }); res.end(out.raw); log('info', 'req', { rid, m: req.method, p: url.pathname, s: 200, ms: Date.now() - t0 }); return; }
      if (out && out.status && out.body) { status = out.status; out = out.body; }
      send(res, status, out); log('info', 'req', { rid, m: req.method, p: url.pathname.replace(/[A-Z]{2}-\d{4}-\d+/g, ':case'), s: status, ms: Date.now() - t0, u: ctx.user ? ctx.user.id : undefined });
    } catch (e) {
      const err = mapError(e); if (!res.headersSent) send(res, err.status, { error: { code: err.code, message: err.message, ...(err.extra || {}) } });
      log(err.status >= 500 ? 'error' : 'warn', 'req_error', { rid, m: req.method, p: url.pathname.replace(/[A-Z]{2}-\d{4}-\d+/g, ':case'), s: err.status, code: err.code });
    }
  });
  server.on('close', () => host.close());
  return { server, host, cfg, otp, market, views, listen: () => new Promise(r => server.listen(cfg.port, cfg.host, () => r(server.address()))), close: () => new Promise(r => { server.close(() => r()); server.closeAllConnections && server.closeAllConnections(); host.close(); }) };
}

if (require.main === module) {
  const app = createServer(); app.listen().then(a => { process.stdout.write(JSON.stringify({ ts: new Date().toISOString(), level: 'info', msg: 'listening', url: `http://${a.address}:${a.port}`, db: app.cfg.dbFile, ai: app.cfg.geminiKey ? 'gemini key configured' : 'no gemini key' }) + '\n'); });
  const stop = () => { app.close().then(() => process.exit(0)); }; process.on('SIGINT', stop); process.on('SIGTERM', stop);
}
module.exports = { createServer, ApiError };
