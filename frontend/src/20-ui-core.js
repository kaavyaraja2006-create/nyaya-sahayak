/* ===== 20 ui core: helpers, theme, overlays, router, event delegation ===== */
Object.assign(ICON_PATHS, {
  left: '<path d="m15 18-6-6 6-6"/>', arrow: '<path d="M5 12h14M12 5l7 7-7 7"/>', alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
  okc: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>', monitor: '<rect width="20" height="14" x="2" y="3" rx="2"/><path d="M8 21h8M12 17v4"/>',
  db: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5M3 12a9 3 0 0 0 18 0"/>', play: '<path d="M6 3l14 9-14 9z"/>',
  sort: '<path d="m21 16-4 4-4-4M17 20V4M3 8l4-4 4 4M7 4v16"/>', pen: '<path d="M21.17 6.81a1 1 0 0 0-3.99-3.99L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.35a.5.5 0 0 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5z"/>',
  msg: '<path d="M22 17a2 2 0 0 1-2 2H6.83a2 2 0 0 0-1.41.59l-2.2 2.2A.71.71 0 0 1 2 21.29V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z"/>', lock: '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  pin: '<path d="M20 10c0 5-5.5 10.2-7.4 11.8a1 1 0 0 1-1.2 0C9.5 20.2 4 15 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>', term: '<path d="m4 17 6-6-6-6M12 19h8"/>',
  cpu: '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2"/>', fit: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
  cal: '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>', pilcrow: '<path d="M13 4v16M17 4v16M19 4H9.5a4.5 4.5 0 0 0 0 9H13"/>', up: '<path d="m18 15-6-6-6 6"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 3.13a4 4 0 0 1 0 7.75M22 21v-2a4 4 0 0 0-3-3.87"/><circle cx="9" cy="7" r="4"/>', ban: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
});
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const UI = { user: null, R: null, opened: new Set(), prevPath: '', live: null, nextHash: null, docQ: '', cloud: {} };
const ACT = {}, FORM = {}, INPUT = {};

