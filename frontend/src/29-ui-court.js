/* ===== 29 ui court: role-aware navigation, court desk, people & assignment, hearings, public tracking switch, transcript workspace ===== */
Object.assign(ICON_PATHS, { gavel: '<path d="m14 13-8.4 8.4a2 2 0 0 1-2.8-2.8L11.2 10.2M16 16l6-6M8 8l6-6M9 7l8 8M21 11l-8-8"/>' });

/* ---- what the signed-in user may do on a case (the server sends these; the standalone build derives them) ---- */
const accessOf = C => C.access || caseAccess(UI.user, C);
function canOf(C) {
  if (C.can) return C.can; const u = UI.user, mg = canManageCase(u, C);
  return { manage: mg, assignCourt: mg && (u.role === 'STENOGRAPHER' || u.role === 'JUDGE'), startHearing: u.role === 'STENOGRAPHER' && C.stenographerId === u.id, delete: mg && C.userId === u.id, full: caseAccess(u, C) === 'full' };
}
function peopleOf(C) {
  if (C.people) return C.people;
  const P = id => { const x = id && loadDB().users.find(u => u.id === id); return x ? { id: x.id, name: x.fullName, role: x.role, verified: !!x.verified, enrollmentNumber: x.role === 'LAWYER' ? x.registrationNumber : undefined } : null; };
  return { judge: P(C.judgeId), lawyers: (C.lawyerIds || []).map(P).filter(Boolean), stenographer: P(C.stenographerId) };
}
function currentCaseAny() { try { const u = currentUser(); const id = UI.R && UI.R.parts[0] === 'cases' && UI.R.parts[1] !== 'new' ? UI.R.parts[1] : null; return id && u ? CaseSvc.getAny(u.id, id) : null; } catch (e) { return null; } }
function withCaseAny(id, fn) { try { const u = currentUser(); if (!u) throw new ServiceError('UNAUTHENTICATED', 'Sign in to continue.'); return fn(CaseSvc.getAny(u.id, id), u); } catch (e) { return errView(e); } }

