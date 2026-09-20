'use strict';
/* One-time passwords for lawyer sign-in.
   - generated on the server with crypto.randomInt; only an HMAC of the code is stored (never the code itself)
   - expires (default 5 min), single use (consumed atomically), at most N wrong guesses per code, older codes are invalidated by a new request
   - requests and verifications are rate limited per person and per client address; the response for an unknown lawyer is indistinguishable from a real one
   - the code is only ever sent to the registered mobile number (SMS gateway webhook); it is never included in an API response */
const crypto = require('crypto');
const { Throttle } = require('./security');

class OtpError extends Error { constructor(status, code, message, extra) { super(message); this.status = status; this.code = code; this.extra = extra; } }
const HEX24 = /^[0-9a-f]{24}$/;
const mask = m => String(m).replace(/\d(?=\d{3})/g, '•');

class OtpService {
  constructor(cfg, store, secret, log) {
    this.cfg = cfg; this.store = store; this.secret = secret; this.log = log; this.outbox = [];
    this.idReq = new Throttle(cfg.otpRequestsPerWindow, cfg.otpWindowMs);          /* per enrolment+mobile */
    this.ipReq = new Throttle(cfg.otpIpRequestsPerWindow, cfg.otpWindowMs);        /* per client address */
    this.verFail = new Throttle(cfg.otpVerifyFailuresPerWindow, cfg.otpWindowMs);  /* wrong codes per client address */
    this.lastSent = new Map();
    if (cfg.otpDelivery === 'console') log('warn', 'otp_delivery_console', { note: 'No SMS gateway configured (SMS_WEBHOOK_URL). One-time codes are written to this log. Development only.' });
  }
  hash(id, salt, code) { return crypto.createHmac('sha256', this.secret).update(`otp:${id}:${salt}:${code}`).digest('hex'); }
  async deliver(mobile, code) {
    const message = `Your NyayaSahayak sign-in code is ${code}. It expires in ${Math.round(this.cfg.otpTtlSeconds / 60)} minutes. Do not share it with anyone.`; const mode = this.cfg.otpDelivery;
    if (mode === 'memory') { this.outbox.push({ to: mobile, message, code }); return; }
    if (mode === 'webhook') {
      if (!this.cfg.smsWebhookUrl) throw new OtpError(503, 'OTP_NOT_CONFIGURED', 'One-time codes cannot be sent right now. Contact the administrator.');
      let r; try { r = await fetch(this.cfg.smsWebhookUrl, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(this.cfg.smsWebhookToken ? { Authorization: 'Bearer ' + this.cfg.smsWebhookToken } : {}) }, body: JSON.stringify({ to: mobile, message }), signal: AbortSignal.timeout(10000) }); } catch (e) { throw new OtpError(503, 'OTP_DELIVERY_FAILED', 'The one-time code could not be sent. Try again shortly.'); }
      if (!r.ok) throw new OtpError(503, 'OTP_DELIVERY_FAILED', 'The one-time code could not be sent. Try again shortly.'); return;
    }
    if (this.cfg.production && process.env.OTP_ALLOW_CONSOLE !== '1') throw new OtpError(503, 'OTP_NOT_CONFIGURED', 'One-time codes cannot be sent right now. Contact the administrator.');
    this.log('warn', 'otp_console_delivery', { to: mask(mobile), code });   /* development fallback only */
  }
  /* user: the matching lawyer account, or null. key identifies the enrolment+mobile pair for throttling. */
  async request({ user, key, ip, mobile }) {
    const retry = t => Math.ceil(this.cfg.otpWindowMs / 1000);
    if (this.ipReq.blocked(ip) || this.idReq.blocked(key)) throw new OtpError(429, 'TOO_MANY_REQUESTS', 'Too many code requests. Wait a few minutes and try again.', { retryAfterSeconds: retry() });
    const last = this.lastSent.get(key); const now = Date.now();
    if (last && now - last < this.cfg.otpResendSeconds * 1000) throw new OtpError(429, 'RESEND_TOO_SOON', `Please wait ${Math.ceil((this.cfg.otpResendSeconds * 1000 - (now - last)) / 1000)} seconds before asking for another code.`, { retryAfterSeconds: Math.ceil((this.cfg.otpResendSeconds * 1000 - (now - last)) / 1000) });
    this.ipReq.fail(ip); this.idReq.fail(key); this.lastSent.set(key, now); if (this.lastSent.size > 5000) this.lastSent.clear();
    const out = { expiresInSeconds: this.cfg.otpTtlSeconds, resendAfterSeconds: this.cfg.otpResendSeconds };
    if (!user) return { challengeId: crypto.randomBytes(12).toString('hex'), ...out };   /* same shape and status as a real request */
    const id = crypto.randomBytes(12).toString('hex'), salt = crypto.randomBytes(8).toString('hex'), code = String(crypto.randomInt(0, 1000000)).padStart(6, '0'), t = Math.floor(now / 1000);
    this.store.q('UPDATE otp_challenges SET invalidated_at=? WHERE user_id=? AND consumed_at IS NULL AND invalidated_at IS NULL').run(t, user.id);
    this.store.q('INSERT INTO otp_challenges(id,user_id,purpose,code_hash,salt,created_at,expires_at,ip) VALUES(?,?,?,?,?,?,?,?)').run(id, user.id, 'lawyer_login', this.hash(id, salt, code), salt, t, t + this.cfg.otpTtlSeconds, ip || '');
    try { await this.deliver(mobile || user.phone, code); } catch (e) { this.store.q('UPDATE otp_challenges SET invalidated_at=? WHERE id=?').run(t, id); throw e; }
    this.store.q('DELETE FROM otp_challenges WHERE created_at < ?').run(t - 86400);
    return { challengeId: id, ...out };
  }
  /* returns { userId } or throws INVALID_OTP. Every failure looks the same to the caller. */
  verify({ challengeId, code, ip }) {
    const bad = () => new OtpError(401, 'INVALID_OTP', 'That code is not valid or has expired. Request a new code.');
    if (this.verFail.blocked(ip)) throw new OtpError(429, 'TOO_MANY_ATTEMPTS', 'Too many incorrect codes. Wait a few minutes and try again.', { retryAfterSeconds: Math.ceil(this.cfg.otpWindowMs / 1000) });
    const id = String(challengeId || ''), c = String(code || '').trim();
    if (!HEX24.test(id) || !/^\d{6}$/.test(c)) { this.verFail.fail(ip); throw bad(); }
    const t = Math.floor(Date.now() / 1000), row = this.store.q('SELECT * FROM otp_challenges WHERE id=?').get(id);
    if (!row || row.consumed_at || row.invalidated_at || row.expires_at <= t) { this.verFail.fail(ip); throw bad(); }
    const got = Buffer.from(this.hash(id, row.salt, c), 'hex'), want = Buffer.from(row.code_hash, 'hex');
    if (got.length !== want.length || !crypto.timingSafeEqual(got, want)) {
      const n = row.attempts + 1; this.store.q('UPDATE otp_challenges SET attempts=?, invalidated_at=CASE WHEN ? >= ? THEN ? ELSE invalidated_at END WHERE id=?').run(n, n, this.cfg.otpMaxAttempts, t, id); this.verFail.fail(ip); throw bad();
    }
    const r = this.store.q('UPDATE otp_challenges SET consumed_at=? WHERE id=? AND consumed_at IS NULL AND invalidated_at IS NULL AND expires_at > ?').run(t, id, t);
    if (r.changes !== 1) { this.verFail.fail(ip); throw bad(); }   /* lost a race with another verify: single use */
    this.verFail.clear(ip); return { userId: row.user_id };
  }
}
module.exports = { OtpService, OtpError };