/* ---- theme / density / motion ---- */
function inNight(p) { const n = new Date(), m = n.getHours() * 60 + n.getMinutes(); const f = p.nightFrom.split(':'), t = p.nightTo.split(':'); const a = +f[0] * 60 + +f[1], b = +t[0] * 60 + +t[1]; return a <= b ? (m >= a && m < b) : (m >= a || m < b); }
function resolvedTheme() { const p = prefs(); if (p.autoNight && inNight(p)) return 'night'; if (p.theme === 'system') return (window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark'; return p.theme; }
function applyPrefs() { const p = prefs(), r = document.documentElement; r.dataset.theme = resolvedTheme(); r.dataset.density = p.density; r.dataset.motion = p.reduceMotion ? 'reduce' : 'full'; }

/* ---- small html helpers ---- */
const docName = d => d ? d.filename.replace(/\.[a-z0-9]+$/i, '') : 'Unknown source';
const plural = (n, a, b) => `${n} ${n === 1 ? a : (b || a + 's')}`;
const caseHref = (C, sub = '') => `#/cases/${C.id}${sub ? '/' + sub : ''}`;
const go = h => { if (location.hash === h) render(); else location.hash = h; };
const CASE_STATUS = { DRAFT: ['idle', 'circle', 'Draft'], ANALYZING: ['info', 'refresh', 'Analysis running'], ACTIVE_REVIEW: ['warn', 'eye', 'Review required'], REVIEW_COMPLETE: ['ok', 'check', 'Completed'], ARCHIVED: ['idle', 'folder', 'Archived'] };
const REVIEW_BADGE = { NEEDS_REVIEW: ['warn', 'warn', 'Needs review'], PENDING: ['warn', 'warn', 'Needs review'], REVIEWED: ['ok', 'check', 'Reviewed'], ACCEPTED: ['ok', 'check', 'Accepted'], REJECTED: ['idle', 'x', 'Rejected'], MODIFIED: ['ok', 'pen', 'Modified'], NEEDS_VERIFICATION: ['warn', 'eye', 'Needs verification'], CONFLICT: ['bad', 'warn', 'Potential conflict'], PROCESSING: ['info', 'refresh', 'Processing'], UNRESOLVED: ['idle', 'circle', 'Unresolved'], UNCERTAIN: ['warn', 'help', 'Uncertain'], INDEXED: ['ok', 'check', 'Indexed'], UPLOADING: ['info', 'upload', 'Uploading'], 'NEEDS REVIEW': ['warn', 'warn', 'Needs review'], ERROR: ['bad', 'warn', 'Error'] };
function badge(key, label, map = REVIEW_BADGE) { const b = map[key] || ['idle', 'circle', label || key]; return `<span class="badge ${b[0]}">${icon(b[1], 12, key === 'PROCESSING' || key === 'ANALYZING' ? 'spin' : '')}${esc(label || b[2])}</span>`; }
const statusBadge = s => badge(s, null, CASE_STATUS);
const idTag = (id, href) => href ? `<a class="tag" href="${href}">${esc(id)}</a>` : `<span class="tag">${esc(id)}</span>`;
function sig(v, kind = '') { v = clamp(Math.round(v || 0), 0, 100); return `<div class="sigbar ${kind}" role="img" aria-label="${v} out of 100"><div class="bar"><i style="width:${v}%"></i></div><b>${v}</b></div>`; }
function empty(o) { return `<div class="empty" role="status"><div class="em-ic">${icon(o.icon || 'layers', 20)}</div><h3>${esc(o.title)}</h3><p>${esc(o.text || '')}</p>${o.action || ''}</div>`; }
const btn = (label, attrs = '', o = {}) => `<button type="button" class="btn ${o.cls || ''}" ${attrs}>${o.icon ? icon(o.icon, 14) : ''}${esc(label)}</button>`;
const linkBtn = (label, href, o = {}) => `<a class="btn ${o.cls || ''}" href="${href}">${o.icon ? icon(o.icon, 14) : ''}${esc(label)}</a>`;
const copyBtn = (text, label = 'Copy') => `<button type="button" class="iconbtn" style="width:24px;height:24px" data-act="copy" data-text="${esc(text)}" aria-label="${esc(label)} ${esc(text)}" title="${esc(label)}">${icon('copy', 13)}</button>`;
const aiTag = (kind, id) => `<button type="button" class="aitag" data-act="ai-info" data-kind="${kind}" data-id="${esc(id)}">${icon('spark', 12)}AI-assisted finding</button>`;
const SIG_NOTE = `<div class="note">${icon('info', 14)}<span>Prototype assessment signals — not legal conclusions. ${esc(SIGNAL_DISCLAIMER)}</span></div>`;
const HUMAN_NOTE = `<span class="badge warn">${icon('eye', 12)}Human verification required</span>`;

/* ---- derived case data (never stored) ---- */
function derive(C) {
  const docs = new Map(C.documents.map(d => [d.id, d])), ev = new Map(C.evidence.map(e => [e.id, e])), claims = new Map(C.claims.map(c => [c.id, c]));
  const rels = new Map(), conf = new Map(), cites = new Map(), auth = new Map();
  C.relationships.forEach(r => { const e = ev.get(r.evidenceId); if (!e) return; if (!rels.has(r.claimId)) rels.set(r.claimId, []); rels.get(r.claimId).push({ rel: r, ev: e }); });
  C.conflicts.forEach(k => k.claims.forEach(id => { if (!conf.has(id)) conf.set(id, []); conf.get(id).push(k); }));
  C.citations.forEach(x => { if (x.claimId) { if (!cites.has(x.claimId)) cites.set(x.claimId, []); cites.get(x.claimId).push(x); } });
  C.authorityLinks.forEach(l => { if (!auth.has(l.claimId)) auth.set(l.claimId, []); auth.get(l.claimId).push(l); });
  const X = { docs, ev, claims, rels, conf, cites, auth };
  X.doc = id => docs.get(id); X.claim = id => claims.get(id);
  X.info = c => {
    const r = rels.get(c.id) || [], strong = r.filter(x => x.rel.relationship !== 'MENTIONS'); const k = conf.get(c.id) || [];
    const status = claimStatus(C, c);
    return { status, rels: r, strong, evCount: r.length, conflicts: k, inConflict: k.length > 0, uncertain: c.uncertainty >= 60, unresolved: !strong.length && c.type !== 'LEGAL_PROPOSITION', reviewed: status === 'REVIEWED' || status === 'REJECTED' || status === 'MODIFIED' };
  };
  X.src = c => { const d = docs.get(c.sourceDocId); if (!d) return 'Unknown source'; return d.kind === 'transcript' ? `${docName(d)} · ${c.timestamp || 'Page ' + c.page}` : `${docName(d)} · Page ${c.page} · Paragraph ${c.para}`; };
  X.href = c => { const d = docs.get(c.sourceDocId); if (!d) return caseHref(C, 'documents'); return d.kind === 'transcript' ? `#/cases/${C.id}/hearing?doc=${d.id}&claim=${c.id}` : `#/cases/${C.id}/documents/${d.id}?claim=${c.id}`; };
  X.para = c => { const d = docs.get(c.sourceDocId); const pg = d && d.pages[c.page - 1]; return pg ? pg.paras[c.para - 1] : null; };
  X.findingOf = id => C.findings.find(f => f.id === id);
  return X;
}
function withCase(id, fn) { try { const u = currentUser(); if (!u) throw new ServiceError('UNAUTHENTICATED', 'Sign in to continue.'); return fn(CaseSvc.get(u.id, id), u); } catch (e) { return errView(e); } }
function errView(e) {
  const code = e && e.code; const msg = code === 'CASE_NOT_FOUND' || code === 'PERMISSION_DENIED' ? 'This case could not be found in your workspace.' : 'We couldn’t retrieve this right now.';
  return { title: 'Case could not be loaded', crumbs: [['Cases', '#/cases']], html: `<div class="page narrow">${empty({ icon: 'warn', title: 'Case could not be loaded', text: msg, action: `<div class="row" style="margin-top:10px">${btn('Try again', 'data-act="reload"', { icon: 'refresh' })}${linkBtn('Return to cases', '#/cases', { cls: 'primary' })}</div>` })}</div>` };
}

/* ---- toasts ---- */
function toast(msg, kind = 'ok') { const t = document.createElement('div'); t.className = 'toast ' + kind; t.setAttribute('role', kind === 'bad' ? 'alert' : 'status'); t.innerHTML = `${icon(kind === 'ok' ? 'okc' : kind === 'bad' ? 'alert' : 'info', 18)}<span>${esc(msg)}</span>`; $('#toasts').appendChild(t); setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .25s'; setTimeout(() => t.remove(), 260); }, kind === 'bad' ? 6000 : 3600); }

/* ---- overlays ---- */
let lastFocus = null;
function openOverlay(inner, cls = '') {
  lastFocus = document.activeElement; const o = $('#overlay'); o.innerHTML = `<div class="scrim ${cls}" data-act="scrim">${inner}</div>`;
  const f = $('[autofocus]', o) || $('input,textarea,select,button,a[href]', $('.modal,.drawer,.pal', o)); if (f) setTimeout(() => f.focus(), 30);
}
function closeOverlay() { const o = $('#overlay'); if (!o.innerHTML) return; o.innerHTML = ''; UI.onClose && UI.onClose(); UI.onClose = null; if (lastFocus && document.contains(lastFocus)) lastFocus.focus(); }
function modal(o) { openOverlay(`<div class="modal ${o.wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(o.title)}"><div class="mh"><h2>${esc(o.title)}</h2><button class="iconbtn" data-act="close" aria-label="Close">${icon('x', 16)}</button></div><div class="mb">${o.body}</div>${o.foot ? `<div class="mf">${o.foot}</div>` : ''}</div>`); }
function drawer(o) { openOverlay(`<aside class="drawer" role="dialog" aria-modal="true" aria-label="${esc(o.title)}"><div class="mh"><h2 style="font-size:15px;font-weight:640">${esc(o.title)}</h2><button class="iconbtn" data-act="close" aria-label="Close">${icon('x', 16)}</button></div><div class="mb">${o.body}</div></aside>`); }
function confirmDialog(o) { UI.confirmCb = o.onConfirm; modal({ title: o.title, body: `<p>${o.text}</p>`, foot: `${btn('Cancel', 'data-act="close"')}${btn(o.label || 'Confirm', 'data-act="confirm"', { cls: o.danger ? 'danger' : 'primary' })}` }); }
ACT.close = () => closeOverlay();
ACT.scrim = (el, e) => { if (e.target === el) closeOverlay(); };
ACT.confirm = () => { const cb = UI.confirmCb; UI.confirmCb = null; closeOverlay(); cb && cb(); };
ACT.reload = () => render();
ACT.copy = el => { const t = el.dataset.text; const done = () => toast('Copied ' + t); if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t).then(done, () => toast('Copy is not available in this view.', 'warn')); else toast('Copy is not available in this view.', 'warn'); };

/* ---- AI-assisted finding explainer ---- */
ACT['ai-info'] = el => {
  const kind = el.dataset.kind, id = el.dataset.id; const C = currentCaseSafe(); if (!C) return; const X = derive(C); let obj, src = '—', loc = '—', gen = '—', agent = '—', status = 'Needs review', rel = '';
  if (kind === 'claim') { obj = X.claim(id); if (!obj) return; src = docName(X.doc(obj.sourceDocId)); loc = X.src(obj); gen = obj.generatedAt; agent = obj.agent; status = REVIEW_BADGE[claimStatus(C, obj)][2]; rel = `${X.info(obj).evCount} linked evidence item(s)`; }
  else if (kind === 'conflict') { obj = C.conflicts.find(k => k.id === id); if (!obj) return; const f = C.findings.find(x => x.conflictId === id); src = obj.supportingSources.map(s => docName(X.doc(s))).join(', '); loc = obj.comparison; gen = f ? f.createdAt : C.lastAnalyzedAt; agent = 'conflict_agent'; status = f ? REVIEW_BADGE[findingStatus(C, f)][2] : 'Needs review'; rel = 'Claim-to-claim comparison'; }
  else if (kind === 'evidence') { obj = X.ev.get(id); if (!obj) return; src = docName(X.doc(obj.sourceDocId)); loc = `Page ${obj.page}${obj.para ? ' · Paragraph ' + obj.para : ''}`; gen = obj.generatedAt; agent = obj.agent; rel = `${C.relationships.filter(r => r.evidenceId === id).length} claim link(s)`; }
  else if (kind === 'citation') { obj = C.citations.find(k => k.id === id); if (!obj) return; src = docName(X.doc(obj.docId)); loc = `Page ${obj.page} · Paragraph ${obj.para}`; gen = C.lastAnalyzedAt; agent = 'citation_audit_agent'; rel = 'Citation compared with retrieved authority text'; }
  else { obj = C.findings.find(f => f.id === id); if (!obj) return; src = 'See linked claims'; loc = obj.claimIds.join(', '); gen = obj.createdAt; agent = obj.agent; status = REVIEW_BADGE[findingStatus(C, obj)][2]; rel = obj.title; }
  drawer({ title: 'AI-assisted finding', body: `<p>This finding was generated using automated document analysis (${esc(PROVIDER.name)}${PROVIDER.llm ? '' : ' — a deterministic rules engine; no language model was used'}).</p>
    <dl class="kv" style="margin:18px 0"><dt>Object</dt><dd class="mono">${esc(id)}</dd><dt>Linked source</dt><dd>${esc(src)}</dd><dt>Source location</dt><dd>${esc(loc)}</dd><dt>Relationship</dt><dd>${esc(rel)}</dd><dt>Generated by</dt><dd class="mono">${esc(agent)}</dd><dt>Generated at</dt><dd class="mono">${esc(fmtDT(gen))}</dd><dt>Review status</dt><dd>${esc(status)}</dd></dl>
    <div class="note warn">${icon('alert', 14)}<span>This finding has not been independently verified. Human review required.</span></div>` });
};
function currentCaseSafe() { try { const u = currentUser(); const id = UI.R && UI.R.parts[0] === 'cases' && UI.R.parts[1] !== 'new' ? UI.R.parts[1] : null; return id && u ? CaseSvc.getAny(u.id, id) : null; } catch (e) { return null; } }

/* ---- downloads ---- */
async function saveFile(filename, data, mime) {
  let dl = null; try { dl = window.claude && window.claude.use ? await window.claude.use('downloads') : null; } catch (e) { dl = null; }
  if (dl) { try { await dl.save({ filename, data }); toast(`${filename} ready`); } catch (e) { if (e && e.code === 'declined') return; toast('The file could not be saved.', 'bad'); } return; }
  if (window.claude) { toast('Downloads are unavailable in this view.', 'warn'); return; }
  const blob = new Blob([data], { type: mime }); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = filename; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000); toast(`${filename} download started`);
}

/* ---- router ---- */
function parseHash() { const h = location.hash.replace(/^#/, '') || '/'; const [path, qs] = h.split('?'); const q = {}; new URLSearchParams(qs || '').forEach((v, k) => q[k] = v); return { path, parts: path.split('/').filter(Boolean).map(decodeURIComponent), q }; }
let renderSeq = 0;
function render() {
  if (UI.poll) { clearInterval(UI.poll); UI.poll = null; } clearInterval(UI.otpTimer);
  const R = parseHash(); const prevPath = UI.R ? UI.R.path : ''; UI.R = R; UI.user = currentUser(); UI.live = null; applyPrefs();
  const p = R.parts; const root = $('#app'); const mainEl = $('.main'); const keep = mainEl && prevPath === R.path ? mainEl.scrollTop : 0;
  if (!p.length) { root.innerHTML = Landing(); root.firstElementChild.scrollTop = 0; return; }
  if (p[0] === 'track' || p[0] === 'find-lawyer') { root.innerHTML = PublicPage(p[0] === 'track' ? TrackView(p[1]) : FindLawyerView()); const lp = $('.landing'); if (lp) lp.scrollTop = 0; mountPublic(p[0] === 'track' ? 'track' : 'find', R); return; }
  if (p[0] === 'login' || p[0] === 'signup' || p[0] === 'forgot-password') { if (UI.user) { go('#/dashboard'); return; } const lw = p[0] === 'login' && p[1] === 'lawyer'; root.innerHTML = AuthView(p[0] === 'forgot-password' ? 'forgot' : lw ? 'lawyer' : p[0]); if (lw) startOtpTimer(); const f = $('form input'); f && f.focus(); return; }
  if (!UI.user) { UI.nextHash = location.hash; go('#/login'); return; }
  let v; try { v = routeView(R); } catch (e) { console.error(e); v = errView(e); }
  if (!v) v = { title: 'Page not found', crumbs: [], html: `<div class="page narrow">${empty({ icon: 'search', title: 'Page not found', text: 'That page does not exist in this workspace.', action: `<div style="margin-top:10px">${linkBtn('Go to cases', '#/cases', { cls: 'primary' })}</div>` })}</div>` };
  root.innerHTML = Shell(v, R); document.title = (v.title ? v.title + ' · ' : '') + 'NyayaSahayak';
  const m = $('.main'); if (m) { m.scrollTop = keep; }
  UI.live = v.live || null; if (v.mount) { try { v.mount(R); } catch (e) { console.error(e); } }
  const fe = R.q.claim ? $('[data-focus]') : null; if (fe) requestAnimationFrame(() => fe.scrollIntoView({ block: 'center', behavior: prefs().reduceMotion ? 'auto' : 'smooth' }));
  if (R.q.autofocus) { const f = $('[data-autofocus]'); f && f.focus(); }
}
window.addEventListener('hashchange', () => { closeOverlay(); document.body.classList.remove('focus'); render(); });

/* ---- delegated events ---- */
document.addEventListener('click', e => {
  const a = e.target.closest('[data-act]'); if (a) { const fn = ACT[a.dataset.act]; if (fn) { if (a.tagName === 'A' && !a.getAttribute('href')) e.preventDefault(); fn(a, e); } return; }
  const row = e.target.closest('tr[data-href],[data-rowhref]'); if (row && !e.target.closest('a,button,input,select,label')) { location.hash = row.dataset.href || row.dataset.rowhref; return; }
  if (!e.target.closest('.menu,[data-menu]')) $$('.menu').forEach(m => m.remove());
});
document.addEventListener('submit', e => { const f = e.target.closest('form[data-form]'); if (f) { e.preventDefault(); const fn = FORM[f.dataset.form]; fn && fn(f, e); } });
document.addEventListener('input', e => { const t = e.target.closest('[data-in]'); if (t) { const fn = INPUT[t.dataset.in]; fn && fn(t, e); } });
document.addEventListener('change', e => { const t = e.target.closest('[data-change]'); if (t) { const fn = INPUT[t.dataset.change]; fn && fn(t, e); } });
document.addEventListener('dragover', e => { const d = e.target.closest('.drop'); if (d) { e.preventDefault(); d.classList.add('over'); } });
document.addEventListener('dragleave', e => { const d = e.target.closest('.drop'); if (d) d.classList.remove('over'); });
document.addEventListener('drop', e => { const d = e.target.closest('.drop'); if (d) { e.preventDefault(); d.classList.remove('over'); const fn = INPUT[d.dataset.drop]; fn && fn({ files: e.dataTransfer.files, dataset: d.dataset }, e); } });
document.addEventListener('keydown', e => {
  const k = e.key; const meta = e.ctrlKey || e.metaKey;
  if (meta && k.toLowerCase() === 'k') { e.preventDefault(); if (UI.user) openPalette(); return; }
  if (k === 'Escape') { if ($('#overlay').innerHTML) { closeOverlay(); return; } if (document.body.classList.contains('focus')) { document.body.classList.remove('focus'); return; } $$('.menu').forEach(m => m.remove()); }
  if (k === 'Tab') { const o = $('#overlay .modal,#overlay .drawer,#overlay .pal'); if (o) { const f = $$('a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])', o).filter(x => x.offsetParent); if (f.length) { const first = f[0], last = f[f.length - 1]; if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); } } } }
  const typing = /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || '');
  if (!typing && !meta && !$('#overlay').innerHTML && UI.user) { if (k === '/') { e.preventDefault(); openPalette(); } else if (k === '?') { e.preventDefault(); shortcutsModal(); } else if (k === '[') ACT['toggle-sidebar'](); }
});
function shortcutsModal() { modal({ title: 'Keyboard shortcuts', body: `<dl class="kv" style="grid-template-columns:150px 1fr"><dt><span class="kbd">Ctrl</span> <span class="kbd">K</span></dt><dd>Search the workspace</dd><dt><span class="kbd">/</span></dt><dd>Search the workspace</dd><dt><span class="kbd">Esc</span></dt><dd>Close a panel or leave focus mode</dd><dt><span class="kbd">[</span></dt><dd>Collapse or expand the sidebar</dd><dt><span class="kbd">?</span></dt><dd>Show this list</dd></dl>` }); }
ACT.shortcuts = () => shortcutsModal();
