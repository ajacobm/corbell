"""Single-page app HTML for the Corbell architecture graph UI.

The entire frontend is one self-contained HTML string. No build step,
no static asset files. Just serve this string and the browser does the rest.
"""

from __future__ import annotations


def build_page(workspace_name: str = "my-platform") -> str:
    """Return the complete HTML for the Corbell UI."""
    return _PAGE_HTML.replace("__WS_NAME__", workspace_name)


_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Corbell · __WS_NAME__</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d1117;
  --bg2:#161b22;
  --bg3:#21262d;
  --border:#30363d;
  --text:#c9d1d9;
  --text2:#8b949e;
  --text3:#6e7681;
  --accent:#58a6ff;
  --teal:#39d353;
  --amber:#ffa657;
  --purple:#bc8cff;
  --red:#ff7b72;
  --pink:#f778ba;
  --glow-blue:rgba(88,166,255,0.2);
  --glow-teal:rgba(57,211,83,0.2);
  --radius:8px;
  --sidebar:230px;
  --panel:300px;
  --header:48px;
  --footer:44px;
}
html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;font-size:13px}

/* ── Layout ─────────────────────────────────────── */
#app{display:grid;grid-template-rows:var(--header) 1fr var(--footer);height:100vh}
#header{display:flex;align-items:center;gap:12px;padding:0 20px;background:var(--bg2);border-bottom:1px solid var(--border);z-index:100}
#header .logo{font-size:18px;font-weight:700;color:var(--text);letter-spacing:-0.5px}
#header .ws-name{font-size:13px;color:var(--text2);padding:3px 10px;background:var(--bg3);border-radius:20px;border:1px solid var(--border)}
#header .stats{margin-left:auto;display:flex;gap:8px}
.stat-pill{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--text2);background:var(--bg3);border:1px solid var(--border);border-radius:20px;padding:3px 10px}
.stat-pill .dot{width:7px;height:7px;border-radius:50%}

#body{display:grid;grid-template-columns:var(--sidebar) 1fr var(--panel);overflow:hidden}

