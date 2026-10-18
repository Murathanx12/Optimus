// New disposable browser; never attaches a personal or finance profile.
const path=require('node:path'),fs=require('node:fs');
const {chromium}=require(process.env.PLAYWRIGHT_CORE_PATH||path.join(process.env.APPDATA,'npm/node_modules/openclaw/node_modules/playwright-core'));
const base=process.env.SHOWCASE_URL||'http://127.0.0.1:8895';
const production=new URL(base).protocol==='https:';
const out=path.join(__dirname,'validation');fs.mkdirSync(out,{recursive:true});
function assert(test,message){if(!test)throw Error(message);}
const csp=JSON.parse(fs.readFileSync(path.join(__dirname,'vercel.json'),'utf8')).headers[0].headers.find(h=>h.key==='Content-Security-Policy').value;
async function withDeploymentHeaders(page){
 // Local preview supplies no deployment headers. Production is checked with
 // its actual response headers and must not be rewritten by the harness.
 if(!['127.0.0.1','localhost','[::1]'].includes(new URL(base).hostname))return;
 await page.route(base+'/**',async route=>{const response=await route.fetch();await route.fulfill({response,headers:{...response.headers(),'content-security-policy':csp}});});
}
async function closePage(page){
 // A full-page screenshot can start a lazy image request. Drain route handlers
 // before disposing the page's API request context, including on failed checks.
 await page.unrouteAll({behavior:'wait'});
 await page.close();
}
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  for(const [name,width,height] of [['desktop',1440,1100],['mobile',390,1000]]){
   const page=await browser.newPage({viewport:{width,height}}),errors=[],requests=[],failedRequests=[];
   await withDeploymentHeaders(page);
   page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
   page.on('pageerror',e=>errors.push(e.message));page.on('requestfailed',r=>failedRequests.push({url:r.url(),error:r.failure()?.errorText}));page.on('request',r=>requests.push(r.url()));
   const response=await page.goto(base,{waitUntil:'networkidle'});
   // Some browser/hosting responses prepend their own same-origin script.
   // Identify it from the actual received HTML, against the committed source;
   // report its aborted requests separately, never ignore a project asset.
   const received=await response.text(),committed=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
   const responseScripts=Array.from(received.matchAll(/<script\b[^>]*\bsrc=['"]([^'"]+)['"]/g),m=>m[1]);
   const injectedScripts=new Set(responseScripts.filter(src=>!committed.includes(`src="${src}"`)&&!committed.includes(`src='${src}'`)).map(src=>new URL(src,base).href));
   function checkNetwork(){const injectedAborts=failedRequests.filter(r=>r.error==='net::ERR_ABORTED'&&injectedScripts.has(r.url));const projectFailures=failedRequests.filter(r=>!injectedAborts.includes(r));assert(!projectFailures.length,'failed project requests '+JSON.stringify(projectFailures));return injectedAborts.length;}
   assert(await page.locator('[data-node]').count()===17,'17 curated modules');
   await page.locator('[data-node="query"]').dispatchEvent('click');
   assert(await page.locator('#detail h3').textContent()==='Scoped retrieval','module selection');
   await page.locator('#search').fill('tombstones');
   assert((await page.locator('#search-status').textContent()).startsWith('1 matching'),'search exact module');
   await page.locator('#search').fill('not-a-module-at-all');
   assert((await page.locator('#search-status').textContent()).startsWith('0 matching'),'honest empty search');
   await page.locator('#search').fill('');
   await page.locator('#zoom-in').click();
   const zoomed=await page.locator('#network').getAttribute('transform');assert(zoomed.includes('1.2'),'zoom in');
   await page.locator('#zoom-out').click();
   await page.locator('#motion').click();assert(await page.locator('svg.paused').count()===1,'pause');
   await page.locator('#trace').click();assert(await page.locator('.edge.trace').count()===3,'trace real route edges');
   assert(await page.locator('#detail h3').textContent()==='Domain routing','trace stage selection');
   await page.locator('#trace').click();await page.locator('#motion').click();
   await page.locator('#reset').click();
   await page.locator('.neural-svg').scrollIntoViewIfNeeded();
   const box=await page.locator('.neural-svg').boundingBox();
   await page.mouse.move(box.x+box.width*.05,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.1,box.y+box.height*.5);await page.mouse.up();
   assert((await page.locator('#network').getAttribute('transform'))!=='translate(600 440) scale(1) translate(-600 -440)','drag pan');
   await page.locator('#reset').click();
   await page.locator('.node-directory summary').click();await page.locator('[data-pick="skills"]').focus();await page.keyboard.press('Enter');
   assert(await page.locator('#detail h3').textContent()==='Reusable skills','keyboard module selection');
   await page.locator('.node-directory summary').click();await page.locator('#reset').click();
   const dimensions=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth}));
   assert(dimensions.width<=width,'horizontal overflow '+JSON.stringify(dimensions));
   assert(errors.length===0,'browser errors '+errors.join('; '));
   checkNetwork();
   assert(requests.every(u=>u.startsWith(base)),'site fetches only local assets');
   await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
   await page.locator('#neural-map').screenshot({path:path.join(out,name+'-map.png')});
   await page.emulateMedia({reducedMotion:'reduce'});await page.waitForFunction(()=>document.getElementById('motion').disabled);assert(await page.locator('#motion').isDisabled(),'reduced motion button');
   assert(await page.locator('.flow').first().evaluate(e=>getComputedStyle(e).animationName)==='none','reduced motion removes animation');
   await page.screenshot({path:path.join(out,name+'-reduced.png'),fullPage:true});
   await page.unrouteAll({behavior:'wait'});
   assert(errors.length===0,'late browser errors '+errors.join('; '));
   console.log(JSON.stringify({name,dimensions,errors,requests:requests.length,reducedMotion:true,responseInjectedScriptAborts:checkNetwork()}));await closePage(page);
  }
  if(production){
   const embed=await browser.newPage({viewport:{width:1100,height:1000}}),errors=[];
   embed.on('pageerror',e=>errors.push(e.message));embed.on('console',m=>{if(m.type()==='error')errors.push(m.text()+' '+m.location().url);});
   await embed.goto(base+'/neural-map.html',{waitUntil:'networkidle'});
   await embed.locator('[data-node="query"]').dispatchEvent('click');
   assert(await embed.locator('#detail h3').textContent()==='Scoped retrieval','production standalone embed selection');
   await embed.locator('#motion').click();assert(await embed.locator('svg.paused').count()===1,'production embed pause');
   assert(!errors.length,'production standalone embed errors '+errors.join('; '));
   await embed.screenshot({path:path.join(out,'production-standalone.png')});await closePage(embed);
   console.log(JSON.stringify({productionStandalone:true,errors,localSvgAndSandboxChecks:'run with local preview'}));
   return;
  }
  const page=await browser.newPage({viewport:{width:1200,height:880}});
  await page.setContent(`<style>body{margin:0;background:#000}img{width:1200px;height:880px}</style><img src="${base}/neural-map.svg">`);
  await page.waitForFunction(()=>document.querySelector('img').complete);
  for(let i=0;i<3;i++){await page.waitForTimeout(1600);await page.screenshot({path:path.join(out,`svg-${i}.png`)});}
  await page.goto(base+'/neural-map.svg');await page.evaluate(()=>{const style=document.createElementNS('http://www.w3.org/2000/svg','style');style.textContent='text{font-family:"DejaVu Sans",sans-serif!important}';document.documentElement.append(style);});await page.screenshot({path:path.join(out,'svg-dejavu.png')});
  await closePage(page);
  const embed=await browser.newPage({viewport:{width:1100,height:1000}});const embedErrors=[];embed.on('pageerror',e=>embedErrors.push(e.message));
  await withDeploymentHeaders(embed);await embed.goto(base);
  await embed.setContent(`<iframe sandbox="allow-scripts" style="width:1060px;height:960px" src="${base}/neural-map.html"></iframe>`);
  const frame=embed.frameLocator('iframe');await frame.locator('[data-node="query"]').dispatchEvent('click');
  assert(await frame.locator('#detail h3').textContent()==='Scoped retrieval','opaque-origin sandbox embed works');assert(!embedErrors.length,'embed errors');
  await embed.screenshot({path:path.join(out,'sandbox-embed.png')});await closePage(embed);
  console.log(JSON.stringify({svgFrames:3,dejaVu:true,sandboxEmbed:true,embedErrors}));
 }finally{
  for(const context of browser.contexts())for(const page of context.pages())await page.unrouteAll({behavior:'wait'});
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
