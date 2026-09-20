'use strict';
/* What each kind of caller is allowed to see of a case, and of a person.
   The engine decides WHO may open a case (caseAccess); this file decides WHAT they receive:
     full    → the complete case (judge, lawyers, workspace creator)
     hearing → case header, hearings, transcripts and document metadata only (stenographer)
     public  → only what a case manager explicitly marked public (no sign-in) */
const clone = o => JSON.parse(JSON.stringify(o));
const EMPTY = ['claims', 'evidence', 'links', 'relationships', 'conflicts', 'authorityLinks', 'citations', 'findings', 'reviews', 'audit', 'agentRuns', 'toolCalls', 'reports'];
const HEARING_LABEL = { SCHEDULED: 'Scheduled', IN_PROGRESS: 'In progress', COMPLETED: 'Completed', ADJOURNED: 'Adjourned', CANCELLED: 'Cancelled' };

function makeViews(host, cfg) {
  const N = host.N; const U = id => host.DB.users.find(u => u.id === id) || null;
  const isAdmin = u => !!u && cfg.adminEmails.includes(String(u.email || '').toLowerCase());
  /* the signed-in user's own account (includes contact details and lawyer profile) */
  const pub = u => ({ id: u.id, fullName: u.fullName, email: u.email, phone: u.phone, role: u.role, organization: u.organization, registrationNumber: u.registrationNumber, experienceYears: u.experienceYears, specialization: u.specialization, createdAt: u.createdAt, verified: !!u.verified, mobileVerified: !!u.mobileVerified, isAdmin: isAdmin(u), profile: u.role === 'LAWYER' ? (u.profile || {}) : undefined });
  /* another person on the same case: name and role only (lawyers also show their enrolment number, which is a public register entry) */
  const person = u => u ? ({ id: u.id, name: u.fullName, role: u.role, verified: !!u.verified, enrollmentNumber: u.role === 'LAWYER' ? u.registrationNumber : undefined }) : null;
  const people = C => ({ judge: person(U(C.judgeId)), lawyers: (C.lawyerIds || []).map(id => person(U(id))).filter(Boolean), stenographer: person(U(C.stenographerId)), creator: (() => { const c = U(C.userId); return c ? { id: c.id, name: c.fullName, role: c.role } : null; })() });

  function snapshot(user, C) {
    const access = N.caseAccess(user, C); if (!access) return null; let s;
    if (access === 'full') s = clone(C);
    else {
      s = { id: C.id, userId: C.userId, name: C.name, number: C.number, type: C.type, jurisdiction: C.jurisdiction, court: C.court, description: '', status: C.status, synthetic: false, createdAt: C.createdAt, updatedAt: C.updatedAt, lastAnalyzedAt: null, counters: {}, analysis: null,
        judgeId: C.judgeId, lawyerIds: clone(C.lawyerIds || []), stenographerId: C.stenographerId, hearings: clone(C.hearings || []), public: clone(C.public || {}),
        documents: C.documents.map(d => d.kind === 'transcript' ? clone(d) : { ...clone({ ...d, pages: [] }), entities: { people: [], locations: [], pii: 0 }, extractNote: '' }) };
      EMPTY.forEach(k => { s[k] = []; });
    }
    const manage = N.canManageCase(user, C), court = ['STENOGRAPHER', 'JUDGE'].includes(user.role);
    s.access = access; s.people = people(C);
    s.can = { manage, assignCourt: manage && court, startHearing: user.role === 'STENOGRAPHER' && C.stenographerId === user.id, delete: manage && C.userId === user.id, full: access === 'full' };
    return s;
  }
  function summary(user, C) {
    const s = snapshot(user, C); if (!s) return null;
    return { id: s.id, name: s.name, number: s.number, type: s.type, jurisdiction: s.jurisdiction, court: s.court, description: s.description, status: s.status, access: s.access, can: s.can, people: s.people, hearings: s.hearings.length,
      documents: s.documents.filter(d => d.kind === 'document').length, transcripts: s.documents.filter(d => d.kind === 'transcript').length, claims: s.claims.length, pendingReviews: s.findings.filter(f => N.findingStatus(s, f) === 'PENDING').length, lastAnalyzedAt: s.lastAnalyzedAt, createdAt: s.createdAt, updatedAt: s.updatedAt };
  }
  const hearingPublic = h => ({ hearingId: h.id, number: h.number, title: h.title || '', scheduledAt: h.scheduledAt, status: h.status, statusLabel: HEARING_LABEL[h.status] || h.status, note: h.publicNote || '', startedAt: h.startedAt || null, endedAt: h.endedAt || null });
  function publicStatus(C, upcoming, live) { if (C.status === 'ARCHIVED') return 'Closed'; if (live) return 'Hearing in progress'; return upcoming ? 'Pending — next hearing scheduled' : 'Pending'; }
  /* No sign-in. Returns null (→ 404) for a case that does not exist AND for one that has not been made public: the two are indistinguishable. */
  function publicCase(id, now = Date.now()) {
    const C = host.DB.cases.find(c => c.id === id); if (!C || !C.public || !C.public.enabled) return null;
    const all = (C.hearings || []).filter(h => h.isPublic).map(hearingPublic);
    const isUp = h => h.status === 'IN_PROGRESS' || (h.status === 'SCHEDULED' && new Date(h.scheduledAt).getTime() >= now - 3600000);
    const upcoming = all.filter(isUp).sort((a, b) => a.scheduledAt.localeCompare(b.scheduledAt));
    const history = all.filter(h => !isUp(h)).sort((a, b) => b.scheduledAt.localeCompare(a.scheduledAt)).map(h => h.status === 'SCHEDULED' ? { ...h, statusLabel: 'Scheduled (date passed, not yet updated)' } : h);
    const live = upcoming.find(h => h.status === 'IN_PROGRESS');
    return { caseId: C.id, title: C.public.title || `Case ${C.id}`, caseNumber: C.number || '', caseType: C.type, court: C.court || '', jurisdiction: C.jurisdiction || '', summary: C.public.summary || '', status: publicStatus(C, upcoming.length > 0, !!live), registeredOn: String(C.createdAt).slice(0, 10), nextHearing: upcoming[0] || null, upcoming, history, counts: { total: all.length, upcoming: upcoming.length, held: all.filter(h => h.status === 'COMPLETED').length }, asOf: new Date(now).toISOString(), notice: 'Only information marked public by the court or case owner is shown. Transcripts, documents, audit logs and the people assigned to the case are never shown here.' };
  }
  return { pub, person, people, snapshot, summary, publicCase, publicStatus, isAdmin, hearingPublic, HEARING_LABEL };
}
module.exports = { makeViews, HEARING_LABEL };
