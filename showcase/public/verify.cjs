// New disposable browser; never attaches a personal or finance profile.
const path=require('node:path'),fs=require('node:fs');
const {chromium}=require(process.env.PLAYWRIGHT_CORE_PATH||path.join(process.env.APPDATA,'npm/node_modules/openclaw/node_modules/playwright-core'));
const base=process.env.SHOWCASE_URL||'http://127.0.0.1:8895';
const out=path.join(__dirname,'validation');fs.mkdirSync(out,{recursive:true});
function assert(test,message){if(!test)throw Error(message);}
const csp=JSON.parse(fs.readFileSync(path.join(__dirname,'vercel.json'),'utf8')).headers[0].headers.find(h=>h.key==='Content-Security-Policy').value;
async function withDeploymentHeaders(page){await page.route(base+'/**',async route=>{const response=await route.fetch();await route.fulfill({response,headers:{...response.headers(),'content-security-policy':csp}});});}
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  for(const [name,width,height] of [['desktop',1440,1100],['mobile',390,1000]]){
   const page=await browser.newPage({viewport:{width,height}}),errors=[],requests=[];
   await withDeploymentHeaders(page);
   page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
   page.on('pageerror',e=>errors.push(e.message));page.on('requestfailed',r=>errors.push(r.url()+': '+r.failure()?.errorText));page.on('request',r=>requests.push(r.url()));
   await page.goto(base,{waitUntil:'networkidle'});
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
   assert(requests.every(u=>u.startsWith(base)),'site fetches only local assets');
   await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
   await page.locator('#neural-map').screenshot({path:path.join(out,name+'-map.png')});
   await page.emulateMedia({reducedMotion:'reduce'});await page.waitForFunction(()=>document.getElementById('motion').disabled);assert(await page.locator('#motion').isDisabled(),'reduced motion button');
   assert(await page.locator('.flow').first().evaluate(e=>getComputedStyle(e).animationName)==='none','reduced motion removes animation');
   await page.screenshot({path:path.join(out,name+'-reduced.png'),fullPage:true});
   console.log(JSON.stringify({name,dimensions,errors,requests:requests.length}));await page.close();
  }
  const page=await browser.newPage({viewport:{width:1200,height:880}});
  await page.setContent(`<style>body{margin:0;background:#000}img{width:1200px;height:880px}</style><img src="${base}/neural-map.svg">`);
  await page.waitForFunction(()=>document.querySelector('img').complete);
  for(let i=0;i<3;i++){await page.waitForTimeout(1600);await page.screenshot({path:path.join(out,`svg-${i}.png`)});}
  await page.goto(base+'/neural-map.svg');await page.evaluate(()=>{const style=document.createElementNS('http://www.w3.org/2000/svg','style');style.textContent='text{font-family:"DejaVu Sans",sans-serif!important}';document.documentElement.append(style);});await page.screenshot({path:path.join(out,'svg-dejavu.png')});
  await page.close();
  const embed=await browser.newPage({viewport:{width:1100,height:1000}});const embedErrors=[];embed.on('pageerror',e=>embedErrors.push(e.message));
  await withDeploymentHeaders(embed);await embed.goto(base);
  await embed.setContent(`<iframe sandbox="allow-scripts" style="width:1060px;height:960px" src="${base}/neural-map.html"></iframe>`);
  const frame=embed.frameLocator('iframe');await frame.locator('[data-node="query"]').dispatchEvent('click');
  assert(await frame.locator('#detail h3').textContent()==='Scoped retrieval','opaque-origin sandbox embed works');assert(!embedErrors.length,'embed errors');
  await embed.screenshot({path:path.join(out,'sandbox-embed.png')});await embed.close();
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
