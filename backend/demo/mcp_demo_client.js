#!/usr/bin/env node
'use strict';
/* MCP demo client. Starts a throw-away server on a temporary database, loads SYNTHETIC DEMONSTRATION DATA (test-only fictional files from
   ../tests/e2e-data), then talks to the real MCP stdio server the way any MCP client would. Nothing here touches your real data. */
const fs = require('fs'), os = require('os'), path = require('path'), { spawn } = require('child_process');
const { createServer } = require('../src/server');
const DATA = path.join(__dirname, '..', '..', 'tests', 'e2e-data'); const b64 = f => fs.readFileSync(path.join(DATA, f)).toString('base64');
(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ns-demo-')); const app = createServer({ dataDir: dir, port: 0, logLevel: 'error', paceMs: 0 }); const a = await app.listen(); const base = `http://127.0.0.1:${a.port}`;
  const api = async (m, p, body, t) => { const r = await fetch(base + p, { method: m, headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: 'Bearer ' + t } : {}) }, body: body ? JSON.stringify(body) : undefined }); return r.json(); };
  const su = await api('POST', '/api/auth/signup', { fullName: 'Demo Reviewer', email: 'demo@example.com', phone: '+91 9000000000', password: 'demo-password-1', confirm: 'demo-password-1', role: 'LEGAL_RESEARCHER' }); const token = su.token;
  for (const x of JSON.parse(fs.readFileSync(path.join(DATA, 'authorities.json'), 'utf8'))) await api('POST', '/api/authorities', { ...x, kind: 'Judgment' }, token);
  const cid = (await api('POST', '/api/cases', { name: 'Depot incident review (SYNTHETIC DEMONSTRATION DATA)', type: 'Criminal' }, token)).case.id;
  for (const f of ['PW-3 Statement.txt', 'PW-5 Statement.txt', 'CCTV Review Report.txt', 'Device Location Record.txt', 'Incident Report.txt', 'Written Submission.txt']) await api('POST', `/api/cases/${cid}/documents`, { filename: f, contentBase64: b64(f) }, token);
  await api('POST', `/api/cases/${cid}/transcripts`, { filename: 'Hearing 3 transcript.txt', contentBase64: b64('Hearing 3 transcript.txt'), hearingDate: '2026-03-20', hearingNumber: '3' }, token);
  await api('POST', `/api/cases/${cid}/analyze`, {}, token); for (let i = 0; i < 200; i++) { const s = await api('GET', `/api/cases/${cid}/analysis`, null, token); if (s.analysis && s.analysis.status !== 'running') break; await new Promise(r => setTimeout(r, 50)); }
  const mcpToken = (await api('POST', '/api/auth/mcp-token', {}, token)).token;
  const p = spawn(process.execPath, ['--disable-warning=ExperimentalWarning', path.join(__dirname, '..', 'mcp-server.js')], { env: { ...process.env, DATA_DIR: dir, NS_MCP_TOKEN: mcpToken }, stdio: ['pipe', 'pipe', 'inherit'] });
  const waiters = new Map(); let buf = ''; p.stdout.on('data', d => { buf += d; let i; while ((i = buf.indexOf('\n')) >= 0) { const l = buf.slice(0, i); buf = buf.slice(i + 1); if (l.trim()) { const m = JSON.parse(l); const w = waiters.get(m.id); if (w) { waiters.delete(m.id); w(m); } } } }); let id = 0;
  const rpc = (method, params) => new Promise(res => { const my = ++id; waiters.set(my, res); p.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: my, method, params }) + '\n'); });
  const tool = async (name, args) => JSON.parse((await rpc('tools/call', { name, arguments: args })).result.content[0].text);
  await rpc('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'nyayasahayak-demo', version: '1.0.0' } }); p.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
  const tools = (await rpc('tools/list', {})).result.tools;
  console.log('=== NyayaSahayak MCP Demo ===\n\nSYNTHETIC DEMONSTRATION DATA — fictional people, places and events.\n\nCase: ' + cid + `\nMCP server: nyayasahayak (${tools.length} tools)\n`);
  const mat = await tool('get_case_material', { case_id: cid }); console.log(`[1] Case Material\n    ${mat.documents.length} documents found\n`);
  const cl = await tool('get_claims', { case_id: cid }); console.log(`[2] Claims\n    ${cl.claims.length} claims found\n    (confidence describes extraction certainty only)\n`);
  const conflictsAll = []; let evCount = 0; for (const c of cl.claims) { const e = await tool('get_evidence', { claim_id: c.id, case_id: cid }); evCount += (e.evidence || []).length; }
  console.log(`[3] Evidence\n    ${evCount} claim–evidence links across ${cl.claims.length} claims\n`);
  const seen = new Set(); for (const c of cl.claims) { const r = await tool('find_claim_conflicts', { case_id: cid, claim_id: c.id }); (r.conflicts || []).forEach(k => { if (!seen.has(k.id)) { seen.add(k.id); conflictsAll.push(k); } }); }
  console.log(`[4] Conflict Detection\n    ${conflictsAll.length} potential conflict(s) identified\n${conflictsAll.slice(0, 3).map(k => `    - ${k.id} ${k.type}: ${k.description.split('. Human')[0]}.`).join('\n')}\n`);
  const sa = await tool('search_authorities', { query: 'phone metadata handset location record', limit: 3, case_id: cid }); console.log(`[5] Authority Search\n    ${sa.results.length} relevant authorities retrieved (ranking signal only, not legal correctness)\n`);
  const ex = await tool('get_authority_excerpt', { authority_id: sa.results[0].authority_id, case_id: cid }); console.log(`[6] Authority Excerpt\n    ${ex.excerpt ? 'Source successfully retrieved' : 'Not available'}: ${ex.citation}\n`);
  const au = await tool('get_audit_history', { case_id: cid }); console.log(`[7] Audit History\n    ${au.events.length} events found\n`);
  console.log('Analysis complete.\nHuman review required for identified conflicts.');
  p.kill(); await app.close(); fs.rmSync(dir, { recursive: true, force: true });
})().catch(e => { console.error('demo failed:', e.message); process.exit(1); });