const HSTATUS = { SCHEDULED: ['info', 'cal', 'Scheduled'], IN_PROGRESS: ['warn', 'mic', 'In progress'], COMPLETED: ['ok', 'check', 'Completed'], ADJOURNED: ['idle', 'clock', 'Adjourned'], CANCELLED: ['idle', 'x', 'Cancelled'] };
const hBadge = s => badge(s, null, HSTATUS);
const toLocalInput = iso => { const d = new Date(iso); return isNaN(d) ? '' : `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const fromLocalInput = v => { const d = new Date(v); return v && !isNaN(d) ? d.toISOString() : ''; };
const tomorrow10 = () => { const d = new Date(Date.now() + 86400000); d.setHours(10, 0, 0, 0); return toLocalInput(d.toISOString()); };
const fld2 = (id, label, inner, hint = '') => `<div class="field" data-f="${id}"><label for="f-${id}">${label}</label>${inner}${hint ? `<span class="hint">${hint}</span>` : ''}<span class="err hide" id="e-${id}"></span></div>`;
function failWith(e, f) { if (e && e.errors && f) showFieldErrors(f, e.errors); else toast((e && e.message) || 'That could not be completed. Try again.', 'bad'); }
const sbtn = (label, o = {}) => `<button type="submit" class="btn ${o.cls || ''}">${o.icon ? icon(o.icon, 14) : ''}${esc(label)}</button>`;
const isOnServer = () => !!Api.on;

/* ---- role-aware sidebar ---- */
function roleNavFull(u, g) {
  if (u.role === 'STENOGRAPHER') return `<div class="navgroup">Court</div>${navItem('gavel', 'Court desk', '#/court', '', g('court') || g('dashboard'))}${navItem('plus', 'Open a case', '#/cases/new', '', UI.R.parts[1] === 'new')}<div class="navgroup">Account</div>${navItem('sliders', 'Settings', '#/settings', '', g('settings'))}`;
  if (u.role === 'CLIENT') return `<div class="navgroup">Find a lawyer</div>${navItem('home', 'Dashboard', '#/dashboard', '', g('dashboard'))}${navItem('search', 'Find a lawyer', '#/find-lawyer', '', false)}${navItem('msg', 'My requests', '#/requests', '', g('requests'))}${navItem('search', 'Track a case', '#/track', '', false)}<div class="navgroup">Account</div>${navItem('sliders', 'Settings', '#/settings', '', g('settings'))}`;
  return null;
}
function roleNavExtra(u, g) {
  let h = '';
  if (u.role === 'JUDGE' || u.role === 'LAWYER') h += `<div class="navgroup">Court</div>${navItem('gavel', 'Court desk', '#/court', '', g('court'))}`;
  if (u.role === 'LAWYER') h += `${navItem('msg', 'Client requests', '#/requests', '', g('requests'))}${navItem('user', 'My lawyer profile', '#/lawyer-profile', '', g('lawyer-profile'))}`;
  if (u.isAdmin) h += `<div class="navgroup">Administration</div>${navItem('shield', 'Verify lawyers', '#/verification', '', g('verification'))}`;
  return h;
}
const blockedView = (why) => ({ title: 'Not available', crumbs: [['Not available']], html: `<div class="page narrow">${empty({ icon: 'lock', title: 'Not available for your account', text: why || 'Your account type does not include this part of the workspace.', action: `<div style="margin-top:10px">${linkBtn('Go to my workspace', '#/dashboard', { cls: 'primary' })}</div>` })}</div>` });

/* ---- people, hearings and public tracking on a case ---- */
function personLine(p) { return p ? `<span class="pl">${icon('user', 13)}<b>${esc(p.name)}</b>${p.verified ? ` <span class="badge ok">${icon('check', 11)}Verified</span>` : ''}${p.enrollmentNumber ? ` <span class="mono faint">${esc(p.enrollmentNumber)}</span>` : ''}</span>` : '<span class="faint">Not assigned</span>'; }
function peoplePanel(C) {
  const P = peopleOf(C), can = canOf(C), u = UI.user; const mine = C.judgeId === u.id || C.stenographerId === u.id || (C.lawyerIds || []).includes(u.id); const ro = C.status === 'ARCHIVED';
  return `<section class="panel"><div class="ph"><h2>People on this case</h2><div class="row">${can.manage && !ro ? btn('Manage', `data-act="people-edit" data-case="${C.id}"`, { cls: 'sm', icon: 'users' }) : ''}${mine ? btn('Leave case', `data-act="case-leave" data-case="${C.id}"`, { cls: 'sm ghost' }) : ''}</div></div><div class="pb"><dl class="kv" style="grid-template-columns:110px 1fr"><dt>Judge</dt><dd>${personLine(P.judge)}</dd><dt>${(P.lawyers || []).length === 1 ? 'Lawyer' : 'Lawyers'}</dt><dd>${(P.lawyers || []).length ? (P.lawyers).map(personLine).join('<br>') : '<span class="faint">Not assigned</span>'}</dd><dt>Stenographer</dt><dd>${personLine(P.stenographer)}</dd></dl><p class="faint" style="font-size:12.5px;margin-top:10px">Only these people can open this case. Contact details are never shown here.</p></div></section>`;
}
const hearingLink = (C, h, acc) => { if (acc === 'hearing') return caseHref(C, 'hearing?h=' + h.id); const d = C.documents.find(x => x.id === h.transcriptDocId) || C.documents.find(x => x.kind === 'transcript' && x.hearingId === h.id); return caseHref(C, 'hearing' + (d ? '?doc=' + d.id : '')); };
function hearingsPanel(C) {
  const can = canOf(C), u = UI.user, ro = C.status === 'ARCHIVED', acc = accessOf(C); const hs = (C.hearings || []).slice().sort((a, b) => String(b.scheduledAt).localeCompare(String(a.scheduledAt)));
  const canStart = can.startHearing && !ro; const busy = hs.some(h => h.status === 'IN_PROGRESS');
  const row = h => { const mineLive = h.status === 'IN_PROGRESS' && (h.stenographerId === u.id || C.judgeId === u.id);
    const acts = [];
    if (canStart && h.status === 'SCHEDULED' && !busy) acts.push(btn('Start hearing', `data-act="hearing-start" data-case="${C.id}" data-h="${h.id}"`, { cls: 'sm primary', icon: 'play' }));
    if (mineLive) acts.push(btn('End hearing', `data-act="hearing-end" data-case="${C.id}" data-h="${h.id}"`, { cls: 'sm' }));
    if (can.manage && !ro && !['COMPLETED', 'IN_PROGRESS'].includes(h.status) || can.manage && !ro && h.status === 'IN_PROGRESS') acts.push(btn('Edit', `data-act="hearing-edit" data-case="${C.id}" data-h="${h.id}"`, { cls: 'sm ghost' }));
    if (['IN_PROGRESS', 'COMPLETED'].includes(h.status) || acc === 'hearing') acts.push(linkBtn(acc === 'hearing' ? 'Transcript' : 'Transcript', hearingLink(C, h, acc), { cls: 'sm', icon: 'mic' }));
    return `<li class="li hrow"><span class="grow" style="min-width:0"><b>${esc(h.title || 'Hearing ' + h.number)}</b> <span class="mono faint" style="font-size:11.5px">${esc(h.id)}</span><br><span class="muted" style="font-size:12.5px">${esc(fmtDT(h.scheduledAt))}${h.startedAt ? ' · started ' + esc(fmtClock(h.startedAt).slice(0, 5)) : ''}${h.endedAt ? ' · ended ' + esc(fmtClock(h.endedAt).slice(0, 5)) : ''}${h.isPublic ? '' : ' · <span title="Not shown on the public case page">not public</span>'}</span></span>${hBadge(h.status)}<span class="row" style="gap:6px;flex-wrap:wrap;justify-content:flex-end">${acts.join('')}</span></li>`; };
  return `<section class="panel"><div class="ph"><h2>Hearings</h2><div class="row">${canStart && !busy ? btn('Start a hearing', `data-act="hearing-start" data-case="${C.id}"`, { cls: 'sm primary', icon: 'play' }) : ''}${can.manage && !ro ? btn('Schedule', `data-act="hearing-new" data-case="${C.id}"`, { cls: 'sm', icon: 'plus' }) : ''}</div></div>${hs.length ? `<ul class="list" style="list-style:none;padding:0;margin:0">${hs.map(row).join('')}</ul>` : `<div class="pb muted">No hearings yet.${can.manage ? ' Schedule one, or start one directly when the hearing begins.' : ''}</div>`}</section>`;
}
function publicPanel(C) {
  const can = canOf(C); if (!can.manage) return ''; const p = C.public || {}; const url = `#/track/${C.id}`; const ro = C.status === 'ARCHIVED';
  return `<section class="panel"><div class="ph"><h2>Public case tracking</h2>${p.enabled ? `<span class="badge ok">${icon('check', 12)}On</span>` : '<span class="badge idle">Off</span>'}</div><div class="pb"><form data-form="pubtrack" data-case="${C.id}" novalidate class="col" style="gap:12px"><label class="switchrow"><input type="checkbox" name="enabled" ${p.enabled ? 'checked' : ''} ${ro ? 'disabled' : ''}><span><b>Let anyone with the Case ID see the hearing dates and status</b><br><span class="faint" style="font-size:12.5px">Shows only the title, court, status and the hearings marked public. Never documents, transcripts, people, claims or the audit trail.</span></span></label>
    ${fld2('ptitle', 'Public title', `<input id="f-ptitle" name="title" maxlength="120" value="${esc(p.title || '')}" placeholder="e.g. Kumar v. State" ${ro ? 'disabled' : ''}>`)}${fld2('psummary', 'Public summary', `<textarea id="f-psummary" name="summary" maxlength="400" style="min-height:64px" placeholder="One or two neutral sentences." ${ro ? 'disabled' : ''}>${esc(p.summary || '')}</textarea>`)}
    <div class="row wrap between"><span class="faint" style="font-size:12.5px">${p.enabled ? `Public page: <a href="${url}" target="_blank" rel="noopener">${esc(location.href.split('#')[0])}${url}</a> ${copyBtn(C.id, 'Copy case ID')}` : 'Turn tracking on to get a public page for this Case ID.'}</span>${ro ? '' : sbtn('Save', { cls: 'sm primary' })}</div></form></div></section>`;
}
const courtSection = C => `<div class="grid2 courtgrid" style="margin-bottom:${canOf(C).manage ? 16 : 22}px">${peoplePanel(C)}${hearingsPanel(C)}</div>${canOf(C).manage ? `<div style="margin-bottom:22px">${publicPanel(C)}</div>` : ''}`;

