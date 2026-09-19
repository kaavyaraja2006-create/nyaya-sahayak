/* ===== 02 auth: local prototype accounts (PBKDF2 when available). Not a substitute for backend JWT auth. ===== */
const ROLES = [['LAWYER', 'Lawyer'], ['JUDGE', 'Judge'], ['STENOGRAPHER', 'Court stenographer'], ['LEGAL_INTERN', 'Legal intern'], ['LEGAL_RESEARCHER', 'Legal researcher'], ['LAW_STUDENT', 'Law student'], ['CLIENT', 'Client (looking for a lawyer)'], ['OTHER', 'Other']];
/* Case-assigned roles: their access to a case comes only from being assigned to it (see caseAccess in 05). */
const STAFF_ROLES = ['LAWYER', 'JUDGE', 'STENOGRAPHER'];
/* Mobile numbers are compared in one canonical form (+CC digits). Returns null when the value is not a plausible mobile number. */
function normPhone(p) {
  let s = String(p || '').replace(/[\s().-]/g, ''); if (!s) return null;
  if (/^\+\d{8,15}$/.test(s)) return s;
  if (/^0?[6-9]\d{9}$/.test(s)) return '+91' + s.slice(-10);
  if (/^91[6-9]\d{9}$/.test(s)) return '+' + s;
  return null;
}
/* State Bar Council enrolment numbers look like D/1234/2015 or TN/123/2018. Stored upper-case without spaces. */
const normEnroll = e => String(e || '').toUpperCase().replace(/\s+/g, '');
const validEnroll = e => /^[A-Z0-9][A-Z0-9/.-]{3,29}$/.test(normEnroll(e)) && /\d/.test(e);
const roleLabel = r => (ROLES.find(x => x[0] === r) || [0, r])[1];
const enc = new TextEncoder();
const toHex = buf => Array.from(new Uint8Array(buf)).map(b => pad(b.toString(16))).join('');
async function hashPassword(pw, saltHex) {
  const salt = saltHex || rid(16);
  try {
    if (typeof crypto !== 'undefined' && crypto.subtle) {
      const key = await crypto.subtle.importKey('raw', enc.encode(pw), 'PBKDF2', false, ['deriveBits']);
      const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', salt: enc.encode(salt), iterations: 120000, hash: 'SHA-256' }, key, 256);
      return `pbkdf2$${salt}$${toHex(bits)}`;
    }
  } catch (e) {}
  let h = 2166136261; const s = salt + pw; for (let i = 0; i < 4000; i++) for (let j = 0; j < s.length; j++) { h ^= s.charCodeAt(j); h = Math.imul(h, 16777619) >>> 0; }
  return `fnv$${salt}$${h.toString(16)}`;
}
function validEmail(e) { return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(e); }
async function signup(f) {
  const db = loadDB(); const errors = {};
  if (!f.fullName || f.fullName.trim().length < 2) errors.fullName = 'Enter your full name.';
  if (!validEmail(f.email || '')) errors.email = 'Enter a valid email address.';
  if (!/^[+\d][\d\s()-]{6,}$/.test(f.phone || '')) errors.phone = 'Enter a valid phone number.';
  if (!f.password || f.password.length < 8) errors.password = 'Use at least 8 characters.';
  if (f.password !== f.confirm) errors.confirm = 'Passwords do not match.';
  if (!ROLES.some(r => r[0] === f.role)) errors.role = 'Select a professional role.';
  if (f.role === 'LAWYER') {
    if (!validEnroll(f.registrationNumber)) errors.registrationNumber = 'Enter your State Bar Council enrolment number (for example D/1234/2015).';
    else if (db.users.some(u => u.role === 'LAWYER' && normEnroll(u.registrationNumber) === normEnroll(f.registrationNumber))) errors.registrationNumber = 'A lawyer account already exists for this enrolment number.';
    if (!normPhone(f.phone)) errors.phone = 'Enter the mobile number registered with your Bar Council (for example +91 98765 43210). OTPs are sent to it.';
  }
  if (Object.keys(errors).length) return { ok: false, errors };
  const email = f.email.trim().toLowerCase();
  if (db.users.some(u => u.email === email)) return { ok: false, errors: { email: 'An account with this email already exists.' } };
  const user = { id: 'U-' + rid(6), fullName: f.fullName.trim(), email, phone: f.phone.trim(), passwordHash: await hashPassword(f.password), role: f.role, organization: (f.organization || '').trim(), registrationNumber: f.role === 'LAWYER' ? normEnroll(f.registrationNumber) : (f.registrationNumber || '').trim(), experienceYears: f.experienceYears ? Number(f.experienceYears) : null, specialization: (f.specialization || '').trim(), verified: false, mobileVerified: false, profile: {}, createdAt: nowISO(), updatedAt: nowISO() };
  db.users.push(user); commit();
  return { ok: true, user: startSession(user) };
}
function startSession(user) { const s = { token: rid(24), userId: user.id, exp: Date.now() + 60 * 60 * 1000 * 8 }; setSession(s); return user; }
async function login(email, password) {
  const db = loadDB(); const u = db.users.find(x => x.email === String(email || '').trim().toLowerCase());
  const fail = { ok: false, error: 'Invalid email or password.' };
  if (!u) { await hashPassword(password || 'x'); return fail; }
  const parts = u.passwordHash.split('$'); const h = await hashPassword(password || '', parts[1]);
  if (h !== u.passwordHash) return fail;
  return { ok: true, user: startSession(u) };
}
function logout() { setSession(null); }
function currentUser() { const s = getSession(); if (!s) return null; return loadDB().users.find(u => u.id === s.userId) || null; }
const publicUser = u => u && ({ id: u.id, fullName: u.fullName, email: u.email, role: u.role, organization: u.organization, specialization: u.specialization, verified: !!u.verified });
const initials = n => String(n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
