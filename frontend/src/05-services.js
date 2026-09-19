/* ===== 05 services: the only layer that touches the store. Every read/write is ownership-checked. ===== */
class ServiceError extends Error { constructor(code, message) { super(message); this.code = code; } }
const E = { NOT_FOUND: ['CASE_NOT_FOUND', 'No case was found for the supplied case_id.'], DENIED: ['PERMISSION_DENIED', 'You do not have access to this case.'] };
function requireUser() { const u = currentUser(); if (!u) throw new ServiceError('UNAUTHENTICATED', 'Sign in to continue.'); return u; }
function ownedCase(userId, caseId) {
  const c = loadDB().cases.find(x => x.id === caseId);
  if (!c) throw new ServiceError(...E.NOT_FOUND);
  if (c.userId !== userId) throw new ServiceError(...E.DENIED);
  return c;
}
function nextId(C, kind, prefix, w = 3) { C.counters[kind] = (C.counters[kind] || 0) + 1; return prefix + pad(C.counters[kind], w); }
function audit(C, o) {
  C.audit.push({ id: nextId(C, 'audit', 'AE-', 4), ts: nowISO(), actorType: o.actor || 'SYSTEM', actorId: o.actorId || null, actorName: o.actorName || (o.actor === 'AI' ? (o.agent || 'AI agent') : o.actor === 'REVIEWER' ? 'Reviewer' : 'System'), event: o.event, description: o.description, object: o.object || null, prev: o.prev || null, next: o.next || null, meta: o.meta || null });
  C.updatedAt = nowISO();
}
const CaseSvc = {
  list(userId) { return loadDB().cases.filter(c => c.userId === userId).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)); },
  get(userId, id) { return ownedCase(userId, id); },
  create(userId, f, synthetic = false) {
    const errors = {}; if (!f.name || !f.name.trim()) errors.name = 'Enter a case name.'; if (Object.keys(errors).length) throw Object.assign(new ServiceError('VALIDATION', 'Please correct the highlighted fields.'), { errors });
    const db = loadDB(); const y = new Date().getFullYear(); db.counters[y] = (db.counters[y] || 0) + 1;
    const C = { id: `NS-${y}-${pad(db.counters[y], 3)}`, userId, name: f.name.trim(), number: (f.number || '').trim(), type: f.type || 'Other', jurisdiction: (f.jurisdiction || '').trim(), court: (f.court || '').trim(), description: (f.description || '').trim(), status: 'DRAFT', synthetic, createdAt: nowISO(), updatedAt: nowISO(), lastAnalyzedAt: null, counters: {}, documents: [], claims: [], evidence: [], links: [], relationships: [], conflicts: [], authorityLinks: [], citations: [], findings: [], reviews: [], audit: [], agentRuns: [], toolCalls: [], reports: [], analysis: null };
    db.cases.push(C); audit(C, { actor: 'REVIEWER', actorId: userId, event: 'CASE_CREATED', description: `Case created: ${C.name}`, object: C.id }); commit(); return C;
  },
  update(userId, id, f) { const C = ownedCase(userId, id); ['name', 'number', 'type', 'jurisdiction', 'court', 'description'].forEach(k => { if (f[k] != null) C[k === 'name' ? 'name' : k] = String(f[k]).trim(); }); if (!C.name) throw new ServiceError('VALIDATION', 'Case name is required.'); C.updatedAt = nowISO(); commit(); return C; },
  archive(userId, id, on = true) { const C = ownedCase(userId, id); C.status = on ? 'ARCHIVED' : (C.claims.length ? 'ACTIVE_REVIEW' : 'DRAFT'); audit(C, { actor: 'REVIEWER', actorId: userId, event: on ? 'CASE_ARCHIVED' : 'CASE_RESTORED', description: on ? 'Case archived' : 'Case restored' }); commit(); return C; },
  remove(userId, id) { const C = ownedCase(userId, id); loadDB().cases = loadDB().cases.filter(x => x.id !== C.id); commit(); },
};
function pendingCount(C) { return C.findings.filter(f => findingStatus(C, f) === 'PENDING').length; }
function findingStatus(C, f) { for (let i = C.reviews.length - 1; i >= 0; i--) if (C.reviews[i].findingId === f.id && C.reviews[i].newStatus) return C.reviews[i].newStatus; return 'PENDING'; }
function claimFinding(C, claimId) { return C.findings.find(f => f.kind === 'CLAIM' && f.claimIds[0] === claimId); }
function claimStatus(C, c) { const f = claimFinding(C, c.id); const s = f ? findingStatus(C, f) : 'PENDING'; return { PENDING: 'NEEDS_REVIEW', ACCEPTED: 'REVIEWED', REJECTED: 'REJECTED', MODIFIED: 'MODIFIED', NEEDS_VERIFICATION: 'NEEDS_VERIFICATION' }[s] || 'NEEDS_REVIEW'; }
const DocSvc = {
  add(userId, caseId, o) {
    const C = ownedCase(userId, caseId); if (C.status === 'ARCHIVED') throw new ServiceError('ARCHIVED', 'Archived cases are read-only.');
    const isT = o.kind === 'transcript'; const id = isT ? nextId(C, 'tr', 'TR-') : nextId(C, 'doc', 'DOC-');
    const d = { id, kind: isT ? 'transcript' : 'document', filename: safeName(o.filename || (isT ? 'Pasted transcript.txt' : 'Untitled.txt')), category: isT ? 'Hearing Transcript' : (o.category || guessCategory(o.filename || '', o.text || '')), mime: o.mime || 'text/plain', size: o.size || (o.text || '').length, uploadedAt: nowISO(), status: 'Indexed', hearingDate: o.hearingDate || null, hearingNumber: o.hearingNumber || null, extractor: o.extractor || 'txt', extractNote: o.extractNote || '', synthetic: !!o.synthetic, pages: [], statementCount: 0 };
    if (isT) { const st = parseTranscript(o.text); d.pages = statementsToPages(st); d.statementCount = st.length; if (!st.length) d.status = 'Needs Review'; }
    else if (o.pages) d.pages = o.pages; else d.pages = splitPages(o.text || '');
    if (!isT && !d.pages.some(p => p.paras.some(x => x.text.trim()))) d.status = 'Needs Review';
    d.pageCount = d.pages.length; d.entities = entitiesOf(d);
    C.documents.push(d); C.status = C.status === 'DRAFT' ? 'DRAFT' : C.status;
    audit(C, { actor: 'REVIEWER', actorId: userId, event: isT ? 'TRANSCRIPT_UPLOADED' : 'DOCUMENT_UPLOADED', description: `${isT ? 'Transcript' : 'Document'} uploaded: ${d.filename}`, object: d.id });
    audit(C, { actor: 'SYSTEM', event: 'DOCUMENT_PROCESSED', description: `Processed ${d.filename}: ${d.pageCount} page(s), ${d.entities.people.length} people, ${d.entities.locations.length} locations`, object: d.id, meta: { pii: d.entities.pii } });
    commit(); return d;
  },
  setCategory(userId, caseId, docId, cat) { const C = ownedCase(userId, caseId); const d = C.documents.find(x => x.id === docId); if (!d || d.kind === 'transcript' || !CATEGORIES.includes(cat)) throw new ServiceError('VALIDATION', 'Invalid document category.'); d.category = cat; C.updatedAt = nowISO(); commit(); return d; },
  remove(userId, caseId, docId) { const C = ownedCase(userId, caseId); const d = C.documents.find(x => x.id === docId); if (!d) throw new ServiceError('DOC_NOT_FOUND', 'Document not found.'); C.documents = C.documents.filter(x => x.id !== docId); audit(C, { actor: 'REVIEWER', actorId: userId, event: 'DOCUMENT_REMOVED', description: `Removed ${d.filename}. Re-run analysis to refresh findings.`, object: docId }); commit(); },
};
function safeName(n) { return String(n).replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').replace(/^\.+/, '').slice(0, 120) || 'file'; }
const ClaimSvc = {
  list(userId, caseId) { return ownedCase(userId, caseId).claims; },
  get(userId, caseId, claimId) { const c = ownedCase(userId, caseId).claims.find(x => x.id === claimId); if (!c) throw new ServiceError('CLAIM_NOT_FOUND', 'No claim was found for the supplied claim_id.'); return c; },
  evidenceFor(userId, caseId, claimId) { const C = ownedCase(userId, caseId); ClaimSvc.get(userId, caseId, claimId); return C.relationships.filter(r => r.claimId === claimId).map(r => ({ rel: r, ev: C.evidence.find(e => e.id === r.evidenceId) })).filter(x => x.ev); },
  conflictsFor(userId, caseId, claimId) { const C = ownedCase(userId, caseId); ClaimSvc.get(userId, caseId, claimId); return C.conflicts.filter(k => k.claims.includes(claimId)); },
};
const ReviewSvc = {
  ACTIONS: { accept: ['ACCEPTED', 'Accepted'], reject: ['REJECTED', 'Rejected'], modify: ['MODIFIED', 'Modified'], verify: ['NEEDS_VERIFICATION', 'Needs verification'], comment: [null, 'Comment added'] },
  open(userId, caseId, findingId) { const C = ownedCase(userId, caseId); const f = C.findings.find(x => x.id === findingId); if (f) { audit(C, { actor: 'REVIEWER', actorId: userId, actorName: currentUser().fullName, event: 'REVIEWER_OPENED_FINDING', description: `Reviewer opened ${f.id} (${f.claimIds.join(', ') || f.kind})`, object: f.id }); saveDB(); } },
  save(userId, caseId, findingId, o) {
    const C = ownedCase(userId, caseId); const f = C.findings.find(x => x.id === findingId); if (!f) throw new ServiceError('FINDING_NOT_FOUND', 'Finding not found.');
    const act = ReviewSvc.ACTIONS[o.action]; if (!act) throw new ServiceError('VALIDATION', 'Choose a review decision.');
    const comment = String(o.comment || '').trim().slice(0, 2000); if (o.action === 'comment' && !comment) throw new ServiceError('VALIDATION', 'Enter a comment.');
    if (o.action === 'modify' && !String(o.modifiedText || '').trim()) throw new ServiceError('VALIDATION', 'Enter the modified wording.');
    const prev = findingStatus(C, f); const next = act[0] || prev; const u = currentUser();
    const rv = { id: nextId(C, 'review', 'RV-'), findingId: f.id, claimIds: f.claimIds.slice(), reviewerId: userId, reviewerName: u ? u.fullName : 'Reviewer', action: o.action, comment, modifiedText: o.action === 'modify' ? String(o.modifiedText).trim().slice(0, 1000) : null, previousStatus: prev, newStatus: next, createdAt: nowISO() };
    C.reviews.push(rv);
    audit(C, { actor: 'REVIEWER', actorId: userId, actorName: rv.reviewerName, event: 'REVIEWER_CHANGED_STATUS', description: `${f.id}: ${act[1]}`, object: f.id, prev, next });
    if (comment) audit(C, { actor: 'REVIEWER', actorId: userId, actorName: rv.reviewerName, event: 'REVIEWER_ADDED_COMMENT', description: `Comment on ${f.id}: “${trunc(comment, 90)}”`, object: f.id });
    audit(C, { actor: 'REVIEWER', actorId: userId, actorName: rv.reviewerName, event: 'REVIEW_SAVED', description: `Review saved for ${f.id}`, object: rv.id });
    if (C.status !== 'ARCHIVED') C.status = pendingCount(C) === 0 && C.findings.length ? 'REVIEW_COMPLETE' : 'ACTIVE_REVIEW';
    commit(); return rv;
  },
  forFinding(C, id) { return C.reviews.filter(r => r.findingId === id); },
};
function buildFindings(C) {
  const prev = C.findings || []; const out = []; const seen = {};
  const add = (key, o) => { const old = prev.find(p => p.key === key); const f = old ? Object.assign(old, o) : Object.assign({ id: nextId(C, 'finding', 'F-'), key, createdAt: nowISO(), agent: 'conflict_agent' }, o); if (!old) { f.createdAt = nowISO(); } out.push(f); seen[key] = 1; };
  C.conflicts.forEach(k => add('CONFLICT:' + k.claimA + ':' + k.claimB, { kind: 'CONFLICT', claimIds: k.claims.slice(), conflictId: k.id, title: `Potential ${k.type.replace('_CONFLICT', '').toLowerCase()} inconsistency`, why: k.description, priority: 'HIGH', agent: 'conflict_agent' }));
  C.citations.filter(x => x.result !== 'POTENTIALLY_RELEVANT').forEach(x => add('CITATION:' + x.docId + ':' + x.page + ':' + x.para + ':' + x.citationText + ':' + (x.claimId || ''), { kind: 'CITATION', claimIds: x.claimId ? [x.claimId] : [], citationId: x.id, title: x.result === 'MISSING_CITATION' ? 'Legal proposition without a citation' : x.result === 'UNRESOLVED' ? 'Citation could not be resolved' : 'Cited passage shows weak relevance', why: x.note, priority: 'MEDIUM', agent: 'citation_audit_agent' }));
  C.claims.forEach(c => { if (c.uncertainty >= 60) add('UNCERTAIN:' + c.id, { kind: 'UNCERTAIN', claimIds: [c.id], title: 'Claim contains uncertainty language', why: 'The source uses approximate or hedged wording. Uncertainty language is recorded for context only; it says nothing about honesty.', priority: 'MEDIUM', agent: 'transcript_agent' }); });
  C.claims.forEach(c => { const rel = C.relationships.filter(r => r.claimId === c.id && r.relationship !== 'MENTIONS'); if (!rel.length && c.type !== 'LEGAL_PROPOSITION') add('SINGLE:' + c.id, { kind: 'SINGLE_SOURCE', claimIds: [c.id], title: 'No corroborating source linked', why: 'No other source in the case material was linked to this claim by the analysis. This can reflect missing material rather than a problem with the claim.', priority: 'LOW', agent: 'evidence_agent' }); });
  C.claims.forEach(c => add('CLAIM:' + c.id, { kind: 'CLAIM', claimIds: [c.id], title: `Review claim ${c.id}`, why: 'AI-extracted claim awaiting human review.', priority: 'LOW', agent: 'claim_agent' }));
  prev.forEach(p => { if (!seen[p.key] && C.reviews.some(r => r.findingId === p.id)) { p.stale = true; out.push(p); } });
  out.sort((a, b) => a.id.localeCompare(b.id));
  C.findings = out; return out;
}
const AuditSvc = { list(userId, caseId) { return ownedCase(userId, caseId).audit; } };
function caseMetrics(C) {
  const claims = C.claims.length; const withEv = C.claims.filter(c => C.relationships.some(r => r.claimId === c.id)).length;
  const reviewedClaims = C.claims.filter(c => claimStatus(C, c) !== 'NEEDS_REVIEW').length; const cit = C.citations.length; const okCit = C.citations.filter(x => x.result === 'POTENTIALLY_RELEVANT' || x.result === 'WEAK_RELEVANCE').length;
  const fr = C.findings.filter(f => findingStatus(C, f) !== 'PENDING').length;
  const pct = (a, b) => b ? Math.round(a / b * 100) : null;
  return { documents: C.documents.filter(d => d.kind === 'document').length, transcripts: C.documents.filter(d => d.kind === 'transcript').length, claims, evidence: C.evidence.length, conflicts: C.conflicts.length, reviews: C.reviews.length, reports: C.reports.length, authorities: uniq(C.authorityLinks.map(a => a.authorityId)).length, coverage: { evidence: pct(withEv, claims), claims: pct(reviewedClaims, claims), citations: pct(okCit, cit), review: pct(fr, C.findings.length) }, pending: pendingCount(C) };
}
const STATUS_LABEL = { DRAFT: 'Draft', ANALYZING: 'Analyzing', ACTIVE_REVIEW: 'Active review', REVIEW_COMPLETE: 'Review complete', ARCHIVED: 'Archived' };
/* global search */
function searchAll(userId, q) {
  q = String(q || '').trim().toLowerCase(); if (q.length < 2) return [];
  const out = []; const has = s => String(s || '').toLowerCase().includes(q);
  CaseSvc.list(userId).forEach(C => {
    if (has(C.name) || has(C.id) || has(C.number)) out.push({ group: 'Cases', label: C.name, sub: C.id, href: `#/cases/${C.id}` });
    C.documents.forEach(d => { if (has(d.filename) || has(d.category)) out.push({ group: d.kind === 'transcript' ? 'Hearings' : 'Documents', label: d.filename, sub: `${C.id} · ${d.id}`, href: d.kind === 'transcript' ? `#/cases/${C.id}/hearing` : `#/cases/${C.id}/documents/${d.id}` }); else if (d.kind === 'document' && out.length < 60 && has(docText(d).slice(0, 60000))) out.push({ group: 'Documents', label: d.filename + ' (text match)', sub: `${C.id} · ${d.id}`, href: `#/cases/${C.id}/documents/${d.id}` }); });
    C.claims.forEach(c => { if (has(c.text) || has(c.id)) out.push({ group: 'Claims', label: `${c.id}  ${trunc(c.text, 80)}`, sub: C.id, href: `#/cases/${C.id}/claims/${c.id}` }); });
    C.evidence.forEach(e => { if (has(e.description) || has(e.id) || has(EVIDENCE_LABEL[e.type])) out.push({ group: 'Evidence', label: `${e.id}  ${trunc(e.description, 70)}`, sub: C.id, href: `#/cases/${C.id}/evidence` }); });
    C.reports.forEach(r => { if (has(r.id) || has('report')) out.push({ group: 'Reports', label: `Report ${r.id}`, sub: C.id, href: `#/cases/${C.id}/report` }); });
  });
  useLibrary(userId); AUTHORITIES.forEach(a => { if (has(a.title) || has(a.citation) || has(a.topics)) out.push({ group: 'Authorities', label: `${a.citation}  ${a.title}`, sub: 'Your authority library', href: `#/authorities?q=${encodeURIComponent(a.citation)}` }); });
  return out.slice(0, 40);
}
