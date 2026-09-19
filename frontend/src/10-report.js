/* ===== 10 report: JSON report object + dependency-free PDF writer ===== */
const REPORT_DISCLAIMER = 'This report is an AI-assisted research and evidence-auditing output. It does not determine guilt, innocence, liability, witness credibility, admissibility, or judicial outcome. Human legal review remains required.';
const LIMITATIONS = ['Claims, evidence and relationships were produced by a deterministic rules engine and are heuristic; they can be incomplete or wrong.', 'Assessment signals are prototype signals, not probabilities of truth or legal validity.', 'Extraction confidence describes extraction certainty only.', 'Authority passages come from the user’s own authority library and have not been verified by this system.', 'Potential conflicts are surfaced for review; the system does not decide which source is accurate.', 'Basic prototype PII redaction is not comprehensive privacy protection or legal compliance.'];
function buildReport(C, user) {
  const redact = prefs().piiRedaction ? redactPII : (x => x); const D = {}; C.documents.forEach(d => D[d.id] = d);
  const loc = c => ({ documentId: c.sourceDocId, document: D[c.sourceDocId] ? D[c.sourceDocId].filename : null, page: c.page, paragraph: c.para, timestamp: c.timestamp });
  const m = caseMetrics(C);
  return {
    generatedAt: nowISO(), generatedBy: user ? { name: user.fullName, role: roleLabel(user.role) } : null, disclaimer: REPORT_DISCLAIMER, pii: prefs().piiRedaction ? 'Basic prototype PII redaction applied (email, phone, Aadhaar-like patterns). Not comprehensive.' : 'PII redaction off',
    case: { id: C.id, name: C.name, number: C.number, type: C.type, jurisdiction: C.jurisdiction, court: C.court, status: STATUS_LABEL[C.status], description: C.description, createdAt: C.createdAt, lastAnalyzedAt: C.lastAnalyzedAt },
    materials: C.documents.map(d => ({ id: d.id, name: d.filename, kind: d.kind, category: d.category, pages: d.pageCount, hearingDate: d.hearingDate, hearingNumber: d.hearingNumber })),
    hearing: C.documents.filter(d => d.kind === 'transcript').map(t => { const st = t.pages.flatMap(p => p.paras); return { id: t.id, file: t.filename, hearingDate: t.hearingDate, hearingNumber: t.hearingNumber, statements: st.length, speakers: uniq(st.map(s => s.speaker)), uncertaintyStatements: st.filter(s => UNCERT.test(s.text)).length }; }),
    claims: C.claims.map(c => ({ id: c.id, text: redact(c.text), type: c.type, speaker: c.speaker, source: loc(c), extractionConfidence: c.confidence, status: claimStatus(C, c), supportSignal: c.supportStrength, conflictSignal: c.conflictStrength, uncertaintySignal: c.uncertainty, generatedBy: c.agent })),
    evidence: C.evidence.map(e => ({ id: e.id, type: e.type, description: redact(e.description), sourceDocumentId: e.sourceDocId, page: e.page })),
    relationships: C.relationships.map(r => ({ claimId: r.claimId, evidenceId: r.evidenceId, relationship: r.relationship, reason: r.reason, sourceLocation: r.sourceLocation, assessmentSignal: r.assessmentSignal })),
    conflicts: C.conflicts.map(k => ({ id: k.id, type: k.type, claimA: k.claimA, claimB: k.claimB, description: redact(k.description), severity: k.severity, sources: k.supportingSources, comparison: k.comparison, reviewStatus: (() => { const f = C.findings.find(x => x.conflictId === k.id); return f ? findingStatus(C, f) : 'PENDING'; })() })),
    authorities: uniq(C.authorityLinks.map(a => a.authorityId)).map(id => { const a = AUTH_BY_ID[id] || { citation: id, title: '(removed from library)', court: '', year: null }; return { id, citation: a.citation, title: a.title, court: a.court, year: a.year, source: 'authority_library', retrievedFor: C.authorityLinks.filter(l => l.authorityId === id).map(l => ({ claimId: l.claimId, retrievalSignal: l.score, passageIndex: l.passageIndex })) }; }),
    citationAudit: C.citations.map(x => ({ id: x.id, claimId: x.claimId, citation: x.citationText, result: x.result, potentialMismatch: x.potentialMismatch, relevanceSignal: x.relevanceSignal, note: x.note })),
    reviews: C.reviews.map(r => ({ id: r.id, findingId: r.findingId, claimIds: r.claimIds, reviewer: r.reviewerName, action: r.action, comment: redact(r.comment), modifiedText: r.modifiedText ? redact(r.modifiedText) : null, previousStatus: r.previousStatus, newStatus: r.newStatus, at: r.createdAt })),
    auditTrail: C.audit.map(e => ({ at: e.ts, actor: e.actorName, event: e.event, description: redact(e.description) })),
    coverage: { ...m.coverage, note: 'Workflow coverage indicators — not legal conclusions.' }, signalDisclaimer: SIGNAL_DISCLAIMER, limitations: LIMITATIONS,
  };
}
const WIN = (() => { const w = {}; const t = '278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278 556 556 556 556 556 556 556 556 556 556 278 278 584 584 584 556 1015 667 667 722 722 667 611 778 722 278 500 667 556 833 722 778 667 778 722 667 611 722 667 944 667 667 611 278 278 278 469 556 333 556 556 500 556 556 278 556 556 222 222 500 222 833 556 556 556 556 333 500 278 556 500 722 500 500 500 334 260 334 584'.split(' ').map(Number); t.forEach((v, i) => w[32 + i] = v); return w; })();
const WINBOLD_SCALE = 1.06;
const PDF_MAP = { '\u2014': '\x97', '\u2013': '\x96', '\u2018': '\x91', '\u2019': '\x92', '\u201c': '\x93', '\u201d': '\x94', '\u2022': '\x95', '\u2026': '\x85', '\u00b7': '\xb7', '\u00b6': '\xb6', '\u00a7': '\xa7', '\u2194': '<->', '\u2192': '->', '\u2713': 'v', '\u00a0': ' ' };
const pdfSafe = s => String(s).replace(/[^\x00-\x7f]/g, c => PDF_MAP[c] != null ? PDF_MAP[c] : (c.charCodeAt(0) < 256 ? c : '?')).replace(/[\x00-\x08\x0b-\x1f]/g, ' ');
const pdfEsc = s => s.replace(/[\\()]/g, m => '\\' + m);
function strW(s, size, bold) { let w = 0; for (let i = 0; i < s.length; i++) w += (WIN[s.charCodeAt(i)] || 556); return w * size / 1000 * (bold ? WINBOLD_SCALE : 1); }
function wrap(s, size, maxW, bold) {
  const out = []; String(s).split('\n').forEach(par => { const words = pdfSafe(par).split(/\s+/).filter(Boolean); let line = ''; if (!words.length) { out.push(''); return; }
    words.forEach(w => { const t = line ? line + ' ' + w : w; if (strW(t, size, bold) <= maxW) line = t; else { if (line) out.push(line); while (strW(w, size, bold) > maxW) { let k = w.length; while (k > 1 && strW(w.slice(0, k), size, bold) > maxW) k--; out.push(w.slice(0, k)); w = w.slice(k); } line = w; } }); out.push(line); });
  return out;
}
function reportToPDF(R) {
  const W = 595, H = 842, M = 54, CW = W - 2 * M; const pages = [[]]; let y = H - M - 16;
  const cur = () => pages[pages.length - 1]; const newPage = () => { pages.push([]); y = H - M - 16; };
  const need = h => { if (y - h < M + 24) newPage(); };
  const text = (s, o = {}) => { const size = o.size || 10, lead = o.lead || size * 1.4, bold = !!o.bold; const lines = wrap(s, size, CW - (o.indent || 0), bold); lines.forEach(l => { need(lead); cur().push({ t: l, x: M + (o.indent || 0), y, size, bold, gray: o.gray }); y -= lead; }); y -= o.after || 0; };
  const h1 = s => { need(40); y -= 8; text(s, { size: 13, bold: true, after: 2 }); cur().push({ rule: true, y: y + 6 }); y -= 4; };
  text('NyayaSahayak — Source-Traceable Audit Report', { size: 17, bold: true, lead: 22 });
  text(R.case.name, { size: 12, bold: true, after: 2 });
  text(`${R.case.id}${R.case.number ? ' · ' + R.case.number : ''} · ${R.case.type || ''}${R.case.jurisdiction ? ' · ' + R.case.jurisdiction : ''}`, { size: 9, gray: true });
  text(`Generated ${fmtDT(R.generatedAt)}${R.generatedBy ? ' by ' + R.generatedBy.name + ' (' + R.generatedBy.role + ')' : ''}`, { size: 9, gray: true, after: 8 });
  text(R.disclaimer, { size: 9, bold: true, after: 6 });
  h1('1. Case information');
  [['Case ID', R.case.id], ['Case number', R.case.number || '—'], ['Type', R.case.type || '—'], ['Jurisdiction', R.case.jurisdiction || '—'], ['Court / institution', R.case.court || '—'], ['Status', R.case.status], ['Last analyzed', R.case.lastAnalyzedAt ? fmtDT(R.case.lastAnalyzedAt) : 'Not analyzed'], ['Description', R.case.description || '—']].forEach(([k, v]) => text(`${k}: ${v}`, { size: 9.5 }));
  h1('2. Materials analyzed'); if (!R.materials.length) text('No material.', { size: 9.5 }); R.materials.forEach(m => text(`${m.id}  ${m.name} — ${m.category}, ${m.pages} page(s)`, { size: 9.5 }));
  h1('3. Hearing transcript summary'); if (!R.hearing.length) text('No hearing transcript was supplied.', { size: 9.5 }); R.hearing.forEach(t => text(`${t.id}  ${t.file}${t.hearingDate ? ' · hearing date ' + t.hearingDate : ''}${t.hearingNumber ? ' · hearing no. ' + t.hearingNumber : ''}: ${t.statements} statements, speakers: ${t.speakers.join(', ')}; ${t.uncertaintyStatements} statement(s) with uncertainty language.`, { size: 9.5 }));
  h1('4. Extracted claims'); if (!R.claims.length) text('No claims extracted.', { size: 9.5 }); R.claims.forEach(c => { text(`${c.id}  [${c.type}]  ${c.status.replace(/_/g, ' ')}`, { size: 9.5, bold: true }); text(c.text, { size: 9.5, indent: 12 }); text(`Source: ${c.source.document || c.source.documentId}, page ${c.source.page}, paragraph ${c.source.paragraph}${c.source.timestamp ? ', ' + c.source.timestamp : ''}${c.speaker ? ' · speaker ' + c.speaker : ''} · support signal ${c.supportSignal}/100 · conflict signal ${c.conflictSignal}/100 · uncertainty ${c.uncertaintySignal}/100`, { size: 8.5, indent: 12, gray: true, after: 3 }); });
  text(R.signalDisclaimer, { size: 8.5, gray: true });
  h1('5. Evidence mapping'); if (!R.evidence.length) text('No evidence items.', { size: 9.5 }); R.evidence.forEach(e => text(`${e.id}  ${e.type}  ${e.description} (source ${e.sourceDocumentId})`, { size: 9.5 })); R.relationships.forEach(r => text(`${r.claimId} ${r.relationship} ${r.evidenceId} — ${r.reason}`, { size: 8.5, indent: 12, gray: true }));
  h1('6. Potential conflicts'); if (!R.conflicts.length) text('No potential conflicts were identified.', { size: 9.5 }); R.conflicts.forEach(k => { text(`${k.id}  ${k.type}  (${k.claimA} ↔ ${k.claimB}) — review: ${k.reviewStatus.replace(/_/g, ' ')}`, { size: 9.5, bold: true }); text(k.description, { size: 9.5, indent: 12, after: 3 }); });
  h1('7. Legal authority references'); text(AUTH_LABEL + '. Retrieval signals are not legal correctness.', { size: 8.5, gray: true }); if (!R.authorities.length) text('No authority passages were retrieved.', { size: 9.5 }); R.authorities.forEach(a => text(`${a.citation}  ${a.title} (${a.year}) — retrieved for ${a.retrievedFor.map(x => x.claimId).join(', ')}`, { size: 9.5 }));
  h1('8. Citation audit'); if (!R.citationAudit.length) text('No citations found.', { size: 9.5 }); R.citationAudit.forEach(x => text(`${x.id}  ${x.claimId || '—'}  ${x.citation}  →  ${x.result.replace(/_/g, ' ')}${x.note ? ' — ' + x.note : ''}`, { size: 9.5 }));
  h1('9. Human review actions'); if (!R.reviews.length) text('No review actions recorded yet.', { size: 9.5 }); R.reviews.forEach(r => text(`${fmtDT(r.at)}  ${r.findingId}  ${r.action.toUpperCase()}  ${r.previousStatus.replace(/_/g, ' ')} → ${r.newStatus.replace(/_/g, ' ')}  by ${r.reviewer}${r.comment ? ' — “' + r.comment + '”' : ''}`, { size: 9.5 }));
  h1('10. Audit trail'); R.auditTrail.forEach(e => text(`${fmtDT(e.at)} ${fmtClock(e.at)}  ${e.actor}: ${e.description}`, { size: 8.5 }));
  h1('11. System limitations'); R.limitations.forEach(l => text('• ' + l, { size: 9.5 })); text(R.pii, { size: 9, gray: true });
  /* emit */
  const objs = []; const add = s => { objs.push(s); return objs.length; };
  add('<< /Type /Catalog /Pages 2 0 R >>'); add('PLACEHOLDER'); add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'); add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>');
  const pageIds = []; const total = pages.length;
  pages.forEach((ops, pi) => {
    let c = ''; ops.forEach(o => { if (o.rule) { c += `0.75 G 0.5 w ${M} ${o.y.toFixed(1)} m ${W - M} ${o.y.toFixed(1)} l S\n`; return; } c += `BT /${o.bold ? 'F2' : 'F1'} ${o.size} Tf ${o.gray ? '0.35 g' : '0 g'} ${o.x.toFixed(1)} ${o.y.toFixed(1)} Td (${pdfEsc(o.t)}) Tj ET\n`; });
    c += `BT /F1 8 Tf 0.4 g ${M} 30 Td (${pdfEsc('NyayaSahayak - AI-assisted output - human review required')}) Tj ET\nBT /F1 8 Tf 0.4 g ${W - M - 50} 30 Td (${pdfEsc(`Page ${pi + 1} of ${total}`)}) Tj ET\n`;
    const cid = add(`<< /Length ${c.length} >>\nstream\n${c}endstream`); pageIds.push(add(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${W} ${H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${cid} 0 R >>`));
  });
  objs[1] = `<< /Type /Pages /Kids [${pageIds.map(i => i + ' 0 R').join(' ')}] /Count ${pageIds.length} >>`;
  let out = '%PDF-1.4\n'; const offs = []; objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const xref = out.length; out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => pad(o, 10) + ' 00000 n \n').join('') + `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  const bytes = new Uint8Array(out.length); for (let i = 0; i < out.length; i++) bytes[i] = out.charCodeAt(i) & 255; return bytes;
}
const ReportSvc = {
  generate(userId, caseId) { const C = ownedCase(userId, caseId); const u = currentUser(); const R = buildReport(C, u); const rec = { id: nextId(C, 'report', 'RPT-'), createdAt: R.generatedAt, generatedBy: u ? u.fullName : null, counts: { claims: R.claims.length, evidence: R.evidence.length, conflicts: R.conflicts.length, reviews: R.reviews.length } }; C.reports.push(rec); audit(C, { actor: 'REVIEWER', actorId: userId, actorName: rec.generatedBy, event: 'REPORT_GENERATED', description: `Report ${rec.id} generated`, object: rec.id }); commit(); return { rec, report: R }; },
};
