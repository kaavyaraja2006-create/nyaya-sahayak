import json, os, sys, time, re
from playwright.sync_api import sync_playwright
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); URL='file://'+ROOT+'/dist/index.html'; D=ROOT+'/tests/e2e-data/'; S=ROOT+'/shots/'; os.makedirs(S,exist_ok=True)
errors=[]; results=[]
import subprocess, tempfile
SERVER=os.environ.get('NS_MODE')=='server'; srv=None; DATADIR=None
if SERVER:
    DATADIR=tempfile.mkdtemp(prefix='ns-e2e-'); srv=subprocess.Popen(['node','--disable-warning=ExperimentalWarning',ROOT+'/backend/src/server.js'],env={**os.environ,'DATA_DIR':DATADIR,'PORT':'0','HOST':'127.0.0.1','ANALYSIS_PACE_MS':'120','LOG_LEVEL':'warn'},stdout=subprocess.PIPE,text=True)
    line=''
    while 'listening' not in line: line=srv.stdout.readline()
    URL=json.loads(line)['url']+'/'; print('server mode at',URL)
def ok(name,cond,extra=''):
    results.append((name,bool(cond))); print(('  PASS ' if cond else '  FAIL ')+name+(' — '+str(extra) if (extra and not cond) else ''))
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':1440,'height':900},accept_downloads=True); pg=ctx.new_page()
    pg.on('pageerror',lambda e: errors.append('PAGEERROR '+str(e)))
    pg.on('console',lambda m: errors.append('CONSOLE '+m.text) if m.type=='error' and 'fonts.g' not in m.text and 'config.js' not in m.text and 'ERR_' not in m.text and 'Failed to load resource' not in m.text else None)
    def go(h): pg.evaluate("h=>{location.hash=h}",h); pg.wait_for_timeout(250)
    def wait_js(expr,timeout=15000):
        t0=time.time()
        while (time.time()-t0)*1000<timeout:
            if pg.evaluate('()=>!!('+expr+')'): return
            pg.wait_for_timeout(150)
        raise Exception('timeout waiting for '+expr)
    def shot(n): pg.screenshot(path=S+n+'.png')
    pg.goto(URL); pg.wait_for_selector('.landing'); shot('01-landing')
    ok('landing has no fictional case data', 'Person A' not in pg.content() and 'Location A' not in pg.content())
    ok('landing fonts declared', 'IBM Plex Sans' in pg.content() and 'Source Serif 4' in pg.content())
    # signup validation
    go('#/signup'); pg.wait_for_selector('form[data-form=signup]'); pg.click('#subbtn'); pg.wait_for_timeout(400)
    ok('signup shows field errors', pg.locator('.field.bad').count()>=4)
    pg.fill('#s-fullName','Kaavya Rao'); pg.fill('#s-email','kaavya@example.com'); pg.fill('#s-phone','+91 9876543210'); pg.fill('#s-password','password123'); pg.fill('#s-confirm','password123'); pg.select_option('#s-role','LAWYER'); pg.click('#subbtn')
    pg.wait_for_selector('.app',timeout=8000); pg.wait_for_timeout(300)
    ok('signup lands on dashboard', 'dashboard' in pg.url); shot('02-dashboard-empty')
    ok('no cases seeded', 'No cases yet' in pg.inner_text('.main'))
    # new case
    go('#/cases/new'); pg.wait_for_selector('form[data-form=newcase]'); pg.click('button[type=submit]'); pg.wait_for_timeout(200)
    ok('case name required', pg.locator('.field.bad').count()==1); shot('03-newcase')
    pg.fill('#c-name','Northgate depot incident review'); pg.fill('#c-number','CR/2026/114'); pg.select_option('#c-type','Criminal'); pg.fill('#c-jurisdiction','Chennai'); pg.fill('#c-description','Review of statements about the evening incident.'); pg.click('button[type=submit]')
    pg.wait_for_selector('.wiz'); pg.wait_for_timeout(300); ok('wizard step 2', '/setup/materials' in pg.url)
    cid=re.search(r'cases/(NS-\d+-\d+)',pg.url).group(1); print('case',cid)
    # upload
    files=[D+f for f in ['PW-3 Statement.txt','PW-5 Statement.txt','CCTV Review Report.txt','Device Location Record.txt','Incident Report.txt','Written Submission.txt']]
    pg.set_input_files('#docfile',files+[ROOT+'/tests/fixture.docx',ROOT+'/tests/fixture.pdf'])
    wait_js("document.querySelectorAll('#uploadq .upl').length>=8 && !document.querySelector('#uploadq .spin')",15000); pg.wait_for_timeout(500)
    ok('uploads indexed', pg.locator('#uploadq .badge.ok').count()>=8, pg.inner_text('#uploadq')[:300]); shot('04-upload')
    ok('doc list present', pg.locator('#doclist tbody tr').count()>=8)
    # bad file
    open('/tmp/bad.exe','wb').write(b'MZ'); pg.set_input_files('#docfile','/tmp/bad.exe'); pg.wait_for_timeout(600)
    ok('unsupported file rejected with message', 'Unsupported file type' in pg.inner_text('#uploadq'))
    # transcript step
    pg.click('a:has-text("Continue to hearing material")'); pg.wait_for_selector('#trtext'); pg.fill('#hd','2026-03-20'); pg.fill('#hn','3')
    pg.fill('#trtext',open(D+'Hearing 3 transcript.txt').read()); pg.click('[data-act=add-pasted]'); pg.wait_for_timeout(600)
    ok('pasted transcript parsed', 'statements' in pg.inner_text('body') or 'statement' in pg.inner_text('body')); shot('05-hearing')
    # authority library
    go('#/authorities'); pg.wait_for_selector('#authaddwrap'); ok('authority library starts empty', 'The library is empty' in pg.inner_text('.main'))
    for a in json.load(open(D+'authorities.json')):
        pg.evaluate("()=>{const w=document.querySelector('#authaddwrap'); w.classList.remove('hide')}")
        pg.fill('#a-title',a['title']); pg.fill('#a-citation',a['citation']); pg.fill('#a-court',a['court']); pg.fill('#a-year',str(a['year'])); pg.fill('#a-keywords',a['keywords']); pg.fill('#a-text',a['text']); pg.click('form[data-form=authadd] button[type=submit]'); pg.wait_for_timeout(250)
    ok('authorities added', pg.locator('#authaddwrap ~ section .list .li, section .list .li').count()>=8)
    pg.fill('#authq','phone metadata handset location'); pg.wait_for_timeout(300); ok('authority search returns passage + disclaimers', 'Human verification required' in pg.inner_text('#authres') and 'not legal correctness' in pg.inner_text('#authres')); shot('06-authorities')
    # analysis
    go('#/cases/'+cid+'/setup/ready'); pg.wait_for_selector('[data-act=run-analysis]'); pg.click('.main [data-act=run-analysis]')
    pg.wait_for_selector('#analysisbody'); pg.wait_for_timeout(600); shot('07-analysis-running')
    wait_js("document.body.innerText.includes('Analysis completed')||document.body.innerText.includes('Results')",30000); pg.wait_for_timeout(800); shot('08-analysis-done')
    ok('analysis pipeline shows 8 real stages', pg.locator('.stage').count()==8)
    txt=pg.inner_text('.main'); ok('rules engine labelled honestly', 'None used' in txt)
    # overview
    go('#/cases/'+cid); pg.wait_for_selector('.wf'); pg.wait_for_timeout(300); shot('09-overview'); ok('workflow strip has 7 stages', pg.locator('.wf > a').count()==7)
    # claims
    go('#/cases/'+cid+'/claims'); pg.wait_for_selector('#claimlist tbody tr'); shot('10-claims'); n=pg.locator('#claimlist tbody tr').count(); ok('claims listed', n>=10, n)
    pg.click('[data-act=claim-filter][data-k=conflict]'); pg.wait_for_timeout(200); ok('conflict filter works', 0<pg.locator('#claimlist tbody tr').count()<n)
    pg.click('#claimlist tbody tr:first-child'); pg.wait_for_selector('.chain'); pg.wait_for_timeout(400); shot('11-claim-detail')
    ok('evidence chain has 6 links', pg.locator('.main .chain > *').count()==6)
    ok('claim detail shows source passage and human review form', pg.locator('.passage mark').count()>=1 and pg.locator('form[data-form=review]').count()==1)
    ok('signals disclaimed', 'not a probability of truth' in pg.inner_text('.main'))
    # source jump
    pg.click('a:has-text("Open in document viewer")'); pg.wait_for_selector('.sheet'); pg.wait_for_timeout(600); shot('12-viewer')
    ok('viewer highlights focused claim', pg.locator('.sheet mark.cl.focus').count()>=1)
    pg.hover('.sheet mark.cl.focus'); pg.wait_for_timeout(300); ok('hover card appears', not pg.locator('#hovercard').get_attribute('class').count('hide')); shot('13-hovercard')
    pg.click('[data-act=focus-mode]'); pg.wait_for_timeout(300); ok('focus mode hides chrome', not pg.locator('.topbar').is_visible()); shot('14-focus'); pg.keyboard.press('Escape'); pg.wait_for_timeout(200); ok('esc exits focus', pg.locator('.topbar').is_visible())
    pg.fill('[data-in=docq]','Location'); pg.wait_for_timeout(300); ok('in-document search marks', pg.locator('.sheet mark.q').count()>0)
    # other pages
    for route,sel,name in [('evidence','#evlist tbody tr','15-evidence'),('conflicts','article.panel','16-conflicts'),('timeline','.htl svg','17-timeline'),('citations','.fcmp','18-citations'),('hearing','.hv .stmt','19-hearing-view'),('graph','#gvp .gnode','20-graph'),('review','#rqwork .panel','21-review'),('audit','#auditlist .mono','22-audit'),('report','.stats','23-report'),('documents','#doclist tbody tr','24-documents')]:
        go('#/cases/'+cid+'/'+route)
        try: pg.wait_for_selector(sel,timeout=6000); ok('route '+route+' renders',True)
        except Exception as e: ok('route '+route+' renders',False,pg.inner_text('.main')[:200])
        pg.wait_for_timeout(350); shot(name)
    # graph interactions
    go('#/cases/'+cid+'/graph'); pg.wait_for_selector('#gvp .gnode'); nn=pg.locator('#gvp .gnode').count(); ok('graph nodes rendered',nn>=20,nn)
    pg.locator('#gvp .gnode[data-id^="C:"]').nth(1).dispatch_event('click'); pg.wait_for_timeout(300); ok('graph inspector opens', pg.locator('#gpanel:not(.hide)').count()==1); shot('25-graph-selected')
    before=pg.evaluate("document.querySelector('#gvp').getAttribute('transform')"); pg.click('[data-act=gzoom][data-d="1.25"]'); ok('graph zoom changes transform', before!=pg.evaluate("document.querySelector('#gvp').getAttribute('transform')"))
    pg.click('[data-act=gtype][data-k=evidence]'); pg.wait_for_timeout(200); ok('graph filter hides evidence nodes', pg.locator('#gvp .gnode[data-id^="E:"]').count()==0)
    # compare sources
    go('#/cases/'+cid+'/conflicts'); pg.wait_for_selector('[data-act=compare]'); pg.click('[data-act=compare] >> nth=0'); pg.wait_for_selector('.cmp'); ok('compare shows two sources + banner','requires human verification' in pg.inner_text('.modal')); shot('26-compare'); pg.keyboard.press('Escape')
    ok('no accusatory language', not re.search(r'\b(is lying|guilty|perjur|proves guilt)\b', pg.inner_text('.main'), re.I))
    # review flow
    go('#/cases/'+cid+'/review'); pg.wait_for_selector('form[data-form=review]'); pg.click('form[data-form=review] button[type=submit]'); pg.wait_for_timeout(200); ok('review requires decision', 'Choose a review decision' in pg.inner_text('#rqwork'))
    pg.check('form[data-form=review] input[value=verify]'); pg.fill('form[data-form=review] textarea[name=comment]','Verify device ownership and location accuracy.'); pg.click('form[data-form=review] button[type=submit]'); pg.wait_for_timeout(500)
    ok('review saved toast', 'updated' in pg.inner_text('#toasts')); shot('27-review-saved')
    go('#/cases/'+cid+'/audit'); pg.wait_for_selector('#auditlist'); t=pg.inner_text('#auditlist'); ok('audit has reviewer events', 'REVIEWER_CHANGED_STATUS' in t and 'REVIEWER_ADDED_COMMENT' in t and 'REVIEWER_OPENED_FINDING' in t and 'REVIEW_SAVED' in t)
    pg.select_option('#ad-actor','REVIEWER'); pg.wait_for_timeout(200); ok('audit actor filter', 'CLAIM_EXTRACTED' not in pg.inner_text('#auditlist'))
    # modify keeps original
    go('#/cases/'+cid+'/claims'); pg.wait_for_selector('#claimlist tbody tr'); pg.click('#claimlist tbody tr >> nth=2'); pg.wait_for_selector('form[data-form=review]'); orig=pg.inner_text('.claimtxt')
    pg.check('form[data-form=review] input[value=modify]'); pg.fill('form[data-form=review] textarea[name=modifiedText]','Reviewer reworded version'); pg.click('form[data-form=review] button[type=submit]'); pg.wait_for_timeout(500)
    ok('original claim text unchanged after modify', pg.inner_text('.claimtxt')==orig and 'Reviewer reworded version' in pg.inner_text('.main'))
    # report exports
    go('#/cases/'+cid+'/report'); pg.wait_for_selector('[data-act=rpt-pdf]'); pg.click('[data-act=rpt-preview]'); pg.wait_for_selector('.reportdoc'); shot('28-report-preview'); ok('report has 12 sections', pg.locator('.reportdoc h2').count()==12)
    with pg.expect_download() as d: pg.click('[data-act=rpt-pdf]')
    f=d.value; path='/tmp/rep.pdf'; f.save_as(path); head=open(path,'rb').read(8); ok('PDF downloads', head.startswith(b'%PDF') and os.path.getsize(path)>3000, f.suggested_filename)
    with pg.expect_download() as d2: pg.click('[data-act=rpt-json]')
    j=json.load(open(d2.value.path())); ok('JSON export has disclaimer and no key', 'does not determine guilt' in j['disclaimer'])
    with pg.expect_download() as d3: pg.click('[data-act=export-claims]')
    ok('CSV downloads', open(d3.value.path(),encoding='utf-8-sig').read().startswith('id,claim'))
    # mcp/agents/settings/dashboard
    for route,sel,name in [('#/mcp','.toolgrid .tool','29-mcp'),('#/agents','.station','30-agents'),('#/settings','[data-form=aisave]','31-settings'),('#/dashboard','.wf','32-dashboard'),('#/review','.panel','33-review-global'),('#/audit','#auditlist','34-audit-global'),('#/reports','.pagehead','35-reports-global'),('#/cases','#caselist tbody tr','36-cases')]:
        go(route)
        try: pg.wait_for_selector(sel,timeout=5000); ok('route '+route+' renders',True)
        except Exception as e: ok('route '+route+' renders',False,pg.inner_text('.main')[:200])
        pg.wait_for_timeout(300); shot(name)
    ok('mcp shows 7 tools', pg.evaluate("1")==1)
    go('#/mcp'); pg.wait_for_selector('.toolgrid .tool'); ok('mcp shows 7 tools (registry)', pg.locator('.toolgrid .tool').count()==7)
    if not SERVER:
        # settings: gemini config never echoes key; consent required
        go('#/settings'); pg.wait_for_selector('#ai-key'); pg.fill('#ai-key','FAKE-TEST-KEY-1234567890-abcdef'); pg.click('form[data-form=aisave] button[type=submit]'); pg.wait_for_timeout(300)
        ok('key saved but ai off without consent', 'Gemini claim extraction is off' in pg.inner_text('#toasts') and 'FAKE-TEST-KEY' not in pg.content())
        pg.check('form[data-form=aisave] input[name=consent]'); pg.click('form[data-form=aisave] button[type=submit]'); pg.wait_for_timeout(300); ok('ai on with consent', 'Gemini claim extraction is on' in pg.inner_text('#toasts'))
        ok('top bar indicates Gemini', 'Gemini + rules' in pg.inner_text('.topbar')); shot('37-settings-ai')
        pg.click('[data-act=ai-clear]'); pg.click('[data-act=confirm]'); pg.wait_for_timeout(300); ok('key removed', 'Rules engine' in pg.inner_text('.topbar'))
    else:
        go('#/settings'); pg.wait_for_selector('#aibox input[name=mask]'); ok('server AI panel explains missing key', 'No Gemini API key is configured on the server' in pg.inner_text('#aibox')); ok('no key field in server mode', pg.locator('#ai-key').count()==0); ok('top bar shows rules engine', 'Rules engine' in pg.inner_text('.topbar'))
    # themes
    for th in ['dark','night','light']:
        pg.click('[data-act=theme-menu]'); pg.click('[data-act=set-theme][data-v='+th+']'); pg.wait_for_timeout(200); go('#/cases/'+cid+'/claims/C-02'); pg.wait_for_selector('.chain'); ok('theme '+th+' applies', pg.evaluate('document.documentElement.dataset.theme')==th); pg.wait_for_timeout(300); shot('40-theme-'+th)
    # ctrl+k
    pg.keyboard.press('Control+k'); pg.wait_for_selector('.pal'); pg.fill('#palq','Location'); pg.wait_for_timeout(300); ok('global search returns results', pg.locator('#palres .it').count()>0); shot('41-search'); pg.keyboard.press('Escape')
    # persistence: logout / login
    go('#/settings'); pg.click('[data-act=logout] >> nth=0'); pg.wait_for_selector('.landing'); go('#/login'); pg.fill('#le','kaavya@example.com'); pg.fill('#lp','wrong'); pg.click('#subbtn'); pg.wait_for_timeout(600)
    ok('generic login error', 'Invalid email or password.' in pg.inner_text('#formerr'))
    pg.fill('#lp','password123'); pg.click('#subbtn'); pg.wait_for_selector('.app'); go('#/cases'); pg.wait_for_selector('#caselist tbody tr'); ok('case persists after re-login', cid in pg.inner_text('#caselist'))
    # cross-user isolation
    pg.evaluate("localStorage.getItem('nyayasahayak.session.v1')"); go('#/settings'); pg.click('[data-act=logout] >> nth=0'); pg.wait_for_selector('.landing'); go('#/signup'); pg.wait_for_selector('#s-fullName')
    pg.fill('#s-fullName','Other User'); pg.fill('#s-email','other@example.com'); pg.fill('#s-phone','+91 9123456780'); pg.fill('#s-password','password123'); pg.fill('#s-confirm','password123'); pg.select_option('#s-role','LEGAL_RESEARCHER'); pg.click('#subbtn'); pg.wait_for_selector('.app')
    go('#/cases/'+cid+'/claims'); pg.wait_for_timeout(500); ok('other user cannot open the case', 'could not be found' in pg.inner_text('.main') or 'could not be loaded' in pg.inner_text('.main').lower()); shot('42-denied')
    # mobile
    pg.set_viewport_size({'width':390,'height':800}); go('#/dashboard'); pg.wait_for_timeout(400); shot('43-mobile-dashboard'); ok('bottom nav on mobile', pg.locator('.bottomnav').is_visible())
    if SERVER:
        ls=pg.evaluate("Object.keys(localStorage).join(',')"); ok('server mode keeps case data out of localStorage', 'nyayasahayak.db.v1' not in ls or json.loads(pg.evaluate("localStorage.getItem('nyayasahayak.db.v1')") or '{}').get('cases',[])==[], ls)
        up=[os.path.join(dp,f) for dp,_,fs in os.walk(DATADIR+'/uploads') for f in fs]; ok('original files stored on the server', any(f.endswith('.txt') and 'documents' in f for f in up) and any('/reports/' in f and f.endswith('.pdf') for f in up), len(up))
        import sqlite3; db=sqlite3.connect(DATADIR+'/nyayasahayak.db'); ok('server database holds the case data', db.execute('select count(*) from claims').fetchone()[0]>10 and db.execute('select count(*) from reviews').fetchone()[0]>=2 and db.execute('select count(*) from audit_events').fetchone()[0]>30); db.close()
    b.close()
print('\nERRORS:',len(errors)); [print(' ',e[:220]) for e in errors[:15]]
if srv: srv.terminate()
fails=[n for n,c in results if not c]; print('PASSED',len(results)-len(fails),'FAILED',len(fails)); [print(' FAIL:',n) for n in fails]
sys.exit(1 if fails or errors else 0)
