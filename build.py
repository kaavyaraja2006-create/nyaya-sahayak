import glob,sys,os
def read(p): return open(p,encoding='utf-8').read()
core=sorted(glob.glob('src/[0-1][0-9]-*.js'))
ui=sorted(glob.glob('src/[2-9][0-9]-*.js'))
FIX=['tests/fixtures/09-demo.js','tests/fixtures/authorities.js']
NAMES="esc,pad,nowISO,rid,clamp,uniq,icon,loadDB,saveDB,commit,subscribe,prefs,setPref,getSession,setSession,signup,login,logout,currentUser,ServiceError,CaseSvc,DocSvc,ClaimSvc,ReviewSvc,AuditSvc,AuthSvc,ownedCase,claimStatus,findingStatus,pendingCount,caseMetrics,searchAll,buildFindings,mcpCall,MCP,MCP_TOOL_NAMES,runAnalysis,PIPELINE,AUTHORITIES,AUTH_LABEL,AUTH_KINDS,useLibrary,searchAuthorities,auditCitations,extractCitations,splitAuthorityText,extractClaims,parseTranscript,splitPages,sentences,eventTime,locations,anchorsOf,compareClaims,parseFile,parseDocx,parsePdf,buildReport,reportToPDF,ReportSvc,redactPII,detectPII,entitiesOf,guessCategory,textToParas,tokens,wrap,strW,setServerMode,claimFinding,PROVIDER,aiConfig,setAiConfig,clearAiConfig,aiReady,refreshProvider,geminiExtractClaims,geminiGenerate,locateQuote,maskPII"
def wrapjs(body,tail=''):
    return "(function(window){'use strict';\n"+body+"\nwindow.NS={"+NAMES+"};\n"+tail+"\n})(typeof window!=='undefined'?window:globalThis);\n"
def join(files): return '\n'.join(read(f) for f in files)
os.makedirs('dist',exist_ok=True)
mode=sys.argv[1] if len(sys.argv)>1 else 'app'
if mode=='engine':
    out=wrapjs(join(core)); open('dist/engine.js','w',encoding='utf-8').write(out); print('engine',len(out))
elif mode=='core':
    out=wrapjs(join(core+FIX),"window.NS.createDemoCase=createDemoCase;window.NS.DEMO=DEMO;window.NS.TEST_AUTHORITIES=TEST_AUTHORITIES;")
    open('dist/core.js','w',encoding='utf-8').write(out); print('core',len(out))
else:
    js=wrapjs(join(core+ui),"window.NS.__ui={routeView,Shell,UI,render,derive,parseHash};\nif(typeof document!=='undefined'&&document.getElementById&&document.getElementById('app')){boot();}")
    open('dist/app.js','w',encoding='utf-8').write(js)
    tpl=read('src/template.html') if os.path.exists('src/template.html') else '<html><body><div id="app"></div><div id="overlay"></div><div id="toasts"></div><script>@@JS@@</script></body></html>'
    html=tpl.replace('@@CSS@@',read('src/style.css')).replace('@@JS@@',js.replace('</script','<\\/script'))
    open('dist/index.html','w',encoding='utf-8').write(html); print('app',len(js),'index.html',len(html))