/* ── Sidebar ─────────────────────────────────────── */
#sidebar{background:var(--bg2);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.sidebar-section{padding:12px 14px 6px;font-size:10px;font-weight:600;color:var(--text3);letter-spacing:0.08em;text-transform:uppercase}
.sidebar-scroll{flex:1;overflow-y:auto;padding-bottom:8px}
.sidebar-scroll::-webkit-scrollbar{width:4px}
.sidebar-scroll::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.sidebar-item{display:flex;align-items:center;gap:8px;padding:6px 14px;cursor:pointer;border-radius:0;transition:background 0.15s}
.sidebar-item:hover{background:var(--bg3)}
.sidebar-item.active{background:rgba(88,166,255,0.1);border-right:2px solid var(--accent)}
.sidebar-item .si-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.sidebar-item .si-label{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
.sidebar-item .si-badge{font-size:10px;color:var(--text3);background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:1px 6px}
#sidebar-search{padding:10px 12px 6px;position:relative}
#sidebar-search input{width:100%;background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:12px;font-family:inherit;outline:none}
#sidebar-search input:focus{border-color:var(--accent)}
.sidebar-divider{height:1px;background:var(--border);margin:6px 0}
.section-toggle{display:flex;align-items:center;justify-content:space-between;cursor:pointer;padding:8px 14px 4px}
.section-toggle:hover .sidebar-section{color:var(--text2)}

/* ── Graph canvas ────────────────────────────────── */
#graph-panel{position:relative;overflow:hidden;background:var(--bg)}
#graph-panel svg{width:100%;height:100%}
.grid-line{stroke:var(--border);stroke-width:0.5;opacity:0.4}
.node-service circle{fill:var(--bg2);stroke:var(--teal);stroke-width:1.5;transition:all 0.2s}
.node-service.hovered circle,.node-service.selected circle{stroke:var(--accent);stroke-width:2.5;filter:drop-shadow(0 0 8px var(--glow-blue))}
.node-datastore circle{fill:var(--bg2);stroke:var(--amber);stroke-width:1.5}
.node-datastore.hovered circle{stroke:var(--amber);filter:drop-shadow(0 0 6px rgba(255,166,87,0.3))}
.node-queue circle{fill:var(--bg2);stroke:var(--purple);stroke-width:1.5}
.node-queue.hovered circle{stroke:var(--purple);filter:drop-shadow(0 0 6px rgba(188,140,255,0.3))}
.node-flow circle{fill:var(--bg2);stroke:var(--pink);stroke-width:1.5}
.node text{fill:var(--text2);font-size:11px;font-family:'Inter',sans-serif;pointer-events:none;text-anchor:middle}
.node text.node-label{fill:var(--text);font-size:11.5px;font-weight:500}
.node text.node-sublabel{font-size:9.5px;fill:var(--text3)}
.link{stroke-opacity:0.65;fill:none}
.link.db_read{stroke:var(--amber);stroke-width:1.5}
.link.http_call{stroke:var(--accent);stroke-width:1.5}
.link.queue_publish{stroke:var(--purple);stroke-width:1.5}
.link.git_coupling{stroke:var(--red);stroke-width:1;stroke-dasharray:4,3}
.link.hovered{stroke-opacity:1;stroke-width:2.5}

/* Tooltip */
#tooltip{position:fixed;pointer-events:none;background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:8px 12px;font-size:12px;z-index:999;opacity:0;transition:opacity 0.15s;max-width:220px}
#tooltip .tt-title{font-weight:600;color:var(--text);margin-bottom:3px}
#tooltip .tt-sub{color:var(--text2);font-size:11px}

/* Graph controls */
#graph-controls{position:absolute;bottom:16px;right:16px;display:flex;gap:6px}
.graph-btn{background:var(--bg2);border:1px solid var(--border);color:var(--text2);border-radius:6px;width:32px;height:32px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:14px;transition:all 0.15s}
.graph-btn:hover{border-color:var(--accent);color:var(--accent)}
#graph-hint{position:absolute;top:14px;left:50%;transform:translateX(-50%);font-size:11px;color:var(--text3);pointer-events:none;opacity:0.7}

/* Legend */
#legend{position:absolute;bottom:16px;left:16px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:10px 14px;display:flex;flex-direction:column;gap:5px}
.legend-row{display:flex;align-items:center;gap:7px;font-size:11px;color:var(--text2)}
.legend-line{width:20px;height:2px;border-radius:1px}
.legend-circle{width:10px;height:10px;border-radius:50%;border:2px solid}

/* ── Detail panel ────────────────────────────────── */
#detail-panel{background:var(--bg2);border-left:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
#detail-empty{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:var(--text3)}
#detail-empty .de-icon{font-size:40px;opacity:0.3}
#detail-empty p{font-size:12px}
#detail-content{flex:1;overflow-y:auto;display:none;flex-direction:column}
#detail-content::-webkit-scrollbar{width:4px}
#detail-content::-webkit-scrollbar-thumb{background:var(--border)}
#detail-header{padding:16px 16px 12px;border-bottom:1px solid var(--border)}
#detail-header .dh-name{font-size:16px;font-weight:700;color:var(--text);margin-bottom:6px}
.dh-badges{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:6px}
.badge{display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:500;padding:2px 8px;border-radius:20px;border:1px solid}
.badge-lang{color:var(--teal);border-color:var(--teal);background:rgba(57,211,83,0.08)}
.badge-type{color:var(--accent);border-color:var(--accent);background:rgba(88,166,255,0.08)}
.badge-tag{color:var(--text2);border-color:var(--border);background:var(--bg3)}
.dh-repo{font-size:10px;color:var(--text3);font-family:'JetBrains Mono',monospace;word-break:break-all}
.detail-section{padding:12px 16px;border-bottom:1px solid var(--border)}
.detail-section h4{font-size:10px;font-weight:600;color:var(--text3);letter-spacing:0.08em;text-transform:uppercase;margin-bottom:8px;display:flex;align-items:center;gap:6px}
.detail-section h4 .count{font-size:10px;color:var(--text3);background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:0 6px}
.dep-item{display:flex;align-items:center;gap:7px;padding:4px 0;font-size:12px;border-radius:4px;cursor:default}
.dep-item .dep-icon{font-size:12px;width:16px;text-align:center;flex-shrink:0}
.dep-item .dep-target{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)}
.dep-item .dep-kind{font-size:10px;color:var(--text3);background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:0 6px;flex-shrink:0}
.dep-item.clickable{cursor:pointer}
.dep-item.clickable:hover .dep-target{color:var(--accent)}
.method-list{max-height:280px;overflow-y:auto}
.method-list::-webkit-scrollbar{width:3px}
.method-list::-webkit-scrollbar-thumb{background:var(--border)}
.method-item{padding:3px 0;border-bottom:1px solid rgba(48,54,61,0.5)}
.method-item:last-child{border-bottom:none}
.method-sig{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--teal);word-break:break-all;line-height:1.5}
.method-file{font-size:10px;color:var(--text3)}
.flow-item{display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12px}
.flow-dot{width:6px;height:6px;border-radius:50%;background:var(--pink);flex-shrink:0}
.coupling-item{display:flex;gap:6px;padding:3px 0;font-size:11px;color:var(--text2);align-items:flex-start}
.coupling-strength{font-size:10px;padding:1px 6px;border-radius:10px;border:1px solid;flex-shrink:0}
.coupling-high{color:var(--red);border-color:var(--red);background:rgba(255,123,114,0.08)}
.coupling-med{color:var(--amber);border-color:var(--amber);background:rgba(255,166,87,0.08)}
.coupling-files{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--text3);line-height:1.5}

