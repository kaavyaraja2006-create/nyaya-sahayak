'use strict';
/* Hosts the analysis engine (dist/engine.js — the same services, agents and tool layer the browser build uses) inside the server process.
   The engine keeps one in-memory DB object; this host loads it from SQLite at start and writes changes back after every commit. */
const path = require('path');
const { Store } = require('./db');

const SESSION_KEY = 'nyayasahayak.session.v1', DB_KEY = 'nyayasahayak.db.v1', AI_KEY = 'nyayasahayak.ai.v1';
const mem = {}; let onCommit = () => {};
globalThis.localStorage = { getItem: k => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); if (k === DB_KEY) onCommit(); }, removeItem: k => { delete mem[k]; } };
globalThis.NS_CONFIG = globalThis.NS_CONFIG || {};
require(path.join(__dirname, '..', '..', 'dist', 'engine.js'));
const N = globalThis.NS;

class Host {
  constructor(cfg, log) {
    this.cfg = cfg; this.log = log; this.N = N; this.store = new Store(cfg.dbFile); this.store.claimStatus = N.claimStatus;
    globalThis.NS_CONFIG.GEMINI_API_KEY = cfg.geminiKey; globalThis.NS_CONFIG.GEMINI_MODEL = cfg.geminiModel; globalThis.NS_CONFIG.GEMINI_CONSENT = false;
    this.DB = N.loadDB(); this.store.loadInto(this.DB, N); N.setServerMode(true); this.timer = null; this.recover();
    onCommit = () => this.schedule();
  }
  /* analyses that were running when the process stopped cannot resume: mark them honestly */
  recover() {
    this.DB.cases.forEach(C => { if (C.status === 'ANALYZING' || (C.analysis && C.analysis.status === 'running')) {
      if (C.analysis) { C.analysis.status = 'failed'; C.analysis.completedAt = new Date().toISOString(); (C.analysis.stages || []).forEach(s => { if (s.status === 'running' || s.status === 'pending') s.status = 'failed'; }); }
      C.status = C.claims.length ? 'ACTIVE_REVIEW' : 'DRAFT'; C.audit.push({ id: 'AE-R' + (C.audit.length + 1), ts: new Date().toISOString(), actorType: 'SYSTEM', actorId: null, actorName: 'System', event: 'ANALYSIS_INTERRUPTED', description: 'Analysis was interrupted by a server restart. Uploaded material and earlier results are preserved.', object: C.analysis ? C.analysis.id : null, prev: null, next: null, meta: null });
    } });
    this.flush();
  }
  schedule() { if (this.timer) return; this.timer = setTimeout(() => { this.timer = null; try { this.flush(); } catch (e) { this.log('error', 'persist_failed', { message: e.message }); } }, 40); }
  flush() { if (this.closed) return; if (this.timer) { clearTimeout(this.timer); this.timer = null; } this.store.persist(this.DB); }
  userSettings(uid) { return this.store.settings[uid] || { consent: false, mask: true }; }
  setUserSettings(uid, s) { this.store.settings[uid] = { consent: !!s.consent, mask: s.mask !== false, model: s.model || undefined }; const u = this.DB.users.find(x => x.id === uid); if (u) u.updatedAt = new Date().toISOString(); this.flush(); }
  /* run engine code as a specific user (session + AI settings are per request; handlers are synchronous so requests never interleave here) */
  as(uid, fn) {
    if (this.depth > 0 && this.cur === uid) return fn(N);
    const s = this.userSettings(uid); this.depth = (this.depth || 0) + 1; this.cur = uid; mem[SESSION_KEY] = JSON.stringify({ token: 'srv', userId: uid, exp: Date.now() + 60000 }); mem[AI_KEY] = JSON.stringify({ consent: !!s.consent, mask: s.mask !== false, model: s.model || undefined });
    try { return fn(N); } finally { this.depth--; if (!this.depth) this.cur = null; delete mem[SESSION_KEY]; delete mem[AI_KEY]; }
  }
  close() { if (this.closed) return; try { this.flush(); } catch (e) {} this.closed = true; this.store.close(); }
}
module.exports = { Host, N };
