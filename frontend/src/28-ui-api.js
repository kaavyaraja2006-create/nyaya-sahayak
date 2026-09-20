/* ===== 28 ui api: talks to the NyayaSahayak backend when the page is served by it; otherwise the same calls run against the in-browser engine (standalone file mode) ===== */
const Api = { on: false, token: null, exp: 0, aiOn: false, aiKeyOnServer: false };
const TOKEN_KEY = 'ns.token';
try { const t = JSON.parse(sessionStorage.getItem(TOKEN_KEY) || 'null'); if (t && t.exp > Date.now()) { Api.token = t.token; Api.exp = t.exp; } } catch (e) {}
const aiActive = () => Api.on ? Api.aiOn : aiReady();
Api.setToken = (t, mins) => { Api.token = t; Api.exp = Date.now() + (mins || 60) * 60000; try { t ? sessionStorage.setItem(TOKEN_KEY, JSON.stringify({ token: t, exp: Api.exp })) : sessionStorage.removeItem(TOKEN_KEY); } catch (e) {} };
Api.detect = async () => {
  if (typeof location === 'undefined' || location.protocol === 'file:' || typeof fetch !== 'function') return false;
  try { const r = await fetch('/api/health', { cache: 'no-store' }); const j = await r.json(); if (j && j.service === 'nyayasahayak') { Api.on = true; setServerMode(true); Api.aiKeyOnServer = !!(j.ai && j.ai.configured); return true; } } catch (e) {}
  return false;
};
Api.req = async (method, path, body) => {
  let r; try { r = await fetch('/api' + path, { method, headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(Api.token ? { Authorization: 'Bearer ' + Api.token } : {}) }, body: body !== undefined ? JSON.stringify(body) : undefined }); }
  catch (e) { throw new ServiceError('NETWORK', 'The server could not be reached. Check that it is running and try again.'); }
  let j = null; try { j = await r.json(); } catch (e) {}
  if (!r.ok) { const er = (j && j.error) || { code: 'HTTP_' + r.status, message: 'The request could not be completed.' }; if (r.status === 401 && Api.token && !/login|signup|otp/.test(path)) { localSignOut(); if (typeof toast === 'function') toast('Your session has expired. Sign in again.', 'warn'); if (typeof go === 'function') go('#/login'); } const e = new ServiceError(er.code, er.message); if (er.errors) e.errors = er.errors; if (er.retryAfterSeconds) e.retryAfterSeconds = er.retryAfterSeconds; throw e; }
  return j;
};
function localSignOut() { Api.setToken(null); const db = loadDB(); db.users = []; db.cases = []; db.authorities = []; setSession(null); }
function mergeCase(snap) { const db = loadDB(); const i = db.cases.findIndex(c => c.id === snap.id); if (i >= 0) db.cases[i] = snap; else db.cases.push(snap); notify(); return snap; }
function applySync(j) { const db = loadDB(); db.users = [{ ...j.user, passwordHash: '' }]; db.cases = j.cases; db.authorities = j.authorities; setSession({ token: 'srv', userId: j.user.id, exp: Api.exp || (Date.now() + 3600000) }); }
async function refreshAiState() { if (!Api.on || !Api.token) return null; try { const s = await Api.req('GET', '/ai/status'); Api.aiOn = s.provider === 'gemini+rules'; Api.aiKeyOnServer = s.keyConfiguredOnServer; Api.aiStatus = s; return s; } catch (e) { return null; } }
const fileToB64 = f => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => { const s = String(r.result); res(s.slice(s.indexOf(',') + 1)); }; r.onerror = () => rej(new ServiceError('READ_ERROR', 'The file could not be read.')); r.readAsDataURL(f); });