/* ── Constraints bar ─────────────────────────────── */
#footer{background:var(--bg2);border-top:1px solid var(--border);display:flex;align-items:center;gap:10px;padding:0 16px;overflow:hidden}
#footer .footer-label{font-size:10px;font-weight:600;color:var(--amber);letter-spacing:0.06em;text-transform:uppercase;white-space:nowrap;display:flex;align-items:center;gap:5px}
#constraints-pills{display:flex;gap:6px;overflow-x:auto;flex:1;scrollbar-width:none;padding:4px 0}
#constraints-pills::-webkit-scrollbar{display:none}
.constraint-pill{display:flex;align-items:center;gap:5px;white-space:nowrap;font-size:11px;padding:3px 10px;border-radius:20px;background:rgba(255,166,87,0.07);border:1px solid rgba(255,166,87,0.2);color:var(--amber);cursor:pointer;transition:all 0.15s;flex-shrink:0}
.constraint-pill:hover{background:rgba(255,166,87,0.15);border-color:rgba(255,166,87,0.4)}
.no-constraints{font-size:11px;color:var(--text3);font-style:italic}

/* Constraint overlay */
#constraint-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:none;align-items:center;justify-content:center}
#constraint-overlay.show{display:flex}
#constraint-box{background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:24px;max-width:520px;width:90%;max-height:80vh;overflow-y:auto}
#constraint-box h3{font-size:16px;font-weight:700;margin-bottom:16px;color:var(--amber);display:flex;align-items:center;gap:8px}
.constraint-entry{padding:10px 0;border-bottom:1px solid var(--border)}
.constraint-entry:last-child{border-bottom:none}
.ce-text{color:var(--text);font-size:13px;line-height:1.6}
.ce-source{font-size:10px;color:var(--text3);margin-top:3px}
.close-btn{float:right;background:var(--bg3);border:1px solid var(--border);color:var(--text2);padding:4px 12px;border-radius:6px;cursor:pointer;font-size:12px}

