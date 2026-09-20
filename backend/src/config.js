'use strict';
const path = require('path');
const env = process.env;
const num = (v, d) => { const n = Number(v); return Number.isFinite(n) && n > 0 ? n : d; };
function load(over = {}) {
  const root = path.resolve(__dirname, '..');
  const dataDir = path.resolve(over.dataDir || env.DATA_DIR || path.join(root, 'data'));
  return {
    port: over.port != null ? over.port : (env.PORT !== undefined && env.PORT !== '' && Number.isFinite(Number(env.PORT)) ? Number(env.PORT) : 8000),
    host: over.host || env.HOST || '127.0.0.1',
    dataDir,
    dbFile: over.dbFile || env.DATABASE_FILE || path.join(dataDir, 'nyayasahayak.db'),
    uploadsDir: path.join(dataDir, 'uploads'),
    secretKey: over.secretKey || env.SECRET_KEY || '',
    tokenMinutes: num(over.tokenMinutes || env.ACCESS_TOKEN_EXPIRE_MINUTES, 60),
    corsOrigins: (over.corsOrigins || env.CORS_ORIGINS || '').split(',').map(s => s.trim()).filter(Boolean),
    maxUploadBytes: num(over.maxUploadBytes || env.MAX_UPLOAD_MB, 8) * (over.maxUploadBytes ? 1 : 1024 * 1024),
    logLevel: over.logLevel || env.LOG_LEVEL || 'info',
    geminiKey: over.geminiKey != null ? over.geminiKey : (env.GEMINI_API_KEY || ''),
    geminiModel: over.geminiModel || env.GEMINI_MODEL || env.AI_MODEL || 'gemini-2.5-flash',
    paceMs: over.paceMs != null ? over.paceMs : num(env.ANALYSIS_PACE_MS, 150),
    staticFile: over.staticFile || path.join(root, '..', 'dist', 'index.html'),
    loginMaxFailures: num(over.loginMaxFailures || env.LOGIN_MAX_FAILURES, 5),
    loginWindowMs: num(over.loginWindowMs || env.LOGIN_WINDOW_MS, 15 * 60 * 1000),
    production: env.NODE_ENV === 'production',
    /* one-time passwords for lawyer sign-in */
    otpDelivery: over.otpDelivery || (env.SMS_WEBHOOK_URL ? 'webhook' : 'console'),   /* 'webhook' | 'console' (development) | 'memory' (tests only, set in code) */
    smsWebhookUrl: over.smsWebhookUrl != null ? over.smsWebhookUrl : (env.SMS_WEBHOOK_URL || ''),
    smsWebhookToken: env.SMS_WEBHOOK_TOKEN || '',
    otpTtlSeconds: num(over.otpTtlSeconds || env.OTP_TTL_SECONDS, 300),
    otpMaxAttempts: num(over.otpMaxAttempts || env.OTP_MAX_ATTEMPTS, 5),
    otpResendSeconds: over.otpResendSeconds != null ? over.otpResendSeconds : num(env.OTP_RESEND_SECONDS, 30),
    otpRequestsPerWindow: num(over.otpRequestsPerWindow || env.OTP_REQUESTS_PER_WINDOW, 3),
    otpIpRequestsPerWindow: num(over.otpIpRequestsPerWindow || env.OTP_IP_REQUESTS_PER_WINDOW, 10),
    otpVerifyFailuresPerWindow: num(over.otpVerifyFailuresPerWindow || env.OTP_VERIFY_FAILURES, 10),
    otpWindowMs: num(over.otpWindowMs || env.OTP_WINDOW_MS, 15 * 60 * 1000),
    /* accounts (by e-mail) allowed to verify lawyers / judges / stenographers */
    adminEmails: (over.adminEmails || env.ADMIN_EMAILS || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean),
    /* public endpoints (no sign-in): requests per minute per client address */
    publicPerMinute: num(over.publicPerMinute || env.PUBLIC_RATE_PER_MIN, 40),
    messagesPerMinute: num(over.messagesPerMinute || env.MESSAGES_PER_MIN, 30),
  };
}
module.exports = { load };
