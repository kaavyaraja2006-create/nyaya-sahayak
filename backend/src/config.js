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
  };
}
module.exports = { load };