FORM.pubtrack = async f => { const d = { enabled: !!f.enabled.checked, title: f.title.value, summary: f.summary.value }; try { await Data.setPublic(f.dataset.case, d); toast(d.enabled ? 'Public tracking is on.' : 'Public tracking is off.'); render(); } catch (e) { failWith(e, f); } };
ACT['case-leave'] = el => confirmDialog({ title: 'Leave this case?', text: 'You will lose access to it. Other people assigned to the case are not affected.', label: 'Leave case', danger: true, onConfirm: async () => { try { await Data.leaveCase(el.dataset.case); toast('You left the case.'); go(UI.user.role === 'STENOGRAPHER' ? '#/court' : '#/cases'); } catch (e) { toast(e.message, 'bad'); } } });

/* ---- schedule / edit hearing ---- */
ACT['hearing-new'] = el => modal({ title: 'Schedule a hearing', body: `<form data-form="hschedule" data-case="${el.dataset.case}" novalidate class="col" style="gap:12px">${fld2('scheduledAt', 'Date and time *', `<input id="f-scheduledAt" name="scheduledAt" type="datetime-local" value="${tomorrow10()}" required>`)}${fld2('title', 'Title', `<input id="f-title" name="title" maxlength="120" placeholder="e.g. Arguments">`)}<label class="switchrow"><input type="checkbox" name="isPublic" checked><span>Show this hearing on the public case page (if tracking is on)</span></label>${fld2('publicNote', 'Public note', `<input id="f-publicNote" name="publicNote" maxlength="200" placeholder="Optional, shown publicly">`)}<div class="row" style="justify-content:flex-end">${btn('Cancel', 'data-act="close"')}${sbtn('Schedule', { cls: 'primary' })}</div></form>` });
FORM.hschedule = async f => { try { await Data.scheduleHearing(f.dataset.case, { scheduledAt: fromLocalInput(f.scheduledAt.value), title: f.title.value, isPublic: f.isPublic.checked, publicNote: f.publicNote.value }); closeOverlay(); toast('Hearing scheduled.'); render(); } catch (e) { failWith(e, f); } };
ACT['hearing-edit'] = el => {
  const C = currentCaseAny(); const h = C && (C.hearings || []).find(x => x.id === el.dataset.h); if (!h) return; const open = ['SCHEDULED', 'ADJOURNED'].includes(h.status);
  const opts = ['SCHEDULED', 'ADJOURNED', 'CANCELLED'].filter(s => s === h.status || (HEARING_NEXT[h.status] || []).includes(s));
  modal({ title: `Edit ${h.id}`, body: `<form data-form="hedit" data-case="${C.id}" data-h="${h.id}" data-status="${h.status}" novalidate class="col" style="gap:12px">${fld2('title', 'Title', `<input id="f-title" name="title" maxlength="120" value="${esc(h.title || '')}">`)}${open ? fld2('scheduledAt', 'Date and time', `<input id="f-scheduledAt" name="scheduledAt" type="datetime-local" value="${toLocalInput(h.scheduledAt)}">`) : ''}
    <label class="switchrow"><input type="checkbox" name="isPublic" ${h.isPublic ? 'checked' : ''}><span>Show on the public case page</span></label>${fld2('publicNote', 'Public note', `<input id="f-publicNote" name="publicNote" maxlength="200" value="${esc(h.publicNote || '')}">`)}
    ${opts.length > 1 ? `${fld2('status', 'Status', `<select id="f-status" name="status" data-change="hstatus">${opts.map(s => `<option value="${s}" ${s === h.status ? 'selected' : ''}>${HSTATUS[s][2]}</option>`).join('')}</select>`)}<div id="nextdate" class="hide">${fld2('nextDate', 'Next hearing date (optional)', `<input id="f-nextDate" name="nextDate" type="datetime-local">`, 'Creates the next hearing automatically.')}</div>` : ''}
    <div class="row" style="justify-content:flex-end">${btn('Cancel', 'data-act="close"')}${sbtn('Save changes', { cls: 'primary' })}</div></form>` });
};
INPUT.hstatus = t => { const n = $('#nextdate'); if (n) n.classList.toggle('hide', t.value !== 'ADJOURNED'); };
FORM.hedit = async f => {
  const cid = f.dataset.case, hid = f.dataset.h; const o = { title: f.title.value, isPublic: f.isPublic.checked, publicNote: f.publicNote.value }; if (f.scheduledAt) o.scheduledAt = fromLocalInput(f.scheduledAt.value);
  try { await Data.updateHearing(cid, hid, o); const to = f.status ? f.status.value : f.dataset.status; if (to !== f.dataset.status) await Data.setHearingStatus(cid, hid, to, { nextDate: f.nextDate && f.nextDate.value ? fromLocalInput(f.nextDate.value) : undefined, scheduledAt: to === 'SCHEDULED' ? (f.scheduledAt ? fromLocalInput(f.scheduledAt.value) : undefined) : undefined }); closeOverlay(); toast('Hearing updated.'); render(); } catch (e) { failWith(e, f); }
};

