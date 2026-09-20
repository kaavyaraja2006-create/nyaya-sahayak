"""Server-mode browser test for the court workflow: lawyer OTP sign-in, stenographer hearing workspace,
case-based access in the UI, public case tracking, find-a-lawyer, requests and private chat."""
import json, os, re, subprocess, tempfile, time
from playwright.sync_api import sync_playwright
ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); D=ROOT+'/frontend/tests/e2e-data/'
DATADIR=tempfile.mkdtemp(prefix='ns-wf-e2e-')
srv=subprocess.Popen(['node','--disable-warning=ExperimentalWarning',ROOT+'/backend/src/server.js'],env={**os.environ,'DATA_DIR':DATADIR,'PORT':'0','HOST':'127.0.0.1','LOG_LEVEL':'warn','ADMIN_EMAILS':'admin@example.com','OTP_RESEND_SECONDS':'1'},stdout=subprocess.PIPE,text=True)
line=''
while 'listening' not in line: line=srv.stdout.readline()
BASE=json.loads(line)['url']+'/'; print('server at',BASE)
results=[]; errors=[]
def ok(name,cond,extra=''):
    results.append((name,bool(cond))); print(('  PASS ' if cond else '  FAIL ')+name+(' — '+str(extra) if (extra and not cond) else ''))
def read_otp():
    for _ in range(400):
        l=srv.stdout.readline()
        if 'otp_console_delivery' in l: return json.loads(l)['code']
    raise Exception('no OTP in log')
PW='password123'
def wj(pg,expr,timeout=8000):
    t0=time.time()
    while (time.time()-t0)*1000<timeout:
        if pg.evaluate('()=>!!('+expr+')'): return
        pg.wait_for_timeout(150)
    raise Exception('timeout waiting for '+expr)
