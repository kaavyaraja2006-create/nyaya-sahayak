'use strict';
/* NyayaSahayak API server. Node 22+, no third-party packages.
   Layers: HTTP → routes (this file) → engine services (dist/engine.js, ownership-checked) → SQLite (db.js). */
const http = require('http'), fs = require('fs'), path = require('path'), crypto = require('crypto');
const { load } = require('./config'); const { Host } = require('./engine-host');
const { signJwt, verifyJwt, loadSecret, Throttle, safeJoin, safeName } = require('./security');

class ApiError extends Error { constructor(status, code, message, extra) { super(message); this.status = status; this.code = code; this.extra = extra; } }
const ID_RE = /^[A-Za-z0-9._-]{1,48}$/;
const MIME = { pdf: 'application/pdf', docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', txt: 'text/plain', md: 'text/plain' };

function createServer(over = {}) {
  const cfg = load(over); const LV = { debug: 10, info: 20, warn: 30, error: 40 };
  const log = (level, msg, f = {}) => { if ((LV[level] || 20) >= (LV[cfg.logLevel] || 20)) process.stdout.write(JSON.stringify({ ts: new Date().toISOString(), level, msg, ...f }) + '\n'); };
  const secret = loadSecret(cfg); const host = new Host(cfg, log); const N = host.N; const throttle = new Throttle(cfg.loginMaxFailures, cfg.loginWindowMs);
  fs.mkdirSync(cfg.uploadsDir, { recursive: true });
  const running = new Set();

  /* ---------- helpers ---------- */
  const pub = u => ({ id: u.id, fullName: u.fullName, email: u.email, phone: u.phone, role: u.role, organization: u.organization, registrationNumber: u.registrationNumber, experienceYears: u.experienceYears, specialization: u.specialization, createdAt: u.createdAt });
  const clone = o => JSON.parse(JSON.stringify(o));
  const issue = (u, scp = 'access', minutes = cfg.tokenMinutes) => { const now = Math.floor(Date.now() / 1000); return signJwt({ sub: u.id, iat: now, exp: now + minutes * 60, jti: crypto.randomBytes(12).toString('hex'), scp }, secret); };
  function mapError(e) {
    if (e instanceof ApiError) return e;
    const c = e && e.code;
    if (c === 'CASE_NOT_FOUND' || c === 'PERMISSION_DENIED') return new ApiError(404, 'CASE_NOT_FOUND', 'No case was found for the supplied case_id.');
    if (c === 'VALIDATION' || c === 'VALIDATION_ERROR') return new ApiError(422, 'VALIDATION_ERROR', e.message, e.errors ? { errors: e.errors } : undefined);
    if (c === 'ARCHIVED' || c === 'ALREADY_RUNNING') return new ApiError(409, c, e.message);
    if (c === 'NO_MATERIAL') return new ApiError(422, c, e.message);
    if (c === 'UNAUTHENTICATED') return new ApiError(401, c, e.message);
    if (typeof c === 'string' && /_NOT_FOUND$/.test(c)) return new ApiError(404, c, e.message);
    if (typeof c === 'string' && c.startsWith('AI_')) return new ApiError(502, c, e.message);
    log('error', 'unhandled', { message: e && e.message, stack: String(e && e.stack || '').split('\n').slice(0, 3).join(' | ') });
    return new ApiError(500, 'INTERNAL_ERROR', 'The server could not complete this request.');
  }
  const own = (ctx, cid) => { if (!ID_RE.test(cid)) throw new ApiError(404, 'CASE_NOT_FOUND', 'No case was found for the supplied case_id.'); return host.as(ctx.user.id, N => N.CaseSvc.get(ctx.user.id, cid)); };
  const summary = C => ({ id: C.id, name: C.name, number: C.number, type: C.type, jurisdiction: C.jurisdiction, court: C.court, description: C.description, status: C.status, documents: C.documents.filter(d => d.kind === 'document').length, transcripts: C.documents.filter(d => d.kind === 'transcript').length, claims: C.claims.length, pendingReviews: C.findings.filter(f => N.findingStatus(C, f) === 'PENDING').length, lastAnalyzedAt: C.lastAnalyzedAt, createdAt: C.createdAt, updatedAt: C.updatedAt });
  const run = (ctx, fn) => { try { return host.as(ctx.user.id, fn); } finally { try { host.flush(); } catch (e) { log('error', 'persist_failed', { message: e.message }); } } };
  const fileLike = (buf, name) => ({ name, size: buf.length, arrayBuffer: async () => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), text: async () => buf.toString('utf8') });

  async function ingest(ctx, cid, body, kind) {
    own(ctx, cid); const b = body || {}; let buf, name, ext;
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
      const d = N.DocSvc.add(ctx.user.id, cid, { filename: name, text: parsed.text, mime: parsed.mime, size: buf.length, extractor: parsed.extractor, extractNote: parsed.note || '', kind, category: b.category && kind === 'document' ? String(b.category) : undefined, hearingDate: b.hearingDate ? String(b.hearingDate).slice(0, 10) : null, hearingNumber: b.hearingNumber ? String(b.hearingNumber).slice(0, 20) : null });
      const sub = kind === 'transcript' ? 'transcripts' : 'documents'; const rel = path.join(ctx.user.id, cid, sub, `${d.id}_${safeName(name)}`);
      const abs = safeJoin(cfg.uploadsDir, rel); fs.mkdirSync(path.dirname(abs), { recursive: true }); fs.writeFileSync(abs, buf, { mode: 0o640 });
      const ex = safeJoin(cfg.uploadsDir, ctx.user.id, cid, 'extracted', `${d.id}.txt`); fs.mkdirSync(path.dirname(ex), { recursive: true }); fs.writeFileSync(ex, parsed.text || '');
      d.storagePath = rel.split(path.sep).join('/'); d.sha256 = crypto.createHash('sha256').update(buf).digest('hex'); N.CaseSvc.get(ctx.user.id, cid).updatedAt = new Date().toISOString();
      log('info', 'document_uploaded', { case: cid, doc: d.id, bytes: buf.length }); return { document: clone({ ...d, pages: undefined }), snapshot: clone(N.CaseSvc.get(ctx.user.id, cid)) };
    });
  }

  /* ---------- route table ---------- */
  const routes = []; const R = (method, pattern, opts, fn) => { if (typeof opts === 'function') { fn = opts; opts = {}; } const keys = []; const re = new RegExp('^' + pattern.replace(/:([a-zA-Z_]+)/g, (_, k) => { keys.push(k); return '([^/]+)'; }) + '/?$'); routes.push({ method, re, keys, opts, fn }); };

  R('GET', '/api/health', { public: true }, () => ({ status: 'ok', service: 'nyayasahayak', version: '1.0.0', storage: 'sqlite', ai: { provider: cfg.geminiKey ? 'gemini+rules' : 'local-rules', configured: !!cfg.geminiKey } }));

  /* auth */
  R('POST', '/api/auth/signup', { public: true }, async ctx => {
    const r = await N.signup(ctx.body || {}); N.setSession(null); if (!r.ok) throw new ApiError(422, 'VALIDATION_ERROR', 'Please correct the highlighted fields.', { errors: r.errors }); host.flush();
    log('info', 'signup', { user: r.user.id }); return { status: 201, body: { token: issue(r.user), expiresInMinutes: cfg.tokenMinutes, user: pub(r.user) } };
  });
  R('POST', '/api/auth/login', { public: true }, async ctx => {
    const email = String((ctx.body || {}).email || '').trim().toLowerCase(); const key = ctx.ip + '|' + email;
    if (throttle.blocked(key)) throw new ApiError(429, 'TOO_MANY_ATTEMPTS', 'Too many failed sign-in attempts. Try again later.');
    const r = await N.login(email, String((ctx.body || {}).password || '')); N.setSession(null);
    if (!r.ok) { throttle.fail(key); log('warn', 'login_failed', { ip: ctx.ip }); throw new ApiError(401, 'INVALID_CREDENTIALS', 'Invalid email or password.'); }
    throttle.clear(key); return { token: issue(r.user), expiresInMinutes: cfg.tokenMinutes, user: pub(r.user) };
  });
  R('POST', '/api/auth/logout', ctx => { host.store.revoke(ctx.claims.jti, ctx.claims.exp); return { ok: true }; });
  R('GET', '/api/auth/me', ctx => ({ user: pub(ctx.user) }));
  R('POST', '/api/auth/mcp-token', ctx => ({ token: issue(ctx.user, 'mcp', 24 * 60), note: 'Set as NS_MCP_TOKEN for backend/mcp-server.js. Valid for 24 hours; scoped to the MCP server only.' }));

  /* whole-account snapshot used by the web client */
  R('GET', '/api/sync', ctx => run(ctx, N => ({ user: pub(ctx.user), cases: N.CaseSvc.list(ctx.user.id).map(clone), authorities: clone(N.AuthSvc.list(ctx.user.id)) })));

  /* cases */
  R('GET', '/api/cases', ctx => run(ctx, N => ({ cases: N.CaseSvc.list(ctx.user.id).map(summary) })));
  R('POST', '/api/cases', ctx => run(ctx, N => { const C = N.CaseSvc.create(ctx.user.id, ctx.body || {}); return { status: 201, body: { case: summary(C), snapshot: clone(C) } }; }));
  R('GET', '/api/cases/:id', ctx => { own(ctx, ctx.params.id); return run(ctx, N => ({ case: summary(N.CaseSvc.get(ctx.user.id, ctx.params.id)) })); });
  R('GET', '/api/cases/:id/snapshot', ctx => run(ctx, N => ({ snapshot: clone(N.CaseSvc.get(ctx.user.id, ctx.params.id)) })));
  R('PUT', '/api/cases/:id', ctx => run(ctx, N => { own(ctx, ctx.params.id); const C = N.CaseSvc.update(ctx.user.id, ctx.params.id, ctx.body || {}); return { case: summary(C), snapshot: clone(C) }; }));
  R('POST', '/api/cases/:id/archive', ctx => run(ctx, N => { const C = N.CaseSvc.archive(ctx.user.id, ctx.params.id, (ctx.body || {}).archived !== false); return { case: summary(C), snapshot: clone(C) }; }));
  R('DELETE', '/api/cases/:id', ctx => run(ctx, N => { own(ctx, ctx.params.id); N.CaseSvc.remove(ctx.user.id, ctx.params.id); try { fs.rmSync(safeJoin(cfg.uploadsDir, ctx.user.id, ctx.params.id), { recursive: true, force: true }); } catch (e) {} return { ok: true }; }));

  /* documents and transcripts */
  R('GET', '/api/cases/:id/documents', ctx => run(ctx, N => ({ documents: N.CaseSvc.get(ctx.user.id, ctx.params.id).documents.filter(d => d.kind === 'document').map(d => clone({ ...d, pages: undefined })) })));
  R('POST', '/api/cases/:id/documents', async ctx => ({ status: 201, body: await ingest(ctx, ctx.params.id, ctx.body, 'document') }));
  R('GET', '/api/cases/:id/transcripts', ctx => run(ctx, N => ({ transcripts: N.CaseSvc.get(ctx.user.id, ctx.params.id).documents.filter(d => d.kind === 'transcript').map(d => clone({ ...d, pages: undefined })) })));
  R('POST', '/api/cases/:id/transcripts', async ctx => ({ status: 201, body: await ingest(ctx, ctx.params.id, ctx.body, 'transcript') }));
  R('PUT', '/api/cases/:id/documents/:docId', ctx => run(ctx, N => { N.DocSvc.setCategory(ctx.user.id, ctx.params.id, ctx.params.docId, String((ctx.body || {}).category || '')); return { snapshot: clone(N.CaseSvc.get(ctx.user.id, ctx.params.id)) }; }));
  R('DELETE', '/api/cases/:id/documents/:docId', ctx => run(ctx, N => { N.DocSvc.remove(ctx.user.id, ctx.params.id, ctx.params.docId); return { snapshot: clone(N.CaseSvc.get(ctx.user.id, ctx.params.id)) }; }));
  R('GET', '/api/cases/:id/documents/:docId/file', { raw: true }, ctx => {
    const C = own(ctx, ctx.params.id); const d = C.documents.find(x => x.id === ctx.params.docId); if (!d || !d.storagePath) throw new ApiError(404, 'DOC_NOT_FOUND', 'Document not found.');
    const abs = safeJoin(cfg.uploadsDir, d.storagePath); if (!abs.startsWith(safeJoin(cfg.uploadsDir, ctx.user.id) + path.sep)) throw new ApiError(404, 'DOC_NOT_FOUND', 'Document not found.'); if (!fs.existsSync(abs)) throw new ApiError(404, 'DOC_NOT_FOUND', 'The stored file is missing.');
    const ext = (d.filename.split('.').pop() || '').toLowerCase(); return { raw: fs.readFileSync(abs), type: MIME[ext] || 'application/octet-stream', name: safeName(d.filename) };
  });

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
  const doReview = (ctx, cid, fid, body) => run(ctx, N => { const b = body || {}; const rv = N.ReviewSvc.save(ctx.user.id, cid, fid, { action: b.action, comment: b.comment, modifiedText: b.modifiedText }); return { review: clone(rv), snapshot: clone(N.CaseSvc.get(ctx.user.id, cid)) }; });
  R('POST', '/api/cases/:id/findings/:fid/review', ctx => ({ status: 201, body: doReview(ctx, ctx.params.id, ctx.params.fid, ctx.body) }));
  R('POST', '/api/cases/:id/findings/:fid/open', ctx => run(ctx, N => { N.ReviewSvc.open(ctx.user.id, ctx.params.id, ctx.params.fid); return { ok: true }; }));
  R('POST', '/api/claims/:claimId/review', ctx => { const cid = (ctx.body || {}).case_id; if (!cid) throw new ApiError(422, 'VALIDATION_ERROR', 'case_id is required.'); const f = run(ctx, N => { const C = N.CaseSvc.get(ctx.user.id, cid); const fin = N.claimFinding(C, ctx.params.claimId); if (!fin) throw new N.ServiceError('CLAIM_NOT_FOUND', 'No claim was found for the supplied claim_id.'); return fin.id; }); return { status: 201, body: doReview(ctx, cid, f, ctx.body) }; });
  R('GET', '/api/cases/:id/reviews', ctx => run(ctx, N => ({ reviews: clone(N.CaseSvc.get(ctx.user.id, ctx.params.id).reviews) })));
  R('GET', '/api/cases/:id/audit', ctx => run(ctx, N => ({ events: clone(N.AuditSvc.list(ctx.user.id, ctx.params.id)) })));

  /* reports */
  R('GET', '/api/cases/:id/report', ctx => run(ctx, N => ({ report: N.buildReport(N.CaseSvc.get(ctx.user.id, ctx.params.id), ctx.user) })));
  R('POST', '/api/cases/:id/report', ctx => run(ctx, N => {
    const { rec, report } = N.ReportSvc.generate(ctx.user.id, ctx.params.id); const dir = safeJoin(cfg.uploadsDir, ctx.user.id, ctx.params.id, 'reports'); fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, rec.id + '.pdf'), Buffer.from(N.reportToPDF(report))); fs.writeFileSync(path.join(dir, rec.id + '.json'), JSON.stringify(report, null, 2)); rec.filePath = `${ctx.user.id}/${ctx.params.id}/reports/${rec.id}.pdf`;
    return { status: 201, body: { report_id: rec.id, report, pdf_url: `/api/cases/${ctx.params.id}/reports/${rec.id}/pdf`, snapshot: clone(N.CaseSvc.get(ctx.user.id, ctx.params.id)) } };
  }));
  R('GET', '/api/cases/:id/reports/:rid/pdf', { raw: true }, ctx => { const C = own(ctx, ctx.params.id); if (!ID_RE.test(ctx.params.rid)) throw new ApiError(404, 'REPORT_NOT_FOUND', 'Report not found.'); const rec = C.reports.find(r => r.id === ctx.params.rid); if (!rec) throw new ApiError(404, 'REPORT_NOT_FOUND', 'Report not found.'); const abs = safeJoin(cfg.uploadsDir, ctx.user.id, C.id, 'reports', rec.id + '.pdf'); if (!fs.existsSync(abs)) throw new ApiError(404, 'REPORT_NOT_FOUND', 'The report file is missing.'); return { raw: fs.readFileSync(abs), type: 'application/pdf', name: `${C.id}-${rec.id}.pdf` }; });

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
  return { server, host, cfg, listen: () => new Promise(r => server.listen(cfg.port, cfg.host, () => r(server.address()))), close: () => new Promise(r => { server.close(() => r()); server.closeAllConnections && server.closeAllConnections(); host.close(); }) };
}

if (require.main === module) {
  const app = createServer(); app.listen().then(a => { process.stdout.write(JSON.stringify({ ts: new Date().toISOString(), level: 'info', msg: 'listening', url: `http://${a.address}:${a.port}`, db: app.cfg.dbFile, ai: app.cfg.geminiKey ? 'gemini key configured' : 'no gemini key' }) + '\n'); });
  const stop = () => { app.close().then(() => process.exit(0)); }; process.on('SIGINT', stop); process.on('SIGTERM', stop);
}
module.exports = { createServer, ApiError };
