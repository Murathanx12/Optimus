(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('architecture-data').textContent);
  const byId = new Map(data.nodes.map(node => [node.id, node]));
  const svg = document.querySelector('.neural-svg');
  const network = svg.querySelector('#network');
  const detail = document.getElementById('detail');
  const motion = document.getElementById('motion');
  const trace = document.getElementById('trace');
  const traceNext = document.getElementById('trace-next');
  const search = document.getElementById('search');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const defaultDetail = detail.innerHTML;
  const initial = new Map(data.nodes.map(n => [n.id,{x:n.x,y:n.y}]));
  let paused = false, selected = null, tracing = false, routeStep = 0, routeClock = 0;
  let zoom = 1, panX = 0, panY = 0, drag = null, suppressClick = false;
  const make = (tag, text, cls) => { const el = document.createElement(tag); el.textContent = text; if(cls) el.className = cls; return el; };
  function select(id) {
    selected = id;
    const n = byId.get(id);
    document.querySelectorAll('[data-node]').forEach(el => { el.classList.toggle('selected',el.dataset.node === id); el.setAttribute('aria-pressed',String(el.dataset.node === id)); });
    document.querySelectorAll('[data-pick]').forEach(el => el.setAttribute('aria-pressed',String(el.dataset.pick === id)));
    if(!n) { detail.innerHTML = defaultDetail; return; }
    detail.replaceChildren(make('p', data.sectors[n.sector] || 'Shared memory', 'meta'),make('h3',n.label),make('p',n.purpose));
    detail.append(make('h4','Responsibilities'));
    const caps = make('ul',''); n.capabilities.forEach(c => caps.append(make('li',c))); detail.append(caps);
    detail.append(make('h4','Connected modules'));
    const links = make('ul','');
    data.edges.filter(e => e.source === id || e.target === id).forEach(e => {
      const outgoing = e.source === id, target = byId.get(outgoing ? e.target : e.source);
      const li = make('li',''); const b = make('button',target.label); b.className='connection-button';
      b.addEventListener('click',() => select(target.id));
      li.append(b,document.createTextNode(' — '+e.relation+(outgoing?'':' (incoming)'))); links.append(li);
    });
    detail.append(links);
    const a = make('a',n.module,'module-source');a.href=n.href;detail.append(a);
    detail.append(make('p','Public source architecture. This module selection does not query personal memory.','boundary'));
  }
  function searchModules() {
    const q = search.value.trim().toLowerCase();
    const matches = new Set(data.nodes.filter(n => [n.label,n.purpose,n.module,...n.capabilities].join(' ').toLowerCase().includes(q)).map(n=>n.id));
    document.querySelectorAll('[data-node]').forEach(el=>el.classList.toggle('dim',q!==''&&!matches.has(el.dataset.node)));
    document.querySelectorAll('[data-pick]').forEach(el=>el.hidden=!matches.has(el.dataset.pick));
    document.getElementById('search-status').textContent=q ? matches.size+' matching modules. Select a highlighted neuron or open the module directory.' : '';
  }
  function transform() { network.setAttribute('transform',`translate(${600+panX} ${440+panY}) scale(${zoom}) translate(-600 -440)`); }
  // Keep each wire and its running current in place. Only the curve geometry
  // changes: obstacle avoidance can choose a new bend without snapping routes.
  const wires = [...svg.querySelectorAll('.edge')].map(edge => {
    const source=byId.get(edge.dataset.source),target=byId.get(edge.dataset.target);
    const values=edge.getAttribute('d').match(/-?\d+(?:\.\d+)?/g).map(Number);
    const dx=target.x-source.x,dy=target.y-source.y;
    const bend=((values[3]-(source.y+target.y)/2)*dx-(values[2]-(source.x+target.x)/2)*dy)/(dx*dx+dy*dy);
    return {source,target,edge,flow:svg.querySelector(`.flow[data-source="${source.id}"][data-target="${target.id}"]`),original:edge.getAttribute('d'),bend,targetBend:bend};
  });
  let geometryFrame=0,geometryTime=0,routesDirty=false;
  function chooseBend(s,t) {
    const dx=t.x-s.x,dy=t.y-s.y;
    let best;
    for(const bend of [.12,-.12,.28,-.28,.46,-.46,.7,-.7]) {
      const cx=(s.x+t.x)/2-dy*bend,cy=(s.y+t.y)/2+dx*bend;
      const endpoint=n=>{const vx=cx-n.x,vy=cy-n.y,scale=((n.ring?12:25)+9)/Math.max(1,Math.hypot(vx,vy));return{x:n.x+vx*scale,y:n.y+vy*scale};};
      const start=endpoint(s),end=endpoint(t);let penalty=Math.abs(bend)*.01;
      for(let k=1;k<40;k++) {const f=k/40,x=(1-f)**2*start.x+2*(1-f)*f*cx+f*f*end.x,y=(1-f)**2*start.y+2*(1-f)*f*cy+f*f*end.y;
        data.nodes.forEach(n=>{if(n.id!==s.id&&n.id!==t.id)penalty+=Math.max(0,(n.ring?12:25)+20-Math.hypot(x-n.x,y-n.y))**2;});
      }
      if(!best||penalty<best.penalty)best={penalty,bend};
    }
    return best.bend;
  }
  function wirePath(wire) {
    const s=wire.source,t=wire.target,dx=t.x-s.x,dy=t.y-s.y;
    const cx=(s.x+t.x)/2-dy*wire.bend,cy=(s.y+t.y)/2+dx*wire.bend;
    const endpoint=n=>{const vx=cx-n.x,vy=cy-n.y,scale=((n.ring?12:25)+9)/Math.max(1,Math.hypot(vx,vy));return{x:n.x+vx*scale,y:n.y+vy*scale};};
    const start=endpoint(s),end=endpoint(t);
    return `M${start.x.toFixed(2)},${start.y.toFixed(2)}Q${cx.toFixed(2)},${cy.toFixed(2)} ${end.x.toFixed(2)},${end.y.toFixed(2)}`;
  }
  function drawConnections(now) {
    geometryFrame=0;
    if(routesDirty){wires.forEach(wire=>{wire.targetBend=chooseBend(wire.source,wire.target);});routesDirty=false;}
    const direct=reduced.matches||document.hidden;
    const mix=direct?1:1-Math.exp(-Math.min(32,geometryTime?now-geometryTime:16)/90);
    geometryTime=now;let settling=false;
    wires.forEach(wire=>{
      wire.bend+=(wire.targetBend-wire.bend)*mix;
      if(Math.abs(wire.targetBend-wire.bend)<.0001)wire.bend=wire.targetBend;else settling=true;
      const path=wirePath(wire);wire.edge.setAttribute('d',path);wire.flow.setAttribute('d',path);
    });
    if(settling)geometryFrame=requestAnimationFrame(drawConnections);else geometryTime=0;
  }
  function restoreConnections() {
    cancelAnimationFrame(geometryFrame);geometryFrame=geometryTime=0;routesDirty=false;
    wires.forEach(wire=>{
      wire.bend=wire.targetBend=chooseBend(wire.source,wire.target);
      wire.edge.setAttribute('d',wire.original);wire.flow.setAttribute('d',wire.original);
    });
  }
  function redrawNodes() {
    svg.querySelectorAll('[data-node]').forEach(el=>{const n=byId.get(el.dataset.node),start=initial.get(n.id);el.setAttribute('transform',`translate(${n.x-start.x} ${n.y-start.y})`);});
    routesDirty=true;
    if(reduced.matches){cancelAnimationFrame(geometryFrame);drawConnections(performance.now());}
    else if(!geometryFrame)geometryFrame=requestAnimationFrame(drawConnections);
  }
  function localPoint(event) { const p=new DOMPoint(event.clientX,event.clientY);return p.matrixTransform(network.getScreenCTM().inverse()); }
  const changeZoom = multiplier => { zoom=Math.max(.7,Math.min(2.4,zoom*multiplier));transform(); };
  document.getElementById('zoom-in').addEventListener('click',()=>changeZoom(1.2));
  document.getElementById('zoom-out').addEventListener('click',()=>changeZoom(1/1.2));
  document.getElementById('reset').addEventListener('click',()=>{zoom=1;panX=panY=0;data.nodes.forEach(n=>Object.assign(n,initial.get(n.id)));redrawNodes();restoreConnections();transform();search.value='';searchModules();select(null);});
  svg.addEventListener('pointerdown',event=>{
    if(event.button!==0)return;
    const node=event.target.closest('[data-node]'),point=localPoint(event);
    drag={id:node?.dataset.node,x:event.clientX,y:event.clientY,point,px:panX,py:panY,moved:false};
    if(drag.id){const n=byId.get(drag.id);drag.nx=n.x;drag.ny=n.y;}
    svg.setPointerCapture(event.pointerId);svg.style.cursor='grabbing';
  });
  svg.addEventListener('pointermove',event=>{
    if(!drag)return;
    if(Math.hypot(event.clientX-drag.x,event.clientY-drag.y)<5&&!drag.moved)return;
    drag.moved=true;
    if(drag.id) {
      const point=localPoint(event),n=byId.get(drag.id);
      const next={x:Math.max(-600,Math.min(1800,drag.nx+point.x-drag.point.x)),y:Math.max(-600,Math.min(1480,drag.ny+point.y-drag.point.y))};
      if(data.nodes.every(other=>other===n||Math.hypot(next.x-other.x,next.y-other.y)>((n.ring?12:25)+(other.ring?12:25)+38))) {
        Object.assign(n,next);redrawNodes();
      }
    } else {
      const p=new DOMPoint(event.clientX,event.clientY).matrixTransform(svg.getScreenCTM().inverse()),start=new DOMPoint(drag.x,drag.y).matrixTransform(svg.getScreenCTM().inverse());
      panX=Math.max(-1800,Math.min(1800,drag.px+p.x-start.x));panY=Math.max(-1480,Math.min(1480,drag.py+p.y-start.y));transform();
    }
  });
  const finishDrag=event=>{if(event.type==='pointerup'&&drag?.id&&!drag.moved)select(drag.id);suppressClick=!!drag?.moved;drag=null;svg.style.cursor='';if(svg.hasPointerCapture(event.pointerId))svg.releasePointerCapture(event.pointerId);setTimeout(()=>{suppressClick=false;},0);};svg.addEventListener('pointerup',finishDrag);svg.addEventListener('pointercancel',finishDrag);
  svg.addEventListener('click',event=>{if(suppressClick){event.preventDefault();event.stopPropagation();return;}const node=event.target.closest('[data-node]');if(node)select(node.dataset.node);});
  document.querySelectorAll('[data-node]').forEach(el=>{el.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(el.dataset.node);}});});
  document.querySelectorAll('[data-pick]').forEach(el=>el.addEventListener('click',()=>select(el.dataset.pick)));
  search.addEventListener('input',searchModules);
  search.addEventListener('keydown',event=>{if(event.key==='Escape'){search.value='';searchModules();}if(event.key==='Enter'){const node=data.nodes.find(n=>[n.label,n.module,n.purpose].join(' ').toLowerCase().includes(search.value.toLowerCase()));if(node)select(node.id);}});
  function updateMotion() {
    const stop=paused||reduced.matches||document.hidden;
    if((reduced.matches||document.hidden)&&geometryFrame){cancelAnimationFrame(geometryFrame);drawConnections(performance.now());}
    svg.classList.toggle('paused',stop);
    motion.textContent=reduced.matches?'Motion off · system setting':paused?'Resume motion':'Pause motion';
    motion.disabled=reduced.matches;motion.setAttribute('aria-pressed',String(paused));
    clearInterval(routeClock);
    if(tracing&&!stop)routeClock=setInterval(()=>{routeStep=(routeStep+1)%data.route.length;showStep();},3200);
  }
  function showStep() {
    const steps=['Choose the relevant project context.','Retrieve source-linked memory.','Pass focused context through MCP.','The assistant receives the context.'];
    select(data.route[routeStep]);
    document.getElementById('trace-status').textContent=`Step ${routeStep+1} of ${data.route.length}: ${steps[routeStep]} Illustrative public architecture only; no private query or model call.`;
  }
  motion.addEventListener('click',()=>{paused=!paused;updateMotion();});
  traceNext.addEventListener('click',()=>{routeStep=(routeStep+1)%data.route.length;showStep();updateMotion();});
  trace.addEventListener('click',()=>{
    tracing=!tracing;trace.setAttribute('aria-pressed',String(tracing));trace.textContent=tracing?'End walkthrough':'How retrieval works';
    traceNext.hidden=!tracing;
    svg.querySelectorAll('.edge').forEach(el=>{const s=data.route.indexOf(el.dataset.source),t=data.route.indexOf(el.dataset.target);el.classList.toggle('trace',tracing&&s>=0&&t===s+1);});
    document.getElementById('trace-status').textContent='The graph is generated from a curated public module table. No personal corpus counts or query scores are shown.';
    routeStep=0;if(tracing)showStep();updateMotion();
  });
  reduced.addEventListener('change',updateMotion);document.addEventListener('visibilitychange',updateMotion);updateMotion();
})();
