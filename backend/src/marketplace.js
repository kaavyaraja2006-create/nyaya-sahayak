'use strict';
/* Find a lawyer: verified lawyer directory, transparent matching, requests, and private user↔lawyer messaging.
   Everything shown about a lawyer comes from that lawyer's own profile or from court-recorded hearings on this platform.
   Nothing here invents qualifications, cases, success rates or experience. */
const crypto = require('crypto');
const { ApiError } = require('./errors');
const { Throttle } = require('./security');

const RELATED = { Civil: ['Property', 'Contract', 'Family', 'Commercial'], Property: ['Civil', 'Contract'], Contract: ['Commercial', 'Civil', 'Corporate'], Commercial: ['Contract', 'Corporate', 'Civil'], Corporate: ['Commercial', 'Contract', 'Employment'], Employment: ['Corporate', 'Civil'], Family: ['Civil'], Criminal: [], Other: [] };
const str = (v, max) => String(v == null ? '' : v).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').trim().slice(0, max);
const int = (v, lo, hi) => { if (v === '' || v == null) return null; const n = Math.round(Number(v)); return Number.isFinite(n) && n >= lo && n <= hi ? n : NaN; };
const low = s => String(s || '').toLowerCase().replace(/\s+/g, ' ').trim();
const inr = n => '₹' + Number(n).toLocaleString('en-IN');