/* ---- people & assignment ---- */
const pickList = (name, list, chosen) => list.length ? `<div class="pickbox">${list.map(p => `<label class="switchrow"><input type="checkbox" name="${name}" value="${esc(p.id)}" ${chosen.includes(p.id) ? 'checked' : ''}><span><b>${esc(p.name)}</b>${p.verified ? ` <span class="badge ok">${icon('check', 11)}Verified</span>` : ''} <span class="mono faint">${esc(p.enrollmentNumber || '')}</span>${p.city ? ` <span class="faint">· ${esc(p.city)}</span>` : ''}</span></label>`).join('')}</div>` : '<div class="faint">Nobody has registered with this role yet.</div>';
ACT['people-edit'] = async el => {
  const C = currentCaseAny(); if (!C) return; const can = canOf(C); el.disabled = true;
  try {
    const [judges, lawyers, stenos] = await Promise.all([can.assignCourt ? Data.directory('judges') : [], Data.directory('lawyers'), can.assignCourt ? Data.directory('stenographers') : []]); el.disabled = false;
    const sel = (name, list, cur) => `<select name="${name}" id="f-${name}"><option value="">— Not assigned —</option>${list.map(p => `<option value="${esc(p.id)}" ${p.id === cur ? 'selected' : ''}>${esc(p.name)}${p.verified ? ' (verified)' : ''}</option>`).join('')}</select>`;
    modal({ wide: true, title: 'People on this case', body: `<form data-form="assign" data-case="${C.id}" data-court="${can.assignCourt ? 1 : 0}" novalidate class="col" style="gap:14px">${can.assignCourt ? `${fld2('judgeId', 'Judge', sel('judgeId', judges, C.judgeId))}${fld2('stenographerId', 'Court stenographer', sel('stenographerId', stenos, C.stenographerId))}` : '<div class="note">' + icon('info', 14) + '<span>Judges and stenographers are assigned by court staff. You can add or remove lawyers.</span></div>'}
      <div class="field" data-f="lawyerIds"><label>Lawyers (up to 12)</label>${pickList('lawyerIds', lawyers, C.lawyerIds || [])}<span class="err hide" id="e-lawyerIds"></span></div><div class="row" style="justify-content:flex-end">${btn('Cancel', 'data-act="close"')}${sbtn('Save', { cls: 'primary' })}</div></form>` });
  } catch (e) { el.disabled = false; toast(e.message, 'bad'); }
};
FORM.assign = async f => { const o = { lawyerIds: $$('input[name=lawyerIds]:checked', f).map(x => x.value) }; if (f.dataset.court === '1') { o.judgeId = f.judgeId.value || null; o.stenographerId = f.stenographerId.value || null; } try { await Data.assign(f.dataset.case, o); closeOverlay(); toast('People updated.'); render(); } catch (e) { failWith(e, f); } };

/* ---- start / end a hearing (stenographer) ---- */
ACT['hearing-start'] = async el => {
  const C = currentCaseAny() || (() => { try { return CaseSvc.getAny(UI.user.id, el.dataset.case); } catch (e) { return null; } })(); if (!C) return; el.disabled = true;
  try {
    const [judges, lawyers] = await Promise.all([Data.directory('judges'), Data.directory('lawyers')]); el.disabled = false; const hid = el.dataset.h || '';
    const sched = (C.hearings || []).filter(h => h.status === 'SCHEDULED');
    modal({ wide: true, title: 'Start a hearing', body: `<form data-form="hstart" data-case="${C.id}" novalidate class="col" style="gap:14px"><div class="note">${icon('info', 14)}<span>Everything you record during this hearing is tied to <b>${esc(C.name)}</b> (<span class="mono">${esc(C.id)}</span>), the hearing, the judge and the lawyers you select here.</span></div>
      ${fld2('hearingId', 'Hearing', `<select id="f-hearingId" name="hearingId"><option value="">New hearing, starting now</option>${sched.map(h => `<option value="${h.id}" ${h.id === hid ? 'selected' : ''}>${esc(h.title || 'Hearing ' + h.number)} · ${esc(fmtDT(h.scheduledAt))}</option>`).join('')}</select>`)}
      ${fld2('title', 'Title (optional)', `<input id="f-title" name="title" maxlength="120" placeholder="e.g. Cross-examination of PW-3">`)}
      ${fld2('judgeId', 'Judge *', `<select name="judgeId" id="f-judgeId"><option value="">Select the judge</option>${judges.map(p => `<option value="${esc(p.id)}" ${p.id === C.judgeId ? 'selected' : ''}>${esc(p.name)}${p.verified ? ' (verified)' : ''}</option>`).join('')}</select>`, judges.length ? '' : 'No judge has registered yet.')}
      <div class="field" data-f="lawyerIds"><label>Lawyer(s) appearing *</label>${pickList('lawyerIds', lawyers, C.lawyerIds || [])}<span class="err hide" id="e-lawyerIds"></span></div>
      <div class="row" style="justify-content:flex-end">${btn('Cancel', 'data-act="close"')}${sbtn('Start hearing', { cls: 'primary', icon: 'play' })}</div></form>` });
  } catch (e) { el.disabled = false; toast(e.message, 'bad'); }
};
FORM.hstart = async f => {
  const b = f.querySelector('button[type=submit]'); b.disabled = true;
  try { const h = await Data.startHearing(f.dataset.case, { hearingId: f.hearingId.value || undefined, title: f.title.value, judgeId: f.judgeId.value, lawyerIds: $$('input[name=lawyerIds]:checked', f).map(x => x.value) }); closeOverlay(); toast('Hearing started. Recording is tied to this case, judge and lawyers.'); go(`#/cases/${f.dataset.case}/hearing?h=${h.id}`); }
  catch (e) { b.disabled = false; failWith(e, f); }
};
ACT['hearing-end'] = el => confirmDialog({ title: 'End this hearing?', text: 'The transcript stays editable after the hearing ends. You can start another hearing afterwards.', label: 'End hearing', onConfirm: async () => { try { await Data.endHearing(el.dataset.case, el.dataset.h, ''); toast('Hearing ended.'); render(); } catch (e) { toast(e.message, 'bad'); } } });

