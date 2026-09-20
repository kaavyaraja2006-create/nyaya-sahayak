/* ===== 03 engine: deterministic, rule-based extraction & comparison (the "mock provider"; no LLM) ===== */
const CATEGORIES = ['FIR / Complaint', 'Charge Sheet', 'Witness Statement', 'Affidavit', 'Investigation Report', 'Medical Report', 'Forensic Report', 'CCTV Report', 'Phone / Digital Record', 'Court Filing', 'Written Submission', 'Evidence Report', 'Other'];
const CAT_FILTER = { Statements: ['Witness Statement', 'Affidavit', 'FIR / Complaint'], Reports: ['Investigation Report', 'Medical Report', 'Forensic Report', 'CCTV Report', 'Evidence Report', 'Charge Sheet'], Evidence: ['Phone / Digital Record', 'CCTV Report', 'Forensic Report', 'Medical Report'], Submissions: ['Court Filing', 'Written Submission'], Other: ['Other'] };
const STOP = new Set('a an the of and or to in on at for by with from as is are was were be been being this that these those it its he she they them his her their we you i not no but if then than so such which who whom whose what when where while about into over after before between during under again further once here there all any both each few more most other some own same too very can will just should now also has have had do does did would could may might shall per via upon within without against among across'.split(' '));
const stem = w => w.length > 6 ? w.replace(/(ations|ation|ated|ates|ing|ion|ed|es|s)$/, '') : (w.length > 3 ? w.replace(/s$/, '') : w);
const tokens = s => (String(s).toLowerCase().match(/[a-z0-9]+/g) || []).filter(w => w.length > 2 && !STOP.has(w)).map(stem);
const jaccard = (a, b) => { const A = new Set(a), B = new Set(b); if (!A.size || !B.size) return 0; let i = 0; A.forEach(x => B.has(x) && i++); return i / (A.size + B.size - i); };

