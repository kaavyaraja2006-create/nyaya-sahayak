#!/usr/bin/env node
'use strict';
/* NyayaSahayak MCP server (Model Context Protocol, stdio transport, JSON-RPC 2.0, newline-delimited).
   The seven tools are the same controlled tool layer the analysis agents use. Every call runs as the user named in NS_MCP_TOKEN and is
   checked for case ownership, so a client can never read another user's data. The database is re-read on every call (read-only use). */
const path = require('path'), readline = require('readline');
const { load } = require('./src/config'); const { verifyJwt, loadSecret } = require('./src/security'); const { Host } = require('./src/engine-host');
const cfg = load(); const secret = loadSecret(cfg);
const err = (...a) => process.stderr.write(a.join(' ') + '\n');
const token = process.env.NS_MCP_TOKEN || ''; let claims = null;
try { claims = verifyJwt(token, secret); if (claims.scp !== 'mcp') throw new Error('scope'); } catch (e) { err('NS_MCP_TOKEN is missing, expired or not an MCP token. Create one with POST /api/auth/mcp-token.'); process.exit(2); }
const log = () => {}; let host = null; const fresh = () => { if (host) host.close(); host = new Host({ ...cfg, geminiKey: '' }, log); return host; };
const N = () => require('./src/engine-host').N;
const TYPE = { 'id': { type: 'string', pattern: '^[A-Za-z0-9._-]{1,48}$' }, 'text': { type: 'string', minLength: 1, maxLength: 500 }, 'int': { type: 'integer', minimum: 1, maximum: 50 } };
function schemaFor(input) { const props = {}, req = []; Object.entries(input).forEach(([k, v]) => { const t = v.replace('!', ''); props[k] = TYPE[t] || { type: 'string' }; if (v.endsWith('!')) req.push(k); }); return { type: 'object', properties: props, required: req, additionalProperties: false }; }
const tools = () => N().MCP_TOOL_NAMES.map(n => ({ name: n, description: N().MCP.tools[n].purpose, inputSchema: schemaFor(N().MCP.tools[n].input) }));
const reply = (id, result) => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, result }) + '\n');
const fail = (id, code, message) => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, error: { code, message } }) + '\n');
function handle(msg) {
  const { id, method, params } = msg; const isNote = id === undefined;
  if (method === 'initialize') return reply(id, { protocolVersion: (params && params.protocolVersion) || '2024-11-05', capabilities: { tools: { listChanged: false } }, serverInfo: { name: process.env.MCP_SERVER_NAME || 'nyayasahayak', version: '1.0.0' }, instructions: 'Case-scoped, read-only access to claims, evidence, conflicts, authorities and audit history. Results are review signals, never legal conclusions.' });
  if (method === 'notifications/initialized' || isNote) return;
  if (method === 'ping') return reply(id, {});
  if (method === 'tools/list') { fresh(); return reply(id, { tools: tools() }); }
  if (method === 'tools/call') {
    const name = params && params.name; if (!N().MCP_TOOL_NAMES.includes(name)) return fail(id, -32602, 'Unknown tool.');
    const h = fresh(); const user = h.DB.users.find(u => u.id === claims.sub); if (!user) return reply(id, { content: [{ type: 'text', text: JSON.stringify({ error: { code: 'UNAUTHENTICATED', message: 'The token does not match an account.' } }) }], isError: true });
    const res = h.as(user.id, n => n.mcpCall(name, (params && params.arguments) || {}, { userId: user.id })); const isError = !!(res && res.error);
    return reply(id, { content: [{ type: 'text', text: JSON.stringify(res) }], isError });
  }
  return fail(id, -32601, 'Method not found.');
}
const rl = readline.createInterface({ input: process.stdin, terminal: false });
rl.on('line', line => { if (!line.trim()) return; let msg; try { msg = JSON.parse(line); } catch (e) { return fail(null, -32700, 'Parse error'); } try { handle(msg); } catch (e) { fail(msg.id === undefined ? null : msg.id, -32603, 'Internal error'); err('internal error:', e.message); } });
rl.on('close', () => { if (host) host.close(); process.exit(0); });
