/* ===== 21 ui shell: landing, auth, app chrome, search palette ===== */
const brandMark = `<span class="brand-mark">${icon('scale', 15)}</span>`;
const DISCLAIMER = 'Decision-support prototype. Does not determine guilt, innocence, liability, credibility, admissibility, or judicial outcomes.';
const chainStep = (ic, k, v, s) => `<div><div class="k">${icon(ic, 13)}${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;

function Landing() {
  const u = currentUser(); const cta = u ? '#/dashboard' : '#/login';
  return `<div class="landing"><header class="l-top"><a class="brand" href="#/">${brandMark}NYAYASAHAYAK</a><nav class="row wrap"><a class="btn ghost" href="#/track">Track a case</a><a class="btn ghost" href="#/find-lawyer">Find a lawyer</a>${u ? `<a class="btn" href="#/dashboard">Open workspace</a>` : `<a class="btn ghost" href="#/login">Sign in</a><a class="btn" href="#/signup">Create account</a>`}</nav></header>
  <main><section class="hero"><p class="lbl" style="margin-bottom:14px">Legal evidence intelligence</p><h1>NyayaSahayak</h1><p class="tagline">Evidence. Context. Traceability.</p>
    <p class="lede">A workspace where a legal professional can trace every claim back to its source, the evidence around it, the authorities cited for it, and the review that followed.</p>
    <div class="ctas"><a class="btn primary lg" href="${cta}">Enter case workspace</a><a class="btn lg" href="#/track">Track a case</a><a class="btn lg" href="#/find-lawyer">Find a lawyer</a><button class="btn lg" data-act="how">Learn how it works</button></div></section>
  <section class="trace-demo" aria-label="The evidence chain"><div class="chain" style="margin:0">${chainStep('file', 'Source', 'Document · page · ¶', 'Exact passage, highlighted')}${chainStep('quote', 'Claim', 'C-001', 'Extracted with its location')}${chainStep('layers', 'Evidence', 'E-001', 'Linked, with a reason')}${chainStep('scale', 'Authority', 'From your library', 'Passage shown, not asserted')}${chainStep('eye', 'Review', 'Your decision', 'Original finding kept')}${chainStep('history', 'Audit', 'Time-stamped', 'Every action recorded')}</div>
    <p class="muted" style="margin-top:12px;font-size:13px;text-align:center">The evidence chain appears on every claim. Nothing is shown without a source.</p></section>
  <section class="section" id="how"><h2 class="serif">How the workspace works</h2><p class="muted" style="max-width:62ch">Case material goes in. Specialised agents read it through a controlled tool layer. Everything they find stays linked to where it came from.</p>
    <div class="how"><div>${icon('upload', 20)}<h3>Add case material</h3><p>Upload PDF, DOCX or TXT documents and a hearing transcript, or paste the transcript text.</p></div><div>${icon('quote', 20)}<h3>Trace claims</h3><p>Each claim carries its document, page and paragraph, and opens at the exact passage.</p></div><div>${icon('compare', 20)}<h3>Compare and check</h3><p>Potential inconsistencies are surfaced between sources. Citations are compared with the authority text you supply.</p></div><div>${icon('checks', 20)}<h3>Review and record</h3><p>You accept, reject, modify or flag each finding. Every action is written to the audit trail and the report.</p></div></div></section>
  <section class="section" style="padding-top:34px"><div class="grid2" style="gap:0;border:1px solid var(--line);border-radius:var(--r-lg);overflow:hidden;background:var(--surface)"><div style="padding:22px 26px;border-right:1px solid var(--line)"><h3 class="serif" style="font-size:18px;margin-bottom:8px">What it does</h3><p class="muted">Organises, traces, compares and retrieves. Surfaces potential conflicts and citation issues for a person to judge.</p></div><div style="padding:22px 26px"><h3 class="serif" style="font-size:18px;margin-bottom:8px">What it never does</h3><p class="muted">Decide guilt, innocence, liability, witness credibility, admissibility, bail, sentencing or outcome.</p></div></div></section></main>
  <footer class="disc">${DISCLAIMER}</footer></div>`;
}
ACT.how = () => { const el = $('#how'); el && el.scrollIntoView({ behavior: prefs().reduceMotion ? 'auto' : 'smooth' }); };

const u0Home = u => u && u.role === 'CLIENT' ? '#/dashboard' : u && u.role === 'STENOGRAPHER' ? '#/court' : '#/dashboard';
function AuthView(mode) {
  const side = `<aside class="auth-side"><div><a class="brand" href="#/">${brandMark}NYAYASAHAYAK</a><h2 class="serif" style="margin-top:48px">Every finding leads back to its source.</h2><ul><li>${icon('quote', 18)}<span>Claims open at the exact page and paragraph they came from.</span></li><li>${icon('lock', 18)}<span>A case is open only to the judge, lawyers and stenographer assigned to it.</span></li><li>${icon('history', 18)}<span>Every AI finding and every reviewer action is written to an audit trail.</span></li></ul></div><p class="faint" style="font-size:12.5px;max-width:44ch">${DISCLAIMER}</p></aside>`;
  if (mode === 'forgot') return `<div class="authwrap">${side}<div class="auth-form"><div style="width:min(520px,100%);margin-top:8vh"><h1 class="serif" style="font-size:24px">Reset your password</h1><div class="note" style="margin:16px 0">${icon('info', 14)}<span>Password reset by email needs a mail service, which this build does not include. Accounts are stored only in this browser, so no reset link can be sent.</span></div><p class="muted">If you can still sign in on this device, use <b>Settings</b> to review your account. Otherwise you can create a new account; cases saved under the old account stay in this browser but are not accessible from the new one.</p><div class="row" style="margin-top:20px"><a class="btn" href="#/login">Back to sign in</a><a class="btn primary" href="#/signup">Create an account</a></div></div></div></div>`;
  if (mode === 'lawyer') return `<div class="authwrap">${side}<div class="auth-form">${LawyerLoginForm()}</div></div>`;
  if (mode === 'login') return `<div class="authwrap">${side}<div class="auth-form"><form data-form="login" novalidate style="margin-top:8vh"><h1 class="serif" style="font-size:24px">Sign in</h1><p class="muted" style="margin:4px 0 22px">Continue to your case workspace.</p>
    <div id="formerr" role="alert"></div><div class="col" style="gap:14px"><div class="field"><label for="le">Email</label><input id="le" name="email" type="email" autocomplete="username" required></div><div class="field"><label for="lp">Password</label><input id="lp" name="password" type="password" autocomplete="current-password" required></div>
    <button class="btn primary lg" type="submit" id="subbtn">Sign in</button></div><p class="muted" style="margin-top:20px"><a href="#/forgot-password">Forgot password?</a> · New here? <a href="#/signup">Create an account</a></p><p class="muted" style="margin-top:8px">Lawyer? <a href="#/login/lawyer">Sign in with your enrolment number and a one-time code</a></p><p class="muted" style="margin-top:8px"><a href="#/track">Track a case</a> · <a href="#/find-lawyer">Find a lawyer</a></p></form></div></div>`;
  const fld = (id, label, type = 'text', extra = '', full = false, hint = '') => `<div class="field ${full ? 'full' : ''}" data-f="${id}"><label for="s-${id}">${label}</label><input id="s-${id}" name="${id}" type="${type}" ${extra}>${hint ? `<span class="hint">${hint}</span>` : ''}<span class="err hide" id="e-${id}"></span></div>`;
  return `<div class="authwrap">${side}<div class="auth-form"><form data-form="signup" novalidate><h1 class="serif" style="font-size:24px">Create your account</h1><p class="muted" style="margin:4px 0 0">Set up a secure professional workspace.</p>
    <div id="formerr" role="alert"></div>
    <div class="fsec">Personal details</div><div class="fgrid">${fld('fullName', 'Full name *', 'text', 'autocomplete="name"', true)}${fld('email', 'Email *', 'email', 'autocomplete="email"')}${fld('phone', 'Phone *', 'tel', 'autocomplete="tel" placeholder="+91 98765 43210"')}${fld('password', 'Password *', 'password', 'autocomplete="new-password"', false, 'At least 8 characters.')}${fld('confirm', 'Confirm password *', 'password', 'autocomplete="new-password"')}</div>
    <div class="fsec">Professional details</div><div class="fgrid"><div class="field full" data-f="role"><label for="s-role">Professional role *</label><select id="s-role" name="role"><option value="">Select a role</option>${ROLES.map(r => `<option value="${r[0]}" ${r[0] === ((UI.R && UI.R.q) || {}).role ? 'selected' : ''}>${r[1]}</option>`).join('')}</select><span class="err hide" id="e-role"></span></div>
    ${fld('organization', 'Organization / institution', 'text', 'autocomplete="organization"')}${fld('registrationNumber', 'Registration / enrolment number', 'text', '', false, 'Lawyers: State Bar Council enrolment number (required), e.g. D/1234/2015.')}${fld('experienceYears', 'Years of experience', 'number', 'min="0" max="70"')}${fld('specialization', 'Specialization')}</div>
    <div class="note" style="margin:18px 0">${icon('info', 14)}<span>Credentials are not checked automatically. Lawyers appear in the client directory only after an administrator verifies their enrolment number.</span></div>
    <button class="btn primary lg" type="submit" id="subbtn" style="width:100%">Create account</button><p class="muted" style="margin-top:18px">Already registered? <a href="#/login">Sign in</a></p></form></div></div>`;
}
FORM.login = async f => {
  const b = $('#subbtn'); b.disabled = true; b.textContent = 'Signing in…'; const r = await Data.login(f.email.value, f.password.value);
  if (!r.ok && r.lawyerOtp) { toast('Lawyers sign in with a one-time code.', 'warn'); go('#/login/lawyer'); return; }
  if (!r.ok) { $('#formerr').innerHTML = `<div class="note warn" style="margin-bottom:14px">${icon('alert', 14)}<span>${esc(r.error)}</span></div>`; b.disabled = false; b.textContent = 'Sign in'; f.password.value = ''; f.password.focus(); return; }
  const n = UI.nextHash; UI.nextHash = null; go(n && !/login|signup|forgot/.test(n) ? n : '#/dashboard'); toast('Signed in.');
};
FORM.signup = async f => {
  const b = $('#subbtn'); b.disabled = true; b.textContent = 'Creating account…';
  const data = {}; new FormData(f).forEach((v, k) => data[k] = v); const r = await Data.signup(data);
  $$('.err', f).forEach(x => { x.classList.add('hide'); x.textContent = ''; }); $$('.field.bad', f).forEach(x => x.classList.remove('bad'));
  if (!r.ok) { Object.entries(r.errors).forEach(([k, m]) => { const e = $('#e-' + k), fl = $(`[data-f="${k}"]`); if (e) { e.innerHTML = icon('alert', 12) + esc(m); e.classList.remove('hide'); } if (fl) fl.classList.add('bad'); }); const first = $('.field.bad input,.field.bad select', f); first && first.focus(); b.disabled = false; b.textContent = 'Create account'; return; }
  if (r.requiresOtp) { UI.otp = { challengeId: r.challengeId, enrollment: data.registrationNumber, mobile: data.phone, resendAt: Date.now() + (r.resendAfterSeconds || 30) * 1000, sent: r.otpSent }; toast('Account created. Enter the one-time code to sign in.'); go('#/login/lawyer'); return; }
  toast('Account created. Welcome.'); go(u0Home(r.user));
};

/* ---- app shell ---- */
function caseNav(C) {
  if (accessOf(C) === 'hearing') return `<div class="navgroup">Case</div>${navItem('home', 'Overview', caseHref(C), '', isCurrent(C, ''))}${navItem('mic', 'Hearings', caseHref(C, 'hearing'), '', isCurrent(C, 'hearing'))}${navItem('folder', 'Add documents', caseHref(C, 'documents'), '', isCurrent(C, 'documents'))}`;
  const m = caseMetrics(C); const open = C.findings.filter(f => f.kind !== 'CLAIM' && findingStatus(C, f) === 'PENDING').length; const citIssues = C.citations.filter(x => x.result !== 'POTENTIALLY_RELEVANT').length;
  const b = (n, attn) => n ? `<span class="badge-n ${attn ? 'attn' : ''}">${n}</span>` : '';
  const G = [['Case', [['home', 'Overview', ''], ['folder', 'Documents', 'documents', m.documents], ['mic', 'Hearings', 'hearing', m.transcripts], ['quote', 'Claims', 'claims', m.claims], ['layers', 'Evidence', 'evidence', m.evidence], ['clock', 'Timeline', 'timeline']]],
    ['Analysis', [['cpu', 'Run analysis', 'analysis'], ['network', 'Evidence graph', 'graph'], ['warn', 'Conflicts', 'conflicts', m.conflicts, true], ['book', 'Authorities', 'authorities'], ['shield', 'Citation audit', 'citations', citIssues, true]]],
    ['Review', [['checks', 'Review queue', 'review', open, true], ['history', 'Audit trail', 'audit']]], ['Output', [['download', 'Reports', 'report']]]];
  return G.map(([g, items]) => `<div class="navgroup">${g}</div>${items.map(([ic, l, sub, n, attn]) => navItem(ic, l, caseHref(C, sub), n ? b(n, attn) : '', isCurrent(C, sub))).join('')}`).join('');
}
function isCurrent(C, sub) { const p = UI.R.parts; if (p[1] !== C.id) return false; const s = p[2] || ''; return s === sub; }
const navItem = (ic, label, href, badgeHtml = '', cur = false) => `<a class="navitem" href="${href}" ${cur ? 'aria-current="page"' : ''} title="${esc(label)}">${icon(ic, 17)}<span>${esc(label)}</span>${badgeHtml}</a>`;
function Shell(v, R) {
  const u = UI.user, C = v.case || null, p = R.parts; const p0 = p[0];
  const g = (h) => p0 === h;
  let side;
  if (C) side = `<div class="sb-case"><a href="#/cases" class="faint" style="font-size:12px;display:flex;gap:4px;align-items:center">${icon('left', 12)}All cases</a><div class="name serif" style="margin-top:6px;font-size:14.5px">${esc(C.name)}</div><div class="mono faint" style="font-size:11.5px;margin-top:2px">${esc(C.id)}</div></div>${caseNav(C)}`;
  else side = roleNavFull(u, g) || `<div class="navgroup">Cases</div>${navItem('home', 'Dashboard', '#/dashboard', '', g('dashboard'))}${navItem('folder', 'My cases', '#/cases', '', g('cases'))}${navItem('checks', 'Review queue', '#/review', '', g('review'))}${navItem('book', 'Authorities', '#/authorities', '', g('authorities'))}${navItem('download', 'Reports', '#/reports', '', g('reports'))}${navItem('history', 'Audit log', '#/audit', '', g('audit'))}`;
  const lim = ['STENOGRAPHER', 'CLIENT'].includes(u.role);
  const sys = `<div class="navgroup">System</div>${navItem('plug', 'MCP tools', '#/mcp', '', g('mcp'))}${navItem('cpu', 'Agent runs', '#/agents', '', g('agents'))}${navItem('sliders', 'Settings', '#/settings', '', g('settings'))}`;
  const foot = `<div class="sb-foot"><a class="navitem" href="#/settings" title="Profile"><span class="avatar" style="width:26px;height:26px;font-size:11px">${esc(initials(u.fullName))}</span><span style="min-width:0"><span class="trunc" style="display:block;font-size:13px;color:var(--text)">${esc(u.fullName)}</span><span class="faint" style="font-size:11.5px">${esc(roleLabel(u.role))}</span></span></a></div>`;
  const crumbs = (v.crumbs || []).map((c, i, a) => i === a.length - 1 ? `<span class="cur trunc">${esc(c[0])}</span>` : `<a href="${c[1] || '#'}" class="trunc">${esc(c[0])}</a><span class="sep">${icon('right', 12)}</span>`).join('');
  const nItems = notifItems(u.id).length; const ai = aiActive();
  const cls = 'app' + (prefs().sidebarCollapsed ? ' collapsed' : '') + (lim ? ' lim' : '');
  const ctx = C ? `<div class="topctx"><span class="k">CASE / ${esc(C.id)}</span><span class="t trunc">${esc(C.name)}</span></div>` : `<div class="topctx"><span class="k">WORKSPACE</span><span class="t">NyayaSahayak</span></div>`;
  return `<div class="${cls}" id="appgrid"><header class="topbar"><button class="iconbtn" data-act="toggle-sidebar" aria-label="Toggle sidebar" title="Toggle sidebar ( [ )">${icon('panel', 18)}</button><a class="brand" href="#/dashboard" aria-label="NyayaSahayak home">${brandMark}<span class="hide-sm">NYAYASAHAYAK</span></a>${ctx}
    <div class="grow" style="text-align:center"><span class="lbl hide-sm">${esc(v.workspace || v.title || '')}</span></div>
    <button class="searchbtn" style="margin:0;width:230px" data-act="palette" aria-label="Search the workspace">${icon('search', 15)}<span class="grow">Search…</span><span class="kbd">Ctrl K</span></button>
    <div class="row" style="gap:6px"><a class="revpill" href="${C ? caseHref(C, 'review') : '#/review'}" title="Findings that need a reviewer">${icon('eye', 13)}${nItems} to review</a><span class="aistat ${ai ? 'on' : ''}" title="${ai ? 'Claim extraction uses Gemini (' + esc(aiModel()) + '). Other stages use the rules engine.' : 'Rules engine only. Enable Gemini in Settings to use AI claim extraction.'}"><i></i>${ai ? 'Gemini + rules' : 'Rules engine'}</span>
    <div class="rel"><button class="iconbtn" data-act="notif" data-menu aria-label="Notifications, ${nItems} to review" title="Notifications">${icon('bell', 17)}${nItems ? `<span class="dot">${nItems > 99 ? '99+' : nItems}</span>` : ''}</button></div>
    <div class="rel"><button class="iconbtn" data-act="theme-menu" data-menu aria-label="Appearance" title="Appearance">${icon(resolvedTheme() === 'light' ? 'sun' : 'moon', 17)}</button></div>
    <div class="rel"><button class="iconbtn" data-act="user-menu" data-menu aria-label="Account menu" style="width:38px"><span class="avatar">${esc(initials(u.fullName))}</span></button></div></div></header>
    <nav class="sidebar" aria-label="Primary">${side}${C ? '' : lim ? '' : roleNavExtra(u, g) + sys}${C && !lim ? `<div class="navgroup">System</div>${navItem('plug', 'MCP tools', '#/mcp?case=' + C.id, '', false)}${navItem('cpu', 'Agent runs', '#/agents?case=' + C.id, '', false)}${navItem('sliders', 'Settings', '#/settings', '', false)}` : ''}${foot}</nav>
    <div class="main" id="main">${C ? caseHead(C) : ''}${v.noCrumbs || !crumbs ? '' : `<nav class="crumbs pagecrumbs" aria-label="Breadcrumb">${crumbs}</nav>`}${v.html}</div></div>${bottomNav(C)}<button class="btn focusexit primary" data-act="exit-focus">${icon('x', 14)}Exit focus mode</button>`;
}
function bottomNav(C) {
  const items = C ? [['home', 'Home', caseHref(C)], ['folder', 'Docs', caseHref(C, 'documents')], ['quote', 'Claims', caseHref(C, 'claims')], ['checks', 'Review', caseHref(C, 'review')]] : [['home', 'Home', '#/dashboard'], ['folder', 'Cases', '#/cases'], ['checks', 'Review', '#/review'], ['sliders', 'Settings', '#/settings']];
  return `<nav class="bottomnav" aria-label="Mobile">${items.map(([i, l, h]) => `<a href="${h}" ${location.hash.startsWith(h) && h !== '#/' ? 'aria-current="page"' : ''}>${icon(i, 19)}${l}</a>`).join('')}<button data-act="toggle-sidebar">${icon('menu', 19)}More</button></nav>`;
}
function caseHead(C) {
  const meta = [C.type, C.jurisdiction, C.court].filter(Boolean).join(' · '); const last = C.lastAnalyzedAt ? `Last analyzed ${fmtClock(C.lastAnalyzedAt).slice(0, 5)} · ${relTime(C.lastAnalyzedAt)}` : 'Not analyzed yet'; const running = C.status === 'ANALYZING';
  return `<div class="casehead"><div class="grow muted trunc" style="font-size:13px;min-width:0">${esc(meta || 'No court or jurisdiction recorded')}${C.number ? ` · <span class="mono">${esc(C.number)}</span>` : ''}</div><div class="row wrap" style="gap:14px">${statusBadge(C.status)}<span class="muted" style="font-size:12.5px">${esc(last)}</span>${accessOf(C) !== 'full' ? '' : btn(running ? 'Analyzing…' : C.claims.length ? 'Re-run analysis' : 'Analyze materials', `data-act="run-analysis" data-case="${C.id}" ${running || C.status === 'ARCHIVED' ? 'disabled' : ''}`, { cls: C.claims.length ? '' : 'primary', icon: 'play' })}</div></div>`;
}
ACT['toggle-sidebar'] = () => { const g = $('#appgrid'); if (!g) return; if (window.innerWidth <= 980) g.classList.toggle('navopen'); else { setPref('sidebarCollapsed', !prefs().sidebarCollapsed); g.classList.toggle('collapsed', prefs().sidebarCollapsed); } };
ACT['exit-focus'] = () => document.body.classList.remove('focus');
ACT['run-analysis'] = el => startAnalysis(el.dataset.case);
async function startAnalysis(caseId) {
  const u = currentUser(); let C; try { C = CaseSvc.get(u.id, caseId); } catch (e) { return toast('Unable to load case. Try again.', 'bad'); }
  if (!C.documents.length) { toast('Add at least one document or transcript before analyzing.', 'warn'); go(caseHref(C, 'documents')); return; }
  toast('Analysis started.', 'ok'); go(caseHref(C, 'analysis'));
  try { const a = await Data.analyze(caseId); const st = a && a.status; toast(st === 'completed' ? 'Analysis completed.' : st === 'partial' ? 'Analysis finished with some stages incomplete.' : 'Analysis did not complete.', st === 'completed' ? 'ok' : 'warn'); }
  catch (e) { toast(e && e.message ? e.message : 'Analysis could not start.', 'bad'); }
  if (UI.R && UI.R.parts[0] === 'cases' && UI.R.parts[1] === caseId) render();
}

/* ---- menus ---- */
function openMenu(el, html) { const wrap = el.closest('.rel'); const had = $('.menu', wrap); $$('.menu').forEach(m => m.remove()); if (had) return; const m = document.createElement('div'); m.className = 'menu'; m.setAttribute('role', 'menu'); m.innerHTML = html; wrap.appendChild(m); const f = $('button,a', m); }
ACT['theme-menu'] = el => { const t = prefs().theme; const opt = (v, l, ic) => `<button class="mi" role="menuitemradio" aria-checked="${t === v}" data-act="set-theme" data-v="${v}">${icon(ic, 15)}${l}${t === v ? `<span style="margin-left:auto">${icon('check', 14)}</span>` : ''}</button>`; openMenu(el, opt('light', 'Light', 'sun') + opt('dark', 'Dark', 'moon') + opt('night', 'Night', 'moon') + opt('system', 'System', 'monitor')); };
ACT['set-theme'] = el => { setPref('theme', el.dataset.v); applyPrefs(); $$('.menu').forEach(m => m.remove()); render(); };
ACT['user-menu'] = el => { const u = UI.user; openMenu(el, `<div style="padding:8px 10px"><div style="font-weight:600">${esc(u.fullName)}</div><div class="muted" style="font-size:12.5px">${esc(roleLabel(u.role))}${u.organization ? ' · ' + esc(u.organization) : ''}</div><div class="faint" style="font-size:12px">${esc(u.email)}</div></div><hr><a class="mi" href="#/settings">${icon('sliders', 15)}Settings</a><button class="mi" data-act="logout">${icon('logout', 15)}Sign out</button>`); };
ACT.logout = async () => { await Data.logout(); toast('Signed out.'); go('#/'); };
function notifItems(uid) {
  const out = []; CaseSvc.list(uid).forEach(C => { if (C.status === 'ARCHIVED') return; C.findings.forEach(f => { if (f.kind !== 'CLAIM' && findingStatus(C, f) === 'PENDING') out.push({ C, f }); }); });
  const rank = { CONFLICT: 0, CITATION: 1, UNCERTAIN: 2, SINGLE_SOURCE: 3 }; return out.sort((a, b) => (rank[a.f.kind] - rank[b.f.kind]));
}
ACT.notif = el => {
  const items = notifItems(UI.user.id);
  const kindLabel = f => f.kind === 'CONFLICT' ? 'Potential conflict' : f.kind === 'CITATION' ? 'Citation requires review' : f.kind === 'UNCERTAIN' ? 'Uncertain claim' : 'Missing corroboration';
  const recent = []; CaseSvc.list(UI.user.id).forEach(C => C.audit.slice(-40).forEach(e => { if (['ANALYSIS_COMPLETED', 'REPORT_GENERATED', 'DOCUMENT_PROCESSED'].includes(e.event)) recent.push({ C, e }); })); recent.sort((a, b) => b.e.ts.localeCompare(a.e.ts));
  const recHtml = recent.length ? `<hr><div class="faint" style="padding:4px 10px;font-size:11.5px">Recent activity</div>${recent.slice(0, 3).map(({ C, e }) => `<a class="mi" href="${objHref(C, e.object)}">${icon('check', 14)}<span style="min-width:0"><span class="trunc" style="display:block;max-width:230px">${esc(e.description)}</span><span class="faint mono" style="font-size:11px">${esc(C.id)} · ${fmtClock(e.ts).slice(0, 5)}</span></span></a>`).join('')}` : '';
  openMenu(el, (items.length ? `<div style="padding:8px 10px;font-weight:600">${plural(items.length, 'item')} require review</div>${items.slice(0, 5).map(({ C, f }) => `<a class="mi" href="#/cases/${C.id}/review/${f.id}" style="align-items:flex-start">${icon(f.kind === 'CONFLICT' ? 'warn' : 'circle', 15)}<span><span class="mono">${esc(f.claimIds[0] || f.id)}</span> ${esc(kindLabel(f))}<br><span class="faint" style="font-size:12px">${esc(C.name)}</span></span></a>`).join('')}${items.length > 5 ? `<div class="faint" style="padding:6px 10px;font-size:12px">and ${items.length - 5} more in the review queues</div>` : ''}` : `<div style="padding:14px 12px" class="muted">No findings require review right now.</div>` ) + recHtml);
};

/* ---- global search palette ---- */
let palSel = 0, palRes = [];
function openPalette() {
  openOverlay(`<div class="pal" role="dialog" aria-modal="true" aria-label="Search"><div class="pi">${icon('search', 18)}<input id="palq" data-in="pal" placeholder="Search NyayaSahayak — cases, documents, claims, evidence, hearings, authorities…" autocomplete="off" aria-label="Search" autofocus></div><div class="res" id="palres" role="listbox"></div></div>`);
  paintPalette('');
}
ACT.palette = () => openPalette();
function paintPalette(q) {
  const u = currentUser(); const el = $('#palres'); if (!el) return; let res = [];
  if (q.trim().length >= 2) res = searchAll(u.id, q);
  else { res = [{ group: 'Go to', label: 'All cases', sub: '', href: '#/cases' }, { group: 'Go to', label: 'Create a new case', sub: '', href: '#/cases/new' }, { group: 'Go to', label: 'Authority search', sub: '', href: '#/authorities' }, { group: 'Go to', label: 'Settings', sub: '', href: '#/settings' }]; CaseSvc.list(u.id).slice(0, 4).forEach(c => res.push({ group: 'Recent cases', label: c.name, sub: c.id, href: caseHref(c) })); }
  palRes = res; palSel = 0;
  if (!res.length) { el.innerHTML = `<div style="padding:26px;text-align:center" class="muted">No matches for “${esc(q)}”. Try a claim ID, a document name or a place.</div>`; return; }
  let g = '', out = ''; res.forEach((r, i) => { if (r.group !== g) { g = r.group; out += `<div class="grp">${esc(g)}</div>`; } out += `<button class="it" role="option" data-act="pal-go" data-i="${i}" aria-selected="${i === 0}">${esc(r.label)}<span class="s">${esc(r.sub)}</span></button>`; }); el.innerHTML = out;
}
INPUT.pal = t => paintPalette(t.value);
ACT['pal-go'] = el => { const r = palRes[+el.dataset.i]; if (r) { closeOverlay(); go(r.href); } };
document.addEventListener('keydown', e => {
  if (!$('.pal')) return; const its = $$('#palres .it'); if (!its.length) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); palSel = (palSel + (e.key === 'ArrowDown' ? 1 : -1) + its.length) % its.length; its.forEach((x, i) => x.setAttribute('aria-selected', i === palSel)); its[palSel].scrollIntoView({ block: 'nearest' }); }
  else if (e.key === 'Enter') { e.preventDefault(); its[palSel].click(); }
});
