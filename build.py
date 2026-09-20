"""Build script. Sources live in frontend/src (engine 00-10, UI 20-28, CSS, template); output goes to ./dist.
   Usage (from any directory):  python3 build.py [app|engine|core]
   engine -> dist/engine.js (used by the Node server)   core -> dist/core.js (test build, adds test fixtures)   app -> dist/app.js + dist/index.html"""
import glob, sys, os
ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'frontend')
OUT = os.path.join(ROOT, 'dist')
def read(p): return open(p, encoding='utf-8').read()
core = sorted(glob.glob(os.path.join(SRC, 'src', '[0-1][0-9]-*.js')))
ui = sorted(glob.glob(os.path.join(SRC, 'src', '[2-9][0-9]-*.js')))
FIX = [os.path.join(SRC, 'tests', 'fixtures', '09-demo.js'), os.path.join(SRC, 'tests', 'fixtures', 'authorities.js')]
if not core:
    sys.exit('build.py: no sources found under frontend/src')
NAMES = "esc,pad,nowISO,rid,clamp,uniq,icon,loadDB,saveDB,commit,subscribe,prefs,setPref,getSession,setSession,signup,login,logout,currentUser,ServiceError,CaseSvc,DocSvc,ClaimSvc,ReviewSvc,AuditSvc,AuthSvc,ownedCase,claimStatus,findingStatus,pendingCount,caseMetrics,searchAll,buildFindings,mcpCall,MCP,MCP_TOOL_NAMES,runAnalysis,PIPELINE,AUTHORITIES,AUTH_LABEL,AUTH_KINDS,useLibrary,searchAuthorities,auditCitations,extractCitations,splitAuthorityText,extractClaims,parseTranscript,splitPages,sentences,eventTime,locations,anchorsOf,compareClaims,parseFile,parseDocx,parsePdf,buildReport,reportToPDF,ReportSvc,redactPII,detectPII,entitiesOf,guessCategory,textToParas,tokens,wrap,strW,setServerMode,claimFinding,PROVIDER,aiConfig,setAiConfig,clearAiConfig,aiReady,refreshProvider,geminiExtractClaims,geminiGenerate,locateQuote,maskPII,ROLES,STAFF_ROLES,normPhone,normEnroll,validEnroll,CASE_TYPES,caseAccess,canManageCase,HearingSvc,HEARING_STATUS,DRAFT_MAX_CHARS,userById"
def wrapjs(body, tail=''):
    return "(function(window){'use strict';\n" + body + "\nwindow.NS={" + NAMES + "};\n" + tail + "\n})(typeof window!=='undefined'?window:globalThis);\n"
def join(files): return '\n'.join(read(f) for f in files)
os.makedirs(OUT, exist_ok=True)
mode = sys.argv[1] if len(sys.argv) > 1 else 'app'
if mode == 'engine':
    out = wrapjs(join(core)); open(os.path.join(OUT, 'engine.js'), 'w', encoding='utf-8').write(out); print('engine', len(out))
elif mode == 'core':
    out = wrapjs(join(core + FIX), "window.NS.createDemoCase=createDemoCase;window.NS.DEMO=DEMO;window.NS.TEST_AUTHORITIES=TEST_AUTHORITIES;")
    open(os.path.join(OUT, 'core.js'), 'w', encoding='utf-8').write(out); print('core', len(out))
else:
    js = wrapjs(join(core + ui), "window.NS.__ui={routeView,Shell,UI,render,derive,parseHash};\nif(typeof document!=='undefined'&&document.getElementById&&document.getElementById('app')){boot();}")
    open(os.path.join(OUT, 'app.js'), 'w', encoding='utf-8').write(js)
    tp = os.path.join(SRC, 'src', 'template.html')
    tpl = read(tp) if os.path.exists(tp) else '<html><body><div id="app"></div><div id="overlay"></div><div id="toasts"></div><script>@@JS@@</script></body></html>'
    html = tpl.replace('@@CSS@@', read(os.path.join(SRC, 'src', 'style.css'))).replace('@@JS@@', js.replace('</script', '<\\/script'))
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(html); print('app', len(js), 'index.html', len(html))
