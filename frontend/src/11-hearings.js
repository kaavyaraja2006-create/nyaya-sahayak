/* ===== 11 hearings: Case → Judge → Lawyer(s) → Stenographer → Hearing. Every call is authorised through the case policy in 05. ===== */
const HEARING_STATUS = { SCHEDULED: 'Scheduled', IN_PROGRESS: 'In progress', COMPLETED: 'Completed', ADJOURNED: 'Adjourned', CANCELLED: 'Cancelled' };
const HEARING_NEXT = { SCHEDULED: ['IN_PROGRESS', 'ADJOURNED', 'CANCELLED'], ADJOURNED: ['SCHEDULED', 'CANCELLED'], IN_PROGRESS: ['COMPLETED'], COMPLETED: [], CANCELLED: [] };
const DRAFT_MAX_CHARS = 1000000;
const vErr = (m, errors) => Object.assign(new ServiceError('VALIDATION', m), errors ? { errors } : {});
const hearingOf = (C, hid) => { const h = (C.hearings || []).find(x => x.id === hid); if (!h) throw new ServiceError('HEARING_NOT_FOUND', 'No hearing was found for the supplied hearing_id.'); return h; };
function parseWhen(v, required = true) {
  if (v == null || v === '') { if (required) throw vErr('Choose the hearing date and time.', { scheduledAt: 'Choose the hearing date and time.' }); return null; }
  const d = new Date(v); if (isNaN(d.getTime()) || d.getFullYear() < 2000 || d.getFullYear() > 2100) throw vErr('That date and time is not valid.', { scheduledAt: 'That date and time is not valid.' });
  return d.toISOString();
}
function activeHearingFor(userId) {
  for (const C of loadDB().cases) { const h = (C.hearings || []).find(x => x.status === 'IN_PROGRESS' && x.stenographerId === userId); if (h) return { C, hearing: h }; }
  return null;
}
function pickUsers(ids, role, label) {
  if (!Array.isArray(ids)) throw vErr(`Select ${label}.`); const out = uniq(ids.map(String));
  out.forEach(id => { const u = userById(id); if (!u || u.role !== role) throw vErr(`Each ${label.replace(/s$/, '')} must be a registered ${role.toLowerCase()} account.`); }); return out;
}
const HearingSvc = {
  /* readable by anyone with any access to the case (judge, lawyer, stenographer, creator) */
  list(userId, caseId) { return (ownedCase(userId, caseId, 'hearing').hearings || []).slice().sort((a, b) => (a.scheduledAt || '').localeCompare(b.scheduledAt || '')); },
  get(userId, caseId, hid) { return hearingOf(ownedCase(userId, caseId, 'hearing'), hid); },
  active(userId) { const a = activeHearingFor(userId); return a ? { caseId: a.C.id, hearingId: a.hearing.id } : null; },
  schedule(userId, caseId, o) {
    const C = managedCase(userId, caseId), me = userById(userId); if (C.status === 'ARCHIVED') throw new ServiceError('ARCHIVED', 'Archived cases are read-only.');
    const when = parseWhen(o.scheduledAt); const n = nextId(C, 'hearing', '', 2);
    const h = { id: `HR-${C.id.replace(/^NS-/, '')}-${n}`, caseId: C.id, number: +n, title: String(o.title || '').trim().slice(0, 120), judgeId: C.judgeId || null, lawyerIds: (C.lawyerIds || []).slice(), stenographerId: C.stenographerId || null, scheduledAt: when, status: 'SCHEDULED', isPublic: o.isPublic !== false, publicNote: String(o.publicNote || '').trim().slice(0, 200), startedAt: null, endedAt: null, endNote: '', transcriptDocId: null, createdBy: userId, createdAt: nowISO(), updatedAt: nowISO() };
    (C.hearings || (C.hearings = [])).push(h); audit(C, { actor: 'REVIEWER', actorId: userId, actorName: me.fullName, event: 'HEARING_SCHEDULED', description: `Hearing ${h.id} scheduled for ${when.slice(0, 16).replace('T', ' ')} UTC`, object: h.id }); commit(); return h;
  },
  update(userId, caseId, hid, o) {
    const C = managedCase(userId, caseId), h = hearingOf(C, hid); const open = ['SCHEDULED', 'ADJOURNED'].includes(h.status);
    if ('scheduledAt' in o) { if (!open) throw new ServiceError('BAD_STATE', 'Only a scheduled or adjourned hearing can be moved.'); h.scheduledAt = parseWhen(o.scheduledAt); }
    if ('title' in o) h.title = String(o.title || '').trim().slice(0, 120); if ('isPublic' in o) h.isPublic = !!o.isPublic; if ('publicNote' in o) h.publicNote = String(o.publicNote || '').trim().slice(0, 200);
    h.updatedAt = nowISO(); audit(C, { actor: 'REVIEWER', actorId: userId, actorName: userById(userId).fullName, event: 'HEARING_UPDATED', description: `Hearing ${h.id} updated`, object: h.id }); commit(); return h;
  },
  /* adjourn / cancel / put an adjourned hearing back on the list. Adjourning may name the next date, which creates the next hearing. */
  setStatus(userId, caseId, hid, to, o = {}) {
    const C = managedCase(userId, caseId), h = hearingOf(C, hid);
    if (!['SCHEDULED', 'ADJOURNED', 'CANCELLED'].includes(to) || !HEARING_NEXT[h.status].includes(to)) throw new ServiceError('BAD_STATE', `A ${HEARING_STATUS[h.status].toLowerCase()} hearing cannot be set to ${(HEARING_STATUS[to] || to).toLowerCase()}.`);
    const prev = h.status; let next = null; const when = to === 'SCHEDULED' ? parseWhen(o.scheduledAt) : null;
    if (to === 'ADJOURNED' && o.nextDate) next = HearingSvc.schedule(userId, caseId, { scheduledAt: o.nextDate, title: h.title, isPublic: h.isPublic, publicNote: 'Adjourned from ' + h.id });
    h.status = to; if (when) h.scheduledAt = when; if (o.note != null) h.endNote = String(o.note).trim().slice(0, 300); h.updatedAt = nowISO();
    audit(C, { actor: 'REVIEWER', actorId: userId, actorName: userById(userId).fullName, event: 'HEARING_STATUS_CHANGED', description: `Hearing ${h.id}: ${HEARING_STATUS[prev]} → ${HEARING_STATUS[to]}${next ? '; next hearing ' + next.id : ''}`, object: h.id, prev, next: to }); commit(); return { hearing: h, next };
  },
  /* The stenographer starts a hearing by selecting the case, the judge and the lawyer(s). The system then stamps
     Case ID + Hearing ID + Judge ID + Lawyer ID(s) + Stenographer ID onto the hearing; transcripts and documents added during it are tied to it. */
  start(userId, caseId, o) {
    const C = ownedCase(userId, caseId, 'hearing'), me = userById(userId);
    if (!me || me.role !== 'STENOGRAPHER' || C.stenographerId !== userId) throw new ServiceError(...E.DENIED);
    if (C.status === 'ARCHIVED') throw new ServiceError('ARCHIVED', 'Archived cases are read-only.');
    const busy = activeHearingFor(userId); if (busy) throw new ServiceError('ALREADY_ACTIVE', `You already have hearing ${busy.hearing.id} in progress on ${busy.C.id}. End it before starting another.`);
    if ((C.hearings || []).some(x => x.status === 'IN_PROGRESS')) throw new ServiceError('ALREADY_ACTIVE', 'Another hearing is already in progress for this case.');
    const errors = {}; const judge = userById(o.judgeId); if (!judge || judge.role !== 'JUDGE') errors.judgeId = 'Select the presiding judge.';
    else if (C.judgeId && C.judgeId !== judge.id) errors.judgeId = 'That judge is not assigned to this case. Change the case assignment first.';
    let lawyers = []; try { lawyers = pickUsers(o.lawyerIds || [], 'LAWYER', 'lawyers'); } catch (e) { errors.lawyerIds = e.message; } if (!errors.lawyerIds && !lawyers.length) errors.lawyerIds = 'Select at least one lawyer.';
    if (Object.keys(errors).length) throw vErr('Please correct the highlighted fields.', errors);
    let h; if (o.hearingId) { h = hearingOf(C, o.hearingId); if (h.status !== 'SCHEDULED') throw new ServiceError('BAD_STATE', 'Only a scheduled hearing can be started.'); }
    else { const n = nextId(C, 'hearing', '', 2); h = { id: `HR-${C.id.replace(/^NS-/, '')}-${n}`, caseId: C.id, number: +n, title: String(o.title || '').trim().slice(0, 120), scheduledAt: nowISO(), status: 'SCHEDULED', isPublic: true, publicNote: '', startedAt: null, endedAt: null, endNote: '', transcriptDocId: null, createdBy: userId, createdAt: nowISO() }; (C.hearings || (C.hearings = [])).push(h); }
    const addedLawyers = lawyers.filter(x => !(C.lawyerIds || []).includes(x)); if (!C.judgeId) C.judgeId = judge.id; C.lawyerIds = uniq((C.lawyerIds || []).concat(lawyers));
    Object.assign(h, { judgeId: judge.id, lawyerIds: lawyers, stenographerId: userId, status: 'IN_PROGRESS', startedAt: nowISO(), updatedAt: nowISO() });
    audit(C, { actor: 'REVIEWER', actorId: userId, actorName: me.fullName, event: 'HEARING_STARTED', description: `Hearing ${h.id} started. Judge ${judge.fullName}; ${lawyers.length} lawyer${lawyers.length === 1 ? '' : 's'}: ${lawyers.map(x => userById(x).fullName).join(', ')}.${addedLawyers.length ? ' Added to the case: ' + addedLawyers.map(x => userById(x).fullName).join(', ') + '.' : ''}`, object: h.id, meta: { caseId: C.id, hearingId: h.id, judgeId: judge.id, lawyerIds: lawyers, stenographerId: userId } });
    commit(); return h;
  },
  end(userId, caseId, hid, o = {}) {
    const C = ownedCase(userId, caseId, 'hearing'), h = hearingOf(C, hid); if (h.stenographerId !== userId && C.judgeId !== userId) throw new ServiceError(...E.DENIED);
    if (h.status !== 'IN_PROGRESS') throw new ServiceError('BAD_STATE', 'Only a hearing in progress can be ended.');
    h.status = 'COMPLETED'; h.endedAt = nowISO(); h.updatedAt = nowISO(); if (o.note) h.endNote = String(o.note).trim().slice(0, 300);
    audit(C, { actor: 'REVIEWER', actorId: userId, actorName: userById(userId).fullName, event: 'HEARING_ENDED', description: `Hearing ${h.id} ended`, object: h.id, prev: 'IN_PROGRESS', next: 'COMPLETED' }); commit(); return h;
  },
  /* who may type into / generate the transcript of a hearing */
  canWriteTranscript(userId, C, h) { return h.stenographerId === userId && ['IN_PROGRESS', 'COMPLETED'].includes(h.status) && C.status !== 'ARCHIVED'; },
  /* Turn the typed transcript into the hearing's transcript document (created the first time, revised afterwards). Returns the document. */
  generateTranscript(userId, caseId, hid, text) {
    const C = ownedCase(userId, caseId, 'hearing'), h = hearingOf(C, hid); if (!HearingSvc.canWriteTranscript(userId, C, h)) throw new ServiceError(...E.DENIED);
    const t = String(text || ''); if (t.trim().length < 10) throw vErr('Type or paste the transcript first.', { text: 'Type or paste the transcript first.' }); if (t.length > DRAFT_MAX_CHARS) throw new ServiceError('FILE_TOO_LARGE', 'The transcript is too long.');
    const date = (h.startedAt || h.scheduledAt || nowISO()).slice(0, 10); const old = h.transcriptDocId && C.documents.find(d => d.id === h.transcriptDocId);
    if (old) { const st = parseTranscript(t); old.pages = statementsToPages(st); old.statementCount = st.length; old.status = st.length ? 'Indexed' : 'Needs Review'; old.pageCount = old.pages.length; old.size = t.length; old.entities = entitiesOf(old); old.revisedAt = nowISO(); old.revision = (old.revision || 1) + 1;
      audit(C, { actor: 'REVIEWER', actorId: userId, actorName: userById(userId).fullName, event: 'TRANSCRIPT_UPDATED', description: `Transcript ${old.id} regenerated for hearing ${h.id}. Re-run analysis to refresh findings.`, object: old.id }); commit(); return old; }
    const d = DocSvc.add(userId, caseId, { kind: 'transcript', filename: `Hearing ${h.number} transcript.txt`, text: t, size: t.length, hearingId: h.id, hearingDate: date, hearingNumber: String(h.number) });
    h.transcriptDocId = d.id; h.updatedAt = nowISO(); commit(); return d;
  },
};