/* ---- court desk ---- */
function CourtDeskView() {
  const u = UI.user; const cases = CaseSvc.listAny(u.id).sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt))); const steno = u.role === 'STENOGRAPHER';
  const act = steno ? HearingSvc.active(u.id) : null; const now = Date.now();
  const all = []; cases.forEach(C => (C.hearings || []).forEach(h => all.push({ C, h }))); const upcoming = all.filter(x => ['SCHEDULED', 'IN_PROGRESS'].includes(x.h.status)).sort((a, b) => String(a.h.scheduledAt).localeCompare(String(b.h.scheduledAt))).slice(0, 8);
  const banner = act ? (() => { const C = cases.find(c => c.id === act.caseId), h = C && (C.hearings || []).find(x => x.id === act.hearingId); return C && h ? `<section class="panel livebar"><div class="pb row wrap between"><div><span class="badge warn">${icon('mic', 12)}Hearing in progress</span> <b style="margin-left:6px">${esc(h.title || 'Hearing ' + h.number)}</b> <span class="muted">· ${esc(C.name)} · <span class="mono">${esc(h.id)}</span></span></div><div class="row">${linkBtn('Open transcript workspace', caseHref(C, 'hearing?h=' + h.id), { cls: 'primary', icon: 'mic' })}${btn('End hearing', `data-act="hearing-end" data-case="${C.id}" data-h="${h.id}"`)}</div></div></section>` : ''; })() : '';
  const li = C => { const P = peopleOf(C); const next = (C.hearings || []).filter(h => h.status === 'SCHEDULED').sort((a, b) => String(a.scheduledAt).localeCompare(String(b.scheduledAt)))[0]; const live = (C.hearings || []).find(h => h.status === 'IN_PROGRESS');
    return `<li class="li"><span class="grow" style="min-width:0"><a href="${caseHref(C)}" class="serif" style="font-weight:600;color:var(--text)">${esc(C.name)}</a><br><span class="mono faint" style="font-size:11.5px">${esc(C.id)}${C.type ? ' · ' + esc(C.type) : ''}${C.court ? ' · ' + esc(C.court) : ''}</span><br><span class="muted" style="font-size:12.5px">${P.judge ? 'Judge ' + esc(P.judge.name) : 'No judge yet'} · ${plural((P.lawyers || []).length, 'lawyer')}${next ? ' · next: ' + esc(fmtDT(next.scheduledAt)) : ''}</span></span>${live ? hBadge('IN_PROGRESS') : ''}<span class="row" style="gap:6px">${canOf(C).startHearing && !act && C.status !== 'ARCHIVED' ? btn('Start hearing', `data-act="hearing-start" data-case="${C.id}"`, { cls: 'sm primary', icon: 'play' }) : ''}${linkBtn('Open', caseHref(C), { cls: 'sm' })}</span></li>`; };
  return { title: 'Court desk', workspace: 'Court desk', crumbs: [['Court desk']], html: `<div class="page"><div class="pagehead"><div><p class="lbl" style="margin-bottom:6px">Court desk</p><h1>${steno ? 'Hearings you record' : 'Hearings on your cases'}</h1><p class="sub">${steno ? 'Open a case, choose the judge and lawyers, then start recording. Your transcript is saved as you type.' : 'Every hearing on the cases you are assigned to, with its status.'}</p></div>${linkBtn('Open a case', '#/cases/new', { cls: 'primary', icon: 'plus' })}</div>${banner}
    <div class="split"><section class="panel"><div class="ph"><h2>${steno ? 'Your cases' : 'Cases'}</h2><span class="faint" style="font-size:12px">${cases.length}</span></div>${cases.length ? `<ul class="list" style="list-style:none;padding:0;margin:0">${cases.map(li).join('')}</ul>` : `<div class="pb">${empty({ icon: 'folder', title: 'No cases yet', text: steno ? 'Open a case file to record its hearings. You can assign the judge and lawyers afterwards.' : 'You will see a case here once you are assigned to it.', action: `<div style="margin-top:10px">${linkBtn('Open a case', '#/cases/new', { cls: 'primary', icon: 'plus' })}</div>` })}</div>`}</section>
    <aside class="col"><section class="panel"><div class="ph"><h2>Upcoming and live</h2></div>${upcoming.length ? `<ul class="list" style="list-style:none;padding:0;margin:0">${upcoming.map(({ C, h }) => `<li class="li"><a class="grow" href="${caseHref(C, steno ? 'hearing?h=' + h.id : '')}" style="min-width:0;color:var(--text)"><b>${esc(h.title || 'Hearing ' + h.number)}</b><br><span class="faint" style="font-size:12px">${esc(C.name)} · ${esc(fmtDT(h.scheduledAt))}</span></a>${hBadge(h.status)}</li>`).join('')}</ul>` : '<div class="pb muted">No upcoming hearings.</div>'}</section></aside></div></div>` };
}