/* Loading */
#loading{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:var(--bg);z-index:50;flex-direction:column;gap:16px}
.spinner{width:36px;height:36px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin 0.8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
#loading p{color:var(--text2);font-size:13px}

/* Scrollbars */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
</style>
</head>
<body>
<div id="app">
  <!-- Header -->
  <div id="header">
    <span class="logo">🏗️ Corbell</span>
    <span class="ws-name" id="ws-label">__WS_NAME__</span>
    <div class="stats" id="header-stats"></div>
  </div>

  <!-- Body -->
  <div id="body">
    <!-- Sidebar -->
    <div id="sidebar">
      <div id="sidebar-search"><input id="search-input" placeholder="Filter services…" autocomplete="off"/></div>
      <div class="sidebar-scroll" id="sidebar-scroll">
        <div class="section-toggle"><div class="sidebar-section">Services</div></div>
        <div id="svc-list"></div>
        <div class="sidebar-divider"></div>
        <div class="section-toggle"><div class="sidebar-section">Data Stores</div></div>
        <div id="store-list"></div>
        <div class="sidebar-divider"></div>
        <div class="section-toggle"><div class="sidebar-section">Queues</div></div>
        <div id="queue-list"></div>
        <div class="sidebar-divider"></div>
        <div class="section-toggle"><div class="sidebar-section">Flows</div></div>
        <div id="flow-list"></div>
      </div>
    </div>

    <!-- Graph -->
    <div id="graph-panel">
      <div id="loading"><div class="spinner"></div><p>Loading architecture graph…</p></div>
      <svg id="graph-svg"></svg>
      <div id="tooltip">
        <div class="tt-title" id="tt-title"></div>
        <div class="tt-sub" id="tt-sub"></div>
      </div>
      <div id="graph-hint">Click a node to inspect · Scroll to zoom · Drag to pan</div>
      <div id="legend">
        <div class="legend-row"><div class="legend-circle" style="border-color:var(--teal)"></div>Service</div>
        <div class="legend-row"><div class="legend-circle" style="border-color:var(--amber)"></div>Data store</div>
        <div class="legend-row"><div class="legend-circle" style="border-color:var(--purple)"></div>Queue</div>
        <div class="legend-row"><div class="legend-circle" style="border-color:var(--pink)"></div>Flow</div>
        <div class="sidebar-divider" style="margin:4px 0"></div>
        <div class="legend-row"><div class="legend-line" style="background:var(--amber)"></div>DB dep</div>
        <div class="legend-row"><div class="legend-line" style="background:var(--accent)"></div>HTTP call</div>
        <div class="legend-row"><div class="legend-line" style="background:var(--purple)"></div>Queue pub</div>
        <div class="legend-row"><div class="legend-line" style="background:var(--red);height:1px;background-image:repeating-linear-gradient(90deg,var(--red) 0,var(--red) 4px,transparent 4px,transparent 7px)"></div>Git coupling</div>
      </div>
      <div id="graph-controls">
        <button class="graph-btn" id="btn-fit" title="Fit graph">⊡</button>
        <button class="graph-btn" id="btn-zoom-in" title="Zoom in">+</button>
        <button class="graph-btn" id="btn-zoom-out" title="Zoom out">−</button>
      </div>
    </div>

    <!-- Detail panel -->
    <div id="detail-panel">
      <div id="detail-empty">
        <div class="de-icon">🔍</div>
        <p>Click a node to inspect</p>
      </div>
      <div id="detail-content"></div>
    </div>
  </div>

  <!-- Footer: constraints bar -->
  <div id="footer">
    <div class="footer-label">⚠ Constraints</div>
    <div id="constraints-pills"></div>
  </div>
</div>

<!-- Constraint overlay -->
<div id="constraint-overlay">
  <div id="constraint-box">
    <button class="close-btn" onclick="closeConstraints()">✕ Close</button>
    <h3>⚠ Workspace Constraints</h3>
    <div id="constraint-entries"></div>
  </div>
</div>

<script>
// ── Color helpers ──────────────────────────────────────────────────────────
const LANG_COLOR = {python:'#3572A5',javascript:'#f1e05a',typescript:'#3178c6',go:'#00ADD8',java:'#b07219',default:'#8b949e'};
const KIND_COLOR = {db_read:'#ffa657',http_call:'#58a6ff',queue_publish:'#bc8cff',git_coupling:'#ff7b72'};
const KIND_ICON  = {db_read:'🗄',http_call:'🌐',queue_publish:'📨',flow_step:'▶',git_coupling:'⚡'};

// ── State ──────────────────────────────────────────────────────────────────
let graphData = null;
let simulation = null;
let svg, gMain, zoomBehavior;
let selectedId = null;
let allConstraints = [];

// ── Boot ───────────────────────────────────────────────────────────────────
async function boot() {
  const [gResp, cResp] = await Promise.all([
    fetch('/api/graph').then(r=>r.json()),
    fetch('/api/constraints').then(r=>r.json()).catch(()=>[])
  ]);
  graphData = gResp;
  allConstraints = Array.isArray(cResp) ? cResp : [];
  document.getElementById('loading').style.display='none';
  buildSidebar(graphData);
  buildGraph(graphData);
  buildConstraintsBar(allConstraints);
  buildHeaderStats(graphData);
}

// ── Header stats ───────────────────────────────────────────────────────────
function buildHeaderStats(g) {
  const svcs = g.nodes.filter(n=>n.type==='service').length;
  const stores = g.nodes.filter(n=>n.type==='datastore').length;
  const flows = g.nodes.filter(n=>n.type==='flow').length;
  const el = document.getElementById('header-stats');
  el.innerHTML = `
    <div class="stat-pill"><div class="dot" style="background:var(--teal)"></div>${svcs} services</div>
    ${stores?`<div class="stat-pill"><div class="dot" style="background:var(--amber)"></div>${stores} stores</div>`:''}
    ${flows?`<div class="stat-pill"><div class="dot" style="background:var(--pink)"></div>${flows} flows</div>`:''}
    ${allConstraints.length?`<div class="stat-pill"><div class="dot" style="background:var(--amber)"></div>${allConstraints.length} constraints</div>`:''}
  `;
}

// ── Sidebar ─────────────────────────────────────────────────────────────────
function buildSidebar(g) {
  const svcs = g.nodes.filter(n=>n.type==='service').sort((a,b)=>a.label.localeCompare(b.label));
  const stores = g.nodes.filter(n=>n.type==='datastore');
  const queues = g.nodes.filter(n=>n.type==='queue');
  const flows = g.nodes.filter(n=>n.type==='flow');

  function item(n, dotColor, badge) {
    const d = document.createElement('div');
    d.className='sidebar-item';
    d.dataset.id=n.id;
    d.innerHTML=`<div class="si-dot" style="background:${dotColor}"></div><span class="si-label">${n.label||n.id}</span>${badge?`<span class="si-badge">${badge}</span>`:''}`;
    d.onclick=()=>selectNode(n.id, n.type);
    return d;
  }

  const svcList = document.getElementById('svc-list');
  svcs.forEach(n=>svcList.appendChild(item(n,'var(--teal)',n.method_count||'')));
  const storeList = document.getElementById('store-list');
  stores.forEach(n=>storeList.appendChild(item(n,'var(--amber)',n.kind)));
  const queueList = document.getElementById('queue-list');
  queues.forEach(n=>queueList.appendChild(item(n,'var(--purple)',n.kind)));
  const flowList = document.getElementById('flow-list');
  flows.forEach(n=>flowList.appendChild(item(n,'var(--pink)',n.step_count?n.step_count+'steps':'')));

  if(!stores.length) storeList.innerHTML='<div style="padding:5px 14px;color:var(--text3);font-size:11px;font-style:italic">None detected</div>';
  if(!queues.length) queueList.innerHTML='<div style="padding:5px 14px;color:var(--text3);font-size:11px;font-style:italic">None detected</div>';
  if(!flows.length) flowList.innerHTML='<div style="padding:5px 14px;color:var(--text3);font-size:11px;font-style:italic">None detected</div>';

  // Search filter
  document.getElementById('search-input').addEventListener('input', e=>{
    const q = e.target.value.toLowerCase();
    document.querySelectorAll('#svc-list .sidebar-item').forEach(el=>{
      el.style.display = el.dataset.id.toLowerCase().includes(q)||el.querySelector('.si-label').textContent.toLowerCase().includes(q)?'':'none';
    });
  });
}

// ── D3 Graph ─────────────────────────────────────────────────────────────────
function buildGraph(g) {
  const container = document.getElementById('graph-panel');
  const W = container.clientWidth, H = container.clientHeight;
  svg = d3.select('#graph-svg');

  // Defs: arrowheads per color
  const defs = svg.append('defs');
  Object.entries(KIND_COLOR).forEach(([kind, color])=>{
    defs.append('marker').attr('id',`arrow-${kind}`).attr('viewBox','0 -5 10 10').attr('refX',22).attr('refY',0).attr('markerWidth',6).attr('markerHeight',6).attr('orient','auto')
      .append('path').attr('d','M0,-5L10,0L0,5').attr('fill',color).attr('opacity',0.8);
  });
  defs.append('marker').attr('id','arrow-default').attr('viewBox','0 -5 10 10').attr('refX',22).attr('refY',0).attr('markerWidth',6).attr('markerHeight',6).attr('orient','auto')
    .append('path').attr('d','M0,-5L10,0L0,5').attr('fill','#8b949e').attr('opacity',0.6);

  zoomBehavior = d3.zoom().scaleExtent([0.15,4]).on('zoom', e=>gMain.attr('transform', e.transform));
  svg.call(zoomBehavior);
  gMain = svg.append('g');

  // Subtle grid
  const gridG = gMain.append('g').attr('class','grid');
  for(let x=-2000;x<4000;x+=60) gridG.append('line').attr('class','grid-line').attr('x1',x).attr('x2',x).attr('y1',-2000).attr('y2',4000);
  for(let y=-2000;y<4000;y+=60) gridG.append('line').attr('class','grid-line').attr('x1',-2000).attr('x2',4000).attr('y1',y).attr('y2',y);

  const nodes = g.nodes.map(n=>Object.assign({},n));
  const nodeMap = Object.fromEntries(nodes.map(n=>[n.id,n]));
  const edges = g.edges.filter(e=>nodeMap[e.source]&&nodeMap[e.target]).map(e=>Object.assign({},e,{source:nodeMap[e.source],target:nodeMap[e.target]}));

  // Force sim
  simulation = d3.forceSimulation(nodes)
    .force('link',d3.forceLink(edges).id(d=>d.id).distance(d=>d.kind==='git_coupling'?200:d.kind==='http_call'?180:140).strength(0.6))
    .force('charge',d3.forceManyBody().strength(-380))
    .force('center',d3.forceCenter(W/2,H/2))
    .force('collision',d3.forceCollide().radius(d=>nodeRadius(d)+24))
    .alphaDecay(0.025);

  // Links
  const link = gMain.append('g').selectAll('line').data(edges).join('line')
    .attr('class', d=>`link ${d.kind}`)
    .attr('marker-end', d=>`url(#arrow-${KIND_COLOR[d.kind]?d.kind:'default'})`)
    .on('mouseover', function(e,d){
      d3.select(this).classed('hovered',true);
      showTooltip(e,`${KIND_ICON[d.kind]||'→'} ${d.kind.replace(/_/g,' ')}`,`${d.source.label||d.source.id} → ${d.target.label||d.target.id}`);
    })
    .on('mouseout', function(){d3.select(this).classed('hovered',false);hideTooltip()})
    .on('mousemove', moveTooltip);

  // Nodes
  const node = gMain.append('g').selectAll('g').data(nodes).join('g')
    .attr('class', d=>`node node-${d.type}`)
    .attr('data-id', d=>d.id)
    .call(d3.drag().on('start',dragStart).on('drag',dragging).on('end',dragEnd))
    .on('click', (e,d)=>{ e.stopPropagation(); selectNode(d.id, d.type); })
    .on('mouseover',(e,d)=>{d3.select(e.currentTarget).classed('hovered',true);showTooltip(e,d.label||d.id,nodeSubLabel(d))})
    .on('mouseout',(e,d)=>{d3.select(e.currentTarget).classed('hovered',false);hideTooltip()})
    .on('mousemove', moveTooltip);

  node.append('circle').attr('r', d=>nodeRadius(d));

  // Language ring for services
  node.filter(d=>d.type==='service').append('circle')
    .attr('r', d=>nodeRadius(d)+3)
    .attr('fill','none')
    .attr('stroke', d=>LANG_COLOR[d.language]||LANG_COLOR.default)
    .attr('stroke-width',1.5)
    .attr('opacity',0.35);

  // Icon inside node
  node.append('text').attr('dy','0.35em').attr('font-size', d=>d.type==='service'?'14px':'12px').text(d=>nodeIcon(d));

  // Label below
  node.append('text').attr('class','node-label').attr('dy', d=>nodeRadius(d)+14).text(d=>truncate(d.label||d.id,16));
  node.filter(d=>d.type==='service'&&d.language).append('text').attr('class','node-sublabel').attr('dy', d=>nodeRadius(d)+24).text(d=>d.language);

  simulation.on('tick',()=>{
    link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y).attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
    node.attr('transform',d=>`translate(${d.x},${d.y})`);
  });

  // Bg click deselect
  svg.on('click',()=>deselect());

  // Controls
  document.getElementById('btn-fit').onclick=fitGraph;
  document.getElementById('btn-zoom-in').onclick=()=>svg.transition().call(zoomBehavior.scaleBy,1.4);
  document.getElementById('btn-zoom-out').onclick=()=>svg.transition().call(zoomBehavior.scaleBy,0.7);

  // Auto-fit after sim settles
  setTimeout(fitGraph, 2200);
}

