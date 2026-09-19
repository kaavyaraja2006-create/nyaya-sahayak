'use strict';
const crypto = require('crypto'), fs = require('fs'), path = require('path');
const b64u = b => Buffer.from(b).toString('base64url');
function signJwt(payload, secret) {
  const h = b64u(JSON.stringify({ alg: 'HS256', typ: 'JWT' })), p = b64u(JSON.stringify(payload));
  const sig = crypto.createHmac('sha256', secret).update(h + '.' + p).digest('base64url'); return `${h}.${p}.${sig}`;
}
function verifyJwt(token, secret) {
  const parts = String(token || '').split('.'); if (parts.length !== 3) throw new Error('malformed');
  let head; try { head = JSON.parse(Buffer.from(parts[0], 'base64url').toString()); } catch (e) { throw new Error('malformed'); }
  if (head.alg !== 'HS256') throw new Error('alg');
  const expect = crypto.createHmac('sha256', secret).update(parts[0] + '.' + parts[1]).digest(); const got = Buffer.from(parts[2], 'base64url');
  if (got.length !== expect.length || !crypto.timingSafeEqual(got, expect)) throw new Error('signature');
  let pl; try { pl = JSON.parse(Buffer.from(parts[1], 'base64url').toString()); } catch (e) { throw new Error('malformed'); }
  if (!pl.exp || pl.exp * 1000 < Date.now()) throw new Error('expired'); return pl;
}
function loadSecret(cfg) {
  if (cfg.secretKey && cfg.secretKey.length >= 16) return cfg.secretKey;
  fs.mkdirSync(cfg.dataDir, { recursive: true }); const f = path.join(cfg.dataDir, '.secret');
  if (fs.existsSync(f)) return fs.readFileSync(f, 'utf8').trim();
  const s = crypto.randomBytes(32).toString('hex'); fs.writeFileSync(f, s, { mode: 0o600 }); return s;
}
class Throttle {
  constructor(max, windowMs) { this.max = max; this.win = windowMs; this.m = new Map(); }
  _c(k) { const now = Date.now(); const a = (this.m.get(k) || []).filter(t => now - t < this.win); this.m.set(k, a); return a; }
  blocked(k) { return this._c(k).length >= this.max; }
  fail(k) { const a = this._c(k); a.push(Date.now()); }
  clear(k) { this.m.delete(k); }
}
function safeJoin(root, ...parts) { const full = path.resolve(root, ...parts); const r = path.resolve(root); if (full !== r && !full.startsWith(r + path.sep)) throw new Error('path escape'); return full; }
const safeName = n => String(n || 'file').replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').replace(/^\.+/, '').slice(0, 120) || 'file';
module.exports = { signJwt, verifyJwt, loadSecret, Throttle, safeJoin, safeName };