function makeMarketplace(host, cfg, views, log) {
  const N = host.N, store = host.store, U = id => host.DB.users.find(u => u.id === id) || null;
  const msgLimit = new Throttle(cfg.messagesPerMinute, 60000);
  const touch = u => { u.updatedAt = new Date().toISOString(); host.flush(); };

  /* ---------- lawyer profile (own) ---------- */
  function cleanProfile(b, u) {
    const errors = {}; const p = {};
    const areas = Array.isArray(b.practiceAreas) ? b.practiceAreas : String(b.practiceAreas || '').split(',');
    p.practiceAreas = [...new Set(areas.map(a => str(a, 30)).filter(Boolean))]; if (p.practiceAreas.some(a => !N.CASE_TYPES.includes(a))) errors.practiceAreas = 'Choose practice areas from the list.'; if (p.practiceAreas.length > 9) errors.practiceAreas = 'Choose up to 9 practice areas.';
    p.city = str(b.city, 80); p.state = str(b.state, 80);
    const courts = Array.isArray(b.courts) ? b.courts : String(b.courts || '').split(/[\n,;]/); p.courts = [...new Set(courts.map(c => str(c, 100)).filter(Boolean))].slice(0, 10);
    const fmin = int(b.feeMin, 0, 100000000), fmax = int(b.feeMax, 0, 100000000); if (Number.isNaN(fmin)) errors.feeMin = 'Enter an amount in rupees.'; if (Number.isNaN(fmax)) errors.feeMax = 'Enter an amount in rupees.';
    p.feeMin = Number.isNaN(fmin) ? null : fmin; p.feeMax = Number.isNaN(fmax) ? null : fmax; if (p.feeMin != null && p.feeMax != null && p.feeMin > p.feeMax) errors.feeMax = 'The maximum fee cannot be below the minimum.';
    p.feeNote = str(b.feeNote, 160); p.listed = !!b.listed;
    const yrs = int(b.experienceYears, 0, 70); if (Number.isNaN(yrs)) errors.experienceYears = 'Enter years between 0 and 70.';
    if (p.listed && !p.practiceAreas.length) errors.practiceAreas = 'Choose at least one practice area to be listed.'; if (p.listed && !p.city) errors.city = 'Enter your city to be listed.';
    if (Object.keys(errors).length) throw new ApiError(422, 'VALIDATION_ERROR', 'Please correct the highlighted fields.', { errors });
    return { profile: p, experienceYears: yrs };
  }
  function saveProfile(user, b) { const { profile, experienceYears } = cleanProfile(b || {}, user); user.profile = profile; if (experienceYears != null || (b || {}).experienceYears === '') user.experienceYears = experienceYears; touch(user); return user.profile; }

  /* ---------- directory ---------- */
  const isListed = u => !!(u && u.role === 'LAWYER' && u.verified && u.profile && u.profile.listed && (u.profile.practiceAreas || []).length && u.profile.city);
  /* Court-recorded appearances: hearings a stenographer recorded (started) that name this lawyer, on cases whose owner made them public. */
  function history(lawyerId) {
    const cases = []; let hearings = 0;
    host.DB.cases.forEach(C => { if (!(C.public && C.public.enabled)) return; const hs = (C.hearings || []).filter(h => ['IN_PROGRESS', 'COMPLETED'].includes(h.status) && h.stenographerId && (h.lawyerIds || []).includes(lawyerId)); if (!hs.length) return; hearings += hs.length; cases.push({ caseId: C.id, title: C.public.title || `Case ${C.id}`, type: C.type, court: C.court || '', status: views.publicStatus(C, false, false), year: +String(C.createdAt).slice(0, 4), hearings: hs.length }); });
    const byType = {}; cases.forEach(c => { byType[c.type] = (byType[c.type] || 0) + 1; }); cases.sort((a, b) => b.year - a.year);
    return { cases: cases.length, hearings, byType, recent: cases.slice(0, 5), basis: 'Counted from hearings recorded by court stenographers on this platform, for cases whose owner made them public.' };
  }
  function publicLawyer(u, full = true) {
    const p = u.profile || {}; const h = history(u.id);
    return { id: u.id, name: u.fullName, enrollmentNumber: u.registrationNumber, verified: true, practiceAreas: p.practiceAreas || [], city: p.city || '', state: p.state || '', courts: p.courts || [], experienceYears: u.experienceYears, fee: { min: p.feeMin == null ? null : p.feeMin, max: p.feeMax == null ? null : p.feeMax, note: p.feeNote || '', currency: 'INR' }, history: full ? h : { cases: h.cases, hearings: h.hearings, byType: h.byType } };
  }

  /* ---------- matching ---------- */
  function cleanQuery(b) {
    const errors = {}; const q = { description: str(b.description, 3000), caseType: str(b.caseType, 30), city: str(b.city, 80), court: str(b.court, 120) };
    if (q.description.length < 15) errors.description = 'Describe your case in at least a couple of sentences.'; if (!N.CASE_TYPES.includes(q.caseType)) errors.caseType = 'Choose a case type.'; if (!q.city) errors.city = 'Enter your city.';
    const bud = int(b.budget, 0, 1000000000); if (Number.isNaN(bud)) errors.budget = 'Enter your budget in rupees.'; q.budget = Number.isNaN(bud) ? null : bud;
    if (Object.keys(errors).length) throw new ApiError(422, 'VALIDATION_ERROR', 'Please correct the highlighted fields.', { errors });
    return q;
  }
  /* Rule score. Only criteria the person filled in (plus experience and record) can earn or lose points, so leaving an optional field blank never counts against a lawyer. */
  function scoreLawyer(u, q, hist) {
    const p = u.profile || {}; const parts = []; const add = (key, label, pts, max, detail) => parts.push({ key, label, points: Math.round(pts * 10) / 10, max, detail });
    const areas = p.practiceAreas || []; const exact = areas.includes(q.caseType), rel = !exact && areas.some(a => (RELATED[q.caseType] || []).includes(a));
    if (!exact && !rel) return null;   /* practice area is a hard requirement */
    add('area', 'Case type / practice area', exact ? 30 : 12, 30, exact ? `Practises ${q.caseType} law` : `Practises related areas (${areas.filter(a => (RELATED[q.caseType] || []).includes(a)).join(', ')})`);
    if (q.court) { const cs = (p.courts || []).map(low), qc = low(q.court); const hit = cs.find(c => c.includes(qc) || qc.includes(c)); add('court', 'Court / jurisdiction', hit ? 20 : 0, 20, hit ? `Appears in ${q.court}` : `No stated practice in ${q.court}`); }
    { const same = low(p.city) === low(q.city) || (low(p.city) && low(q.city) && (low(p.city).includes(low(q.city)) || low(q.city).includes(low(p.city)))); add('city', 'Location', same ? 15 : 0, 15, same ? `Based in ${p.city}` : `Based in ${p.city}, not ${q.city}`); }
    { const y = u.experienceYears; add('experience', 'Experience', y == null ? 0 : Math.min(y, 15) / 15 * 10, 10, y == null ? 'Experience not stated' : `${y} year${y === 1 ? '' : 's'} of practice (stated by the lawyer)`); }
    { const n = (hist.byType[q.caseType] || 0); add('record', 'Relevant court-recorded cases', Math.min(n, 3) / 3 * 15, 15, n ? `${n} public ${q.caseType} case${n === 1 ? '' : 's'} recorded on this platform` : `No court-recorded ${q.caseType} cases on this platform yet`); }
    if (q.budget != null) { const lo = p.feeMin, hi = p.feeMax; let pts = 0, d;
      if (lo == null && hi == null) d = 'Fees not stated'; else if (lo != null && lo > q.budget) d = `Stated minimum ${inr(lo)} is above your budget of ${inr(q.budget)}`; else if (hi != null && hi <= q.budget) { pts = 10; d = `Stated fees (up to ${inr(hi)}) fit within ${inr(q.budget)}`; } else { pts = 6; d = `Stated fees start at ${inr(lo == null ? 0 : lo)}, within ${inr(q.budget)}; the upper end may exceed it`; }
      add('budget', 'Budget', pts, 10, d); }
    const max = parts.reduce((s, x) => s + x.max, 0), pts = parts.reduce((s, x) => s + x.points, 0);
    return { score: Math.round(100 * pts / max), parts };
  }
  async function aiRefine(q, ranked, consent) {
    const off = reason => ({ used: false, reason });
    if (!consent) return off('not requested'); if (!cfg.geminiKey) return off('AI is not configured on this server'); if (!ranked.length) return off('no candidates');
    const cands = ranked.map(r => ({ id: r.lawyer.id, practiceAreas: r.lawyer.practiceAreas, city: r.lawyer.city, courts: r.lawyer.courts, experienceYears: r.lawyer.experienceYears, courtRecordedCasesOfThisType: (r.lawyer.history.byType[q.caseType] || 0) }));
    const prompt = `You help a member of the public compare lawyers. Use ONLY the facts supplied below. Never invent or assume any qualification, experience, case, fee or success rate, and never rank by likelihood of winning.\nCASE (personal details removed): type=${q.caseType}; city=${q.city}; court=${q.court || 'not given'}.\nDescription: """${N.maskPII(q.description)}"""\nLAWYERS (JSON): ${JSON.stringify(cands)}\nFor every lawyer id return relevance (0-100: how well their stated practice areas, courts and recorded cases fit the description) and note (one plain sentence, max 180 characters, using only the supplied facts).`;
    const schema = { type: 'OBJECT', properties: { matches: { type: 'ARRAY', items: { type: 'OBJECT', properties: { id: { type: 'STRING' }, relevance: { type: 'NUMBER' }, note: { type: 'STRING' } }, required: ['id', 'relevance', 'note'] } } }, required: ['matches'] };
    try {
      const out = await N.geminiGenerate(prompt, schema, { cfg: { key: cfg.geminiKey, model: cfg.geminiModel }, timeoutMs: 20000 }); const ok = new Set(cands.map(c => c.id)); const map = new Map();
      ((out && out.matches) || []).forEach(m => { if (m && ok.has(m.id) && Number.isFinite(Number(m.relevance))) map.set(m.id, { relevance: Math.max(0, Math.min(100, Math.round(Number(m.relevance)))), note: str(String(m.note || '').replace(/\s+/g, ' '), 200) }); });
      if (!map.size) return off('the AI service returned nothing usable'); return { used: true, model: cfg.geminiModel, map };
    } catch (e) { log('warn', 'match_ai_failed', { code: e && e.code }); return off('the AI service was unavailable'); }
  }
  async function match(body) {
    const q = cleanQuery(body || {}); const ranked = [];
    host.DB.users.forEach(u => { if (!isListed(u)) return; const hist = history(u.id); const s = scoreLawyer(u, q, hist); if (s) ranked.push({ lawyer: publicLawyer(u, false), rule: s, sortYears: u.experienceYears || 0 }); });
    const ai = await aiRefine(q, ranked, !!(body || {}).aiConsent);
    const out = ranked.map(r => { const a = ai.used ? ai.map.get(r.lawyer.id) : null; const score = a ? Math.round(0.75 * r.rule.score + 0.25 * a.relevance) : r.rule.score;
      return { lawyer: r.lawyer, score, ruleScore: r.rule.score, breakdown: r.rule.parts, aiNote: a ? a.note : null, relevantCases: r.lawyer.history.byType[q.caseType] || 0, sortYears: r.sortYears }; })
      .sort((a, b) => b.score - a.score || b.sortYears - a.sortYears || a.lawyer.name.localeCompare(b.lawyer.name)).slice(0, 12).map(({ sortYears, ...x }) => x);
    return { query: { caseType: q.caseType, city: q.city, court: q.court, budget: q.budget }, results: out, ai: { used: ai.used, model: ai.used ? ai.model : null, reason: ai.used ? null : ai.reason },
      method: 'Score = share of available points across: case type / practice area (30), court (20, if given), location (15), experience (10), court-recorded cases of this type (15), budget (10, if given). Blank optional fields are not counted against anyone. Only verified, listed lawyers are considered.', total: out.length };
  }

  /* ---------- requests ---------- */
  const reqRow = id => store.q('SELECT * FROM lawyer_requests WHERE id=?').get(String(id || ''));
  const forbid = () => new ApiError(403, 'FORBIDDEN', 'You do not have access to this request.');
  function present(row, me) {
    const client = U(row.client_id), lawyer = U(row.lawyer_id), accepted = row.status === 'ACCEPTED', iAmLawyer = me.id === row.lawyer_id;
    const unread = accepted ? store.q('SELECT COUNT(*) n FROM messages WHERE request_id=? AND sender_id<>? AND id > COALESCE((SELECT last_id FROM message_reads WHERE request_id=? AND user_id=?),0)').get(row.id, me.id, row.id, me.id).n : 0;
    const r = { id: row.id, status: row.status, caseType: row.case_type, city: row.city, court: row.court, budget: row.budget_max, description: row.description, matchScore: row.match_score, matchReasons: JSON.parse(row.match_reasons || '[]'), aiUsed: !!row.ai_used, createdAt: row.created_at, decidedAt: row.decided_at, decisionNote: row.decision_note || '', unread, viewer: iAmLawyer ? 'LAWYER' : 'CLIENT',
      lawyer: lawyer ? { id: lawyer.id, name: lawyer.fullName, enrollmentNumber: lawyer.registrationNumber, city: (lawyer.profile || {}).city || '', practiceAreas: (lawyer.profile || {}).practiceAreas || [] } : null, client: client ? { id: client.id, name: client.fullName } : null };
    if (accepted) { if (lawyer) r.lawyer.contact = { email: lawyer.email, phone: lawyer.phone }; if (client) r.client.contact = { email: client.email, phone: client.phone }; }
    return r;
  }
  function createRequest(client, b) {
    if (client.role !== 'CLIENT') throw new ApiError(403, 'FORBIDDEN_ROLE', 'Only client accounts can send requests to lawyers. Create a client account to continue.');
    const q = cleanQuery(b || {}); const lawyer = U(String((b || {}).lawyerId || '')); if (!isListed(lawyer)) throw new ApiError(404, 'LAWYER_NOT_FOUND', 'That lawyer is not available.');
    if (store.q("SELECT 1 x FROM lawyer_requests WHERE client_id=? AND lawyer_id=? AND status='PENDING'").get(client.id, lawyer.id)) throw new ApiError(409, 'ALREADY_REQUESTED', 'You already have a pending request with this lawyer.');
    if (store.q("SELECT COUNT(*) n FROM lawyer_requests WHERE client_id=? AND status='PENDING'").get(client.id).n >= 5) throw new ApiError(429, 'TOO_MANY_PENDING', 'You have 5 requests waiting for an answer. Wait for a reply before sending more.');
    const s = scoreLawyer(lawyer, q, history(lawyer.id)); const id = 'REQ-' + crypto.randomBytes(5).toString('hex').toUpperCase();
    store.q('INSERT INTO lawyer_requests(id,client_id,lawyer_id,status,case_type,city,court,budget_min,budget_max,description,match_score,match_reasons,ai_used,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)').run(id, client.id, lawyer.id, 'PENDING', q.caseType, q.city, q.court, null, q.budget, q.description, s ? s.score : null, JSON.stringify(s ? s.parts : []), 0, new Date().toISOString());
    return present(reqRow(id), client);
  }
  function listRequests(user) {
    if (!['CLIENT', 'LAWYER'].includes(user.role)) return [];
    const rows = store.q(user.role === 'LAWYER' ? 'SELECT * FROM lawyer_requests WHERE lawyer_id=? ORDER BY created_at DESC' : 'SELECT * FROM lawyer_requests WHERE client_id=? ORDER BY created_at DESC').all(user.id);
    return rows.map(r => present(r, user));
  }
  function mine(user, id) { const row = reqRow(id); if (!row || (row.client_id !== user.id && row.lawyer_id !== user.id)) throw forbid(); return row; }
  const getRequest = (user, id) => present(mine(user, id), user);
  function decide(user, id, b) {
    const row = mine(user, id); if (row.lawyer_id !== user.id) throw forbid();
    const d = String((b || {}).decision || '').toUpperCase(); if (!['ACCEPTED', 'REJECTED'].includes(d)) throw new ApiError(422, 'VALIDATION_ERROR', 'Decision must be ACCEPTED or REJECTED.');
    const r = store.q("UPDATE lawyer_requests SET status=?, decision_note=?, decided_at=? WHERE id=? AND status='PENDING'").run(d, str((b || {}).note, 500), new Date().toISOString(), row.id);
    if (r.changes !== 1) throw new ApiError(409, 'ALREADY_DECIDED', 'This request has already been answered.');
    return present(reqRow(id), user);
  }
  /* ---------- private conversation (accepted requests only; the two participants only) ---------- */
  function openThread(user, id) { const row = mine(user, id); if (row.status !== 'ACCEPTED') throw new ApiError(409, 'NOT_ACCEPTED', 'Messaging opens once the lawyer accepts the request.'); return row; }
  function messages(user, id, after) {
    const row = openThread(user, id); const a = Math.max(0, parseInt(after, 10) || 0);
    const list = store.q('SELECT id,sender_id,body,created_at FROM messages WHERE request_id=? AND id>? ORDER BY id LIMIT 200').all(row.id, a).map(m => ({ id: m.id, mine: m.sender_id === user.id, body: m.body, createdAt: m.created_at }));
    const top = list.length ? list[list.length - 1].id : null; if (top) store.q('INSERT INTO message_reads(request_id,user_id,last_id) VALUES(?,?,?) ON CONFLICT(request_id,user_id) DO UPDATE SET last_id=MAX(last_id,excluded.last_id)').run(row.id, user.id, top);
    return list;
  }
  function postMessage(user, id, b) {
    const row = openThread(user, id); const body = str((b || {}).body, 4000);
    if (!body) throw new ApiError(422, 'VALIDATION_ERROR', 'Write a message first.', { errors: { body: 'Write a message first.' } });
    if (msgLimit.blocked(user.id)) throw new ApiError(429, 'TOO_MANY_MESSAGES', 'You are sending messages too quickly. Wait a moment.'); msgLimit.fail(user.id);
    const t = new Date().toISOString(); const r = store.q('INSERT INTO messages(request_id,sender_id,body,created_at) VALUES(?,?,?,?)').run(row.id, user.id, body, t);
    return { id: Number(r.lastInsertRowid), mine: true, body, createdAt: t };
  }
  return { saveProfile, isListed, publicLawyer, history, match, createRequest, listRequests, getRequest, decide, messages, postMessage, scoreLawyer, cleanQuery };
}
module.exports = { makeMarketplace };
