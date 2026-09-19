/* ===== 06 mcp: controlled tool layer. Tools never touch the store directly — they call services with the caller's identity.
   This is an in-browser, MCP-shaped implementation of the seven tool contracts. The Python MCP server in the backend build exposes the same contracts. ===== */
const MCP = { serverName: 'nyayasahayak', tools: {}, log: [] };
const ID_RE = /^[A-Za-z0-9._-]{1,48}$/;
const now_ms = () => (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
function defTool(name, purpose, input, handler) { MCP.tools[name] = { name, purpose, input, handler }; }
function validate(schema, args) {
  const a = args && typeof args === 'object' ? args : {}; const out = {};
  for (const [k, spec] of Object.entries(schema)) {
    const req = spec.endsWith('!'), t = spec.replace('!', ''); const v = a[k];
    if (v == null || v === '') { if (req) throw new ServiceError('VALIDATION_ERROR', `Missing required field: ${k}.`); continue; }
    if (t === 'id') { if (typeof v !== 'string' || !ID_RE.test(v)) throw new ServiceError('VALIDATION_ERROR', `Invalid value for ${k}.`); out[k] = v; }
    else if (t === 'text') { if (typeof v !== 'string' || v.length > 2000) throw new ServiceError('VALIDATION_ERROR', `Invalid value for ${k}.`); out[k] = v; }
    else if (t === 'int') { const n = Number(v); if (!Number.isInteger(n) || n < 1 || n > 25) throw new ServiceError('VALIDATION_ERROR', `Invalid value for ${k}.`); out[k] = n; }
  }
  return out;
}
const srcLoc = c => `page ${c.page}${c.para ? ', paragraph ' + c.para : ''}${c.timestamp ? ', ' + c.timestamp : ''}`;
defTool('get_case_material', 'Retrieve the inventory of documents and transcripts for a case (metadata only, no full text).', { case_id: 'id!' }, (ctx, a) => {
  const C = CaseSvc.get(ctx.userId, a.case_id);
  return { case_id: C.id, documents: C.documents.map(d => ({ id: d.id, name: d.filename, type: (d.category || '').toUpperCase().replace(/[^A-Z]+/g, '_').replace(/^_|_$/g, ''), kind: d.kind, pages: d.pageCount, status: d.status, description: `${d.category}, ${d.pageCount} page(s)` })) };
});
defTool('get_claims', 'List extracted claims for a case. `confidence` describes extraction certainty only — never truth or legal validity.', { case_id: 'id!' }, (ctx, a) => {
  const C = CaseSvc.get(ctx.userId, a.case_id);
  return { case_id: C.id, claims: C.claims.map(c => ({ id: c.id, text: c.text, type: c.type, speaker: c.speaker, source_document_id: c.sourceDocId, source_location: srcLoc(c), confidence: c.confidence, review_status: claimStatus(C, c) })), confidence_note: 'Extraction confidence only; not a probability of truth or legal validity.' };
});
defTool('get_evidence', 'List evidence linked to a claim, with the relationship of each item to the claim. Claim ids are case-scoped, so case_id is required.', { case_id: 'id!', claim_id: 'id!' }, (ctx, a) => {
  const rows = ClaimSvc.evidenceFor(ctx.userId, a.case_id, a.claim_id);
  return { case_id: a.case_id, claim_id: a.claim_id, evidence: rows.map(({ rel, ev }) => ({ id: ev.id, type: ev.type, description: ev.description, source_document_id: ev.sourceDocId, relationship: rel.relationship, reason: rel.reason })) };
});
defTool('search_authorities', 'Search the user’s authority library. `relevance_score` is a retrieval/ranking signal only, not legal correctness.', { query: 'text!', limit: 'int', case_id: 'id' }, (ctx, a) => {
  if (a.case_id) CaseSvc.get(ctx.userId, a.case_id);
  const r = searchAuthorities(a.query, a.limit || 5);
  return { results: r.map(x => ({ authority_id: x.authorityId, title: x.title, citation: x.citation, relevance_score: x.relevanceScore, passage_index: x.passageIndex })), source_label: AUTH_LABEL };
});
defTool('get_authority_excerpt', 'Return source text of an authority. The AI must use this retrieved text and never invent authority content.', { authority_id: 'id!', passage_index: 'int', case_id: 'id' }, (ctx, a) => {
  if (a.case_id) CaseSvc.get(ctx.userId, a.case_id);
  const A = AUTH_BY_ID[a.authority_id]; if (!A) throw new ServiceError('AUTHORITY_NOT_FOUND', 'No authority was found for the supplied authority_id.');
  const i = a.passage_index; if (i && !A.paras[i - 1]) throw new ServiceError('AUTHORITY_NOT_FOUND', 'That paragraph does not exist in the authority.');
  return { authority_id: A.id, citation: A.citation, title: A.title, excerpt: i ? A.paras[i - 1] : A.paras.join('\n'), passage_index: i || null, source: 'authority_library', label: AUTH_LABEL };
});
defTool('find_claim_conflicts', 'Identify potential conflicts involving a claim. Never determines which source is truthful.', { case_id: 'id!', claim_id: 'id!' }, (ctx, a) => {
  const cs = ClaimSvc.conflictsFor(ctx.userId, a.case_id, a.claim_id);
  return { case_id: a.case_id, claim_id: a.claim_id, conflicts: cs.map(k => ({ id: k.id, type: k.type, claim_a: k.claimA, claim_b: k.claimB, related_claims: k.claims, description: k.description, severity: k.severity, supporting_sources: k.supportingSources })), note: 'Potential conflicts only. Human verification is required.' };
});
defTool('get_audit_history', 'Return the audit trail for a case.', { case_id: 'id!' }, (ctx, a) => {
  const ev = AuditSvc.list(ctx.userId, a.case_id);
  return { case_id: a.case_id, events: ev.map(e => ({ event: e.event, actor: e.actorType === 'AI' ? 'AI' : e.actorType, timestamp: e.ts, description: e.description })) };
});
const MCP_TOOL_NAMES = Object.keys(MCP.tools);
function mcpCall(name, args, ctx) {
  const t0 = now_ms(); const requestId = 'req-' + rid(6); let res, ok = true, code = null; const tool = MCP.tools[name];
  try {
    if (!ctx || !ctx.userId) throw new ServiceError('UNAUTHENTICATED', 'Authentication required.');
    if (!tool) throw new ServiceError('TOOL_NOT_FOUND', 'Unknown tool.');
    useLibrary(ctx.userId); res = tool.handler(ctx, validate(tool.input, args));
  } catch (e) {
    ok = false; code = e instanceof ServiceError ? e.code : 'INTERNAL_ERROR';
    res = { error: { code, message: e instanceof ServiceError ? e.message : 'The tool could not complete this request.' } };
  }
  const latency = Math.round((now_ms() - t0) * 10) / 10;
  const rec = { requestId, tool: name, caseId: (args && args.case_id) || null, ok, code, latencyMs: latency, ts: nowISO(), agent: ctx && ctx.agent || null, analysisId: ctx && ctx.analysisId || null };
  MCP.log.push({ tool: name, requestId, ok, code, latencyMs: latency, ts: rec.ts }); if (MCP.log.length > 200) MCP.log.shift();
  if (ok && rec.caseId) { try { const C = ownedCase(ctx.userId, rec.caseId); C.toolCalls.push(rec); if (C.toolCalls.length > 300) C.toolCalls.splice(0, C.toolCalls.length - 300); } catch (e) {} }
  return res;
}
