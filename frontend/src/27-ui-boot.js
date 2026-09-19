/* ===== 27 ui boot: route table, hover card, keyboard affordances, start-up ===== */
function routeView(R) {
  const p = R.parts, q = R.q, p0 = p[0]; const u = currentUser();
  if (p0 === 'dashboard') return DashboardView();
  if (p0 === 'history') { go('#/cases'); return DashboardView(); }
  if (p0 === 'review') return ReviewGlobalView();
  if (p0 === 'authorities') return AuthoritiesView(null, q);
  if (p0 === 'reports') return ReportsGlobalView();
  if (p0 === 'audit') return AuditView(null);
  if (p0 === 'mcp') return McpView(q);
  if (p0 === 'agents') return AgentsView(q);
  if (p0 === 'settings') return SettingsView();
  if (p0 === 'cases') {
    if (!p[1]) return CasesView(); if (p[1] === 'new') return NewCaseView();
    const res = withCase(p[1], (C) => {
      const sub = p[2] || ''; let v = null;
      switch (sub) {
        case '': v = OverviewView(C); break; case 'setup': v = SetupView(C, p[3]); break;
        case 'documents': v = p[3] ? DocViewerView(C, p[3], q) : DocumentsView(C); break;
        case 'hearing': v = HearingView(C, q); break; case 'claims': v = p[3] ? ClaimDetailView(C, p[3]) : ClaimsView(C); break;
        case 'evidence': v = EvidenceView(C); break; case 'graph': v = GraphView(C, q); break; case 'timeline': v = TimelineView(C); break;
        case 'conflicts': v = ConflictsView(C); break; case 'authorities': v = AuthoritiesView(C, q); break; case 'citations': v = CitationsView(C, q); break;
        case 'analysis': v = AnalysisView(C); break; case 'review': v = ReviewView(C, p[3]); break; case 'audit': v = AuditView(C); break; case 'report': v = ReportView(C); break;
      }
      if (v) v.case = C; return v;
    });
    return res;
  }
  return null;
}

/* hover card on highlighted source passages */
document.addEventListener('mouseover', e => {
  const hc = $('#hovercard'); if (!hc) return; const m = e.target.closest && e.target.closest('mark.cl[data-hover]');
  if (!m) { if (!hc.classList.contains('hide')) hc.classList.add('hide'); return; }
  const C = currentCaseSafe(); if (!C) return; const X = derive(C); const ids = m.dataset.hover.split(','); const c = X.claim(ids[0]); if (!c) return; const i = X.info(c);
  hc.innerHTML = `<div class="row between"><span class="tag">CLAIM ${esc(c.id)}</span>${badge(i.status)}</div><div class="t">${esc(trunc(c.text, 150))}</div><dl class="kv" style="grid-template-columns:96px 1fr;gap:3px 8px"><dt>Source</dt><dd>${esc(X.src(c))}</dd><dt>Linked evidence</dt><dd class="mono">${i.strong.slice(0, 4).map(r => r.ev.id).join(', ') || '—'}</dd>${i.inConflict ? `<dt>Conflict</dt><dd>${esc(i.conflicts[0].id)} · requires human verification</dd>` : ''}${ids.length > 1 ? `<dt>Also here</dt><dd class="mono">${esc(ids.slice(1).join(', '))}</dd>` : ''}</dl>`;
  const r = m.getBoundingClientRect(); hc.classList.remove('hide'); const h = hc.offsetHeight; let top = r.bottom + 8; if (top + h > innerHeight - 8) top = Math.max(8, r.top - h - 8); hc.style.top = top + 'px'; hc.style.left = Math.max(8, Math.min(r.left, innerWidth - 336)) + 'px';
});
document.addEventListener('scroll', () => { const hc = $('#hovercard'); hc && hc.classList.add('hide'); }, true);
/* keyboard activation for role=button elements */
document.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('[role=button][data-act]') && !/^(BUTTON|A|INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) { e.preventDefault(); e.target.dispatchEvent(new MouseEvent('click', { bubbles: true })); } });

async function boot() {
  applyPrefs(); subscribe(() => { if (UI.live) UI.live(); });
  await Api.detect(); if (Api.on) { if (Api.token) await Data.resume(); }
  setInterval(() => { const p = prefs(); if (p.autoNight || p.theme === 'system') applyPrefs(); }, 60000);
  if (window.matchMedia) { try { matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => { if (prefs().theme === 'system') applyPrefs(); }); } catch (e) {} }
  if (!location.hash) location.hash = '#/'; render();
}
