/* ===== 07 agents: BaseAgent contract + orchestrator. Provider is the deterministic local rules engine (no LLM). ===== */
class BaseAgent {
  constructor(name, label, purpose, tools = []) { this.name = name; this.label = label; this.purpose = purpose; this.tools = tools; }
  async run(ctx, C) { throw new Error('not implemented'); }
  result(data, o = {}) { return { agent: this.name, status: o.status || 'completed', data, warnings: o.warnings || [], requires_review: !!o.review }; }
}
const claimKey = c => [c.sourceDocId, c.page, c.para, c.start, c.text.slice(0, 40)].join('|');
const evKey = e => e.key;
class DocumentAgent extends BaseAgent {
  constructor() { super('document_agent', 'Document Agent', 'Validate uploaded material, extract pages, entities and PII flags.', ['get_case_material']); }
  async run(ctx, C) {
    const inv = mcpCall('get_case_material', { case_id: C.id }, ctx); if (inv.error) throw new ServiceError(inv.error.code, inv.error.message);
    const docs = C.documents.filter(d => d.kind === 'document'); const warnings = [];
    docs.forEach(d => { d.entities = entitiesOf(d); if (d.status === 'Needs Review') warnings.push(`${d.filename}: no extractable text — scanned PDFs need OCR in the backend build.`); });
    return this.result({ inventory: inv.documents.length, documents: docs.length, pages: docs.reduce((s, d) => s + d.pageCount, 0) }, { warnings, status: warnings.length ? 'degraded' : 'completed', review: !!warnings.length });
  }
}
class TranscriptAgent extends BaseAgent {
  constructor() { super('transcript_agent', 'Transcript Agent', 'Parse hearing transcripts into speakers, statements, questions and uncertainty statements.', []); }
  async run(ctx, C) {
    const ts = C.documents.filter(d => d.kind === 'transcript'); if (!ts.length) return this.result({ transcripts: 0 }, { status: 'skipped', warnings: ['No hearing transcript uploaded — analysis continues with documents only.'] });
    let statements = 0, questions = 0, unc = 0; const speakers = new Set();
    ts.forEach(t => t.pages.forEach(p => p.paras.forEach(s => { statements++; speakers.add(s.speaker); if (s.qkind === 'QUESTION') questions++; if (UNCERT.test(s.text)) unc++; })));
    return this.result({ transcripts: ts.length, statements, speakers: speakers.size, questions, uncertaintyStatements: unc });
  }
}
class ClaimAgent extends BaseAgent {
  constructor() { super('claim_agent', 'Claim Agent', 'Extract source-traceable claims from documents and transcripts.', ['get_claims']); }
  async run(ctx, C) {
    const old = new Map(C.claims.map(c => [claimKey(c), c])); const fresh = []; const warnings = []; const cfg = ctx.aiCfg || aiConfig(); const useAI = !!(cfg.key && cfg.consent); let aiClaims = 0, aiRejected = 0, fallbacks = 0;
    for (const d of C.documents) {
      let claims = null;
      if (useAI) {
        try { const r = await geminiExtractClaims(d, cfg); aiRejected += r.rejected; if (r.claims.length) { claims = r.claims.map(c => Object.assign(c, { provider: 'gemini', model: cfg.model })); aiClaims += claims.length; } else warnings.push(`${d.filename}: the AI returned no claims that could be matched to the source text; the rules engine was used.`); }
        catch (e) { warnings.push(`${d.filename}: AI extraction unavailable (${e.message}) The rules engine was used.`); }
        if (!claims) { fallbacks++; audit(C, { actor: 'SYSTEM', event: 'AI_PROVIDER_FALLBACK', description: `AI extraction fell back to the rules engine for ${d.filename}`, object: d.id }); }
      }
      if (!claims) claims = extractClaims(d).map(c => Object.assign(c, { provider: 'local-rules', model: 'deterministic-v1' }));
      claims.forEach(c => fresh.push(c));
    }
    const used = new Set(C.claims.map(c => c.id)); let counter = C.counters.claim || 0; const at = nowISO();
    C.claims = fresh.map(c => { const o = old.get(claimKey(c)); c.id = o ? o.id : (() => { let id; do { id = 'C-' + pad(++counter, 2); } while (used.has(id)); used.add(id); return id; })(); c.generatedAt = o ? o.generatedAt : at; c.agent = 'claim_agent'; return c; });
    C.counters.claim = Math.max(counter, C.counters.claim || 0);
    C.claims.forEach(c => { if (!old.has(claimKey(c))) audit(C, { actor: 'AI', agent: 'Claim Agent', event: 'CLAIM_EXTRACTED', description: `AI extracted Claim ${c.id}`, object: c.id }); });
    const check = mcpCall('get_claims', { case_id: C.id }, ctx); if (check.error) throw new ServiceError(check.error.code, check.error.message);
    if (!C.claims.length) warnings.push('No claims could be extracted from the supplied material.');
    const data = { claims: C.claims.length, verifiedViaMcp: check.claims.length }; if (useAI) { data.viaGemini = aiClaims; data.rejectedUnverifiable = aiRejected; }
    return this.result(data, { review: true, warnings, status: (C.claims.length && !warnings.length) ? 'completed' : 'degraded' });
  }
}
class EvidenceAgent extends BaseAgent {
  constructor() { super('evidence_agent', 'Evidence Agent', 'Identify evidence items and map claim–evidence relationships.', ['get_evidence']); }
  async run(ctx, C) {
    const old = new Map(C.evidence.map(e => [e.key, e])); const items = extractEvidence(C.documents, C.claims); let n = C.counters.evidence || 0; const used = new Set(C.evidence.map(e => e.id));
    C.evidence = items.map(e => { const o = old.get(e.key); e.id = o ? o.id : (() => { let id; do { id = 'E-' + pad(++n, 2); } while (used.has(id)); used.add(id); return id; })(); e.generatedAt = o ? o.generatedAt : nowISO(); e.agent = 'evidence_agent'; return e; });
    C.counters.evidence = Math.max(n, C.counters.evidence || 0);
    ctx.rel = relateCase(C); C.links = ctx.rel.links; C.relationships = ctx.rel.relationships;
    if (C.evidence.length) audit(C, { actor: 'AI', agent: 'Evidence Agent', event: 'EVIDENCE_EXTRACTED', description: `AI identified ${C.evidence.length} evidence item(s): ${C.evidence.slice(0, 4).map(e => e.id).join(', ')}${C.evidence.length > 4 ? '…' : ''}`, object: 'evidence' });
    if (C.relationships.length) audit(C, { actor: 'AI', agent: 'Evidence Agent', event: 'RELATIONSHIP_CREATED', description: `AI linked ${C.relationships.length} claim–evidence relationship(s)`, object: 'relationships' });
    let mcpChecked = 0; C.claims.slice(0, 200).forEach(c => { if (C.relationships.some(r => r.claimId === c.id)) { const r = mcpCall('get_evidence', { case_id: C.id, claim_id: c.id }, ctx); if (!r.error) mcpChecked++; } });
    return this.result({ evidence: C.evidence.length, relationships: C.relationships.length, claimsWithEvidence: mcpChecked }, { review: true });
  }
}
class ConflictAgent extends BaseAgent {
  constructor() { super('conflict_agent', 'Conflict Agent', 'Detect potential inconsistencies between claims and sources. Never decides which source is accurate.', ['find_claim_conflicts']); }
  async run(ctx, C) {
    C.conflicts = (ctx.rel || relateCase(C)).conflicts; computeSignals(C);
    C.conflicts.forEach(k => audit(C, { actor: 'AI', agent: 'Conflict Agent', event: 'CONFLICT_DETECTED', description: `Potential conflict detected (${k.id}): ${k.claimA} ↔ ${k.claimB}`, object: k.id }));
    let verified = 0; uniq(C.conflicts.flatMap(k => k.claims)).forEach(cid => { const r = mcpCall('find_claim_conflicts', { case_id: C.id, claim_id: cid }, ctx); if (!r.error && r.conflicts.length) verified++; });
    return this.result({ conflicts: C.conflicts.length, claimsInvolved: verified }, { status: C.conflicts.length ? 'findings' : 'completed', review: C.conflicts.length > 0, warnings: C.conflicts.length ? ['Potential conflicts detected — human verification required.'] : [] });
  }
}
class LegalResearchAgent extends BaseAgent {
  constructor() { super('legal_research_agent', 'Legal Research Agent', 'Retrieve passages from the curated authority corpus that appear relevant to identified propositions.', ['search_authorities', 'get_authority_excerpt']); }
  async run(ctx, C) {
    const out = []; let n = 0; const seen = new Set();
    for (const k of C.claims) {
      const r = mcpCall('search_authorities', { query: k.text, limit: 2, case_id: C.id }, ctx); if (r.error) continue;
      r.results.filter(x => x.relevance_score >= AUTH_THRESHOLD).forEach(x => {
        const ex = mcpCall('get_authority_excerpt', { authority_id: x.authority_id, passage_index: x.passage_index, case_id: C.id }, ctx); if (ex.error) return;
        const matched = uniq(tokens(k.text).filter(t => tokens(ex.excerpt).includes(t))).slice(0, 8);
        out.push({ id: 'AL-' + pad(++n, 3), claimId: k.id, authorityId: x.authority_id, passageIndex: x.passage_index, passage: ex.excerpt, score: x.relevance_score, matchedTerms: matched }); seen.add(x.authority_id);
      });
    }
    C.authorityLinks = out; if (out.length) audit(C, { actor: 'AI', agent: 'Legal Research Agent', event: 'AUTHORITY_RETRIEVED', description: `Retrieved ${out.length} passage(s) from ${seen.size} authority record(s) — retrieval signal only`, object: 'authorities' });
    return this.result({ links: out.length, authorities: seen.size }, { review: out.length > 0, warnings: AUTHORITIES.length ? [] : ['Your authority library is empty, so no authorities could be retrieved.'] });
  }
}
class CitationAuditAgent extends BaseAgent {
  constructor() { super('citation_audit_agent', 'Citation Audit Agent', 'Compare cited propositions with retrieved authority text and flag potential mismatches.', ['get_authority_excerpt']); }
  async run(ctx, C) {
    C.citations = auditCitations(C); C.citations.forEach(x => audit(C, { actor: 'AI', agent: 'Citation Audit Agent', event: 'CITATION_AUDITED', description: `Citation audited (${x.id}): ${x.result.replace(/_/g, ' ').toLowerCase()}`, object: x.id }));
    buildFindings(C);
    const issues = C.citations.filter(x => x.result !== 'POTENTIALLY_RELEVANT').length;
    return this.result({ citations: C.citations.length, needingReview: issues, findings: C.findings.length }, { review: issues > 0, status: issues ? 'findings' : 'completed' });
  }
}
class ReportAgent extends BaseAgent {
  constructor() { super('report_agent', 'Report Agent', 'Assemble report inputs and confirm coverage.', ['get_audit_history']); }
  async run(ctx, C) { const r = mcpCall('get_audit_history', { case_id: C.id }, ctx); if (r.error) throw new ServiceError(r.error.code, r.error.message); return this.result({ auditEvents: r.events.length, ready: true }); }
}
const PIPELINE = [new DocumentAgent(), new TranscriptAgent(), new ClaimAgent(), new EvidenceAgent(), new ConflictAgent(), new LegalResearchAgent(), new CitationAuditAgent(), new ReportAgent()];
const AGENT_META = Object.fromEntries(PIPELINE.map(a => [a.name, a]));
const runningAnalyses = new Set();
async function runAnalysis(userId, caseId, opts = {}) {
  const C = ownedCase(userId, caseId); if (runningAnalyses.has(C.id)) throw new ServiceError('ALREADY_RUNNING', 'Analysis is already running for this case.');
  if (C.status === 'ARCHIVED') throw new ServiceError('ARCHIVED', 'Archived cases are read-only.');
  if (!C.documents.length) throw new ServiceError('NO_MATERIAL', 'Add at least one document or transcript before analyzing.');
  useLibrary(userId); runningAnalyses.add(C.id); const pace = opts.paceMs == null ? 280 : opts.paceMs;
  const aid = nextId(C, 'analysis', 'AN-'); const prevStatus = C.status;
  refreshProvider(); C.analysis = { id: aid, status: 'running', startedAt: nowISO(), completedAt: null, provider: { ...PROVIDER }, stages: PIPELINE.map(a => ({ agent: a.name, label: a.label, status: 'pending' })) }; C.status = 'ANALYZING';
  audit(C, { actor: 'SYSTEM', event: 'ANALYSIS_STARTED', description: `Analysis ${aid} started (${PROVIDER.name})`, object: aid }); commit();
  const ctx = { userId, caseId: C.id, analysisId: aid, agent: null, aiCfg: opts.aiCfg || aiConfig() }; let failed = 0, degraded = 0;
  try {
    for (const agent of PIPELINE) {
      const st = C.analysis.stages.find(s => s.agent === agent.name); st.status = 'running'; ctx.agent = agent.name; commit(); if (pace) await sleep(pace);
      const run = { id: nextId(C, 'run', 'RUN-'), analysisId: aid, agent: agent.name, label: agent.label, status: 'running', inputSummary: `${C.documents.length} material item(s)`, outputSummary: '', startedAt: nowISO(), completedAt: null, durationMs: 0, error: null, warnings: [], requiresReview: false, tools: agent.tools };
      C.agentRuns.push(run); const t0 = now_ms(); const mark = C.toolCalls.length;
      try {
        const res = await agent.run(ctx, C); run.status = res.status; run.warnings = res.warnings; run.requiresReview = res.requires_review; run.outputSummary = Object.entries(res.data).map(([k, v]) => `${k}: ${v}`).join(' · ');
        st.status = res.status; if (res.status === 'degraded') degraded++;
      } catch (e) { failed++; run.status = 'failed'; st.status = 'failed'; run.error = e instanceof ServiceError ? e.message : 'The agent could not complete.'; audit(C, { actor: 'SYSTEM', event: 'AGENT_FAILED', description: `${agent.label} failed — other stages continued`, object: run.id }); }
      run.durationMs = Math.round(now_ms() - t0); run.completedAt = nowISO(); run.mcpCalls = C.toolCalls.slice(mark).filter(t => t.agent === agent.name).length; commit();
    }
    C.analysis.status = failed ? (failed === PIPELINE.length ? 'failed' : 'partial') : 'completed'; C.analysis.completedAt = nowISO(); C.lastAnalyzedAt = nowISO();
    C.status = C.findings.length ? (pendingCount(C) === 0 ? 'REVIEW_COMPLETE' : 'ACTIVE_REVIEW') : 'ACTIVE_REVIEW';
    audit(C, { actor: 'SYSTEM', event: 'ANALYSIS_COMPLETED', description: `Analysis ${aid} ${C.analysis.status}: ${C.claims.length} claims, ${C.evidence.length} evidence, ${C.conflicts.length} potential conflicts`, object: aid });
  } catch (e) { C.analysis.status = 'failed'; C.status = prevStatus === 'ANALYZING' ? 'DRAFT' : prevStatus; }
  finally { runningAnalyses.delete(C.id); commit(); }
  return C.analysis;
}