const Data = {
  async signup(f) { if (!Api.on) return signup(f); try { const j = await Api.req('POST', '/auth/signup', f); if (j.requiresOtp) return { ok: true, requiresOtp: true, challengeId: j.challengeId, otpSent: j.otpSent !== false, resendAfterSeconds: j.resendAfterSeconds || 30, user: j.user, message: j.message }; Api.setToken(j.token, j.expiresInMinutes); applySync({ user: j.user, cases: [], authorities: [] }); await refreshAiState(); return { ok: true, user: j.user }; } catch (e) { return e.errors ? { ok: false, errors: e.errors } : { ok: false, errors: { email: e.message } }; } },
  async login(email, pw) { if (!Api.on) return login(email, pw); try { const j = await Api.req('POST', '/auth/login', { email, password: pw }); Api.setToken(j.token, j.expiresInMinutes); applySync(await Api.req('GET', '/sync')); await refreshAiState(); return { ok: true, user: j.user }; } catch (e) { return { ok: false, lawyerOtp: e.code === 'LAWYER_OTP_REQUIRED', error: e.code === 'INVALID_CREDENTIALS' ? 'Invalid email or password.' : e.message }; } },
  async resume() { if (!Api.on || !Api.token) return false; try { applySync(await Api.req('GET', '/sync')); await refreshAiState(); return true; } catch (e) { localSignOut(); return false; } },
  async logout() { if (Api.on) { try { await Api.req('POST', '/auth/logout', {}); } catch (e) {} localSignOut(); } else logout(); },
  async createCase(f) { if (!Api.on) return CaseSvc.create(UI.user.id, f); const j = await Api.req('POST', '/cases', f); mergeCase(j.snapshot); return j.snapshot; },
  async updateCase(id, f) { if (!Api.on) return CaseSvc.update(UI.user.id, id, f); const j = await Api.req('PUT', '/cases/' + id, f); return mergeCase(j.snapshot); },
  async archiveCase(id, on) { if (!Api.on) return CaseSvc.archive(UI.user.id, id, on); const j = await Api.req('POST', `/cases/${id}/archive`, { archived: on }); return mergeCase(j.snapshot); },
  async removeCase(id) { if (!Api.on) return CaseSvc.remove(UI.user.id, id); await Api.req('DELETE', '/cases/' + id); const db = loadDB(); db.cases = db.cases.filter(c => c.id !== id); notify(); },
  /* server mode: the server reads, stores and indexes the original file; the browser only sends bytes */
  async uploadFile(caseId, file, o = {}) { const j = await Api.req('POST', `/cases/${caseId}/${o.kind === 'transcript' ? 'transcripts' : 'documents'}`, { filename: file.name, contentBase64: await fileToB64(file), hearingDate: o.hearingDate || undefined, hearingNumber: o.hearingNumber || undefined, hearingId: o.hearingId || undefined }); mergeCase(j.snapshot); return j.document; },
  async addTranscriptText(caseId, o) { if (!Api.on) return DocSvc.add(UI.user.id, caseId, { kind: 'transcript', filename: 'Pasted transcript.txt', text: o.text, size: o.text.length, hearingDate: o.hearingDate || null, hearingNumber: o.hearingNumber || null }); const j = await Api.req('POST', `/cases/${caseId}/transcripts`, { text: o.text, hearingDate: o.hearingDate || undefined, hearingNumber: o.hearingNumber || undefined }); mergeCase(j.snapshot); return j.snapshot.documents.find(d => d.id === j.document.id); },
  async setCategory(caseId, docId, cat) { if (!Api.on) return DocSvc.setCategory(UI.user.id, caseId, docId, cat); const j = await Api.req('PUT', `/cases/${caseId}/documents/${docId}`, { category: cat }); mergeCase(j.snapshot); },
  async removeDocument(caseId, docId) { if (!Api.on) return DocSvc.remove(UI.user.id, caseId, docId); const j = await Api.req('DELETE', `/cases/${caseId}/documents/${docId}`); mergeCase(j.snapshot); },
  async saveReview(caseId, fid, o) { if (!Api.on) return ReviewSvc.save(UI.user.id, caseId, fid, o); const j = await Api.req('POST', `/cases/${caseId}/findings/${fid}/review`, o); mergeCase(j.snapshot); return j.review; },
  openFinding(caseId, fid) { if (!Api.on) { try { ReviewSvc.open(UI.user.id, caseId, fid); } catch (e) {} return; } Api.req('POST', `/cases/${caseId}/findings/${fid}/open`, {}).then(() => Api.req('GET', `/cases/${caseId}/snapshot`)).then(j => { const db = loadDB(); const i = db.cases.findIndex(c => c.id === caseId); if (i >= 0) db.cases[i] = j.snapshot; }).catch(() => {}); },
  async addAuthority(f) { if (!Api.on) return AuthSvc.add(UI.user.id, f); const j = await Api.req('POST', '/authorities', f); const db = loadDB(); db.authorities.push(j.authority); useLibrary(UI.user.id); notify(); return j.authority; },
  async removeAuthority(id) { if (!Api.on) return AuthSvc.remove(UI.user.id, id); await Api.req('DELETE', '/authorities/' + id); const db = loadDB(); db.authorities = db.authorities.filter(a => a.id !== id); useLibrary(UI.user.id); notify(); },
  async analyze(caseId) {
    if (!Api.on) return runAnalysis(UI.user.id, caseId, {});
    await Api.req('POST', `/cases/${caseId}/analyze`, {});
    for (;;) { await sleep(350); const j = await Api.req('GET', `/cases/${caseId}/snapshot`); mergeCase(j.snapshot); const A = j.snapshot.analysis; if (!A || A.status !== 'running') { useLibrary(UI.user.id); return A; } }
  },
  async generateReport(caseId) {
    if (!Api.on) { const { rec, report } = ReportSvc.generate(UI.user.id, caseId); return { rec, report, pdf: reportToPDF(report) }; }
    const j = await Api.req('POST', `/cases/${caseId}/report`, {}); mergeCase(j.snapshot);
    const r = await fetch(j.pdf_url, { headers: { Authorization: 'Bearer ' + Api.token } }); if (!r.ok) throw new ServiceError('REPORT_FILE', 'The PDF could not be downloaded.');
    return { rec: { id: j.report_id }, report: j.report, pdf: new Uint8Array(await r.arrayBuffer()) };
  },
  async downloadOriginal(caseId, doc) { const r = await fetch(`/api/cases/${caseId}/documents/${doc.id}/file`, { headers: { Authorization: 'Bearer ' + Api.token } }); if (!r.ok) throw new ServiceError('FILE', 'The original file could not be downloaded.'); return new Uint8Array(await r.arrayBuffer()); },
  /* ---- people, hearings and public tracking (server: REST; standalone: the in-browser engine) ---- */
  async directory(kind, q = '') {
    if (Api.on) return (await Api.req('GET', `/directory/${kind}?q=${encodeURIComponent(q)}`)).people;
    const role = { judges: 'JUDGE', lawyers: 'LAWYER', stenographers: 'STENOGRAPHER' }[kind]; const s = q.toLowerCase();
    return loadDB().users.filter(u => u.role === role && (!s || u.fullName.toLowerCase().includes(s))).map(u => ({ id: u.id, name: u.fullName, role: u.role, verified: !!u.verified, enrollmentNumber: u.role === 'LAWYER' ? u.registrationNumber : undefined, city: (u.profile || {}).city || '' }));
  },
  async assign(caseId, o) { if (!Api.on) return CaseSvc.assign(UI.user.id, caseId, o); const j = await Api.req('PUT', `/cases/${caseId}/assignment`, o); return mergeCase(j.snapshot); },
  async leaveCase(caseId) { if (!Api.on) return CaseSvc.leave(UI.user.id, caseId); await Api.req('POST', `/cases/${caseId}/leave`, {}); const db = loadDB(); db.cases = db.cases.filter(c => c.id !== caseId); notify(); },
  async setPublic(caseId, o) { if (!Api.on) return CaseSvc.setPublic(UI.user.id, caseId, o); const j = await Api.req('PUT', `/cases/${caseId}/public`, o); return mergeCase(j.snapshot); },
  async scheduleHearing(caseId, o) { if (!Api.on) return HearingSvc.schedule(UI.user.id, caseId, o); const j = await Api.req('POST', `/cases/${caseId}/hearings`, o); mergeCase(j.snapshot); return j.hearing; },
  async updateHearing(caseId, hid, o) { if (!Api.on) return HearingSvc.update(UI.user.id, caseId, hid, o); const j = await Api.req('PUT', `/cases/${caseId}/hearings/${hid}`, o); mergeCase(j.snapshot); return j.hearing; },
  async setHearingStatus(caseId, hid, status, o = {}) { if (!Api.on) return HearingSvc.setStatus(UI.user.id, caseId, hid, status, o).hearing; const j = await Api.req('POST', `/cases/${caseId}/hearings/${hid}/status`, { status, ...o }); mergeCase(j.snapshot); return j.hearing; },
  async startHearing(caseId, o) { if (!Api.on) return HearingSvc.start(UI.user.id, caseId, o); const j = await Api.req('POST', `/cases/${caseId}/hearings/start`, o); mergeCase(j.snapshot); return j.hearing; },
  async endHearing(caseId, hid, note) { if (!Api.on) return HearingSvc.end(UI.user.id, caseId, hid, { note }); const j = await Api.req('POST', `/cases/${caseId}/hearings/${hid}/end`, { note }); mergeCase(j.snapshot); return j.hearing; },
  /* the stenographer's typing area: saved on the server while typing (browser storage in standalone mode) */
  async getDraft(caseId, hid) { if (!Api.on) { const t = safeLS.get(`ns.draft.${caseId}.${hid}`); return { text: t || '', rev: 0 }; } return Api.req('GET', `/cases/${caseId}/hearings/${hid}/draft`); },
  async saveDraft(caseId, hid, text, baseRev) { if (!Api.on) { safeLS.set(`ns.draft.${caseId}.${hid}`, text); return { rev: (baseRev || 0) + 1, savedAt: new Date().toISOString(), chars: text.length }; } return Api.req('PUT', `/cases/${caseId}/hearings/${hid}/draft`, { text, baseRev }); },
  async generateTranscript(caseId, hid, text) { if (!Api.on) return HearingSvc.generateTranscript(UI.user.id, caseId, hid, text); const j = await Api.req('POST', `/cases/${caseId}/hearings/${hid}/transcript`, { text }); mergeCase(j.snapshot); return j.document; },
  async publicCase(id) { if (!Api.on) throw new ServiceError('NEEDS_SERVER', 'Public case tracking is available when the app is served by the NyayaSahayak server.'); return (await Api.req('GET', '/public/cases/' + encodeURIComponent(id))).case; },
  /* lawyer sign-in by one-time code */
  async lawyerOtpRequest(enrollmentNumber, mobile) { return Api.req('POST', '/auth/lawyer/otp/request', { enrollmentNumber, mobile }); },
  async lawyerOtpVerify(challengeId, otp) { const j = await Api.req('POST', '/auth/lawyer/otp/verify', { challengeId, otp }); Api.setToken(j.token, j.expiresInMinutes); applySync(await Api.req('GET', '/sync')); await refreshAiState(); return j.user; },
  /* find a lawyer, requests and private messages: server only */
  async matchLawyers(q) { if (!Api.on) throw new ServiceError('NEEDS_SERVER', 'Finding a lawyer needs the NyayaSahayak server.'); return Api.req('POST', '/public/lawyers/match', q); },
  async sendRequest(o) { return (await Api.req('POST', '/requests', o)).request; },
  async requests() { return (await Api.req('GET', '/requests')).requests; },
  async request(id) { return (await Api.req('GET', '/requests/' + id)).request; },
  async decideRequest(id, decision, note) { return (await Api.req('POST', `/requests/${id}/decision`, { decision, note })).request; },
  async messages(id, after = 0) { return (await Api.req('GET', `/requests/${id}/messages?after=${after}`)).messages; },
  async postMessage(id, body) { return (await Api.req('POST', `/requests/${id}/messages`, { body })).message; },
  async lawyerProfile() { return Api.req('GET', '/lawyer/profile'); },
  async saveLawyerProfile(o) { const j = await Api.req('PUT', '/lawyer/profile', o); if (j.user) { const db = loadDB(); const i = db.users.findIndex(u => u.id === j.user.id); if (i >= 0) db.users[i] = { ...db.users[i], ...j.user, passwordHash: '' }; notify(); } return j; },
  async adminLawyers() { return (await Api.req('GET', '/admin/lawyers')).lawyers; },
  async verifyLawyer(id, verified) { return Api.req('POST', `/admin/lawyers/${id}/verify`, { verified }); },
};
const aiModel = () => Api.on ? ((Api.aiStatus && Api.aiStatus.model) || '') : aiConfig().model;