function nodeRadius(d) {
  if(d.type==='service') return Math.max(20, Math.min(36, 18+Math.sqrt(d.method_count||0)*1.5));
  if(d.type==='datastore') return 18;
  if(d.type==='queue') return 18;
  if(d.type==='flow') return 14;
  return 16;
}
function nodeIcon(d) {
  if(d.type==='service') return '◈';
  if(d.type==='datastore') return '🗄';
  if(d.type==='queue') return '📨';
  if(d.type==='flow') return '▶';
  return '●';
}
function nodeSubLabel(d) {
  if(d.type==='service') return `${d.language} · ${d.method_count||0} methods`;
  if(d.type==='datastore') return d.kind;
  if(d.type==='queue') return d.kind;
  if(d.type==='flow') return `${d.step_count} steps`;
  return '';
}
function truncate(s,n) { return s&&s.length>n?s.slice(0,n)+'…':s; }

// ── Drag ──────────────────────────────────────────────────────────────────
function dragStart(e,d) { if(!e.active) simulation.alphaTarget(0.3).restart(); d.fx=d.x;d.fy=d.y; }
function dragging(e,d) { d.fx=e.x;d.fy=e.y; }
function dragEnd(e,d) { if(!e.active) simulation.alphaTarget(0); d.fx=null;d.fy=null; }