/* ---- hearing-scope pages (stenographer): overview, documents, restricted pages ---- */
function HearingOverviewView(C) {
  return { title: 'Overview', workspace: 'Court desk', crumbs: crumbsFor(C, ['Overview']), html: `<div class="page"><div class="pagehead"><div><p class="lbl" style="margin-bottom:6px">Case</p><h1>${esc(C.name)}</h1><p class="sub"><span class="mono">Case ID ${esc(C.id)}</span>${C.type ? ' · ' + esc(C.type) : ''}${C.court ? ' · ' + esc(C.court) : ''}${C.number ? ' · ' + esc(C.number) : ''}</p></div><div class="row wrap">${linkBtn('Transcript workspace', caseHref(C, 'hearing'), { cls: 'primary', icon: 'mic' })}${linkBtn('Upload documents', caseHref(C, 'documents'), { icon: 'upload' })}</div></div>
    <div class="note" style="margin-bottom:18px">${icon('lock', 14)}<span>Your role can record hearings, save transcripts and add documents to this case. Analysis results, claims, the audit trail and reports are visible only to the judge and the lawyers.</span></div>${courtSection(C)}</div>` };
}
function HearingDocsView(C) {
  const docs = C.documents.filter(d => d.kind === 'document'); const ro = C.status === 'ARCHIVED';
  return { title: 'Documents', crumbs: crumbsFor(C, ['Documents']), mount: paintQueue, html: `<div class="page narrow"><div class="pagehead"><div><p class="lbl" style="margin-bottom:6px">Case documents</p><h1>Add documents</h1><p class="sub">You can add documents to the case. Only the judge and the lawyers can read them.</p></div></div>${ro ? '' : uploadPanel(C)}<section class="panel"><div class="ph"><h2>Uploaded documents</h2><span class="faint" style="font-size:12px">${docs.length}</span></div>${docs.length ? `<ul class="list" style="list-style:none;padding:0;margin:0">${docs.map(d => `<li class="li"><span class="grow trunc"><b>${esc(d.filename)}</b><br><span class="faint" style="font-size:12px">${esc(fmtDT(d.uploadedAt))}${d.hearingId ? ' · ' + esc(d.hearingId) : ''}</span></span><span class="badge idle">${icon('lock', 11)}Contents hidden</span></li>`).join('')}</ul>` : '<div class="pb muted">No documents yet.</div>'}</section></div>` };
}
const restrictedView = C => ({ title: 'Not available', crumbs: crumbsFor(C, ['Not available']), html: `<div class="page narrow">${empty({ icon: 'lock', title: 'This page is not available to your role', text: 'As the court stenographer you can record hearings, save transcripts and add documents. Analysis results are for the judge and the lawyers.', action: `<div class="row" style="margin-top:10px">${linkBtn('Transcript workspace', caseHref(C, 'hearing'), { cls: 'primary', icon: 'mic' })}${linkBtn('Case overview', caseHref(C))}</div>` })}</div>` });