/* ---- segmentation ---- */
function textToParas(text) {
  let parts = String(text).replace(/\r/g, '').split(/\n\s*\n/).map(s => s.replace(/\s*\n\s*/g, ' ').trim()).filter(Boolean);
  if (parts.length <= 1 && String(text).includes('\n')) parts = String(text).split('\n').map(s => s.trim()).filter(Boolean);
  return parts;
}
function splitPages(text) {
  const t = String(text).replace(/\r/g, '');
  let chunks;
  if (t.includes('\f')) chunks = t.split('\f');
  else if (/^\s*(?:-{2,}\s*)?page\s+\d+(?:\s+of\s+\d+)?\s*(?:-{2,})?\s*$/im.test(t)) chunks = t.split(/^\s*(?:-{2,}\s*)?page\s+\d+(?:\s+of\s+\d+)?\s*(?:-{2,})?\s*$/im);
  else {
    const paras = textToParas(t); chunks = []; let cur = [], len = 0;
    paras.forEach(p => { if (len + p.length > 2400 && cur.length) { chunks.push(cur.join('\n\n')); cur = []; len = 0; } cur.push(p); len += p.length; });
    if (cur.length) chunks.push(cur.join('\n\n'));
  }
  const pages = chunks.map(c => textToParas(c)).filter(p => p.length).map((ps, i) => ({ n: i + 1, paras: ps.map(text => ({ text })) }));
  return pages.length ? pages : [{ n: 1, paras: [{ text: '' }] }];
}
const MASK_RE = /\b(a\.m|p\.m|Dr|Mr|Mrs|Ms|No|vs|St|Sec|Art|Ex|Fig|Cr|Hon|Smt|Shri|v)\./gi;
function sentences(text) {
  const masked = text.replace(MASK_RE, m => m.slice(0, -1) + '\u0001'); const out = []; const re = /[^.!?\n]+(?:[.!?]+["')\]]*|$)/g; let m;
  while ((m = re.exec(masked))) { const raw = text.slice(m.index, m.index + m[0].length); const lead = raw.length - raw.trimStart().length; const t = raw.trim(); if (t) out.push({ text: t, start: m.index + lead, end: m.index + lead + t.length }); }
  return out;
}

/* ---- time / date / location / anchors ---- */
function toMin(h, m, mer) { h = +h; m = +m || 0; if (mer) { mer = mer.toLowerCase(); if (mer === 'p' && h < 12) h += 12; if (mer === 'a' && h === 12) h = 0; } return h * 60 + m; }
function parseTimes(s) {
  const out = []; const re = /\b(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*([ap])\.?\s?m\b\.?|\b([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?\b/gi; let m;
  while ((m = re.exec(s))) {
    if (m[3]) { if (+m[1] > 12 || +m[1] < 1) continue; out.push({ h: +m[1], m: +(m[2] || 0), mer: m[3].toLowerCase(), text: m[0].trim(), idx: m.index }); }
    else out.push({ h: +m[4], m: +m[5], mer: null, text: m[0].trim(), idx: m.index });
  }
  return out;
}
function eventTime(sentence) {
  const ts = parseTimes(sentence); if (!ts.length) return null;
  if (ts.length >= 2 && /\b(between|from)\b/i.test(sentence) && ts[1].idx - ts[0].idx < 40) {
    if (!ts[0].mer && ts[1].mer) ts[0].mer = ts[1].mer;
    let a = toMin(ts[0].h, ts[0].m, ts[0].mer), b = toMin(ts[1].h, ts[1].m, ts[1].mer); if (a > b) [a, b] = [b, a];
    return { a, b, text: `${minToClock(a)} – ${minToClock(b)}`, range: true };
  }
  const t = ts[0]; const v = toMin(t.h, t.m, t.mer); return { a: v, b: v, text: minToClock(v), range: false };
}
const DATE_RE = /\b(\d{1,2}[\/.-]\d{1,2}[\/.-]\d{2,4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4})\b/g;
const LOC_STOP = new Set(['I', 'The', 'He', 'She', 'It', 'They', 'We', 'You', 'This', 'That', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December', 'Court', 'Hon', 'Honourable', 'Section', 'Act', 'Article', 'Page', 'PM', 'AM', 'Exhibit', 'Statement', 'Paragraph', 'Para', 'Report']);
function locations(s) {
  const found = new Map(); const add = raw => {
    let lab = raw.replace(/^the\s+/i, '').replace(/[.,;:]+$/, '').trim(); if (!lab) return; const first = lab.split(/\s+/)[0]; if (LOC_STOP.has(first) || /^(?:PW|DW|CW)-?\d/.test(lab)) return;
    const key = lab.toLowerCase(); if (!found.has(key)) found.set(key, { key, label: lab.charAt(0).toUpperCase() + lab.slice(1) });
  };
  const prep = /\b(?:[Nn]ear|[Aa]t|[Ii]n|[Ii]nside|[Oo]utside|[Aa]round|[Tt]owards|[Ff]rom|[Bb]eside|[Oo]pposite)\s+(?:the\s+)?((?:Location|Site|Zone|Sector|Gate|Block|Area|Point|Junction|Platform)\s+[A-Z0-9][\w-]*|[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){0,3}|(?:warehouse|station|shop|market|junction|bus stand|house|office|hospital|building|residence|premises|parking lot|gate|crossing|factory|godown|farm|plot)\b(?:\s+[A-Z][\w-]*)?)/g;
  let m; while ((m = prep.exec(s))) add(m[1]);
  const bare = /\b(?:Location|Site|Zone|Sector|Gate|Block|Area|Point)\s+[A-Z0-9]\b/g; while ((m = bare.exec(s))) add(m[0]);
  return Array.from(found.values());
}
const NAME_STOP = new Set(['Location', 'Site', 'Zone', 'Sector', 'Witness', 'Statement', 'Report', 'Record', 'Metadata', 'Court', 'Page', 'Section', 'Act', 'Article', 'Phone', 'Device', 'Incident', 'Investigation', 'Evidence', 'Exhibit', 'Forensic', 'Medical', 'Camera', 'Footage', 'Hearing', 'Transcript', 'Cross', 'Examination', 'Chief', 'Prosecution', 'Defence', 'Reference', 'Authority', 'Public', 'Police', 'Station', 'District', 'State', 'India', 'Chennai', 'Government']);
const ANCHOR_ROLES = 'Person|Suspect|Witness|Accused|Complainant|Officer|Party|Vehicle|Driver|Respondent|Petitioner|Plaintiff|Defendant|Appellant|Claimant|Tenant|Landlord|Buyer|Seller|Vendor|Company|Employee|Employer';
function anchorsOf(s) {
  const set = new Set();
  (s.match(new RegExp('\\b(?:' + ANCHOR_ROLES + ')\\s+[A-Z0-9]\\b', 'g')) || []).forEach(x => set.add(x.toLowerCase()));
  (s.match(/\b(?:PW|DW|CW)-?\d+\b/g) || []).forEach(x => set.add(x.toLowerCase().replace('-', '')));
  (s.match(/\b(?:Mr|Ms|Mrs|Dr|Shri|Smt|Sri)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?/g) || []).forEach(x => set.add(x.toLowerCase().replace(/\./g, '')));
  const nm = /(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b/g; let m;
  while ((m = nm.exec(s))) if (!NAME_STOP.has(m[1]) && !NAME_STOP.has(m[2]) && !LOC_STOP.has(m[1])) set.add((m[1] + ' ' + m[2]).toLowerCase());
  (s.match(/\b(accused|suspect|respondent|petitioner|plaintiff|defendant|appellant|claimant|complainant)\b/gi) || []).forEach(x => set.add(x.toLowerCase()));
  if (/\b(?:the|a)\s+(?:person|individual|man|woman|driver|male|female)\b/i.test(s)) set.add('subject');
  return Array.from(set);
}
const UNCERT = /\b(approximately|about|around|roughly|cannot remember|can't remember|cannot recall|can't recall|do not recall|don't recall|do not remember|not sure|unsure|i think|i believe|perhaps|maybe|possibly|might|may have|could have|not certain|no exact)\b/i;
const EVENT_VERBS = ['arrived', 'left', 'entered', 'exited', 'departed', 'reached', 'returned', 'observed', 'saw', 'seen', 'called', 'paid', 'signed', 'delivered', 'received', 'sent', 'met', 'visible', 'reported'];
const ASSERT = /\b(was|were|is|are|had|has|saw|seen|observed|noticed|stated|states|said|reported|recorded|records|indicates?|indicated|shows?|showed|found|arrived|left|entered|exited|visible|located|places?|placed|identified|alleges?|alleged|claims?|claimed|contends?|submit(?:s|ted)?|held|provides?|according|registered|captured|departed|reached|returned|signed|paid|delivered|received)\b/i;
const LEGAL = /\b(section|article|rule|act\b|statute|precedent|held that|court has|principle|doctrine|liable|admissib|burden of proof|corroborat|propos|cited|authority|paragraph\s+\d+|para\.?\s+\d+|DEMO-\d+)/i;
const SPEECH = /\b(I|we|my|me)\b/;

function guessCategory(name, text) {
  const s = (name + ' ' + String(text).slice(0, 600)).toLowerCase();
  if (/cctv|footage|surveillance/.test(s)) return 'CCTV Report';
  if (/phone|handset|metadata|call detail|cell tower|device/.test(s)) return 'Phone / Digital Record';
  if (/forensic|lab report|dna|fingerprint/.test(s)) return 'Forensic Report';
  if (/medical|hospital|injury|post.?mortem/.test(s)) return 'Medical Report';
  if (/witness|statement of|deposition/.test(s)) return 'Witness Statement';
  if (/affidavit/.test(s)) return 'Affidavit';
  if (/charge.?sheet|chargesheet/.test(s)) return 'Charge Sheet';
  if (/\bfir\b|first information|complaint/.test(s)) return 'FIR / Complaint';
  if (/investigation|incident report/.test(s)) return 'Investigation Report';
  if (/written submission|submissions/.test(s)) return 'Written Submission';
  return 'Other';
}
const EVIDENCE_TYPE = { 'FIR / Complaint': 'DOCUMENT', 'Charge Sheet': 'DOCUMENT', 'Witness Statement': 'WITNESS_STATEMENT', 'Affidavit': 'DOCUMENT', 'Investigation Report': 'DOCUMENT', 'Medical Report': 'MEDICAL_RECORD', 'Forensic Report': 'FORENSIC_REPORT', 'CCTV Report': 'CCTV', 'Phone / Digital Record': 'PHONE_METADATA', 'Court Filing': 'DOCUMENT', 'Written Submission': 'DOCUMENT', 'Evidence Report': 'DOCUMENT', 'Other': 'OTHER' };
const EVIDENCE_LABEL = { DOCUMENT: 'Document', WITNESS_STATEMENT: 'Witness statement', DIGITAL_RECORD: 'Digital record', CCTV: 'CCTV', MEDICAL_RECORD: 'Medical record', FORENSIC_REPORT: 'Forensic report', PHOTOGRAPH: 'Photograph', OBJECT_EXHIBIT: 'Object / exhibit', HEARING_STATEMENT: 'Hearing statement', PHONE_METADATA: 'Phone metadata', OTHER: 'Other' };
const PRIMARY_CATS = new Set(['CCTV Report', 'Phone / Digital Record', 'Forensic Report', 'Medical Report']);

/* ---- transcript parsing ---- */
function parseTranscript(text) {
  const lines = String(text).replace(/\r/g, '').split('\n'); const st = []; let pendingTs = null;
  const lineRe = /^\s*[\[(]?(\d{1,2}:\d{2}(?::\d{2})?)[\])]?\s*[-–—]?\s*([A-Za-z][\w .'’()-]{0,32}?)\s*:\s*(.+)$/;
  const noTs = /^\s*([A-Za-z][\w .'’()-]{0,32}?)\s*:\s*(.+)$/; const tsOnly = /^\s*[\[(]?(\d{1,2}:\d{2}(?::\d{2})?)[\])]?\s*$/;
  lines.forEach(line => {
    if (!line.trim()) return; let m;
    if ((m = line.match(tsOnly))) { pendingTs = m[1]; return; }
    if ((m = line.match(lineRe))) { st.push({ ts: m[1], speaker: m[2].trim(), text: m[3].trim() }); pendingTs = null; return; }
    if ((m = line.match(noTs)) && m[1].length <= 30 && !/^(note|exhibit|page|case)$/i.test(m[1].trim())) { st.push({ ts: pendingTs, speaker: m[1].trim(), text: m[2].trim() }); pendingTs = null; return; }
    if (st.length) st[st.length - 1].text += ' ' + line.trim(); else st.push({ ts: pendingTs, speaker: 'Unattributed', text: line.trim() });
  });
  st.forEach(s => { s.text = s.text.replace(/^["“]|["”]$/g, ''); s.qkind = /^(q|question)$/i.test(s.speaker) || /\?\s*$/.test(s.text) ? 'QUESTION' : (/^(a|answer)$/i.test(s.speaker) ? 'ANSWER' : 'STATEMENT'); s.role = speakerRole(s.speaker); });
  return st;
}
function speakerRole(n) { const s = String(n).toLowerCase(); if (/judge|court|bench|hon|magistrate/.test(s)) return 'Judge'; if (/counsel|advocate|prosecut|defen[cs]e|lawyer|apc|spp|adv/.test(s)) return 'Counsel'; if (/^(pw|dw|cw)-?\d+|witness|deponent|expert/.test(s)) return 'Witness'; return 'Other'; }
function statementsToPages(st, per = 14) {
  const pages = []; for (let i = 0; i < st.length; i += per) pages.push({ n: pages.length + 1, paras: st.slice(i, i + per).map(s => ({ text: s.text, speaker: s.speaker, ts: s.ts, qkind: s.qkind, role: s.role })) });
  return pages.length ? pages : [{ n: 1, paras: [] }];
}

/* ---- entity + PII detection (rule-based) ---- */
function docText(doc) { return doc.pages.map(p => p.paras.map(x => x.text).join('\n')).join('\n'); }
function entitiesOf(doc) {
  const t = docText(doc); const ppl = new Set(), locs = new Map(), dates = new Set();
  t.split('\n').forEach(l => { anchorsOf(l).forEach(a => a !== 'subject' && ppl.add(a)); locations(l).forEach(x => locs.set(x.key, x.label)); });
  let m; DATE_RE.lastIndex = 0; while ((m = DATE_RE.exec(t))) dates.add(m[1]);
  return { people: Array.from(ppl).slice(0, 30), locations: Array.from(locs.values()).slice(0, 30), dates: Array.from(dates).slice(0, 20), pii: detectPII(t) };
}
const PII_RE = { email: /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, phone: /(?<![\d/])(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)/g, aadhaarLike: /(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)/g };
function detectPII(t) { const r = {}; Object.keys(PII_RE).forEach(k => { r[k] = (t.match(PII_RE[k]) || []).length; }); return r; }
function redactPII(t) { return String(t).replace(PII_RE.email, '[email redacted]').replace(PII_RE.aadhaarLike, '[id redacted]').replace(PII_RE.phone, '[phone redacted]'); }

/* ---- claim extraction ---- */
function docSpeaker(doc) {
  if (!['Witness Statement', 'Affidavit'].includes(doc.category)) return null;
  const head = doc.pages[0].paras.slice(0, 3).map(p => p.text).join(' ').slice(0, 500);
  const m = head.match(/\b(?:Statement of|Witness|Deponent|Deposition of|Affidavit of)\s*[:\-]?\s*((?:PW|DW|CW)-?\d+|(?:Mr|Ms|Mrs|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?|[A-Z][a-z]+\s+[A-Z][a-z]+)/) || head.match(/\b((?:PW|DW|CW)-?\d+)\b/);
  return m ? m[1] : null;
}
function extractClaims(doc, limit = 30) {
  const out = []; const dSpeaker = docSpeaker(doc); const seen = new Set();
  doc.pages.forEach(pg => pg.paras.forEach((para, pi) => {
    if (doc.kind === 'transcript' && (para.qkind === 'QUESTION' || para.role === 'Judge')) return;
    sentences(para.text).forEach(sn => {
      if (out.length >= limit) return; const s = sn.text; const w = s.split(/\s+/).length; if (w < 5 || w > 70) return;
      if (/^(page|signature|signed|date|place|hereby|note:)\b/i.test(s)) return;
      const time = eventTime(s), locs = locations(s), anc = anchorsOf(s), legal = LEGAL.test(s), assert = ASSERT.test(s);
      if (doc.kind !== 'transcript' && pg.n === 1 && pi === 0 && w <= 16 && !time && !locs.length) return; /* title / heading line */
      const ok = (assert && (time || locs.length || anc.length || legal || (doc.kind === 'transcript' && SPEECH.test(s)))) || (time && locs.length);
      if (!ok) return; const norm = s.toLowerCase().replace(/\W+/g, ' ').trim(); if (seen.has(norm)) return; seen.add(norm);
      const speaker = doc.kind === 'transcript' ? para.speaker : dSpeaker;
      let type = 'EVENT'; const tags = [];
      if (legal) type = 'LEGAL_PROPOSITION';
      else if (/match(?:ing|es)?\s+(?:the\s+)?description|identif/i.test(s)) type = 'IDENTITY';
      else if (locs.length) type = 'LOCATION'; else if (time) type = 'TIMELINE';
      else if (PRIMARY_CATS.has(doc.category) && /record|metadata|footage|report|analysis|registered|captured/i.test(s)) type = 'EVIDENCE_INTERPRETATION';
      else if (/\b(said|stated|states|claims?|alleg|contends?|submit)/i.test(s) || doc.kind === 'transcript') type = 'STATEMENT';
      if (locs.length && time) tags.push('TIMELINE'); if (locs.length && type !== 'LOCATION') tags.push('LOCATION');
      const hedge = UNCERT.test(s); const flags = [];
      if (hedge) flags.push(time || /\btime\b/i.test(s) ? 'TIME_UNCERTAINTY' : 'GENERAL_UNCERTAINTY');
      let conf = 0.5 + (time ? 0.12 : 0) + (locs.length ? 0.12 : 0) + (anc.length ? 0.1 : 0) + (speaker ? 0.06 : 0) + (assert ? 0.05 : 0) - (hedge ? 0.1 : 0);
      out.push({ text: s, type, tags, speaker: speaker || null, sourceDocId: doc.id, sourceType: doc.kind === 'transcript' ? 'TRANSCRIPT' : 'DOCUMENT', page: pg.n, para: pi + 1, start: sn.start, end: sn.end, timestamp: doc.kind === 'transcript' ? (para.ts || null) : null, eventTime: time, locations: locs, anchors: anc, confidence: Math.round(clamp(conf, 0.3, 0.97) * 100) / 100, uncertaintyFlags: flags, hedge });
    });
  }));
  return out;
}

/* ---- evidence extraction (never invents: each item points to a source location) ---- */
function extractEvidence(docs, claims) {
  const ev = [];
  docs.forEach(d => {
    if (d.kind === 'transcript') {
      const speakers = uniq(claims.filter(c => c.sourceDocId === d.id && c.speaker).map(c => c.speaker));
      speakers.forEach(sp => { const c = claims.find(x => x.sourceDocId === d.id && x.speaker === sp); ev.push({ type: 'HEARING_STATEMENT', description: `Hearing statement by ${sp}`, sourceDocId: d.id, page: c.page, para: c.para, timestamp: c.timestamp, key: 'H:' + d.id + sp }); });
      return;
    }
    const first = d.pages[0].paras[0]; const cat = d.category || 'Other';
    ev.push({ type: EVIDENCE_TYPE[cat] || 'OTHER', description: `${cat}: ${trunc((first && first.text) || d.filename, 90)}`, sourceDocId: d.id, page: 1, para: 1, key: 'D:' + d.id, isPrimaryDoc: true });
    d.pages.forEach(pg => pg.paras.forEach((pa, pi) => {
      const re = /\b(?:Exhibit|Ex\.?)\s*([A-Z]{1,2}[-\s]?\d+)\b/g; let m;
      while ((m = re.exec(pa.text))) ev.push({ type: 'OBJECT_EXHIBIT', description: `Exhibit ${m[1]} referenced in ${d.filename}`, sourceDocId: d.id, page: pg.n, para: pi + 1, key: 'X:' + m[1].replace(/\s/g, '') });
      if (/\bphotograph(s)?\b/i.test(pa.text) && !ev.some(e => e.key === 'P:' + d.id)) ev.push({ type: 'PHOTOGRAPH', description: `Photograph referenced in ${d.filename}`, sourceDocId: d.id, page: pg.n, para: pi + 1, key: 'P:' + d.id });
    }));
  });
  const seen = new Set(); return ev.filter(e => !seen.has(e.key) && seen.add(e.key));
}

/* ---- claim ↔ claim comparison ---- */
const TIME_TOL = 30;
function subjectMatch(a, b) {
  const A = a.anchors.filter(x => x !== 'subject'), B = b.anchors.filter(x => x !== 'subject');
  if (A.some(x => B.includes(x))) return 'anchor';
  if (a.anchors.includes('subject') && b.anchors.includes('subject')) return 'generic';
  if (jaccard(tokens(a.text), tokens(b.text)) >= 0.3) return 'lexical'; return null;
}
const overlapMin = (a, b) => { const lo = Math.max(a.a - TIME_TOL, b.a - TIME_TOL), hi = Math.min(a.b + TIME_TOL, b.b + TIME_TOL); return hi - lo; };
function compareClaims(a, b) {
  if (a.id === b.id || (a.sourceDocId === b.sourceDocId && a.page === b.page && a.para === b.para && a.start === b.start)) return null;
  const sm = subjectMatch(a, b); if (!sm) return null;
  const la = a.locations.map(x => x.key), lb = b.locations.map(x => x.key); const sameLoc = la.some(k => lb.includes(k));
  const ta = a.eventTime, tb = b.eventTime; const both = ta && tb; const ov = both ? overlapMin(ta, tb) : null;
  if (la.length && lb.length && both) {
    if (ov >= 0 && sameLoc) return { rel: 'SUPPORTS', reason: `Both describe ${a.locations.find(x => lb.includes(x.key)).label} during an overlapping time interval (${ta.text} / ${tb.text}).`, strength: clamp(60 + (sm === 'anchor' ? 20 : 0) + (ta.range || tb.range ? 0 : 10), 0, 100) };
    if (ov >= 0 && !sameLoc) return { rel: 'CONFLICTS', ctype: 'LOCATION_CONFLICT', reason: `${a.locations.map(x => x.label).join(', ')} vs ${b.locations.map(x => x.label).join(', ')} during an overlapping time interval (${ta.text} / ${tb.text}).`, tight: clamp(Math.round(100 - Math.abs((ta.a + ta.b) / 2 - (tb.a + tb.b) / 2) * 1.2), 20, 100), overlap: ov };
    if (ov < 0 && sameLoc) { const va = EVENT_VERBS.filter(v => new RegExp('\\b' + v + '\\b', 'i').test(a.text)), vb = EVENT_VERBS.filter(v => new RegExp('\\b' + v + '\\b', 'i').test(b.text)); const gap = Math.abs((ta.a + ta.b) / 2 - (tb.a + tb.b) / 2); if (va.some(v => vb.includes(v)) && gap >= 45) return { rel: 'CONFLICTS', ctype: 'TEMPORAL_CONFLICT', reason: `Same location and event described at different times (${ta.text} vs ${tb.text}).`, tight: clamp(Math.round(gap / 2), 20, 100), overlap: -gap }; }
  }
  if (sameLoc && !both) return { rel: 'SUPPORTS', reason: `Both refer to ${a.locations.find(x => lb.includes(x.key)).label}; times are not stated for both.`, strength: 40 };
  if (sameLoc && both && ov < 0) return { rel: 'CONTEXTUALIZES', reason: 'Same location referenced at non-overlapping times.', strength: 25 };
  if (jaccard(tokens(a.text), tokens(b.text)) >= 0.22) return { rel: 'CONTEXTUALIZES', reason: 'Shares subject matter and vocabulary.', strength: 20 };
  return null;
}
const docLabel = d => d ? (d.kind === 'transcript' ? `Hearing transcript${d.hearingNumber ? ' #' + d.hearingNumber : ''}` : d.category !== 'Other' ? d.category : d.filename) : 'Unknown source';

/* ---- full relate/conflict pass over a case (pure: returns new arrays) ---- */
function relateCase(C) {
  const docs = C.documents, claims = C.claims; const byDoc = {}; docs.forEach(d => byDoc[d.id] = d);
  const pairs = [];
  for (let i = 0; i < claims.length; i++) for (let j = i + 1; j < claims.length; j++) { const r = compareClaims(claims[i], claims[j]); if (r) pairs.push({ a: claims[i], b: claims[j], r }); }
  const conflicts = []; let cn = 0; const locSig = c => c.locations.map(x => x.key).sort().join('+');
  const raw = pairs.filter(p => p.r.rel === 'CONFLICTS').sort((x, y) => y.r.tight - x.r.tight);
  const groups = new Map(); const seenT = new Set();
  raw.forEach(p => {
    if (p.r.ctype === 'TEMPORAL_CONFLICT') { const k1 = p.a.id + '|' + p.b.sourceDocId, k2 = p.b.id + '|' + p.a.sourceDocId; if (seenT.has(k1) || seenT.has(k2)) return; seenT.add(k1); seenT.add(k2); groups.set('T|' + p.a.id + '|' + p.b.id, { primary: p, sides: [new Set([p.a.id]), new Set([p.b.id])], sigs: ['t', 't'] }); return; }
    const sa = locSig(p.a), sb = locSig(p.b); const flip = sa > sb; const key = 'L|' + (flip ? sb + '||' + sa : sa + '||' + sb);
    let g = groups.get(key); if (!g) { g = { primary: flip ? { ...p, a: p.b, b: p.a } : p, sides: [new Set(), new Set()], sigs: flip ? [sb, sa] : [sa, sb] }; groups.set(key, g); }
    const [x, y] = flip ? [p.b, p.a] : [p.a, p.b]; g.sides[0].add(x.id); g.sides[1].add(y.id);
  });
  groups.forEach(g => {
    const p = g.primary; const dA = byDoc[p.a.sourceDocId], dB = byDoc[p.b.sourceDocId]; const sameSpeaker = p.a.speaker && p.a.speaker === p.b.speaker;
    const type = sameSpeaker ? 'STATEMENT_CONFLICT' : p.r.ctype; const all = uniq([...g.sides[0], ...g.sides[1]]); const extra = all.filter(id => id !== p.a.id && id !== p.b.id);
    const docsAll = uniq(all.map(id => claims.find(c => c.id === id).sourceDocId));
    const cmp = (dA.kind === 'transcript') !== (dB.kind === 'transcript') ? 'Transcript vs Document' : (dA.kind === 'transcript' ? 'Statement vs Statement' : 'Document vs Document');
    const locs = c => c.locations.map(x => x.label).join(', ') || 'no location stated';
    const desc = (`Potential ${p.r.ctype === 'TEMPORAL_CONFLICT' ? 'temporal' : 'location'} inconsistency. Source A (${docLabel(dA)}, page ${p.a.page}) describes ${locs(p.a)}${p.a.eventTime ? ' at ' + p.a.eventTime.text : ''}. Source B (${docLabel(dB)}, page ${p.b.page}) describes ${locs(p.b)}${p.b.eventTime ? ' at ' + p.b.eventTime.text : ''}. ${p.r.ctype === 'LOCATION_CONFLICT' ? 'The time intervals overlap.' : ''} ${extra.length ? extra.length + ' further claim(s) from the case material describe the same locations.' : ''} Human verification is required.`).replace(/\s+/g, ' ');
    conflicts.push({ id: '', type, claimA: p.a.id, claimB: p.b.id, claims: all, sideA: Array.from(g.sides[0]), sideB: Array.from(g.sides[1]), description: desc, whyFlagged: p.r.reason, severity: 'REVIEW_REQUIRED', supportingSources: docsAll, comparison: cmp, tight: p.r.tight, overlap: p.r.overlap, requiresHumanReview: true });
  });
  conflicts.sort((a, b) => b.tight - a.tight).forEach(k => k.id = 'CONFLICT-' + pad(++cn, 3));
  /* claim links */
  const links = pairs.map((p, i) => ({ id: 'L-' + pad(i + 1, 3), a: p.a.id, b: p.b.id, relationship: p.r.rel, reason: p.r.reason, strength: p.r.strength || p.r.tight || 20 }));
  /* claim-evidence relationships: evidence E (from doc D) relates to claim C via the claims contained in D */
  const rel = []; let rn = 0; const lowText = {}; docs.forEach(d => lowText[d.id] = docText(d).toLowerCase());
  claims.forEach(c => C.evidence.forEach(e => {
    if (e.sourceDocId === c.sourceDocId) return;
    if (e.type === 'OBJECT_EXHIBIT' || e.type === 'PHOTOGRAPH') {
      const ref = (e.description.match(/Exhibit ([A-Z]{1,2}[-\s]?\d+)/) || [])[1]; const para = byDoc[c.sourceDocId].pages[c.page - 1].paras[c.para - 1].text;
      if (ref && para.toLowerCase().includes(ref.toLowerCase())) rel.push({ id: 'R-' + pad(++rn, 3), claimId: c.id, evidenceId: e.id, relationship: 'MENTIONS', reason: `The claim's paragraph refers to Exhibit ${ref}.`, viaClaim: null, sourceLocation: `${docLabel(byDoc[e.sourceDocId])}, page ${e.page || 1}`, assessmentSignal: 15 });
      return;
    }
    const inDoc = claims.filter(k => k.sourceDocId === e.sourceDocId && (e.type === 'HEARING_STATEMENT' ? k.speaker === (e.description.split(' by ')[1]) : true)); if (!inDoc.length) return;
    let best = null; const rank = { CONFLICTS: 3, SUPPORTS: 2, CONTEXTUALIZES: 1 };
    inDoc.forEach(k => { const l = links.find(x => (x.a === c.id && x.b === k.id) || (x.b === c.id && x.a === k.id)); if (l && (!best || rank[l.relationship] > rank[best.l.relationship] || (rank[l.relationship] === rank[best.l.relationship] && l.strength > best.l.strength))) best = { l, k }; });
    if (best) rel.push({ id: 'R-' + pad(++rn, 3), claimId: c.id, evidenceId: e.id, relationship: best.l.relationship, reason: best.l.reason, viaClaim: best.k.id, sourceLocation: `${docLabel(byDoc[e.sourceDocId])}, page ${best.k.page}, ¶${best.k.para}`, assessmentSignal: Math.round(best.l.strength) });
    else if (c.locations.some(l => lowText[e.sourceDocId].includes(l.key))) rel.push({ id: 'R-' + pad(++rn, 3), claimId: c.id, evidenceId: e.id, relationship: 'MENTIONS', reason: 'The evidence source mentions a location that also appears in this claim.', viaClaim: null, sourceLocation: `${docLabel(byDoc[e.sourceDocId])}, page ${e.page || 1}`, assessmentSignal: 15 });
  }));
  return { conflicts, links, relationships: rel };
}

/* ---- assessment signals (prototype; NOT probability of truth) ---- */
function computeSignals(C) {
  const byDoc = {}; C.documents.forEach(d => byDoc[d.id] = d);
  C.claims.forEach(c => {
    const supDocs = uniq(C.links.filter(l => l.relationship === 'SUPPORTS' && (l.a === c.id || l.b === c.id)).map(l => { const o = C.claims.find(x => x.id === (l.a === c.id ? l.b : l.a)); return o && o.sourceDocId; }).filter(x => x && x !== c.sourceDocId));
    const mineC = C.conflicts.filter(k => k.claims.includes(c.id)); const conDocs = uniq(mineC.flatMap(k => (k.sideA.includes(c.id) ? k.sideB : k.sideA).map(id => C.claims.find(x => x.id === id)).filter(Boolean).map(o => o.sourceDocId)));
    const d = byDoc[c.sourceDocId]; const primary = d && (PRIMARY_CATS.has(d.category) || d.kind === 'transcript');
    const f = [
      { name: 'Source directness', points: primary ? 10 : 4, note: primary ? 'Primary record or hearing statement' : 'Secondary / narrative document' },
      { name: 'Independent supporting sources', points: 20 * Math.min(3, supDocs.length), note: `${supDocs.length} other source(s) describe a consistent position` },
      { name: 'Extraction consistency', points: Math.round(c.confidence * 15), note: `Extraction confidence ${c.confidence.toFixed(2)} (extraction certainty only)` },
      { name: 'Metadata completeness', points: (c.eventTime ? 4 : 0) + (c.locations.length ? 4 : 0) + (c.speaker ? 4 : 0), note: [c.eventTime ? 'time' : null, c.locations.length ? 'location' : null, c.speaker ? 'speaker' : null].filter(Boolean).join(', ') || 'none recorded' },
      { name: 'Conflict indicators', points: -8 * Math.min(3, conDocs.length), note: `${conDocs.length} source(s) flagged as potentially inconsistent` },
    ];
    c.supportStrength = clamp(10 + f.reduce((s, x) => s + x.points, 0), 0, 100);
    const mine = mineC;
    const cf = [{ name: 'Conflict indicators', points: conDocs.length ? 30 + 12 * Math.min(3, conDocs.length - 1) : 0, note: `${conDocs.length} distinct source(s)` }, { name: 'Interval tightness', points: mine.length ? Math.round(Math.max(...mine.map(k => k.tight)) * 0.3) : 0, note: 'How closely the compared times/locations line up' }];
    const oth = mine.flatMap(k => (k.sideA.includes(c.id) ? k.sideB : k.sideA).map(id => C.claims.find(x => x.id === id)).filter(Boolean));
    cf.push({ name: 'Source quality of the other source', points: oth.some(o => byDoc[o.sourceDocId] && PRIMARY_CATS.has(byDoc[o.sourceDocId].category)) ? 10 : 0, note: 'Primary record on the other side' });
    c.conflictStrength = mine.length ? clamp(cf.reduce((s, x) => s + x.points, 0), 0, 100) : 0;
    const cues = (c.text.match(new RegExp(UNCERT.source, 'gi')) || []).length;
    c.uncertainty = clamp(cues * 30 + (c.uncertaintyFlags.includes('TIME_UNCERTAINTY') ? 15 : 0) + (c.confidence < 0.6 ? 15 : 0), 0, 100);
    c.signalFactors = { support: f, conflict: cf, uncertainty: [{ name: 'Hedging language', points: cues * 30, note: `${cues} cue(s) such as “approximately”, “cannot remember”` }, { name: 'Time uncertainty', points: c.uncertaintyFlags.includes('TIME_UNCERTAINTY') ? 15 : 0, note: 'Time-related hedging detected' }, { name: 'Low extraction confidence', points: c.confidence < 0.6 ? 15 : 0, note: 'Few anchors in the sentence' }] };
    c.supportingDocs = supDocs; c.conflictingDocs = conDocs;
  });
}
const SIGNAL_DISCLAIMER = 'This is a prototype assessment signal, not a probability of truth or legal validity.';