// ── Zoom fit ───────────────────────────────────────────────────────────────
function fitGraph() {
  const container = document.getElementById('graph-panel');
  const W=container.clientWidth, H=container.clientHeight;
  const nodes = simulation?.nodes()||[];
  if(!nodes.length) return;
  let x0=Infinity,x1=-Infinity,y0=Infinity,y1=-Infinity;
  nodes.forEach(n=>{ x0=Math.min(x0,n.x); x1=Math.max(x1,n.x); y0=Math.min(y0,n.y); y1=Math.max(y1,n.y); });
  const pad=80, sw=x1-x0+pad*2, sh=y1-y0+pad*2;
  const scale=Math.min(2, W/sw, H/sh);
  const tx=(W-(x0+x1)*scale)/2, ty=(H-(y0+y1)*scale)/2;
  svg.transition().duration(600).call(zoomBehavior.transform, d3.zoomIdentity.translate(tx,ty).scale(scale));
}

// ── Tooltip ────────────────────────────────────────────────────────────────
function showTooltip(e,title,sub) {
  const t=document.getElementById('tooltip');
  document.getElementById('tt-title').textContent=title;
  document.getElementById('tt-sub').textContent=sub;
  t.style.opacity=1; moveTooltip(e);
}
function hideTooltip() { document.getElementById('tooltip').style.opacity=0; }
function moveTooltip(e) {
  const t=document.getElementById('tooltip');
  t.style.left=Math.min(e.clientX+14,window.innerWidth-240)+'px';
  t.style.top=(e.clientY-38)+'px';
}

