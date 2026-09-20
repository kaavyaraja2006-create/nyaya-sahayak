'use strict';
/* OPTIONAL demo data. The app ships empty; run this once, on purpose, to fill a fresh data folder with clearly fictional
   accounts, cases, hearings, a transcript, lawyer profiles, requests and chat so every screen has something to show.
     cd backend && npm run seed            (uses ./data, or DATA_DIR)
   Everything below is invented. Do not use real personal data here. */
const fs = require('fs'), path = require('path');
const { createServer } = require('../src/server');
const DATA = process.env.DATA_DIR ? path.resolve(process.env.DATA_DIR) : path.join(__dirname, '..', 'data');
const FIX = path.join(__dirname, '..', '..', 'frontend', 'tests', 'e2e-data');
const PW = 'Demo@12345';
const day = (d, h = 10) => { const t = new Date(Date.now() + d * 86400000); t.setHours(h, 0, 0, 0); return t.toISOString(); };
const b64 = s => Buffer.from(s, 'utf8').toString('base64');
const read = f => fs.readFileSync(path.join(FIX, f));

(async () => {
  const app = createServer({ dataDir: DATA, port: 0, logLevel: 'error', paceMs: 0, otpDelivery: 'memory', otpResendSeconds: 0, otpRequestsPerWindow: 50, otpIpRequestsPerWindow: 100, adminEmails: 'admin@demo.example' });
  const a = await app.listen(); const base = `http://127.0.0.1:${a.port}`;
  const call = async (method, p, body, token) => { const r = await fetch(base + '/api' + p, { method, headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: body !== undefined ? JSON.stringify(body) : undefined }); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(`${method} ${p} -> ${r.status} ${JSON.stringify(j.error || j)}`); return j; };
  const step = m => process.stdout.write('  · ' + m + '\n');
  try {
    if (app.host.DB.users.length) { console.log('This data folder already has accounts (' + DATA + ').\nUse a fresh folder:  DATA_DIR=./demo-data npm run seed   then   DATA_DIR=./demo-data npm start'); await app.close(); return; }
    console.log('Seeding demo data into ' + DATA + '\n');
    const accounts = {};
    const signup = async (key, fullName, email, role, phone, extra = {}) => {
      const j = await call('POST', '/auth/signup', { fullName, email, phone, password: PW, confirm: PW, role, ...extra });
      if (role === 'LAWYER') { const code = app.otp.outbox.filter(o => o.to === phone.replace(/\s/g, '')).pop().code; const v = await call('POST', '/auth/lawyer/otp/verify', { challengeId: j.challengeId, otp: code }); accounts[key] = { token: v.token, user: v.user, email, phone, enrol: extra.registrationNumber }; }
      else accounts[key] = { token: j.token, user: j.user, email };
    };
    step('accounts');
    await signup('admin', 'Asha Verma (demo admin)', 'admin@demo.example', 'OTHER', '+91 90000 00001');
    await signup('judge', 'Justice R. Krishnan', 'judge@demo.example', 'JUDGE', '+91 90000 00002', { organization: 'Sessions Court, Chennai (fictional)' });
    await signup('steno', 'Suresh Babu', 'steno@demo.example', 'STENOGRAPHER', '+91 90000 00003', { organization: 'Sessions Court, Chennai (fictional)' });
    await signup('meera', 'Adv. Meera Nair', 'meera@demo.example', 'LAWYER', '+91 90000 00011', { registrationNumber: 'TN/2001/2012', experienceYears: 12, specialization: 'Civil and property' });
    await signup('arjun', 'Adv. Arjun Reddy', 'arjun@demo.example', 'LAWYER', '+91 90000 00012', { registrationNumber: 'TN/3410/2015', experienceYears: 9, specialization: 'Criminal defence' });
    await signup('divya', 'Adv. Divya Iyer', 'divya@demo.example', 'LAWYER', '+91 90000 00013', { registrationNumber: 'TN/5120/2019', experienceYears: 5, specialization: 'Family' });
    await signup('kumar', 'Ravi Kumar (demo client)', 'kumar@demo.example', 'CLIENT', '+91 90000 00021');
    await signup('anita', 'Anita Joseph (demo client)', 'anita@demo.example', 'CLIENT', '+91 90000 00022');
    const T = k => accounts[k].token, U = k => accounts[k].user.id;

    step('lawyer profiles and verification (Divya is left unverified so the verification desk has work)');
    await call('PUT', '/lawyer/profile', { practiceAreas: ['Civil', 'Property', 'Contract'], city: 'Chennai', state: 'Tamil Nadu', courts: ['Madras High Court', 'City Civil Court, Chennai'], feeMin: 20000, feeMax: 75000, feeNote: 'Per appearance; first consultation free', experienceYears: 12, listed: true }, T('meera'));
    await call('PUT', '/lawyer/profile', { practiceAreas: ['Criminal'], city: 'Chennai', state: 'Tamil Nadu', courts: ['Sessions Court, Chennai', 'Madras High Court'], feeMin: 30000, feeMax: 120000, feeNote: 'Fixed fee for a bail application', experienceYears: 9, listed: true }, T('arjun'));
    await call('PUT', '/lawyer/profile', { practiceAreas: ['Family', 'Civil'], city: 'Madurai', state: 'Tamil Nadu', courts: ['Family Court, Madurai'], feeMin: 10000, feeMax: 40000, experienceYears: 5, listed: true }, T('divya'));
    await call('POST', `/admin/lawyers/${U('meera')}/verify`, {}, T('admin')); await call('POST', `/admin/lawyers/${U('arjun')}/verify`, {}, T('admin'));

    step('case 1: criminal matter with documents, authorities, analysis, one recorded hearing and one upcoming');
    const c1 = (await call('POST', '/cases', { name: 'State v. Person A (Northgate depot incident)', number: 'SC/114/2026', type: 'Criminal', jurisdiction: 'Chennai', court: 'Sessions Court, Chennai', description: 'Fictional demonstration case. Review of witness statements and CCTV records about an evening incident.' }, T('steno'))).case.id;
    await call('PUT', `/cases/${c1}/assignment`, { judgeId: U('judge'), lawyerIds: [U('arjun'), U('meera')] }, T('steno'));
    for (const f of ['PW-3 Statement.txt', 'PW-5 Statement.txt', 'CCTV Review Report.txt', 'Device Location Record.txt', 'Incident Report.txt', 'Written Submission.txt']) await call('POST', `/cases/${c1}/documents`, { filename: f, contentBase64: read(f).toString('base64') }, T('arjun'));
    for (const au of JSON.parse(read('authorities.json').toString())) await call('POST', '/authorities', { ...au, kind: 'Judgment' }, T('arjun'));
    const h1 = (await call('POST', `/cases/${c1}/hearings`, { scheduledAt: day(-9), title: 'Examination of PW-3', publicNote: 'Witness examination' }, T('steno'))).hearing.id;
    await call('POST', `/cases/${c1}/hearings/start`, { hearingId: h1, judgeId: U('judge'), lawyerIds: [U('arjun'), U('meera')] }, T('steno'));
    const tx = read('Hearing 3 transcript.txt').toString();
    await call('PUT', `/cases/${c1}/hearings/${h1}/draft`, { text: tx, baseRev: 0 }, T('steno'));
    await call('POST', `/cases/${c1}/hearings/${h1}/transcript`, { text: tx }, T('steno'));
    await call('POST', `/cases/${c1}/hearings/${h1}/end`, { note: 'Adjourned for cross-examination of PW-5.' }, T('steno'));
    await call('POST', `/cases/${c1}/hearings`, { scheduledAt: day(6), title: 'Cross-examination of PW-5', publicNote: 'Please arrive by 10:00' }, T('steno'));
    await call('POST', `/cases/${c1}/hearings`, { scheduledAt: day(13), title: 'Chambers conference', isPublic: false }, T('judge'));
    await call('PUT', `/cases/${c1}/public`, { enabled: true, title: 'State v. Person A', summary: 'Fictional sessions case about an evening incident near a depot.' }, T('judge'));
    await call('POST', `/cases/${c1}/analyze`, {}, T('arjun'));
    for (let i = 0; i < 200; i++) { const r = await call('GET', `/cases/${c1}/analysis`, undefined, T('arjun')); if (r.analysis && r.analysis.status !== 'running') break; await new Promise(r => setTimeout(r, 100)); }

    step('case 2: civil deposit dispute with a recorded, public hearing (gives Adv. Nair court-recorded history)');
    const c2 = (await call('POST', '/cases', { name: 'Sundaram v. Greenview Apartments (deposit)', number: 'OS/58/2026', type: 'Civil', jurisdiction: 'Chennai', court: 'City Civil Court, Chennai', description: 'Fictional demonstration case: refund of a rental security deposit.' }, T('steno'))).case.id;
    await call('PUT', `/cases/${c2}/assignment`, { judgeId: U('judge'), lawyerIds: [U('meera')] }, T('steno'));
    await call('POST', `/cases/${c2}/documents`, { filename: 'Tenancy Summary.txt', contentBase64: b64('[Synthetic demonstration material]\n\nThe tenancy began on 1 April 2024 with a security deposit of Rs 60,000. The tenant vacated on 30 June 2025 and returned the keys on the same day. The landlord acknowledged receipt of the keys in writing on 1 July 2025.\n\nThe agreement states that the deposit is refundable within thirty days of vacating, less proven damage.\n') }, T('meera'));
    await call('POST', `/cases/${c2}/documents`, { filename: 'Sundaram Statement.txt', contentBase64: b64('[Synthetic demonstration material]\n\nMr Sundaram states that he vacated the flat on 30 June 2025 and that no damage was recorded at handover. He states that he has not received the deposit despite two written reminders in August and October 2025.\n') }, T('meera'));
    const h2 = (await call('POST', `/cases/${c2}/hearings`, { scheduledAt: day(-20), title: 'Framing of issues' }, T('steno'))).hearing.id;
    await call('POST', `/cases/${c2}/hearings/start`, { hearingId: h2, judgeId: U('judge'), lawyerIds: [U('meera')] }, T('steno'));
    const tx2 = '11:02:10 Judge: Call the matter. Appearances?\n11:02:24 Counsel (Plaintiff): Meera Nair for the plaintiff, Your Honour.\n11:02:40 Judge: Issues are framed as per the memo. List for evidence.\n';
    await call('PUT', `/cases/${c2}/hearings/${h2}/draft`, { text: tx2, baseRev: 0 }, T('steno')); await call('POST', `/cases/${c2}/hearings/${h2}/transcript`, { text: tx2 }, T('steno')); await call('POST', `/cases/${c2}/hearings/${h2}/end`, { note: 'Listed for plaintiff evidence.' }, T('steno'));
    await call('POST', `/cases/${c2}/hearings`, { scheduledAt: day(21), title: 'Plaintiff evidence' }, T('steno'));
    await call('POST', `/cases/${c2}/analyze`, {}, T('meera'));
    for (let i = 0; i < 200; i++) { const r = await call('GET', `/cases/${c2}/analysis`, undefined, T('meera')); if (r.analysis && r.analysis.status !== 'running') break; await new Promise(r => setTimeout(r, 100)); }
    await call('PUT', `/cases/${c2}/public`, { enabled: true, title: 'Sundaram v. Greenview Apartments', summary: 'Fictional civil suit for refund of a security deposit.' }, T('judge'));

    step('lawyer requests and a private conversation');
    const rq = (await call('POST', '/requests', { lawyerId: U('meera'), description: 'My landlord in Chennai has not refunded my Rs 60,000 security deposit for over a year despite two written reminders.', caseType: 'Civil', city: 'Chennai', court: 'City Civil Court, Chennai', budget: 50000 }, T('kumar'))).request;
    await call('POST', `/requests/${rq.id}/decision`, { decision: 'ACCEPTED', note: 'Happy to help. Please share the tenancy agreement.' }, T('meera'));
    for (const [who, body] of [['kumar', 'Thank you. I have the agreement and both reminder letters.'], ['meera', 'Good. Please send copies. A legal notice is the first step; my fee for it is about Rs 15,000.'], ['kumar', 'That works for me. I will bring them tomorrow at 11.'], ['meera', 'Perfect, see you then.']]) await call('POST', `/requests/${rq.id}/messages`, { body }, T(who));
    await call('POST', '/requests', { lawyerId: U('arjun'), description: 'My brother was named in an FIR about an incident at a depot. We need advice on anticipatory bail.', caseType: 'Criminal', city: 'Chennai', budget: 100000 }, T('anita'));

    const line = '─'.repeat(78);
    console.log(`\nDone. Everything above is fictional.\n${line}\nAll demo accounts use the password  ${PW}\n${line}`);
    console.log('Court staff & admin (sign in with email + password at #/login)');
    console.log('  judge@demo.example      Judge          sees both cases in full, manages people and public tracking');
    console.log('  steno@demo.example      Stenographer   court desk, start hearing, typing area, hearing-only view');
    console.log('  admin@demo.example      Administrator  Verify lawyers (Adv. Divya Iyer is waiting)');
    console.log('  kumar@demo.example      Client         has an accepted request with a chat');
    console.log('  anita@demo.example      Client         has a pending request');
    console.log('Lawyers (sign in at #/login/lawyer with enrolment number + mobile; the code appears in the server terminal)');
    console.log('  Adv. Meera Nair    enrolment TN/2001/2012   mobile 9000000011   civil; has the accepted chat and a public recorded case');
    console.log('  Adv. Arjun Reddy   enrolment TN/3410/2015   mobile 9000000012   criminal; assigned to case 1, has the analysis and a pending request');
    console.log('  Adv. Divya Iyer    enrolment TN/5120/2019   mobile 9000000013   not yet verified');
    console.log(`${line}\nPublic tracking (no sign-in):  #/track/${c1}   and   #/track/${c2}`);
    console.log('Find a lawyer (no sign-in):    #/find-lawyer   try: Civil · Chennai · "security deposit"');
    console.log(`${line}\nStart the app on this data:  ${process.env.DATA_DIR ? 'DATA_DIR=' + process.env.DATA_DIR + ' ' : ''}ADMIN_EMAILS=admin@demo.example npm start`);
  } catch (e) { console.error('\nSeeding failed:', e.message); process.exitCode = 1; }
  finally { await app.close(); }
})();
