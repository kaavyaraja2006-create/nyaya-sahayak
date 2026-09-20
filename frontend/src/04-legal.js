/* ===== 04 legal: user-supplied authority library + retrieval + citation audit =====
   The app ships NO built-in authorities. Every authority is added by the signed-in user (pasted or uploaded from a source they trust).
   Nothing here is legal advice, and retrieval is a lexical ranking signal, not a statement of legal correctness. */
const AUTH_LABEL = 'From your authority library — verify against the original source';
const AUTH_KINDS = ['Judgment', 'Statute', 'Rule / Regulation', 'Article / Commentary', 'Other'];
const AUTHORITIES = [], AUTH_BY_ID = {}, AUTH_BY_CODE = {}, PASSAGES = [], IDF = {};
let LIB_SIG = null;
const normCode = s => String(s || '').toLowerCase().replace(/\s+/g, ' ').trim();
const libRows = uid => (loadDB().authorities || []).filter(a => a.userId === uid);
function splitAuthorityText(text) {
  const raw = textToParas(String(text || '').replace(/\f/g, '\n\n')); const paras = [], nums = [];
  raw.forEach(p => {
    let num = null; const m = p.match(/^\s*(\d{1,4})[.)]\s+(?=\S)/); if (m) { num = +m[1]; p = p.slice(m[0].length); }
    if (p.length <= 900) { paras.push(p); nums.push(num); return; }
    let cur = ''; sentences(p).forEach(sn => { if (cur && (cur.length + sn.text.length) > 700) { paras.push(cur.trim()); nums.push(num); cur = ''; } cur += ' ' + sn.text; }); if (cur.trim()) { paras.push(cur.trim()); nums.push(num); }
  });
  return { paras, nums };
}
function rebuildLibrary(rows) {
  AUTHORITIES.length = 0; PASSAGES.length = 0; Object.keys(AUTH_BY_ID).forEach(k => delete AUTH_BY_ID[k]); Object.keys(AUTH_BY_CODE).forEach(k => delete AUTH_BY_CODE[k]); Object.keys(IDF).forEach(k => delete IDF[k]);
  rows.forEach(a => { AUTHORITIES.push(a); AUTH_BY_ID[a.id] = a; if (a.citation) AUTH_BY_CODE[normCode(a.citation)] = a; });
  AUTHORITIES.forEach(a => a.paras.forEach((p, i) => PASSAGES.push({ authorityId: a.id, idx: i + 1, num: (a.paraNums || [])[i] || null, text: p, toks: tokens(p + ' ' + (i === 0 ? (a.topics || '') + ' ' + a.title : '')) })));
  const df = {}; PASSAGES.forEach(p => new Set(p.toks).forEach(t => df[t] = (df[t] || 0) + 1)); const N = PASSAGES.length; Object.keys(df).forEach(t => IDF[t] = Math.log(1 + N / df[t]));
  PASSAGES.forEach(p => p.vec = vec(p.toks));
}
function useLibrary(uid) { const rows = libRows(uid); const sig = uid + ':' + rows.map(a => a.id + a.addedAt).join('|'); if (sig !== LIB_SIG) { rebuildLibrary(rows); LIB_SIG = sig; } return rows; }
const AuthSvc = {
  list(uid) { return libRows(uid); },
  add(uid, o) {
    const errors = {}; const title = String(o.title || '').trim(), text = String(o.text || '').trim(); const year = o.year ? Number(o.year) : null;
    if (title.length < 2) errors.title = 'Enter the authority title.'; if (text.length < 40) errors.text = 'Paste or upload the authority text (at least a short passage).'; if (text.length > 400000) errors.text = 'The text is larger than 400 KB. Add the relevant part.';
    if (year != null && (!Number.isInteger(year) || year < 1000 || year > 2100)) errors.year = 'Enter a valid year.'; if (o.kind && !AUTH_KINDS.includes(o.kind)) errors.kind = 'Choose a type.';
    if (Object.keys(errors).length) throw Object.assign(new ServiceError('VALIDATION', 'Please correct the highlighted fields.'), { errors });
    const sp = splitAuthorityText(text); if (!sp.paras.length) throw Object.assign(new ServiceError('VALIDATION', 'No text could be read.'), { errors: { text: 'No readable text was found.' } });
    const db = loadDB(); db.authorities = db.authorities || []; const key = 'auth:' + uid; db.counters[key] = (db.counters[key] || 0) + 1;
    const rec = { id: 'AUTH-' + pad(db.counters[key], 3), userId: uid, citation: String(o.citation || '').trim() || title.slice(0, 60), title, court: String(o.court || '').trim(), year, kind: o.kind || 'Other', sourceNote: String(o.sourceNote || '').trim().slice(0, 300), paras: sp.paras, paraNums: sp.nums, topics: String(o.keywords || '').trim().slice(0, 300), addedAt: nowISO() };
    db.authorities.push(rec); commit(); useLibrary(uid); return rec;
  },
  remove(uid, id) { const db = loadDB(); const a = (db.authorities || []).find(x => x.id === id && x.userId === uid); if (!a) throw new ServiceError('AUTHORITY_NOT_FOUND', 'No authority was found for the supplied authority_id.'); db.authorities = db.authorities.filter(x => x !== a); commit(); useLibrary(uid); },
};
function vec(toks) { const v = {}; toks.forEach(t => v[t] = (v[t] || 0) + 1); let n = 0; Object.keys(v).forEach(t => { v[t] *= (IDF[t] || 0.6); n += v[t] * v[t]; }); return { v, n: Math.sqrt(n) || 1 }; }
PASSAGES.forEach(p => p.vec = vec(p.toks));
function cosine(a, b) { let d = 0; Object.keys(a.v).forEach(t => { if (b.v[t]) d += a.v[t] * b.v[t]; }); return d / (a.n * b.n); }
function searchAuthorities(query, limit = 5) {
  const qt = tokens(query); if (!qt.length) return []; const q = vec(qt); const best = {};
  PASSAGES.forEach(p => { const s = cosine(q, p.vec); if (s > 0 && (!best[p.authorityId] || s > best[p.authorityId].score)) best[p.authorityId] = { score: s, p }; });
  return Object.keys(best).map(id => { const a = AUTH_BY_ID[id], b = best[id]; const shared = uniq(qt.filter(t => b.p.toks.includes(t))); return { authorityId: id, citation: a.citation, title: a.title, court: a.court, year: a.year, relevanceScore: Math.round(b.score * 100) / 100, passageIndex: b.p.idx, passage: b.p.text, matchedTerms: shared.slice(0, 8), source: 'authority_library', kind: a.kind, sourceNote: a.sourceNote }; })
    .filter(r => r.relevanceScore >= 0.05).sort((x, y) => y.relevanceScore - x.relevanceScore).slice(0, limit);
}
const AUTH_THRESHOLD = 0.25;

