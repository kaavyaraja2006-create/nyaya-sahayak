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
  if (!r.ok) { const er = (j && j.error) || { code: 'HTTP_' + r.status, message: 'The request could not be completed.' }; if (r.status === 401 && Api.token && !/login|signup/.test(path)) { localSignOut(); if (typeof toast === 'function') toast('Your session has expired. Sign in again.', 'warn'); if (typeof go === 'function') go('#/login'); } const e = new ServiceError(er.code, er.message); if (er.errors) e.errors = er.errors; throw e; }
  return j;
};
function localSignOut() { Api.setToken(null); const db = loadDB(); db.users = []; db.cases = []; db.authorities = []; setSession(null); }
function mergeCase(snap) { const db = loadDB(); const i = db.cases.findIndex(c => c.id === snap.id); if (i >= 0) db.cases[i] = snap; else db.cases.push(snap); notify(); return snap; }
function applySync(j) { const db = loadDB(); db.users = [{ ...j.user, passwordHash: '' }]; db.cases = j.cases; db.authorities = j.authorities; setSession({ token: 'srv', userId: j.user.id, exp: Api.exp || (Date.now() + 3600000) }); }
async function refreshAiState() { if (!Api.on || !Api.token) return null; try { const s = await Api.req('GET', '/ai/status'); Api.aiOn = s.provider === 'gemini+rules'; Api.aiKeyOnServer = s.keyConfiguredOnServer; Api.aiStatus = s; return s; } catch (e) { return null; } }
const fileToB64 = f => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => { const s = String(r.result); res(s.slice(s.indexOf(',') + 1)); }; r.onerror = () => rej(new ServiceError('READ_ERROR', 'The file could not be read.')); r.readAsDataURL(f); });

const Data = {
  async signup(f) { if (!Api.on) return signup(f); try { const j = await Api.req('POST', '/auth/signup', f); Api.setToken(j.token, j.expiresInMinutes); applySync({ user: j.user, cases: [], authorities: [] }); await refreshAiState(); return { ok: true, user: j.user }; } catch (e) { return e.errors ? { ok: false, errors: e.errors } : { ok: false, errors: { email: e.message } }; } },
  async login(email, pw) { if (!Api.on) return login(email, pw); try { const j = await Api.req('POST', '/auth/login', { email, password: pw }); Api.setToken(j.token, j.expiresInMinutes); applySync(await Api.req('GET', '/sync')); await refreshAiState(); return { ok: true, user: j.user }; } catch (e) { return { ok: false, error: e.code === 'INVALID_CREDENTIALS' ? 'Invalid email or password.' : e.message }; } },
  async resume() { if (!Api.on || !Api.token) return false; try { applySync(await Api.req('GET', '/sync')); await refreshAiState(); return true; } catch (e) { localSignOut(); return false; } },
  async logout() { if (Api.on) { try { await Api.req('POST', '/auth/logout', {}); } catch (e) {} localSignOut(); } else logout(); },
  async createCase(f) { if (!Api.on) return CaseSvc.create(UI.user.id, f); const j = await Api.req('POST', '/cases', f); mergeCase(j.snapshot); return j.snapshot; },
  async updateCase(id, f) { if (!Api.on) return CaseSvc.update(UI.user.id, id, f); const j = await Api.req('PUT', '/cases/' + id, f); return mergeCase(j.snapshot); },
  async archiveCase(id, on) { if (!Api.on) return CaseSvc.archive(UI.user.id, id, on); const j = await Api.req('POST', `/cases/${id}/archive`, { archived: on }); return mergeCase(j.snapshot); },
  async removeCase(id) { if (!Api.on) return CaseSvc.remove(UI.user.id, id); await Api.req('DELETE', '/cases/' + id); const db = loadDB(); db.cases = db.cases.filter(c => c.id !== id); notify(); },
  /* server mode: the server reads, stores and indexes the original file; the browser only sends bytes */
  async uploadFile(caseId, file, o = {}) { const j = await Api.req('POST', `/cases/${caseId}/${o.kind === 'transcript' ? 'transcripts' : 'documents'}`, { filename: file.name, contentBase64: await fileToB64(file), hearingDate: o.hearingDate || undefined, hearingNumber: o.hearingNumber || undefined }); mergeCase(j.snapshot); return j.document; },
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
};
const aiModel = () => Api.on ? ((Api.aiStatus && Api.aiStatus.model) || '') : aiConfig().model;