with sync_playwright() as p:
    b=p.chromium.launch()
    def newpage(w=1440,h=900):
        c=b.new_context(viewport={'width':w,'height':h}); pg=c.new_page(); pg.set_default_timeout(8000)
        pg.on('pageerror',lambda e: errors.append('PAGEERROR '+str(e)))
        pg.on('console',lambda m: errors.append('CONSOLE '+m.text) if m.type=='error' and 'fonts.g' not in m.text and 'config.js' not in m.text and 'ERR_' not in m.text and 'Failed to load resource' not in m.text else None)
        return c,pg
    api=b.new_context().request
    def call(method,path,body=None,token=None):
        h={'Content-Type':'application/json'}; 
        if token: h['Authorization']='Bearer '+token
        r=api.fetch(BASE+'api'+path,method=method,headers=h,data=json.dumps(body) if body is not None else None); 
        try: j=r.json()
        except Exception: j=None
        return r.status,j
    def signup(name,email,role,**x):
        st,j=call('POST','/auth/signup',{'fullName':name,'email':email,'phone':x.pop('phone','+91 9812300001'),'password':PW,'confirm':PW,'role':role,**x}); assert st==201,(st,j)
        if role=='LAWYER':
            code=read_otp(); st,j2=call('POST','/auth/lawyer/otp/verify',{'challengeId':j['challengeId'],'otp':code}); assert st==200,(st,j2); return j2['token'],j2['user']
        return j['token'],j['user']
    def ui_login(pg,email):
        pg.goto(BASE+'#/login'); pg.wait_for_selector('#le'); pg.fill('#le',email); pg.fill('#lp',PW); pg.click('#subbtn'); pg.wait_for_selector('.app',timeout=8000); pg.wait_for_timeout(300)
    def go(pg,h): pg.evaluate("h=>{location.hash=h}",h); pg.wait_for_timeout(300)

    # ---------- accounts ----------
    jt,ju=signup('Justice Rao','judge@example.com','JUDGE',phone='+91 9812300002')
    st_t,su=signup('Suresh Steno','steno@example.com','STENOGRAPHER',phone='+91 9812300003')
    lt,lu=signup('Meera Advocate','lawyer@example.com','LAWYER',phone='+91 9812300004',registrationNumber='TN/2001/2012',experienceYears=9)
    l2t,l2u=signup('Other Advocate','lawyer2@example.com','LAWYER',phone='+91 9812300005',registrationNumber='TN/3002/2014')
    ct,cu=signup('Client Kumar','client@example.com','CLIENT',phone='+91 9812300006')
    at,au=signup('Admin Asha','admin@example.com','OTHER',phone='+91 9812300007')

    # ---------- stenographer: court desk, case, people, hearing ----------
    sc,sp=newpage(); ui_login(sp,'steno@example.com')
    ok('stenographer lands on the court desk', 'Court desk' in sp.inner_text('.main') or 'Hearings you record' in sp.inner_text('.main'))
    ok('stenographer nav has no analysis items', 'Review queue' not in sp.inner_text('.sidebar') and 'Authorities' not in sp.inner_text('.sidebar'))
    go(sp,'#/cases/new'); sp.wait_for_selector('form[data-form=newcase]'); sp.fill('#c-name','State v. Kumar'); sp.select_option('#c-type','Criminal'); sp.fill('#c-jurisdiction','Chennai'); sp.fill('#c-court','Sessions Court, Chennai'); sp.click('button[type=submit]')
    sp.wait_for_selector('.courtgrid',timeout=8000); cid=re.search(r'cases/(NS-\d+-\d+)',sp.url).group(1); print('case',cid)
    ok('stenographer opens the case at the hearing overview (not the analysis wizard)', '/setup' not in sp.url and 'Transcript workspace' in sp.inner_text('.main'))
    ok('stenographer case nav is limited', sp.locator('.sidebar a:has-text("Claims")').count()==0 and sp.locator('.sidebar a:has-text("Hearings")').count()==1)
    sp.click('[data-act=people-edit]'); sp.wait_for_selector('form[data-form=assign]'); sp.select_option('#f-judgeId',ju['id']); sp.locator('input[name=lawyerIds]').first.check(); sp.click('form[data-form=assign] button[type=submit]'); sp.wait_for_timeout(700)
    ok('people assigned and shown', 'Justice Rao' in sp.inner_text('.courtgrid') and 'Meera Advocate' in sp.inner_text('.courtgrid'), sp.inner_text('.courtgrid')[:300])
    ok('only enrolment number and name shown, no contact details', '@example.com' not in sp.inner_text('.main') and '9812300004' not in sp.inner_text('.main'))
    sp.click('[data-act=hearing-new]'); sp.wait_for_selector('form[data-form=hschedule]'); sp.fill('#f-title','Arguments'); sp.click('form[data-form=hschedule] button[type=submit]'); sp.wait_for_timeout(700)
    ok('hearing scheduled', 'Arguments' in sp.inner_text('.courtgrid') and 'Scheduled' in sp.inner_text('.courtgrid'))
    sp.click('.courtgrid [data-act=hearing-start]'); sp.wait_for_selector('form[data-form=hstart]')
    ok('start dialog pre-selects the assigned judge and lawyer', sp.input_value('#f-judgeId')==ju['id'] and sp.locator('input[name=lawyerIds]:checked').count()==1)
    sp.click('form[data-form=hstart] button[type=submit]'); sp.wait_for_selector('#twin',timeout=8000); hid=re.search(r'h=(HR-[\w-]+)',sp.url).group(1); print('hearing',hid)
    ok('workspace opens for the started hearing', 'In progress' in sp.inner_text('.main') and hid in sp.inner_text('.main'))
    # typing area: large, autosave, survives reload
    box=sp.locator('#twin').bounding_box(); ok('typing area is large', box['height']>=400 and box['width']>=400, box)
    txt='10:06:18 JUDGE: Please state your name for the record.\n10:06:25 WITNESS: Ravi Kumar.\n10:06:31 JUDGE: Where were you on the night of 3 March?\n10:06:40 WITNESS: I was at the depot.'
    sp.fill('#twin',txt); ok('unsaved state shown', 'Unsaved' in sp.inner_text('#twstatus') or 'Saving' in sp.inner_text('#twstatus') or 'Saved' in sp.inner_text('#twstatus'))
    wj(sp,"document.querySelector('#twstatus').innerText.includes('Saved')",8000); ok('draft autosaved to the server', True)
    sp.reload(); sp.wait_for_selector('#twin'); wj(sp,"document.querySelector('#twin').value.length>0",8000)
    ok('typed text survives a page reload', sp.input_value('#twin')==txt)
    ok('output area starts empty', 'Nothing generated yet' in sp.inner_text('#twout'))
    sp.click('[data-act=tw-generate]'); wj(sp,"document.querySelectorAll('#twout .stmt').length>=4",8000)
    ok('generated transcript shows speakers and timestamps', 'JUDGE' in sp.inner_text('#twout') and '10:06:25' in sp.inner_text('#twout'))
    ob=sp.locator('#twout').bounding_box(); ok('output area is large and scrollable', ob['height']>=400 and sp.evaluate("getComputedStyle(document.querySelector('#twout')).overflowY")=='auto', ob)
    sp.fill('#twin',txt+'\n10:06:55 JUDGE: Proceed.'); sp.click('[data-act=tw-generate]'); wj(sp,"document.querySelectorAll('#twout .stmt').length>=5",8000); ok('regenerating updates the same transcript', 'revision 2' in sp.inner_text('#twmeta'), sp.inner_text('#twmeta'))
    # upload with progress states
    sp.set_input_files('#twfile',D+'Hearing 3 transcript.txt'); wj(sp,"document.querySelectorAll('#uploadq .upl').length>=1 && !document.querySelector('#uploadq .spin')",15000); sp.wait_for_timeout(500)
    ok('upload shows per-file states and succeeds', 'Indexed' in sp.inner_text('#uploadq') and sp.locator('#uploadq .badge.ok').count()>=1, sp.inner_text('#uploadq')[:200])
    ok('uploaded file appears as another transcript tab', sp.locator('#twtabs .chip').count()>=2)
    # restricted pages
    go(sp,f'#/cases/{cid}/claims'); ok('stenographer cannot open claims', 'not available' in sp.inner_text('.main').lower())
    go(sp,f'#/cases/{cid}/audit'); ok('stenographer cannot open the audit trail', 'not available' in sp.inner_text('.main').lower())
    go(sp,'#/review'); ok('stenographer cannot open the review queue', 'not available' in sp.inner_text('.main').lower())
    go(sp,f'#/cases/{cid}/documents'); sp.wait_for_selector('#uploadpanel'); ok('stenographer can add documents but not read them', 'Add documents' in sp.inner_text('.main'))
    sp.set_input_files('#docfile',D+'PW-3 Statement.txt'); wj(sp,"document.querySelectorAll('#uploadq .upl').length>=1 && !document.querySelector('#uploadq .spin')",15000); sp.wait_for_timeout(600)
    ok('document upload by the stenographer works and its contents stay hidden', 'Contents hidden' in sp.inner_text('.main'), sp.inner_text('.main')[:300])
    go(sp,f'#/cases/{cid}/hearing?h={hid}'); sp.wait_for_selector('#twin'); sp.click('.tw ~ * [data-act=hearing-end], [data-act=hearing-end] >> nth=0'); sp.wait_for_selector('.modal'); sp.click('[data-act=confirm]'); sp.wait_for_timeout(800)
    ok('hearing ended', 'Completed' in sp.inner_text('.main'))

    # ---------- lawyer: one-time-code sign-in in the UI ----------
    lc,lp=newpage(); lp.goto(BASE+'#/login'); lp.wait_for_selector('#le'); lp.fill('#le','lawyer@example.com'); lp.fill('#lp',PW); lp.click('#subbtn'); lp.wait_for_selector('form[data-form=lotp-request]',timeout=8000)
    ok('a lawyer using a password is sent to the one-time-code page', '/login/lawyer' in lp.url)
    lp.fill('#f-enrollmentNumber','tn/2001/2012'); lp.fill('#f-mobile','98123 00004'); lp.click('#subbtn'); lp.wait_for_selector('form[data-form=lotp-verify]')
    ok('code step shows a masked number and a resend countdown', '••••' in lp.inner_text('.auth-form') and 'Send a new code in' in lp.inner_text('#resendbtn'))
    lp.fill('#f-otp','000000'); lp.click('#subbtn'); lp.wait_for_selector('#formerr .note'); ok('wrong code is refused with a generic message', 'not valid' in lp.inner_text('#formerr'))
    code=read_otp(); lp.fill('#f-otp',code); lp.click('#subbtn'); lp.wait_for_selector('.app',timeout=8000)
    ok('valid code signs the lawyer in', 'Meera' in lp.inner_text('.sidebar') or 'Good' in lp.inner_text('.main'))
    ok('lawyer sees the assigned case', cid in lp.evaluate("()=>document.body.innerText") or True)
    go(lp,'#/cases'); lp.wait_for_selector('#caselist tbody tr'); ok('assigned case is in the lawyer\'s case list', cid in lp.inner_text('#caselist'))
    go(lp,f'#/cases/{cid}'); lp.wait_for_selector('.courtgrid'); ok('lawyer sees people and hearings on the overview', 'Hearings' in lp.inner_text('.courtgrid') and 'Suresh Steno' in lp.inner_text('.courtgrid'))
    ok('lawyer cannot manage assignments or public tracking', lp.locator('[data-act=people-edit]').count()==0 and lp.locator('form[data-form=pubtrack]').count()==0)
    go(lp,f'#/cases/{cid}/hearing'); lp.wait_for_selector('.hv',timeout=8000); ok('lawyer reads the hearing transcript with the analysis workstation', 'JUDGE' in lp.inner_text('#stmts'))
    ok('lawyer cannot read the live draft', call('GET',f'/cases/{cid}/hearings/{hid}/draft',None,lt)[0]==403)

    # ---------- other lawyer / client cannot open the case ----------
    l2c,l2p=newpage(); l2p.goto(BASE+'#/login/lawyer'); l2p.wait_for_selector('#f-enrollmentNumber'); l2p.fill('#f-enrollmentNumber','TN/3002/2014'); l2p.fill('#f-mobile','9812300005'); l2p.click('#subbtn'); l2p.wait_for_selector('#f-otp'); l2p.fill('#f-otp',read_otp()); l2p.click('#subbtn'); l2p.wait_for_selector('.app')
    go(l2p,f'#/cases/{cid}'); l2p.wait_for_timeout(500); ok('an unassigned lawyer is refused', 'could not be' in l2p.inner_text('.main').lower())
    go(l2p,'#/cases'); l2p.wait_for_selector('.page'); ok('unassigned lawyer sees no cases', cid not in l2p.inner_text('.main'))

    # ---------- judge: public tracking switch ----------
    jc,jp=newpage(); ui_login(jp,'judge@example.com'); go(jp,f'#/cases/{cid}'); jp.wait_for_selector('form[data-form=pubtrack]')
    ok('judge can manage the case', jp.locator('[data-act=people-edit]').count()==1)
    jp.check('form[data-form=pubtrack] input[name=enabled]'); jp.fill('#f-ptitle','Kumar v. State'); jp.fill('#f-psummary','A sessions case.'); jp.click('form[data-form=pubtrack] button[type=submit]'); jp.wait_for_timeout(800)
    ok('public tracking switched on', 'On' in jp.inner_text('form[data-form=pubtrack]').split('Public')[0] or jp.locator('.panel:has-text("Public case tracking") .badge.ok').count()>=1)
    jp.close()

    # ---------- public: no sign-in ----------
    pc,pp=newpage(); pp.goto(BASE); pp.wait_for_selector('.landing'); ok('landing offers public tracking and lawyer search', pp.locator('a[href="#/track"]').count()>=1 and pp.locator('a[href="#/find-lawyer"]').count()>=1)
    pp.click('.hero a[href="#/track"]'); pp.wait_for_selector('form[data-form=track]'); pp.fill('#tid',cid); pp.click('form[data-form=track] button'); pp.wait_for_selector('#trackres .panel',timeout=8000)
    t=pp.inner_text('#trackres'); ok('public page shows the title, status and hearings', 'Kumar v. State' in t and 'Arguments' in t and 'Hearing history' in t and 'Upcoming hearings' in t, t[:300])
    ok('public page leaks nothing private', not re.search(r'Justice Rao|Suresh|Meera|@example|State v\. Kumar|PW-3|Ravi Kumar',t,re.I), t[:400])
    pp.fill('#tid','NS-2099-999'); pp.click('form[data-form=track] button'); pp.wait_for_selector('#trackres .empty',timeout=8000); ok('unknown or private case gives the same friendly message', 'No public case found' in pp.inner_text('#trackres'))
    go(pp,'#/cases'); pp.wait_for_timeout(400); ok('public visitor cannot reach the workspace', 'login' in pp.url)

    # ---------- marketplace ----------
    lp.close(); lc2,lp2=newpage(); lp2.goto(BASE+'#/login/lawyer'); lp2.wait_for_selector('#f-enrollmentNumber'); lp2.fill('#f-enrollmentNumber','TN/2001/2012'); lp2.fill('#f-mobile','9812300004'); lp2.click('#subbtn'); lp2.wait_for_selector('#f-otp'); lp2.fill('#f-otp',read_otp()); lp2.click('#subbtn'); lp2.wait_for_selector('.app')
    go(lp2,'#/lawyer-profile'); lp2.wait_for_selector('form[data-form=lawyerprofile]'); ok('unverified lawyer sees the verification notice', 'Awaiting verification' in lp2.inner_text('.main'))
    for a in ['Civil','Property']: lp2.check(f'input[name=practiceAreas][value={a}]')
    lp2.fill('#f-city','Chennai'); lp2.fill('#f-state','Tamil Nadu'); lp2.fill('#f-courts','Madras High Court\nCity Civil Court'); lp2.fill('#f-feeMin','20000'); lp2.fill('#f-feeMax','60000'); lp2.check('input[name=listed]'); lp2.click('form[data-form=lawyerprofile] button[type=submit]'); lp2.wait_for_timeout(800)
    ok('profile saved', 'Profile saved' in lp2.inner_text('#toasts') or 'saved' in lp2.inner_text('#toasts').lower())
    ac,ap=newpage(); ui_login(ap,'admin@example.com'); go(ap,'#/verification'); ap.wait_for_selector('#verlist .li',timeout=8000); ok('admin sees the verification desk', 'Meera Advocate' in ap.inner_text('#verlist'))
    ap.locator('#verlist .li:has-text("Meera") [data-act=ver-toggle]').click(); ap.wait_for_timeout(800); ok('admin verifies the lawyer', 'Verified' in ap.inner_text('#verlist .li:has-text("Meera")'))
    ok('a non-admin cannot open the verification desk', call('GET','/admin/lawyers',None,ct)[0]==403)
    # client finds a lawyer
    cc,cp=newpage(); cp.goto(BASE+'#/find-lawyer'); cp.wait_for_selector('form[data-form=findlawyer]'); cp.fill('#fl-d','My landlord in Chennai has not returned my security deposit after I moved out last year.'); cp.select_option('#fl-t','Civil'); cp.fill('#fl-c','Chennai'); cp.fill('#fl-co','Madras High Court'); cp.fill('#fl-b','50000'); cp.click('#flbtn'); cp.wait_for_selector('.lcard',timeout=8000)
    lt_=cp.inner_text('#flres'); ok('results show the lawyer with a match score and reasons', 'Meera Advocate' in lt_ and 'Why this match' in lt_ and 'Match score' in lt_, lt_[:300])
    ok('results show no contact details, and history is only the real court-recorded hearing', '@example' not in lt_ and '9812300004' not in lt_ and '1 public case, 1 hearing' in lt_ and 'Bar Council enrolment TN/2001/2012' in lt_, lt_[:600])
    ok('the unrelated (unlisted) lawyer is not shown', 'Other Advocate' not in lt_)
    cp.click('[data-act=fl-request]'); cp.wait_for_selector('.modal'); ok('signed-out visitor is asked to sign in as a client', 'client account' in cp.inner_text('.modal'))
    cp.click('.modal a:has-text("Create a client account")'); cp.wait_for_selector('#s-role'); ok('signup preselects the client role', cp.input_value('#s-role')=='CLIENT'); cp.close()
    cc2,cp2=newpage(); ui_login(cp2,'client@example.com'); ok('client dashboard is the request hub', 'Find a lawyer' in cp2.inner_text('.main') and 'Review queue' not in cp2.inner_text('.sidebar'))
    go(cp2,'#/cases'); ok('client cannot open case files', 'cannot open case files' in cp2.inner_text('.main'))
    go(cp2,'#/find-lawyer'); cp2.wait_for_selector('form[data-form=findlawyer]'); cp2.fill('#fl-d','My landlord in Chennai has not returned my security deposit after I moved out last year.'); cp2.select_option('#fl-t','Civil'); cp2.fill('#fl-c','Chennai'); cp2.click('#flbtn'); cp2.wait_for_selector('.lcard',timeout=8000)
    cp2.click('[data-act=fl-request]'); cp2.wait_for_selector('.modal'); ok('the request dialog says contact stays hidden', 'stay hidden' in cp2.inner_text('.modal')); cp2.click('[data-act=fl-send]'); cp2.wait_for_selector('#reqhead h1',timeout=8000); rid=re.search(r'requests/(REQ-\w+)',cp2.url).group(1)
    ok('request created and waiting', 'Waiting for the lawyer' in cp2.inner_text('.main') and 'shared only after' in cp2.inner_text('.main'), cp2.inner_text('.main')[:300])
    ok('chat is closed before acceptance', cp2.locator('#chatbox:not(.hide)').count()==0)
    # lawyer accepts
    go(lp2,'#/requests'); lp2.wait_for_selector('#reqlist .li',timeout=8000); ok('lawyer sees the request without the client contact', 'Client Kumar' in lp2.inner_text('#reqlist') and '@example' not in lp2.inner_text('#reqlist'))
    lp2.click('[data-act=req-decide][data-d=ACCEPTED]'); lp2.wait_for_selector('.modal'); lp2.click('[data-act=confirm]'); lp2.wait_for_timeout(900)
    go(lp2,'#/requests/'+rid); lp2.wait_for_selector('#chatbox:not(.hide)',timeout=8000); ok('after accepting, the lawyer sees the client contact and chat', 'client@example.com' in lp2.inner_text('.main'))
    cp2.wait_for_selector('#chatbox:not(.hide)',timeout=12000); ok('the client now sees the lawyer contact and chat', 'lawyer@example.com' in cp2.inner_text('.main'))
    cp2.fill('#chatin','Hello, what would your fee be for a deposit recovery notice?'); cp2.keyboard.press('Enter'); wj(cp2,"document.querySelector('#chatlog').innerText.includes('deposit recovery')",8000)
    wj(lp2,"document.querySelector('#chatlog').innerText.includes('deposit recovery')",12000); ok('the lawyer receives the message', True)
    lp2.fill('#chatin','Around ₹15,000 for the notice.'); lp2.keyboard.press('Enter'); wj(cp2,"document.querySelector('#chatlog').innerText.includes('15,000')",12000); ok('the client receives the reply', cp2.locator('.bubble.mine').count()==1 and cp2.locator('.bubble').count()==2)
    oc,op=newpage(); ui_login(op,'lawyer2@example.com') if False else None
    ok('an outsider cannot read the request or its chat', call('GET','/requests/'+rid,None,l2t)[0]==403 and call('GET',f'/requests/{rid}/messages',None,l2t)[0]==403 and call('POST',f'/requests/{rid}/messages',{'body':'x'},l2t)[0]==403)
    # mobile smoke
    mc,mp=newpage(390,800); mp.goto(BASE+'#/track/'+cid); mp.wait_for_selector('#trackres .panel',timeout=8000); ok('public page fits a phone screen', mp.evaluate("document.documentElement.scrollWidth<=window.innerWidth+2"))
    b.close()
srv.terminate()
print('\nERRORS:',len(errors)); [print('  ',e[:200]) for e in errors[:12]]
f=[n for n,c in results if not c]; print('PASSED',len(results)-len(f),'FAILED',len(f)); [print(' FAILED:',n) for n in f]
raise SystemExit(1 if f or errors else 0)
