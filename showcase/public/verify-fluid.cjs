// A real-pointer regression check for route changes, not a replacement for verify.cjs.
const path=require('node:path'),fs=require('node:fs');
const {chromium}=require(process.env.PLAYWRIGHT_CORE_PATH||path.join(process.env.APPDATA,'npm/node_modules/openclaw/node_modules/playwright-core'));
const base=process.env.SHOWCASE_URL||'http://127.0.0.1:8895';
const out=path.join(__dirname,'validation');fs.mkdirSync(out,{recursive:true});
const assert=(value,message)=>{if(!value)throw Error(message);};
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/neural-map.html',{waitUntil:'networkidle'});
  await page.locator('.neural-svg').scrollIntoViewIfNeeded();
  const start=await page.locator('[data-node="context"] .soma').evaluate(el=>{
   const m=el.getScreenCTM(),p=new DOMPoint(+el.getAttribute('cx'),+el.getAttribute('cy')).matrixTransform(m);
   return{x:p.x,y:p.y,dy:120*m.d};
  });
  await page.evaluate(()=>{
   window.wireBefore=document.querySelector('.edge[data-source="audit"][data-target="sources"]');
   window.flowBefore=document.querySelector('.flow[data-source="audit"][data-target="sources"]');
   window.currentBefore=flowBefore.getAnimations()[0];window.phaseBefore=currentBefore.startTime;
   window.childChanges=0;window.wireObserver=new MutationObserver(records=>{childChanges+=records.filter(r=>r.type==='childList').length;});wireObserver.observe(document.querySelector('#network'),{childList:true,subtree:true});
  });
  await page.mouse.move(start.x,start.y);await page.mouse.down();
  // Move durable context down through the corridor that requires a real route
  // change in the unrelated audit -> source connection. Record every frame.
  const frames=await page.evaluate(async target=>{
   const svg=document.querySelector('.neural-svg'),samples=[];
   svg.dispatchEvent(new PointerEvent('pointermove',{pointerId:1,clientX:target.x,clientY:target.y,bubbles:true}));
   const started=performance.now();
   while(performance.now()-started<900){await new Promise(requestAnimationFrame);samples.push({t:performance.now()-started,d:wireBefore.getAttribute('d'),pulse:flowBefore.getAttribute('d')});}
   return samples;
  },{x:start.x,y:start.y+start.dy});
  await page.mouse.up();
  const continuity=await page.evaluate(()=>({sameWire:wireBefore===document.querySelector('.edge[data-source="audit"][data-target="sources"]'),sameFlow:flowBefore===document.querySelector('.flow[data-source="audit"][data-target="sources"]'),sameAnimation:currentBefore===flowBefore.getAnimations()[0],sameStartTime:phaseBefore===currentBefore.startTime,childChanges,selected:document.querySelector('#detail h3').textContent}));
  const graph=JSON.parse(fs.readFileSync(path.join(__dirname,'architecture.json'),'utf8'));
  const s=graph.nodes.find(n=>n.id==='audit'),t=graph.nodes.find(n=>n.id==='sources'),dx=t.x-s.x,dy=t.y-s.y;
  const bends=frames.map(f=>{const v=f.d.match(/-?\d+(?:\.\d+)?/g).map(Number);return((v[3]-(s.y+t.y)/2)*dx-(v[2]-(s.x+t.x)/2)*dy)/(dx*dx+dy*dy);});
  const maxBendStep=Math.max(...bends.slice(1).map((b,i)=>Math.abs(b-bends[i])));
  assert(frames.length>=12,'enough actual animation frames');
  assert(new Set(frames.map(f=>f.d)).size>=5,'route morph has intermediate shapes');
  assert(bends[0]>-.1&&Math.abs(bends.at(-1)+.12)<.002,'route settles onto the required new bend');
  assert(maxBendStep<.08,'no abrupt route switch: '+maxBendStep);
  assert(frames.every(f=>f.d===f.pulse),'current follows the very same live curve');
  assert(continuity.sameWire&&continuity.sameFlow&&continuity.sameAnimation&&continuity.sameStartTime&&continuity.childChanges===0,'wire/current DOM and animation phase survive drag');
  assert(continuity.selected==='Memory is a system.','drag does not trigger selection');
  await page.screenshot({path:path.join(out,'fluid-connection-drag.png'),fullPage:true});
  await page.locator('#reset').click();
  const original=await page.locator('.edge[data-source="audit"][data-target="sources"]').getAttribute('d');
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.mouse.move(start.x,start.y);await page.mouse.down();
  const immediate=await page.evaluate(target=>{
   document.querySelector('.neural-svg').dispatchEvent(new PointerEvent('pointermove',{pointerId:1,clientX:target.x,clientY:target.y,bubbles:true}));return wireBefore.getAttribute('d');
  },{x:start.x,y:start.y+start.dy});
  await page.mouse.up();await page.waitForTimeout(180);
  assert(immediate!==original&&immediate===await page.locator('.edge[data-source="audit"][data-target="sources"]').getAttribute('d'),'reduced-motion route responds immediately without easing');
  await page.locator('#reset').click();await page.waitForTimeout(180);
  assert(original===await page.locator('.edge[data-source="audit"][data-target="sources"]').getAttribute('d'),'reset is exact and remains stable');
  assert(!errors.length,'page errors: '+errors.join('; '));
  const receipt={base,frames:frames.length,intermediateShapes:new Set(frames.map(f=>f.d)).size,maxBendStep,initialBend:bends[0],finalBend:bends.at(-1),continuity,reducedMotionImmediate:true,resetExact:true,errors};
  fs.writeFileSync(path.join(out,'fluid-motion-receipt.json'),JSON.stringify({receipt,samples:frames},null,2));console.log(JSON.stringify(receipt));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
