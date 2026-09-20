"""Standalone (file://) build: the court workflow runs in the browser engine; server-only features say so clearly."""
import os, re, tempfile, time
from playwright.sync_api import sync_playwright
ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); URL='file://'+ROOT+'/dist/index.html'
results=[]; errors=[]
def ok(n,c,x=''):
    results.append((n,bool(c))); print(('  PASS ' if c else '  FAIL ')+n+(' — '+str(x) if (x and not c) else ''))
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_context(viewport={'width':1440,'height':900}).new_page(); pg.set_default_timeout(8000)
    pg.on('pageerror',lambda e: errors.append('PAGEERROR '+str(e)))
    pg.on('console',lambda m: errors.append('CONSOLE '+m.text) if m.type=='error' and 'fonts.g' not in m.text and 'config.js' not in m.text and 'ERR_' not in m.text and 'Failed to load resource' not in m.text else None)
    def go(h): pg.evaluate("h=>{location.hash=h}",h); pg.wait_for_timeout(300)
    def wj(expr,t=8000):
        t0=time.time()
        while (time.time()-t0)*1000<t:
            if pg.evaluate('()=>!!('+expr+')'): return
            pg.wait_for_timeout(150)
        raise Exception('timeout '+expr)
    def signup(name,email,role,extra=None):
        go('#/signup'); pg.wait_for_selector('#s-fullName'); pg.fill('#s-fullName',name); pg.fill('#s-email',email); pg.fill('#s-phone','+91 98765'+str(10000+abs(hash(email))%89999)); pg.fill('#s-password','password123'); pg.fill('#s-confirm','password123'); pg.select_option('#s-role',role)
        if extra: pg.fill('#s-registrationNumber',extra)
        pg.click('#subbtn'); pg.wait_for_selector('.app')
    def logout(): go('#/settings'); pg.click('[data-act=logout] >> nth=0'); pg.wait_for_selector('.landing')
    pg.goto(URL); pg.wait_for_selector('.landing')
    go('#/track'); ok('public tracking says it needs the server in the standalone build', 'runs on the NyayaSahayak server' in pg.inner_text('body'))
    go('#/find-lawyer'); ok('find-a-lawyer says it needs the server', 'runs on the NyayaSahayak server' in pg.inner_text('body') and pg.locator('#flbtn[disabled]').count()==1)
    go('#/login/lawyer'); ok('one-time-code sign-in explains it needs the server', 'password' in pg.inner_text('.auth-form'))
    go('#/signup'); pg.wait_for_selector('#s-fullName'); pg.fill('#s-fullName','Lawyer NoEnrol'); pg.fill('#s-email','ne@example.com'); pg.fill('#s-phone','+91 9876500000'); pg.fill('#s-password','password123'); pg.fill('#s-confirm','password123'); pg.select_option('#s-role','LAWYER'); pg.click('#subbtn'); pg.wait_for_timeout(400)
    ok('lawyer signup requires an enrolment number', pg.locator('#e-registrationNumber:not(.hide)').count()==1)
    signup('Justice Rao','j@example.com','JUDGE'); logout()
    signup('Meera Advocate','l@example.com','LAWYER','D/1234/2015'); logout()
    signup('Suresh Steno','s@example.com','STENOGRAPHER')
    ok('stenographer lands on the court desk', 'Hearings you record' in pg.inner_text('.main'))
    go('#/cases/new'); pg.wait_for_selector('form[data-form=newcase]'); pg.fill('#c-name','State v. Kumar'); pg.click('button[type=submit]'); pg.wait_for_selector('.courtgrid'); cid=re.search(r'cases/(NS-\d+-\d+)',pg.url).group(1)
    pg.click('[data-act=people-edit]'); pg.wait_for_selector('form[data-form=assign]'); pg.select_option('#f-judgeId',index=1); pg.locator('input[name=lawyerIds]').first.check(); pg.click('form[data-form=assign] button[type=submit]'); pg.wait_for_timeout(500)
    ok('judge and lawyer assigned in the browser engine', 'Justice Rao' in pg.inner_text('.courtgrid') and 'Meera Advocate' in pg.inner_text('.courtgrid'))
    pg.click('.courtgrid [data-act=hearing-start]'); pg.wait_for_selector('form[data-form=hstart]'); pg.click('form[data-form=hstart] button[type=submit]'); pg.wait_for_selector('#twin')
    pg.fill('#twin','10:00:01 JUDGE: Please state your name.\n10:00:09 WITNESS: Ravi Kumar.'); pg.click('[data-act=tw-generate]'); wj("document.querySelectorAll('#twout .stmt').length>=2")
    ok('typing and generating a transcript work without a server', 'WITNESS' in pg.inner_text('#twout'))
    pg.reload(); pg.wait_for_selector('#twin'); wj("document.querySelector('#twin').value.length>0"); ok('draft persists in browser storage', 'Ravi Kumar' in pg.input_value('#twin'))
    go('#/cases/'+cid+'/claims'); ok('stenographer is refused analysis pages', 'not available' in pg.inner_text('.main').lower())
    logout(); pg.goto(URL); pg.wait_for_selector('.landing'); go('#/login'); pg.fill('#le','l@example.com'); pg.fill('#lp','password123'); pg.click('#subbtn'); pg.wait_for_selector('.app'); go('#/cases'); pg.wait_for_selector('#caselist tbody tr'); ok('the assigned lawyer sees the case; the transcript is readable', cid in pg.inner_text('#caselist'))
    go('#/cases/'+cid+'/hearing'); pg.wait_for_selector('.hv'); ok('lawyer reads the transcript', 'Ravi Kumar' in pg.inner_text('#stmts'))
    b.close()
print('\nERRORS:',len(errors)); [print('  ',e[:200]) for e in errors[:10]]
f=[n for n,c in results if not c]; print('PASSED',len(results)-len(f),'FAILED',len(f)); [print(' FAILED:',n) for n in f]
raise SystemExit(1 if f or errors else 0)
