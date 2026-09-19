/* ===== 01 store: persistence (browser prototype; replaced by REST + SQLite in the backend build) ===== */
const KEY_DB = 'nyayasahayak.db.v1', KEY_SESSION = 'nyayasahayak.session.v1', KEY_PREFS = 'nyayasahayak.prefs.v1';
const memStore = {};
const safeLS = {
  get(k) { try { const v = window.localStorage.getItem(k); return v == null ? (memStore[k] ?? null) : v; } catch (e) { return memStore[k] ?? null; } },
  set(k, v) { memStore[k] = v; try { window.localStorage.setItem(k, v); return true; } catch (e) { return false; } },
  del(k) { delete memStore[k]; try { window.localStorage.removeItem(k); } catch (e) {} },
};
let DB = null, storageWarn = false;
const listeners = new Set();
function loadDB() {
  if (DB) return DB;
  try { DB = JSON.parse(safeLS.get(KEY_DB) || 'null'); } catch (e) { DB = null; }
  if (!DB || typeof DB !== 'object') DB = { version: 1, users: [], cases: [], counters: {}, authorities: [] };
  if (!Array.isArray(DB.authorities)) DB.authorities = [];
  return DB;
}
let SERVER_MODE = false; const setServerMode = v => { SERVER_MODE = !!v; };
function saveDB() {
  if (SERVER_MODE) return true;
  const ok = safeLS.set(KEY_DB, JSON.stringify(DB));
  storageWarn = !ok; return ok;
}
const subscribe = fn => { listeners.add(fn); return () => listeners.delete(fn); };
const notify = () => listeners.forEach(fn => { try { fn(); } catch (e) { console.error(e); } });
function commit() { saveDB(); notify(); }

/* preferences */
const DEFAULT_PREFS = { theme: 'light', density: 'comfortable', reduceMotion: false, autoNight: false, nightFrom: '22:00', nightTo: '06:00', sidebarCollapsed: false, conflictSensitivity: 'standard', piiRedaction: true, showTechnical: false };
let PREFS = null;
function prefs() { if (!PREFS) { try { PREFS = Object.assign({}, DEFAULT_PREFS, JSON.parse(safeLS.get(KEY_PREFS) || '{}')); } catch (e) { PREFS = { ...DEFAULT_PREFS }; } } return PREFS; }
function setPref(k, v) { prefs()[k] = v; safeLS.set(KEY_PREFS, JSON.stringify(PREFS)); notify(); }

/* session */
function getSession() { try { const s = JSON.parse(safeLS.get(KEY_SESSION) || 'null'); if (s && s.exp > Date.now()) return s; } catch (e) {} return null; }
function setSession(s) { if (s) safeLS.set(KEY_SESSION, JSON.stringify(s)); else safeLS.del(KEY_SESSION); }