/* ---- citations ---- */
function libCodeRegex() { const codes = AUTHORITIES.map(a => a.citation).filter(c => c && c.length >= 3).sort((a, b) => b.length - a.length).map(c => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+')); if (!codes.length) return null; return new RegExp('(?<![\\w])(' + codes.join('|') + ')(?![\\w])(?:[,\\s]+(?:para(?:graph)?s?\\.?|¶)\\s*(\\d+))?', 'gi'); }
function extractCitations(doc) {
  const out = [];
  doc.pages.forEach(pg => pg.paras.forEach((pa, pi) => {
    const t = pa.text; const taken = [];
    const titled = /\[(\d+)\]\s*([A-Z][^\[\]\n]{2,90}?)[,\s]+(?:para(?:graph)?s?\.?|¶)\s*(\d+)/g; let m;
    while ((m = titled.exec(t))) { taken.push([m.index, m.index + m[0].length]); out.push({ raw: m[0], title: m[2].trim(), paraRef: +m[3], start: m.index, end: m.index + m[0].length, docId: doc.id, page: pg.n, para: pi + 1, kind: 'titled' }); }
    const re = libCodeRegex(); if (re) { re.lastIndex = 0; while ((m = re.exec(t))) { if (taken.some(r => m.index >= r[0] && m.index < r[1])) continue; out.push({ raw: m[0], code: normCode(m[1]), paraRef: m[2] ? +m[2] : null, start: m.index, end: m.index + m[0].length, docId: doc.id, page: pg.n, para: pi + 1, kind: 'code' }); } }
    const stat = /\b((?:Section|Article|Rule)\s+\d+[A-Z]?(?:\s*\(\d+\))?\s+of\s+the\s+[A-Z][A-Za-z ]{2,40}?(?:Act|Code|Rules|Constitution)(?:,?\s*\d{4})?)/g;
    while ((m = stat.exec(t))) out.push({ raw: m[0], statute: m[1], start: m.index, end: m.index + m[0].length, docId: doc.id, page: pg.n, para: pi + 1, kind: 'statute' });
  }));
  return out;
}
function resolveAuthority(c) {
  if (c.code) return AUTH_BY_CODE[c.code] || null;
  if (c.statute) { const ct = tokens(c.statute); let best = null, bs = 0; AUTHORITIES.forEach(a => { const at = tokens(a.title + ' ' + a.citation); const cov = at.filter(x => ct.includes(x)).length / (at.length || 1); if (cov > bs) { bs = cov; best = a; } }); return bs >= 0.8 ? best : null; }
  if (c.title) { const hit = AUTH_BY_CODE[normCode(c.title)]; if (hit) return hit; const ct = tokens(c.title); let best = null, bs = 0; AUTHORITIES.forEach(a => { const at = tokens(a.title); const cov = ct.filter(x => at.includes(x)).length / (ct.length || 1); if (cov > bs) { bs = cov; best = a; } }); return bs >= 0.7 ? best : null; }
  return null;
}
const paraIndex = (a, ref) => { if (!ref) return -1; const byNum = (a.paraNums || []).findIndex(n => n === ref); if (byNum >= 0) return byNum; return a.paras[ref - 1] ? ref - 1 : -1; };
function auditCitations(C) {
  const out = []; let n = 0; const byDoc = {}; C.documents.forEach(d => byDoc[d.id] = d);
  C.documents.forEach(d => extractCitations(d).forEach(c => {
    const para = d.pages[c.page - 1].paras[c.para - 1].text; const sn = sentences(para).find(s => c.start >= s.start && c.start < s.end) || { text: para, start: 0, end: para.length };
    const claim = C.claims.find(k => k.sourceDocId === d.id && k.page === c.page && k.para === c.para && k.start <= c.start && k.end >= c.start) || C.claims.find(k => k.sourceDocId === d.id && k.page === c.page && k.para === c.para) || null;
    const proposition = sn.text.replace(c.raw, ' ').replace(/\s+/g, ' ').trim();
    const rec = { id: 'CIT-' + pad(++n, 3), kind: 'CITATION', claimId: claim ? claim.id : null, citationText: c.raw, docId: d.id, page: c.page, para: c.para, start: c.start, end: c.end, proposition, authorityId: null, paragraphRef: c.paraRef || null, matchedPassage: null, relevanceSignal: 0, result: 'UNRESOLVED', potentialMismatch: true, requiresReview: true, note: '' };
    const a = resolveAuthority(c);
    if (!a) { rec.note = AUTHORITIES.length ? 'The cited authority was not found in your authority library. Add it to the library to compare the citation with its text.' : 'Your authority library is empty. Add the cited authority to compare the citation with its text.'; out.push(rec); return; }
    rec.authorityId = a.id;
    const pIdx = paraIndex(a, c.paraRef); if (c.paraRef && pIdx < 0) { rec.note = `Paragraph ${c.paraRef} was not found in ${a.citation}.`; out.push(rec); return; }
    const passages = c.paraRef ? [{ idx: pIdx + 1, text: a.paras[pIdx], toks: tokens(a.paras[pIdx] + ' ' + (a.topics || '')) }] : PASSAGES.filter(p => p.authorityId === a.id);
    const q = vec(tokens(proposition)); let best = null; passages.forEach(p => { const s = cosine(q, vec(p.toks)); if (!best || s > best.s) best = { s, p }; });
    rec.matchedPassage = { idx: best.p.idx, text: best.p.text }; rec.relevanceSignal = Math.round(best.s * 100) / 100;
    rec.result = best.s >= 0.12 ? 'POTENTIALLY_RELEVANT' : 'WEAK_RELEVANCE'; rec.potentialMismatch = best.s < 0.12; rec.requiresReview = true;
    rec.note = best.s >= 0.12 ? 'The cited passage appears related to the proposition. Reviewer verification required.' : 'The cited passage shows limited lexical overlap with the proposition. Potential mismatch — reviewer verification required.';
    out.push(rec);
  }));
  C.claims.filter(k => k.type === 'LEGAL_PROPOSITION').forEach(k => {
    if (out.some(r => r.claimId === k.id)) return; if (out.some(r => r.docId === k.sourceDocId && r.page === k.page && r.para === k.para)) return;
    out.push({ id: 'CIT-' + pad(++n, 3), kind: 'MISSING', claimId: k.id, citationText: '—', docId: k.sourceDocId, page: k.page, para: k.para, start: k.start, end: k.end, proposition: k.text, authorityId: null, paragraphRef: null, matchedPassage: null, relevanceSignal: 0, result: 'MISSING_CITATION', potentialMismatch: true, requiresReview: true, note: 'A legal proposition was identified with no citation attached.' });
  });
  return out;
}
function researchAuthorities(C) {
  const out = []; let n = 0;
  C.claims.forEach(k => { searchAuthorities(k.text, 2).filter(r => r.relevanceScore >= AUTH_THRESHOLD).forEach(r => out.push({ id: 'AL-' + pad(++n, 3), claimId: k.id, authorityId: r.authorityId, passageIndex: r.passageIndex, passage: r.passage, score: r.relevanceScore, matchedTerms: r.matchedTerms })); });
  return out;
}
