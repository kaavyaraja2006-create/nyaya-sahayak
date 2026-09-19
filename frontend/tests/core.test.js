const fs=require('fs'); const store={}; globalThis.localStorage={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=String(v)},removeItem:k=>{delete store[k]}};
require('../dist/core.js'); const N=globalThis.NS; const assert=require('assert');
let pass=0, fail=0; const T=[]; const test=(n,f)=>T.push([n,f]);
const user=async(email,name='Test User')=>(await N.signup({fullName:name,email,phone:'+91 9876543210',password:'password1',confirm:'password1',role:'LAWYER'})).user;
const fileLike=(buf,name)=>({name,size:buf.length,arrayBuffer:async()=>buf.buffer.slice(buf.byteOffset,buf.byteOffset+buf.byteLength),text:async()=>buf.toString('utf8')});

test('signup validates and hashes passwords',async()=>{
  const bad=await N.signup({fullName:'',email:'x',phone:'1',password:'a',confirm:'b',role:''}); assert(!bad.ok && bad.errors.email && bad.errors.password && bad.errors.confirm && bad.errors.role);
  const u=await user('one@test.io'); const db=N.loadDB(); const rec=db.users.find(x=>x.id===u.id); assert(rec.passwordHash.startsWith('pbkdf2$')); assert(!JSON.stringify(rec).includes('password1'));
  const dup=await N.signup({fullName:'Dup',email:'ONE@test.io',phone:'+91 9876543210',password:'password1',confirm:'password1',role:'LAWYER'}); assert(!dup.ok && dup.errors.email);
});
test('login: generic error, no field leak',async()=>{
  const a=await N.login('one@test.io','wrong'); const b=await N.login('nobody@test.io','password1'); assert(!a.ok&&!b.ok&&a.error===b.error&&a.error==='Invalid email or password.');
  const ok=await N.login('one@test.io','password1'); assert(ok.ok); assert(N.currentUser().email==='one@test.io'); N.logout(); assert(N.currentUser()===null);
});
test('case ownership isolation across users (services + MCP)',async()=>{
  const A=await user('a@test.io','User A'); const B=await user('b@test.io','User B'); const C=N.createDemoCase(A.id);
  assert.throws(()=>N.CaseSvc.get(B.id,C.id),e=>e.code==='PERMISSION_DENIED'); assert.strictEqual(N.CaseSvc.list(B.id).length,0);
  for(const t of ['get_case_material','get_claims','get_audit_history']){ const r=N.mcpCall(t,{case_id:C.id},{userId:B.id}); assert.strictEqual(r.error.code,'PERMISSION_DENIED',t); }
  assert.strictEqual(N.mcpCall('get_claims',{case_id:C.id},{}).error.code,'UNAUTHENTICATED');
  assert.strictEqual(N.searchAll(B.id,'Person A').length>=0,true); assert(!N.searchAll(B.id,'depot').some(r=>r.group==='Claims'));
  assert.throws(()=>N.DocSvc.add(B.id,C.id,{filename:'x.txt',text:'hello world'}),e=>e.code==='PERMISSION_DENIED');
});
test('MCP validation and structured errors',async()=>{
  const A=await user('v@test.io'); const C=N.createDemoCase(A.id); const ctx={userId:A.id};
  assert.strictEqual(N.mcpCall('get_claims',{},ctx).error.code,'VALIDATION_ERROR'); assert.strictEqual(N.mcpCall('get_claims',{case_id:'../etc/passwd'},ctx).error.code,'VALIDATION_ERROR');
  assert.strictEqual(N.mcpCall('get_claims',{case_id:'NS-1999-999'},ctx).error.code,'CASE_NOT_FOUND'); assert.strictEqual(N.mcpCall('get_authority_excerpt',{authority_id:'AUTH-999'},ctx).error.code,'AUTHORITY_NOT_FOUND');
  assert.strictEqual(N.mcpCall('nope',{},ctx).error.code,'TOOL_NOT_FOUND'); assert.strictEqual(N.mcpCall('get_evidence',{case_id:C.id,claim_id:'C-99'},ctx).error.code,'CLAIM_NOT_FOUND');
  assert.strictEqual(N.mcpCall('search_authorities',{query:'x'.repeat(2500)},ctx).error.code,'VALIDATION_ERROR'); assert.strictEqual(N.mcpCall('search_authorities',{query:'witness',limit:99},ctx).error.code,'VALIDATION_ERROR');
  const raw=JSON.stringify(N.mcpCall('get_claims',{case_id:'NS-1999-999'},ctx)); assert(!/stack|at\s.*\(/i.test(raw));
});
test('full pipeline on synthetic case: claims, conflicts, evidence, authorities, citations, findings',async()=>{
  const A=await user('p@test.io'); const C0=N.createDemoCase(A.id); assert(C0.synthetic); await N.runAnalysis(A.id,C0.id,{paceMs:0}); const C=N.ownedCase(A.id,C0.id);
  assert.strictEqual(C.analysis.status,'completed'); assert(C.claims.length>=15); assert(C.conflicts.length>=2); assert(C.evidence.length>=10); assert(C.citations.some(x=>x.result==='UNRESOLVED')); assert(C.citations.some(x=>x.result==='MISSING_CITATION')); assert(C.citations.some(x=>x.result==='POTENTIALLY_RELEVANT'));
  assert(C.claims.every(c=>c.sourceDocId&&c.page&&c.para&&c.confidence>=0.3&&c.confidence<=0.97)); assert(C.claims.every(c=>{const d=C.documents.find(x=>x.id===c.sourceDocId); return d.pages[c.page-1].paras[c.para-1].text.slice(c.start,c.end)===c.text;}),'offsets point at exact source text');
  assert(C.conflicts.every(k=>k.severity==='REVIEW_REQUIRED'&&/Human verification is required/.test(k.description)&&!/\b(lying|liar|guilty|perjur)/i.test(k.description)));
  assert(C.claims.every(c=>c.supportStrength>=0&&c.supportStrength<=100&&c.conflictStrength>=0&&c.conflictStrength<=100));
  const names=C.agentRuns.map(r=>r.agent); assert.deepStrictEqual(names,N.PIPELINE.map(a=>a.name)); assert(C.agentRuns.every(r=>r.completedAt&&r.durationMs>=0));
  const tools=new Set(C.toolCalls.map(t=>t.tool)); N.MCP_TOOL_NAMES.forEach(t=>assert(tools.has(t),'tool used: '+t));
  assert(C.authorityLinks.every(l=>N.AUTHORITIES.some(a=>a.id===l.authorityId)&&l.passage.length>10));
  assert.strictEqual(C.status,'ACTIVE_REVIEW'); assert(C.audit.some(e=>e.event==='CONFLICT_DETECTED')&&C.audit.some(e=>e.event==='CLAIM_EXTRACTED'));
});
test('reruns keep claim ids and reviews stable',async()=>{
  const A=await user('r@test.io'); const C0=N.createDemoCase(A.id); await N.runAnalysis(A.id,C0.id,{paceMs:0}); let C=N.ownedCase(A.id,C0.id);
  const f=C.findings.find(x=>x.kind==='CLAIM'); N.ReviewSvc.save(A.id,C.id,f.id,{action:'accept',comment:''}); const ids=C.claims.map(c=>c.id).join();
  await N.runAnalysis(A.id,C.id,{paceMs:0}); C=N.ownedCase(A.id,C.id); assert.strictEqual(C.claims.map(c=>c.id).join(),ids); assert.strictEqual(N.findingStatus(C,C.findings.find(x=>x.id===f.id)),'ACCEPTED');
});
test('human review: record + audit + status, never overwrites AI finding',async()=>{
  const A=await user('h@test.io'); const C0=N.createDemoCase(A.id); await N.runAnalysis(A.id,C0.id,{paceMs:0}); const C=N.ownedCase(A.id,C0.id);
  const f=C.findings.find(x=>x.kind==='CONFLICT'); const before=JSON.stringify({why:f.why,title:f.title,claimIds:f.claimIds}); const n=C.audit.length;
  assert.throws(()=>N.ReviewSvc.save(A.id,C.id,f.id,{action:'comment',comment:' '}),e=>e.code==='VALIDATION'); assert.throws(()=>N.ReviewSvc.save(A.id,C.id,f.id,{action:'bogus'}),e=>e.code==='VALIDATION'); assert.throws(()=>N.ReviewSvc.save(A.id,C.id,f.id,{action:'modify',modifiedText:''}),e=>e.code==='VALIDATION');
  const rv=N.ReviewSvc.save(A.id,C.id,f.id,{action:'verify',comment:'Verify device ownership.'}); assert.strictEqual(rv.previousStatus,'PENDING'); assert.strictEqual(rv.newStatus,'NEEDS_VERIFICATION');
  assert.strictEqual(N.findingStatus(C,f),'NEEDS_VERIFICATION'); assert(C.audit.length>=n+3); assert(C.audit.slice(n).some(e=>e.event==='REVIEWER_ADDED_COMMENT')&&C.audit.slice(n).some(e=>e.event==='REVIEW_SAVED'));
  assert.strictEqual(JSON.stringify({why:f.why,title:f.title,claimIds:f.claimIds}),before);
  const rv2=N.ReviewSvc.save(A.id,C.id,f.id,{action:'comment',comment:'Note only'}); assert.strictEqual(rv2.newStatus,'NEEDS_VERIFICATION'); assert.strictEqual(C.reviews.length,2);
  const cf=C.findings.find(x=>x.kind==='CLAIM'); N.ReviewSvc.save(A.id,C.id,cf.id,{action:'modify',modifiedText:'Reworded claim'}); const cl=C.claims.find(c=>c.id===cf.claimIds[0]); assert(cl.text&&cl.text!=='Reworded claim'); assert.strictEqual(N.claimStatus(C,cl),'MODIFIED');
});
test('file parsers: txt, docx, pdf (reportlab + own writer), limits',async()=>{
  const t=await N.parseFile(fileLike(fs.readFileSync('tests/fixture.txt'),'a.txt')); assert(t.ok&&/Person C/.test(t.text));
  const d=await N.parseFile(fileLike(fs.readFileSync('tests/fixture.docx'),'a.docx')); assert(d.ok,d.error); assert(d.text.includes('\f')&&d.text.includes('Person B near Location D')&&d.text.includes('& the log shows <this>'),d.text);
  assert.strictEqual(N.splitPages(d.text).length,2);
  const p=await N.parseFile(fileLike(fs.readFileSync('tests/fixture.pdf'),'a.pdf')); assert(p.ok,p.error); const pp=N.splitPages(p.text); assert.strictEqual(pp.length,2); assert(/near Location D with a red bag/.test(pp[0].paras.map(x=>x.text).join(' ')),JSON.stringify(pp)); assert(/Location E at 7:20 PM/.test(p.text));
  assert(!(await N.parseFile(fileLike(Buffer.from('x'),'a.exe'))).ok); assert(!(await N.parseFile({name:'a.txt',size:9e6})).ok); assert(!(await N.parseFile({name:'a.txt',size:0})).ok);
  const bad=await N.parseFile(fileLike(Buffer.from('not a zip at all'),'bad.docx')); assert(!bad.ok);
});
test('report JSON + generated PDF is structurally valid and round-trips through the PDF reader',async()=>{
  const A=await user('rep@test.io'); const C0=N.createDemoCase(A.id); await N.runAnalysis(A.id,C0.id,{paceMs:0}); N.localStorage; 
  const {rec,report}=N.ReportSvc.generate(A.id,C0.id); assert(rec.id==='RPT-001'); assert(/does not determine guilt/.test(report.disclaimer)); assert(report.syntheticLabel===undefined);
  const bytes=N.reportToPDF(report); const s=Buffer.from(bytes).toString('latin1'); assert(s.startsWith('%PDF-1.4')&&s.trimEnd().endsWith('%%EOF'));
  const xr=+s.match(/startxref\n(\d+)/)[1]; assert(s.slice(xr).startsWith('xref')); const cnt=+s.match(/xref\n0 (\d+)/)[1]; const offs=[...s.slice(xr).matchAll(/(\d{10}) 00000 n/g)].map(m=>+m[1]); assert.strictEqual(offs.length,cnt-1);
  offs.forEach((o,i)=>assert(s.slice(o).startsWith((i+1)+' 0 obj'),'xref offset '+(i+1)));
  const pages=(s.match(/\/Type \/Page /g)||[]).length; assert(pages>=2); fs.writeFileSync('/home/claude/ns/dist/sample-report.pdf',bytes);
  const back=await N.parsePdf(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)); assert(/Source-Traceable Audit Report/.test(back.text)&&/Potential location inconsistency/.test(back.text.replace(/\s+/g,' ')),back.text.slice(0,300));
  assert(N.CaseSvc.get(A.id,C0.id).audit.some(e=>e.event==='REPORT_GENERATED'));
  const js=JSON.stringify(report); assert(!/passwordHash|token/.test(js));
});
test('PII detection and redaction (basic, rule-based)',()=>{
  const t='Mail a.b@example.com or call 9876543210 / +91 98765 43210, id 1234 5678 9012.'; const d=N.detectPII(t); assert.strictEqual(d.email,1); assert(d.phone>=1); assert.strictEqual(d.aadhaarLike,1);
  const r=N.redactPII(t); assert(!/example\.com|9876543210|1234 5678 9012/.test(r));
});
test('authority library: per-user, no built-in authorities, retrieval only from the user\'s own text',async()=>{
  const A=await user('lib1@test.io'); const B=await user('lib2@test.io'); N.useLibrary(A.id); assert.strictEqual(N.AUTHORITIES.length,0,'app must ship with no authorities'); assert.deepStrictEqual(N.searchAuthorities('phone metadata handset',3),[]);
  N.createDemoCase(A.id); N.useLibrary(A.id); const r=N.searchAuthorities('phone metadata handset location cell tower',3); assert(r.length&&r[0].citation==='DEMO-002'&&r.every(x=>x.source==='authority_library'&&x.passage.length>20&&x.relevanceScore>0&&x.relevanceScore<=1),JSON.stringify(r));
  assert.deepStrictEqual(N.searchAuthorities('zzzz qqqq',3),[]);
  N.useLibrary(B.id); assert.strictEqual(N.AUTHORITIES.length,0,'user B must not see user A authorities'); assert.throws(()=>N.AuthSvc.remove(B.id,'AUTH-001'),e=>e.code==='AUTHORITY_NOT_FOUND');
  assert.throws(()=>N.AuthSvc.add(B.id,{title:'x',text:'short'}),e=>e.code==='VALIDATION'&&!!e.errors.title&&!!e.errors.text);
  const a=N.AuthSvc.add(B.id,{title:'Sample Act, 2001',citation:'Sample Act 2001',kind:'Statute',text:'12. A person who signs a contract must be given a copy of the signed contract within seven days.\n\n13. Notice of termination must be in writing.'}); assert.strictEqual(a.id,'AUTH-001'); assert.deepStrictEqual(a.paraNums,[12,13]);
  const mcp=N.mcpCall('search_authorities',{query:'notice of termination in writing',limit:2},{userId:B.id}); assert(mcp.results&&mcp.results[0].citation==='Sample Act 2001'); const mcpA=N.mcpCall('search_authorities',{query:'notice of termination in writing',limit:2},{userId:A.id}); assert(!mcpA.results.some(x=>x.citation==='Sample Act 2001'));
  N.AuthSvc.remove(B.id,'AUTH-001'); assert.strictEqual(N.AUTHORITIES.length,0);
});
test('citation audit resolves against the user library and says so when it is empty',async()=>{
  const A=await user('cit@test.io'); const C0=N.CaseSvc.create(A.id,{name:'Cit test'}); N.DocSvc.add(A.id,C0.id,{filename:'Sub.txt',category:'Written Submission',text:'It is submitted that a witness account gains weight when corroborated by independent surveillance records, see Sample Act 2001, paragraph 12.'});
  await N.runAnalysis(A.id,C0.id,{paceMs:0}); let C=N.ownedCase(A.id,C0.id); const c0=C.citations.filter(x=>x.kind==='CITATION'); assert(c0.length===0,'nothing to resolve without a library entry matching the code');
  N.AuthSvc.add(A.id,{title:'Sample Act, 2001',citation:'Sample Act 2001',kind:'Statute',text:'12. A witness account gains evidentiary weight when it is corroborated by independent surveillance records or device logs.\n\n13. Notice must be in writing.'});
  await N.runAnalysis(A.id,C0.id,{paceMs:0}); C=N.ownedCase(A.id,C0.id); const r=C.citations.find(x=>/Sample Act 2001/.test(x.citationText)); assert(r&&r.authorityId==='AUTH-001'&&r.result==='POTENTIALLY_RELEVANT'&&r.matchedPassage.idx===1,JSON.stringify(r));
});
test('engine: time ranges, PM inheritance, hedging, transcripts, empty input',()=>{
  const e=N.eventTime('The log shows the handset between 10:20 and 10:50 PM.'); assert.strictEqual(e.a,22*60+20); assert.strictEqual(e.b,22*60+50);
  assert.strictEqual(N.eventTime('at 12:05 a.m. he left').a,5); assert.strictEqual(N.eventTime('at 12 PM').a,720); assert.strictEqual(N.eventTime('nothing here'),null);
  const st=N.parseTranscript('10:06:18\nPW-3:\nignored\n[10:07:00] Judge: Proceed.\nQ: Where were you?\nA: At Location Z.'); assert(st.some(s=>s.speaker==='Judge'&&s.role==='Judge')&&st.some(s=>s.qkind==='QUESTION'));
  assert.strictEqual(N.splitPages('').length,1); assert.deepStrictEqual(N.parseTranscript(''),[]);
});
test('analysis handles empty/degraded input without crashing',async()=>{
  const A=await user('e@test.io'); const C=N.CaseSvc.create(A.id,{name:'Empty case'}); await assert.rejects(()=>N.runAnalysis(A.id,C.id,{paceMs:0}),e=>e.code==='NO_MATERIAL');
  N.DocSvc.add(A.id,C.id,{filename:'blank.txt',text:'   '}); await N.runAnalysis(A.id,C.id,{paceMs:0}); const X=N.ownedCase(A.id,C.id); assert.strictEqual(X.claims.length,0); assert(X.agentRuns.some(r=>r.status==='degraded')); assert.strictEqual(X.analysis.status,'completed');
  N.CaseSvc.archive(A.id,C.id); await assert.rejects(()=>N.runAnalysis(A.id,C.id,{paceMs:0}),e=>e.code==='ARCHIVED'); assert.throws(()=>N.DocSvc.add(A.id,C.id,{filename:'x.txt',text:'a b c'}),e=>e.code==='ARCHIVED');
});
test('concurrent analysis is rejected; unsafe filenames sanitized; XSS-safe escaping',async()=>{
  const A=await user('c@test.io'); const C=N.createDemoCase(A.id); const p=N.runAnalysis(A.id,C.id,{paceMs:5}); await assert.rejects(()=>N.runAnalysis(A.id,C.id,{paceMs:0}),e=>e.code==='ALREADY_RUNNING'); await p;
  const d=N.DocSvc.add(A.id,C.id,{filename:'../../etc/pass<script>.txt',text:'Person Q was near Location Q at 5:00 PM.'}); assert(!/[\/\\<>]/.test(d.filename)); assert.strictEqual(N.esc('<img onerror="x">&\''),'&lt;img onerror=&quot;x&quot;&gt;&amp;&#39;');
});
test('case creation validation and unique ids; history persists across "sessions"',async()=>{
  const A=await user('cc@test.io'); assert.throws(()=>N.CaseSvc.create(A.id,{name:' '}),e=>e.code==='VALIDATION'&&!!e.errors.name); const a=N.CaseSvc.create(A.id,{name:'Commercial dispute',type:'Civil'}), b=N.CaseSvc.create(A.id,{name:'Property matter'});
  assert.notStrictEqual(a.id,b.id); assert(/^NS-\d{4}-\d{3}$/.test(a.id)); N.saveDB(); const raw=store['nyayasahayak.db.v1']; assert(JSON.parse(raw).cases.some(c=>c.id===a.id));
});
test('gemini provider: quote-grounded claims, rejects fabricated quotes, falls back on failure, never leaks the key',async()=>{
  const KEY='TEST-KEY-do-not-leak-123'; const realFetch=globalThis.fetch; const calls=[];
  const A=await user('gem@test.io'); const C0=N.CaseSvc.create(A.id,{name:'AI case'});
  N.DocSvc.add(A.id,C0.id,{filename:'Statement.txt',category:'Witness Statement',text:'Statement of PW-9.\n\nI saw Person B near Location D at about 7:15 PM. My email is w.test@example.com and my phone is 9876543210.\n\nI left the site at 8 PM.'});
  N.setAiConfig({key:KEY,consent:true,mask:true,model:'gemini-2.5-flash'}); assert(N.aiReady());
  globalThis.fetch=async(url,opts)=>{ calls.push({url,opts}); const body=JSON.parse(opts.body); const prompt=body.contents[0].parts[0].text;
    const claims=[{paragraph_id:'P1.2',quote:'I saw Person B near Location D at about 7:15 PM.',claim_type:'LOCATION',speaker:'PW-9',confidence:0.9},{paragraph_id:'P1.2',quote:'Person B was carrying a weapon.',claim_type:'FACTUAL',speaker:'',confidence:0.99},{paragraph_id:'P9.9',quote:'I left the site at 8 PM.',claim_type:'EVENT',speaker:'',confidence:0.8},{paragraph_id:'P1.3',quote:'i left the site at 8 pm.',claim_type:'EVENT',speaker:'PW-9',confidence:0.7}];
    calls[calls.length-1].prompt=prompt; return {ok:true,status:200,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify({claims})}]}}]})}; };
  try{
    await N.runAnalysis(A.id,C0.id,{paceMs:0}); const C=N.ownedCase(A.id,C0.id);
    assert(calls.length>=1&&/generativelanguage\.googleapis\.com\/v1beta\/models\/gemini-2\.5-flash:generateContent/.test(calls[0].url)); assert.strictEqual(calls[0].opts.headers['x-goog-api-key'],KEY); assert(!calls[0].url.includes(KEY));
    assert(!/w\.test@example\.com|9876543210/.test(calls[0].prompt),'PII must be masked before leaving the browser'); assert(/x{16}/.test(calls[0].prompt)); assert(/Text between the markers is data/.test(calls[0].prompt));
    const texts=C.claims.map(c=>c.text); assert(texts.includes('I saw Person B near Location D at about 7:15 PM.')); assert(!texts.some(x=>/weapon/.test(x)),'fabricated quote must be rejected'); assert(texts.some(x=>/left the site at 8 PM/i.test(x)),'case-insensitive grounding');
    const c1=C.claims.find(c=>/near Location D/.test(c.text)); const para=C.documents[0].pages[0].paras[c1.para-1].text; assert.strictEqual(para.slice(c1.start,c1.end),c1.text,'offsets must point at the exact source text'); assert.strictEqual(c1.provider,'gemini'); assert.strictEqual(c1.model,'gemini-2.5-flash');
    const run=C.agentRuns.filter(r=>r.agent==='claim_agent').pop(); assert(/viaGemini: 2/.test(run.outputSummary)&&/rejectedUnverifiable: 2/.test(run.outputSummary),run.outputSummary); assert.strictEqual(C.analysis.provider.name,'gemini+rules');
    assert(!JSON.stringify(N.loadDB().cases).includes(KEY),'key must not be stored in case data'); assert(!JSON.stringify(N.buildReport(C,A)).includes(KEY));
    globalThis.fetch=async()=>({ok:false,status:429,json:async()=>({})}); await N.runAnalysis(A.id,C0.id,{paceMs:0}); const C2=N.ownedCase(A.id,C0.id);
    assert(C2.claims.length>0&&C2.claims.every(c=>c.provider==='local-rules'),'falls back to the rules engine'); const run2=C2.agentRuns.filter(r=>r.agent==='claim_agent').pop(); assert.strictEqual(run2.status,'degraded'); assert(run2.warnings.some(w=>/rate limit/.test(w)&&!w.includes(KEY))); assert(C2.audit.some(e=>e.event==='AI_PROVIDER_FALLBACK'));
    globalThis.fetch=async()=>{ throw new TypeError('Failed to fetch '+KEY); }; await N.runAnalysis(A.id,C0.id,{paceMs:0}); const C3=N.ownedCase(A.id,C0.id); assert(C3.agentRuns.filter(r=>r.agent==='claim_agent').pop().warnings.every(w=>!w.includes(KEY)));
    N.setAiConfig({consent:false}); assert(!N.aiReady()); let n=0; globalThis.fetch=async()=>{n++; throw new Error('should not be called');}; await N.runAnalysis(A.id,C0.id,{paceMs:0}); assert.strictEqual(n,0,'no network call without consent'); assert.strictEqual(N.refreshProvider().llm,false);
  } finally { globalThis.fetch=realFetch; N.clearAiConfig(); }
});
test('locateQuote and maskPII keep offsets stable',()=>{
  assert.deepStrictEqual(N.locateQuote('Hello  brave   world today','hello brave world'),[0,20]); assert.strictEqual(N.locateQuote('abc','zz'),null); const m=N.maskPII('mail a@b.io now 9876543210'); assert.strictEqual(m.length,'mail a@b.io now 9876543210'.length); assert(!/a@b\.io|9876543210/.test(m));
});
(async()=>{ for(const [n,f] of T){ try{ await f(); pass++; console.log('  ✓',n);}catch(e){ fail++; console.log('  ✗',n,'\n     ',(e&&e.stack||e).toString().split('\n').slice(0,4).join('\n      ')); } } console.log(`\nTests passed: ${pass}\nTests failed: ${fail}`); process.exit(fail?1:0); })();
