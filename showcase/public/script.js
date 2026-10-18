(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('architecture-data').textContent);
  const byId = new Map(data.nodes.map(node => [node.id, node]));
  const svg = document.querySelector('.neural-svg');
  const network = svg.querySelector('#network');
  const detail = document.getElementById('detail');
  const motion = document.getElementById('motion');
  const trace = document.getElementById('trace');
  const search = document.getElementById('search');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const defaultDetail = detail.innerHTML;
  let paused = false, selected = null, tracing = false, routeStep = 0, routeClock = 0;
  let zoom = 1, panX = 0, panY = 0, drag = null;
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
  const changeZoom = multiplier => { zoom=Math.max(.7,Math.min(2.4,zoom*multiplier));transform(); };
  document.getElementById('zoom-in').addEventListener('click',()=>changeZoom(1.2));
  document.getElementById('zoom-out').addEventListener('click',()=>changeZoom(1/1.2));
  document.getElementById('reset').addEventListener('click',()=>{zoom=1;panX=panY=0;transform();search.value='';searchModules();select(null);});
  svg.addEventListener('pointerdown',event=>{
    if(event.target.closest('[data-node]')||event.button!==0||event.pointerType==='touch')return;
    drag={x:event.clientX,y:event.clientY,px:panX,py:panY};svg.setPointerCapture(event.pointerId);svg.style.cursor='grabbing';
  });
  svg.addEventListener('pointermove',event=>{if(!drag)return;const r=svg.getBoundingClientRect();const scale=880/r.width;panX=Math.max(-600,Math.min(600,drag.px+(event.clientX-drag.x)*scale));panY=Math.max(-440,Math.min(440,drag.py+(event.clientY-drag.y)*scale));transform();});
  const finishDrag=()=>{drag=null;svg.style.cursor='';};svg.addEventListener('pointerup',finishDrag);svg.addEventListener('pointercancel',finishDrag);
  document.querySelectorAll('[data-node]').forEach(el=>{el.addEventListener('click',()=>select(el.dataset.node));el.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(el.dataset.node);}});});
  document.querySelectorAll('[data-pick]').forEach(el=>el.addEventListener('click',()=>select(el.dataset.pick)));
  search.addEventListener('input',searchModules);
  search.addEventListener('keydown',event=>{if(event.key==='Escape'){search.value='';searchModules();}if(event.key==='Enter'){const node=data.nodes.find(n=>[n.label,n.module,n.purpose].join(' ').toLowerCase().includes(search.value.toLowerCase()));if(node)select(node.id);}});
  function updateMotion() {
    const stop=paused||reduced.matches||document.hidden;
    svg.classList.toggle('paused',stop);
    motion.textContent=reduced.matches?'Motion off · system setting':paused?'Resume motion':'Pause motion';
    motion.disabled=reduced.matches;motion.setAttribute('aria-pressed',String(paused));
    clearInterval(routeClock);
    if(tracing&&!stop)routeClock=setInterval(()=>{routeStep=(routeStep+1)%data.route.length;select(data.route[routeStep]);},2200);
  }
  motion.addEventListener('click',()=>{paused=!paused;updateMotion();});
  trace.addEventListener('click',()=>{
    tracing=!tracing;trace.setAttribute('aria-pressed',String(tracing));trace.textContent=tracing?'End trace':'Trace retrieval';
    svg.querySelectorAll('.edge').forEach(el=>{const s=data.route.indexOf(el.dataset.source),t=data.route.indexOf(el.dataset.target);el.classList.toggle('trace',tracing&&s>=0&&t===s+1);});
    document.getElementById('trace-status').textContent=tracing?'Illustrative route: domain routing → scoped retrieval → MCP interface → compatible assistant. This is an explanation of source modules, not a recorded query or a model call.':'The graph is generated from a curated public module table. No personal corpus counts or query scores are shown.';
    routeStep=0;if(tracing)select(data.route[0]);updateMotion();
  });
  reduced.addEventListener('change',updateMotion);document.addEventListener('visibilitychange',updateMotion);updateMotion();
})();