/* ---- transcript workspace: large typing area, upload, generated output ---- */
UI.tw = { caseId: null, hid: null, rev: 0, text: '', saved: '', timer: null, saving: false, conflict: false, savedAt: null, fail: 0, doc: null };
const twDirty = () => UI.tw.hid && UI.tw.text !== UI.tw.saved;
window.addEventListener('beforeunload', e => { if (twDirty()) { e.preventDefault(); e.returnValue = ''; } });
function twStatus(msg, kind = 'idle') { const el = $('#twstatus'); if (!el) return; el.className = 'badge ' + kind; el.innerHTML = `${icon(kind === 'ok' ? 'check' : kind === 'bad' ? 'warn' : kind === 'info' ? 'refresh' : 'circle', 12, kind === 'info' ? 'spin' : '')}${esc(msg)}`; }
function twCount() { const el = $('#twcount'); if (el) { const t = UI.tw.text; const lines = t ? t.split('\n').filter(x => x.trim()).length : 0; el.textContent = `${t.length.toLocaleString()} characters · ${plural(lines, 'line')}`; } }
function twSchedule(ms = 900) { clearTimeout(UI.tw.timer); UI.tw.timer = setTimeout(() => twSave(), ms); }
async function twSave(force) {
  const t = UI.tw; if (!t.hid) return true; while (t.saving) await sleep(80); if (!force && !twDirty()) return true; if (t.conflict) return false;
  const text = t.text, at = { c: t.caseId, h: t.hid }; t.saving = true; twStatus('Saving…', 'info');
  try { const r = await Data.saveDraft(at.c, at.h, text, t.rev); t.rev = r.rev; t.saved = text; t.savedAt = r.savedAt || new Date().toISOString(); t.fail = 0; t.saving = false; twStatus('Saved ' + fmtClock(t.savedAt), 'ok'); if (twDirty()) twSchedule(300); return true; }
  catch (e) { t.saving = false; if (e && e.code === 'DRAFT_CONFLICT') { t.conflict = true; twConflictBox(); twStatus('Not saved — changed elsewhere', 'bad'); return false; } t.fail++; twStatus('Not saved — retrying', 'bad'); twSchedule(Math.min(15000, 1500 * t.fail)); return false; }
}
function twConflictBox() { const el = $('#twconflict'); if (!el) return; el.innerHTML = UI.tw.conflict ? `<div class="note warn" style="margin-bottom:10px">${icon('alert', 14)}<span>This transcript was changed in another tab or device. Your text has <b>not</b> been overwritten. ${btn('Keep my version', 'data-act="tw-keep"', { cls: 'sm' })} ${btn('Load the latest version', 'data-act="tw-reload"', { cls: 'sm' })}</span></div>` : ''; }
ACT['tw-keep'] = async () => { const t = UI.tw; try { const d = await Data.getDraft(t.caseId, t.hid); t.rev = d.rev; t.conflict = false; twConflictBox(); await twSave(true); } catch (e) { toast(e.message, 'bad'); } };
ACT['tw-reload'] = async () => { const t = UI.tw; try { const d = await Data.getDraft(t.caseId, t.hid); t.rev = d.rev; t.text = t.saved = d.text || ''; t.conflict = false; const ta = $('#twin'); if (ta) ta.value = t.text; twConflictBox(); twCount(); twStatus('Loaded the latest version', 'ok'); } catch (e) { toast(e.message, 'bad'); } };
INPUT.twin = t => { const s = UI.tw; s.text = t.value; twCount(); if (!s.conflict) { twStatus('Unsaved changes', 'idle'); twSchedule(); } };
ACT['tw-save'] = async () => { const ok = await twSave(true); if (ok) toast('Draft saved.'); };
const twDocs = (C, h) => C.documents.filter(d => d.kind === 'transcript' && d.hearingId === h.id).sort((a, b) => (a.id === h.transcriptDocId ? -1 : b.id === h.transcriptDocId ? 1 : 0));
const twStmts = d => { const o = []; (d.pages || []).forEach(pg => (pg.paras || []).forEach(p => o.push(p))); return o; };
function paintTwOut() {
  const el = $('#twout'); if (!el) return; const C = currentCaseAny(); const t = UI.tw; const h = C && (C.hearings || []).find(x => x.id === t.hid); if (!h) return;
  const docs = twDocs(C, h); if (!docs.length) { el.innerHTML = `<div class="tw-empty">${icon('mic', 22)}<b>Nothing generated yet</b><span class="muted">Type the transcript on the left and choose “Generate transcript”, or upload a transcript file below. The formatted transcript appears here.</span></div>`; $('#twtabs').innerHTML = ''; $('#twmeta').textContent = ''; return; }
  const d = docs.find(x => x.id === t.doc) || docs[0]; t.doc = d.id; const st = twStmts(d);
  $('#twtabs').innerHTML = docs.length > 1 ? docs.map(x => `<button class="chip" data-act="tw-doc" data-id="${x.id}" aria-pressed="${x.id === d.id}">${esc(docName(x))}</button>`).join('') : '';
  $('#twmeta').textContent = `${plural(d.statementCount != null ? d.statementCount : st.length, 'statement')}${d.revision ? ' · revision ' + d.revision : ''}`;
  el.innerHTML = st.length ? st.map(s => `<div class="stmt ${s.qkind === 'QUESTION' ? 'q' : ''}"><div class="mono faint" style="font-size:12px">${esc(s.ts || '')}</div><div><div class="who">${esc(s.speaker || '')}</div><div class="body">${esc(s.text)}</div></div></div>`).join('') : `<div class="tw-empty">${icon('warn', 22)}<b>No speaker turns were recognised</b><span class="muted">The text was saved, but it could not be split into statements. Use one line per turn, like <span class="mono">10:06:18 JUDGE: Please state your name.</span></span></div>`;
}
ACT['tw-doc'] = el => { UI.tw.doc = el.dataset.id; paintTwOut(); };
ACT['tw-download'] = () => { const C = currentCaseAny(), t = UI.tw; const h = C && (C.hearings || []).find(x => x.id === t.hid); const d = h && (twDocs(C, h).find(x => x.id === t.doc) || twDocs(C, h)[0]); if (!d) return toast('Nothing to download yet.', 'warn'); saveFile(docName(d) + '.txt', twStmts(d).map(s => `${s.ts ? s.ts + ' ' : ''}${s.speaker}: ${s.text}`).join('\n'), 'text/plain'); };
ACT['tw-generate'] = async el => {
  const t = UI.tw; if (t.text.trim().length < 10) return toast('Type the transcript first.', 'warn'); el.disabled = true; twStatus('Generating…', 'info');
  try { if (twDirty()) { const ok = await twSave(true); if (!ok) { toast('Your draft could not be saved, so the transcript was not generated.', 'warn'); return; } } const d = await Data.generateTranscript(t.caseId, t.hid, t.text); t.doc = d.id; toast(d.statementCount ? `Transcript generated: ${plural(d.statementCount, 'statement')}.` : 'Transcript saved, but no speaker turns were recognised.', d.statementCount ? 'ok' : 'warn'); twStatus('Saved ' + fmtClock(t.savedAt || new Date().toISOString()), 'ok'); paintTwOut(); const o = $('#twout'); if (o) o.scrollTop = o.scrollHeight; }
  catch (e) { toast(e.message || 'The transcript could not be generated.', 'bad'); twStatus('Generate failed', 'bad'); } finally { el.disabled = false; }
};
async function twUpload(files) { const t = UI.tw; const C = currentCaseAny(); const h = C && (C.hearings || []).find(x => x.id === t.hid); if (!h || !files || !files.length) return; await twSave(true); await ingest(t.caseId, files, { kind: 'transcript', hearingId: h.id, hearingDate: String(h.startedAt || h.scheduledAt).slice(0, 10), hearingNumber: String(h.number) }); }
INPUT.twfile = t => { const fl = Array.from(t.files); t.value = ''; twUpload(fl); };
INPUT.twdrop = t => twUpload(Array.from(t.files));
function twHearing(C, q) { const u = UI.user, hs = C.hearings || []; return hs.find(h => h.id === q.h) || hs.find(h => h.status === 'IN_PROGRESS' && h.stenographerId === u.id) || hs.filter(h => h.stenographerId === u.id && h.status === 'COMPLETED').sort((a, b) => String(b.startedAt).localeCompare(String(a.startedAt)))[0] || null; }
function TranscriptWorkspace(C, q) {
  const u = UI.user, h = twHearing(C, q), can = canOf(C); const head = `<div class="pagehead"><div><p class="lbl" style="margin-bottom:6px">Court transcript</p><h1>Hearing transcript</h1><p class="sub">Type or paste the proceedings on the left. Your text is saved as you type. Generate the transcript to see it formatted on the right.</p></div></div>`;
  const chips = (C.hearings || []).length > 1 ? `<div class="chips" style="margin-bottom:12px">${(C.hearings || []).slice().sort((a, b) => String(b.scheduledAt).localeCompare(String(a.scheduledAt))).map(x => `<a class="chip" aria-pressed="${h && x.id === h.id}" href="${caseHref(C, 'hearing?h=' + x.id)}">${esc(x.title || 'Hearing ' + x.number)} · ${esc(HSTATUS[x.status][2])}</a>`).join('')}</div>` : '';
  if (!h) return { title: 'Hearing transcript', crumbs: crumbsFor(C, ['Hearings']), html: `<div class="page narrow">${head}${empty({ icon: 'mic', title: 'No hearing to record', text: can.startHearing ? 'Start a hearing to open the typing area. Choose the judge and lawyers, and everything you record is tied to that hearing.' : 'A hearing can be started by the stenographer assigned to this case.', action: can.startHearing ? `<div style="margin-top:10px">${btn('Start a hearing', `data-act="hearing-start" data-case="${C.id}"`, { cls: 'primary', icon: 'play' })}</div>` : '' })}${courtSection(C)}</div>` };
  const write = h.stenographerId === u.id && HearingSvc.canWriteTranscript(u.id, C, h) && C.status !== 'ARCHIVED';
  const live = h.status === 'IN_PROGRESS';
  const info = `<div class="row wrap between" style="margin-bottom:12px"><div class="row wrap" style="gap:10px"><b class="serif" style="font-size:17px">${esc(h.title || 'Hearing ' + h.number)}</b><span class="mono faint">${esc(h.id)}</span>${hBadge(h.status)}<span class="muted" style="font-size:12.5px">${h.startedAt ? 'Started ' + esc(fmtDT(h.startedAt)) : esc(fmtDT(h.scheduledAt))}${h.endedAt ? ' · ended ' + esc(fmtClock(h.endedAt).slice(0, 5)) : ''}</span></div><div class="row">${live && h.stenographerId === u.id ? btn('End hearing', `data-act="hearing-end" data-case="${C.id}" data-h="${h.id}"`, { cls: 'sm' }) : ''}${can.startHearing && !live && h.status === 'SCHEDULED' ? btn('Start hearing', `data-act="hearing-start" data-case="${C.id}" data-h="${h.id}"`, { cls: 'sm primary', icon: 'play' }) : ''}</div></div>`;
  const input = `<section class="panel tw-panel"><div class="ph"><h2>${icon('pen', 14)} Type the transcript</h2><span id="twstatus" class="badge idle">${icon('circle', 12)}${write ? 'Ready' : 'Read only'}</span></div><div class="pb tw-body"><div id="twconflict"></div>${write ? '' : `<div class="note" style="margin-bottom:10px">${icon('info', 14)}<span>The typing area is open to the assigned stenographer while the hearing is in progress or after it has ended.</span></div>`}
    <textarea id="twin" class="tw-in" data-in="twin" spellcheck="true" aria-label="Transcript text" ${write ? '' : 'disabled'} placeholder="10:06:18 JUDGE: Please state your name for the record.&#10;10:06:25 WITNESS: Ravi Kumar.&#10;10:06:31 JUDGE: Proceed."></textarea>
    <div class="row wrap between tw-foot"><span id="twcount" class="faint mono" style="font-size:12px"></span><div class="row">${write ? btn('Save now', 'data-act="tw-save"', { cls: 'sm' }) + btn('Generate transcript', 'data-act="tw-generate"', { cls: 'primary', icon: 'spark' }) : ''}</div></div><p class="faint" style="font-size:12.5px;margin-top:8px">One line per speaker turn: <span class="mono">HH:MM:SS SPEAKER: text</span>. Regenerating updates the same transcript; earlier text is never lost.</p></div></section>`;
  const output = `<section class="panel tw-panel"><div class="ph"><h2>${icon('file', 14)} Generated transcript</h2><div class="row"><span id="twmeta" class="faint mono" style="font-size:12px"></span>${btn('Download .txt', 'data-act="tw-download"', { cls: 'sm', icon: 'download' })}</div></div><div class="pb tw-body"><div id="twtabs" class="chips" style="margin-bottom:8px"></div><div id="twout" class="tw-out" tabindex="0" aria-label="Generated transcript" aria-live="polite"></div></div></section>`;
  const upload = write || h.status !== 'CANCELLED' && can.startHearing ? `<section class="panel" style="margin-top:18px"><div class="ph"><h2>${icon('upload', 14)} Upload a transcript file instead</h2></div><div class="pb"><div class="drop" data-drop="twdrop" style="padding:22px">${icon('upload', 22)}<b>Drop a transcript file here</b>${btn('Browse files', 'data-act="pick-files" data-target="twfile"', { cls: 'primary sm' })}<span class="mono faint" style="font-size:12px">PDF · DOCX · TXT</span><input id="twfile" type="file" accept=".pdf,.docx,.txt,.md" class="hide" data-change="twfile"></div><p class="faint" style="font-size:12.5px;margin-top:10px">Uploaded files are added to this hearing’s transcripts and appear on the right.</p><div id="uploadq" class="col" style="gap:8px;margin-top:12px"></div></div></section>` : '';
  return { title: 'Hearing transcript', crumbs: crumbsFor(C, ['Hearings']), noPadding: false, mount() { twInit(C, h, write); paintQueue(); paintTwOut(); }, html: `<div class="page wide">${head}${chips}${info}<div class="tw">${input}${output}</div>${upload}</div>` };
}
async function twInit(C, h, write) {
  const t = UI.tw; const same = t.caseId === C.id && t.hid === h.id; if (!same) { clearTimeout(t.timer); Object.assign(t, { caseId: C.id, hid: h.id, rev: 0, text: '', saved: '', conflict: false, saving: false, fail: 0, doc: h.transcriptDocId || null, savedAt: null }); }
  const ta = $('#twin'); if (!ta) return; if (!write) { try { const d = await Data.getDraft(C.id, h.id).catch(() => null); if (d) ta.value = d.text || ''; } catch (e) {} twCount(); return; }
  if (same && twDirty()) { ta.value = t.text; twStatus('Unsaved changes', 'idle'); twSchedule(300); twCount(); return; }
  twStatus('Loading…', 'info');
  try { const d = await Data.getDraft(C.id, h.id); if (UI.tw.hid !== h.id) return; t.rev = d.rev || 0; t.text = t.saved = d.text || ''; ta.value = t.text; twCount(); twStatus(d.rev ? 'Saved ' + (d.updatedAt ? fmtClock(d.updatedAt) : '') : 'Ready', d.rev ? 'ok' : 'idle'); ta.focus(); }
  catch (e) { twStatus('Could not load the draft', 'bad'); toast(e.message || 'The draft could not be loaded.', 'bad'); }
}