// ── Select node ────────────────────────────────────────────────────────────
function selectNode(id, type) {
  selectedId=id;
  document.querySelectorAll('.node').forEach(el=>el.classList.remove('selected'));
  document.querySelectorAll(`.node[data-id="${id}"]`).forEach(el=>el.classList.add('selected'));
  document.querySelectorAll('.sidebar-item').forEach(el=>el.classList.toggle('active',el.dataset.id===id));
  if(type==='service') loadDetail(id);
  else showSimpleDetail(id, type);
}

function deselect() {
  selectedId=null;
  document.querySelectorAll('.node').forEach(el=>el.classList.remove('selected'));
  document.querySelectorAll('.sidebar-item').forEach(el=>el.classList.remove('active'));
  document.getElementById('detail-empty').style.display='flex';
  document.getElementById('detail-content').style.display='none';
}

// ── Detail panel ────────────────────────────────────────────────────────────
async function loadDetail(serviceId) {
  const empty=document.getElementById('detail-empty');
  const content=document.getElementById('detail-content');
  empty.style.display='none';
  content.innerHTML='<div style="padding:20px;color:var(--text2);text-align:center">Loading…</div>';
  content.style.display='flex';

  const d = await fetch(`/api/service/${serviceId}`).then(r=>r.json());
  if(d.error) { content.innerHTML=`<div style="padding:16px;color:var(--red)">${d.error}</div>`; return; }

  const langColor = LANG_COLOR[d.language]||LANG_COLOR.default;
  const tagBadges = (d.tags||[]).map(t=>`<span class="badge badge-tag">${t}</span>`).join('');

  content.innerHTML = `
    <div id="detail-header">
      <div class="dh-name">${d.name}</div>
      <div class="dh-badges">
        <span class="badge badge-lang" style="color:${langColor};border-color:${langColor};background:${langColor}18">${d.language}</span>
        <span class="badge badge-type">${d.service_type}</span>
        ${tagBadges}
      </div>
      <div class="dh-repo">${d.repo}</div>
    </div>

    <div class="detail-section">
      <h4>Dependencies <span class="count">${d.deps_out.length}</span></h4>
      ${d.deps_out.length ? d.deps_out.map(dep=>{
        const icon=KIND_ICON[dep.kind]||'→';
        const isService=dep.target.includes('::')===false&&!dep.target.startsWith('datastore:')&&!dep.target.startsWith('queue:')&&!dep.target.startsWith('external:');
        const label=dep.target.replace(/^(datastore|queue):[^:]+:/,'').replace(/^external:/,'');
        const clickable=isService&&graphData?.nodes.find(n=>n.id===dep.target&&n.type==='service');
        return `<div class="dep-item${clickable?' clickable':''}" onclick="${clickable?`selectNode('${dep.target}','service')`:''}" >
          <span class="dep-icon">${icon}</span>
          <span class="dep-target" title="${dep.target}">${label||dep.target}</span>
          <span class="dep-kind">${dep.kind.replace(/_/g,' ')}</span>
        </div>`;
      }).join('') : '<div style="color:var(--text3);font-size:11px;font-style:italic">No outbound dependencies</div>'}
    </div>

    ${d.callers.length?`<div class="detail-section">
      <h4>Called by <span class="count">${d.callers.length}</span></h4>
      ${d.callers.map(c=>`<div class="dep-item clickable" onclick="selectNode('${c.source}','service')">
        <span class="dep-icon">←</span>
        <span class="dep-target">${c.source}</span>
        <span class="dep-kind">${c.kind.replace(/_/g,' ')}</span>
      </div>`).join('')}
    </div>`:''}

    ${d.flows.length?`<div class="detail-section">
      <h4>Execution Flows <span class="count">${d.flows.length}</span></h4>
      ${d.flows.map(f=>`<div class="flow-item"><div class="flow-dot"></div><div><span style="color:var(--pink);font-weight:500">${f.name}</span> <span style="color:var(--text3);font-size:10px">${f.step_count} steps</span></div></div>`).join('')}
    </div>`:''}

    ${d.coupling.length?`<div class="detail-section">
      <h4>Git Coupling <span class="count">${d.coupling.length}</span></h4>
      ${d.coupling.slice(0,8).map(c=>{
        const pct=Math.round(c.strength*100);
        const cls=pct>=70?'coupling-high':'coupling-med';
        return `<div class="coupling-item">
          <span class="coupling-strength ${cls}">${pct}%</span>
          <div class="coupling-files">${c.file_a.split('/').pop()}<br/>${c.file_b.split('/').pop()}</div>
        </div>`;
      }).join('')}
    </div>`:''}

    <div class="detail-section">
      <h4>Methods <span class="count">${d.method_count}</span></h4>
      <div class="method-list">
        ${d.methods.slice(0,50).map(m=>{
          const sig=m.signature||(m.class_name?`${m.class_name}.${m.name}`:`${m.name}`);
          return `<div class="method-item">
            <div class="method-sig">${htmlEsc(sig)}</div>
            <div class="method-file">${m.file} ${m.line?`:${m.line}`:''}</div>
          </div>`;
        }).join('')}
        ${d.method_count>50?`<div style="padding:6px 0;color:var(--text3);font-size:11px;font-style:italic">...and ${d.method_count-50} more</div>`:''}
        ${!d.methods.length?'<div style="color:var(--text3);font-size:11px;font-style:italic">No methods indexed. Run: corbell graph build --methods</div>':''}
      </div>
    </div>
  `;
}

function showSimpleDetail(id, type) {
  const node = graphData.nodes.find(n=>n.id===id);
  if(!node) return;
  const empty=document.getElementById('detail-empty');
  const content=document.getElementById('detail-content');
  empty.style.display='none';
  content.style.display='flex';
  const colorMap={datastore:'var(--amber)',queue:'var(--purple)',flow:'var(--pink)'};
  const col=colorMap[type]||'var(--text2)';
  content.innerHTML=`
    <div id="detail-header">
      <div class="dh-name" style="color:${col}">${node.label||node.id}</div>
      <div class="dh-badges"><span class="badge" style="color:${col};border-color:${col}">${type}${node.kind?' · '+node.kind:''}</span></div>
    </div>
    <div class="detail-section">
      <div style="color:var(--text2);font-size:12px;line-height:1.6">ID: <code style="color:var(--teal)">${node.id}</code></div>
      ${node.step_count?`<div style="color:var(--text2);font-size:12px;margin-top:6px">${node.step_count} steps in this flow</div>`:''}</div>
  `;
}

function htmlEsc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Constraints bar ────────────────────────────────────────────────────────
function buildConstraintsBar(items) {
  const pills=document.getElementById('constraints-pills');
  if(!items.length) {
    pills.innerHTML='<span class="no-constraints">None configured — add constraints to a spec file</span>';
    return;
  }
  items.forEach((c,i)=>{
    const pill=document.createElement('div');
    pill.className='constraint-pill';
    const short=c.text.length>55?c.text.slice(0,55)+'…':c.text;
    pill.textContent=short;
    pill.onclick=()=>showAllConstraints();
    pills.appendChild(pill);
  });
  // Build overlay entries
  const entries=document.getElementById('constraint-entries');
  entries.innerHTML=items.map(c=>`<div class="constraint-entry">
    <div class="ce-text">${htmlEsc(c.text)}</div>
    <div class="ce-source">from ${c.source} · ${c.origin}</div>
  </div>`).join('');
}

function showAllConstraints() {
  document.getElementById('constraint-overlay').classList.add('show');
}
function closeConstraints() {
  document.getElementById('constraint-overlay').classList.remove('show');
}
document.getElementById('constraint-overlay').addEventListener('click',e=>{ if(e.target===document.getElementById('constraint-overlay')) closeConstraints(); });

// ── Start ──────────────────────────────────────────────────────────────────
boot().catch(e=>{
  document.getElementById('loading').innerHTML=`<div style="color:var(--red);text-align:center;padding:40px">
    <div style="font-size:36px;margin-bottom:12px">⚠</div>
    <div style="font-size:14px;font-weight:600;margin-bottom:8px">Could not load graph</div>
    <div style="font-size:12px;color:var(--text2)">${e.message}</div>
    <div style="font-size:11px;color:var(--text3);margin-top:8px">Run: corbell graph build</div>
  </div>`;
});
</script>
</body>
</html>"""
