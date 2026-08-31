"""The Workbench IDE (Pillar 4): a Cursor/Claude-Code-style single-page app.

Served by ``admin.py`` at ``/``. A human scientist and the agents share one
surface: a real WebGL 3D molecular viewer (vendored 3Dmol.js), a de novo design
studio, a CRISPR studio, a perception panel, type-specialized RAG, and the
evaluation harness (benchmarks / leaderboards / runs). All panels call the live
backend endpoints; no external assets.
"""

ADMIN_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Science — Research Workbench</title>
<script src="/vendor/3Dmol-min.js"></script>
<style>
:root{--bg:#0d1417;--chrome:#111b1f;--panel:#0f181b;--panel2:#152227;--ink:#dce8e7;
 --soft:#8ca3a4;--faint:#5c7274;--line:#213137;--accent:#2bc4b2;--accent2:#12a594;
 --good:#4fb06b;--warn:#d29a3f;--crit:#e0685a;
 --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
:root[data-theme=light]{--bg:#eef3f2;--chrome:#e3ecea;--panel:#fff;--panel2:#f1f6f5;
 --ink:#0f1e20;--soft:#4a5d5e;--faint:#7d9092;--line:#d6e2e0;--accent:#0f9c8e;--accent2:#0b7a6f}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:13px;overflow:hidden;-webkit-font-smoothing:antialiased}
.app{display:grid;grid-template-columns:230px 1fr 300px;grid-template-rows:46px 1fr;height:100vh}
header{grid-column:1/-1;display:flex;align-items:center;gap:12px;padding:0 14px;background:var(--chrome);border-bottom:1px solid var(--line)}
.logo{width:24px;height:24px;border-radius:6px;background:radial-gradient(120% 120% at 30% 20%,var(--accent),#0a5f57);position:relative}
.logo::after{content:"";position:absolute;inset:0;border-radius:6px;background:linear-gradient(transparent 46%,rgba(255,255,255,.5) 46%,rgba(255,255,255,.5) 54%,transparent 54%)}
header h1{font-size:13px;margin:0;font-weight:600}header .sub{color:var(--faint);font-family:var(--mono);font-size:11px}
header .sp{flex:1}.tbtn{font-family:var(--mono);font-size:11px;color:var(--soft);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:5px 10px;cursor:pointer}
.tbtn:hover{color:var(--accent);border-color:var(--accent)}
.explorer{background:var(--panel);border-right:1px solid var(--line);overflow-y:auto;padding:10px 8px}
.exh{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);padding:8px 8px 6px}
.leaf{display:flex;align-items:center;gap:7px;padding:5px 8px;border-radius:6px;cursor:pointer;color:var(--soft);font-size:12px}
.leaf:hover{background:var(--panel2);color:var(--ink)}.leaf.sel{background:var(--accent);color:#04201d}
.dot{width:6px;height:6px;border-radius:50%;background:var(--accent2);flex:none}
.center{display:flex;flex-direction:column;min-width:0}
.tabs{display:flex;background:var(--chrome);border-bottom:1px solid var(--line);overflow-x:auto}
.tab{padding:9px 14px;font-size:12px;color:var(--soft);cursor:pointer;white-space:nowrap;border-right:1px solid var(--line)}
.tab.active{color:var(--ink);background:var(--bg);box-shadow:inset 0 -2px 0 var(--accent)}
.content{flex:1;overflow-y:auto;padding:16px 18px;min-height:0}
.pane{display:none}.pane.show{display:block}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
input,select,textarea{font-family:var(--sans);font-size:13px;color:var(--ink);background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
input:focus,textarea:focus{outline:2px solid var(--accent);outline-offset:1px}
.grow{flex:1;min-width:120px}
.go{font-family:var(--sans);font-size:12.5px;background:var(--accent);color:#04201d;border:none;border-radius:8px;padding:8px 14px;cursor:pointer;font-weight:600}
.go:hover{background:var(--accent2)}
#viewer3d{width:100%;height:340px;position:relative;background:var(--panel);border:1px solid var(--line);border-radius:10px}
.molgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}
.mol{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden;cursor:pointer}
.mol:hover{border-color:var(--accent)}.mol .d{display:grid;place-items:center;padding:6px;background:repeating-linear-gradient(45deg,transparent,transparent 10px,rgba(127,127,127,.03) 10px,rgba(127,127,127,.03) 20px)}
:root:not([data-theme=light]) .mol .d svg,:root:not([data-theme=light]) #svg2d svg{filter:invert(.92) hue-rotate(180deg)}
.mol .m{padding:8px 10px;border-top:1px solid var(--line);font-size:11px;color:var(--soft)}
.mol .m b{color:var(--ink);font-family:var(--mono)}
table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--faint);font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.08em}
td.num{font-family:var(--mono);text-align:right;font-variant-numeric:tabular-nums}
.card{font-family:var(--mono);font-size:11.5px;white-space:pre-wrap;line-height:1.6;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:12px 14px;color:var(--soft)}
.inspector{background:var(--panel);border-left:1px solid var(--line);overflow-y:auto;padding:14px}
.ih{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);margin:2px 0 8px}
.chip{font-family:var(--mono);font-size:10px;padding:2px 7px;border-radius:5px;background:var(--panel2);color:var(--soft);display:inline-block;margin:2px}
.chip b{color:var(--ink)}#svg2d{display:grid;place-items:center;padding:8px;background:var(--panel2);border:1px solid var(--line);border-radius:8px;min-height:120px}
.out{font-family:var(--mono);font-size:11px;white-space:pre-wrap;color:var(--soft);background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:10px 12px;max-height:220px;overflow:auto}
.pill{font-family:var(--mono);font-size:10px;padding:1px 7px;border-radius:999px}
.pill.ok{background:rgba(79,176,107,.15);color:var(--good)}.pill.no{background:rgba(224,104,90,.15);color:var(--crit)}
.muted{color:var(--faint);font-size:11.5px}
@media(max-width:1000px){.app{grid-template-columns:1fr}.explorer,.inspector{display:none}}
</style></head><body>
<div class="app">
 <header>
   <div class="logo"></div><h1>Claude Science</h1>
   <span class="sub">research workbench</span><span class="sp"></span>
   <span class="sub" id="stat">·</span>
   <button class="tbtn" id="theme">◐</button>
 </header>

 <aside class="explorer">
   <div class="exh">Compounds</div><div id="molmenu"></div>
   <div class="exh">Sequences</div><div id="seqmenu"></div>
   <div class="exh">Targets</div>
   <div class="leaf" onclick="setTarget('CHEMBL203')"><span class="dot"></span>EGFR · CHEMBL203</div>
 </aside>

 <main class="center">
   <div class="tabs">
     <div class="tab active" data-p="structure">◇ Structure</div>
     <div class="tab" data-p="design">⬡ Design studio</div>
     <div class="tab" data-p="crispr">✁ CRISPR</div>
     <div class="tab" data-p="perceive">◎ Perceive</div>
     <div class="tab" data-p="evaluate">▤ Evaluate</div>
   </div>
   <div class="content">
     <div class="pane show" id="structure">
       <div class="row"><input class="grow" id="smi" value="CC(=O)Oc1ccccc1C(=O)O" placeholder="SMILES">
         <button class="go" onclick="loadMol()">Render 3D + 2D</button></div>
       <div id="viewer3d"></div>
       <div class="row" style="margin-top:12px"><div id="svg2d" class="grow"></div></div>
     </div>

     <div class="pane" id="design">
       <div class="row"><input class="grow" id="dq" value="COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1" placeholder="query SMILES">
         <input id="dgen" type="number" value="4" style="width:70px" title="generations">
         <button class="go" onclick="runDesign()">Design candidates</button></div>
       <p class="muted">Graph-GA proposes drug-like molecules toward the query. Click a candidate to load it in the 3D viewer.</p>
       <div class="molgrid" id="dgrid"></div>
     </div>

     <div class="pane" id="crispr">
       <div class="row"><input class="grow" id="dna" value="GGGACCTAGTCATTGGAGGTGACCCGGGATCGGACTGACGTGGTACCGATGCTAGCTAGGACCTAGTCATTGGAGG" placeholder="target DNA locus">
         <button class="go" onclick="runCrispr()">Find guides</button></div>
       <div id="guidetbl"></div>
     </div>

     <div class="pane" id="perceive">
       <div class="row"><input class="grow" id="pq" value="COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1" placeholder="SMILES or sequence">
         <button class="go" onclick="runPerceive()">Perceive</button></div>
       <p class="muted">A multi-level view the agent reasons over — structure, not tokens.</p>
       <div id="pcard" class="card">—</div>
     </div>

     <div class="pane" id="evaluate">
       <div class="row"><label class="muted">Agents</label>
         <input class="grow" id="lagents" value="heuristic,verified:4:openrouter:tencent/hy3:free,random">
         <input id="lenvs" value="variant,ic50,design" placeholder="envs" class="grow">
         <button class="go" onclick="runLeaderboard()">Run leaderboard</button></div>
       <div id="lb_out" class="out">Compare agents (incl. training-free verified best-of-N) across environments.</div>
     </div>
   </div>
 </main>

 <aside class="inspector">
   <div class="ih">Inspector</div>
   <div id="insp" class="muted">Render a molecule to see its profile.</div>
 </aside>
</div>
<script>
const $=s=>document.querySelector(s);
let VIEW=null;
$("#theme").onclick=()=>{const r=document.documentElement;r.setAttribute("data-theme",(r.getAttribute("data-theme")||"dark")==="dark"?"light":"dark");};
document.documentElement.setAttribute("data-theme","dark");
document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));t.classList.add("active");
  document.querySelectorAll(".pane").forEach(p=>p.classList.toggle("show",p.id===t.dataset.p));
  if(t.dataset.p==="structure"&&VIEW)VIEW.resize();});
async function jget(u){return(await fetch(u)).json();}
async function jpost(u,b){return(await fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)})).json();}

const SAMPLES=[["Aspirin","CC(=O)Oc1ccccc1C(=O)O"],["Gefitinib","COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1"],
 ["Imatinib","Cc1ccc(cc1Nc1nccc(n1)-c1cccnc1)NC(=O)c1ccc(CN2CCN(C)CC2)cc1"],["Caffeine","Cn1cnc2c1c(=O)n(C)c(=O)n2C"],["Ibuprofen","CC(C)Cc1ccc(cc1)C(C)C(=O)O"]];
$("#molmenu").innerHTML=SAMPLES.map(([n,s])=>`<div class="leaf" onclick='pickMol(${JSON.stringify(s)})'><span class="dot"></span>${n}</div>`).join("");
$("#seqmenu").innerHTML=[["EGFR peptide","MAEDPEVLKRIGDFGLATEKSRWSGSHQFEQLSGSILW"]].map(([n,s])=>`<div class="leaf" onclick='pickSeq(${JSON.stringify(s)})'><span class="dot" style="background:var(--warn)"></span>${n}</div>`).join("");
function pickMol(s){$("#smi").value=s;document.querySelector('[data-p=structure]').click();loadMol();}
function pickSeq(s){$("#pq").value=s;document.querySelector('[data-p=perceive]').click();runPerceive();}
function setTarget(t){alert("Target "+t+": use the Design studio; the backend can train a Tanimoto-GP on this target's actives.");}

function init3d(){if(VIEW)return;VIEW=$3Dmol.createViewer($("#viewer3d"),{backgroundColor:"0x0f181b"});}
async function loadMol(){
  const smi=$("#smi").value.trim();init3d();
  try{
    const sdf=await(await fetch("/api/mol3d?smiles="+encodeURIComponent(smi))).text();
    VIEW.clear();VIEW.addModel(sdf,"sdf");VIEW.setStyle({},{stick:{radius:0.14},sphere:{scale:0.24}});VIEW.zoomTo();VIEW.render();
  }catch(e){}
  const svg=await(await fetch("/api/mol2d?smiles="+encodeURIComponent(smi))).text();$("#svg2d").innerHTML=svg;
  const d=await jget("/api/descriptors?smiles="+encodeURIComponent(smi));renderInspector(d);
}
function renderInspector(d){
  if(d.error){$("#insp").innerHTML="<span class='muted'>"+d.error+"</span>";return;}
  const alerts=(d.structural_alerts||[]);
  $("#insp").innerHTML=`<div><b>${d.canonical_smiles||''}</b></div>
   <div style="margin-top:8px">
   <span class="chip">MW <b>${d.mol_weight}</b></span><span class="chip">cLogP <b>${d.clogp}</b></span>
   <span class="chip">TPSA <b>${d.tpsa}</b></span><span class="chip">QED <b>${d.qed}</b></span>
   <span class="chip">SA <b>${d.sa_score}</b></span><span class="chip">HBD <b>${d.h_bond_donors}</b></span>
   <span class="chip">HBA <b>${d.h_bond_acceptors}</b></span></div>
   <div style="margin-top:10px">Lipinski <span class="pill ${d.lipinski_pass?'ok':'no'}">${d.lipinski_pass?'pass':'fail'}</span>
   Veber <span class="pill ${d.veber_pass?'ok':'no'}">${d.veber_pass?'pass':'fail'}</span></div>
   <div style="margin-top:8px" class="muted">alerts: ${alerts.length?alerts.join(", "):"none"}</div>`;
}
async function runDesign(){
  $("#dgrid").innerHTML="<span class='muted'>designing…</span>";
  const r=await jpost("/api/design",{query_smiles:$("#dq").value.trim(),generations:Number($("#dgen").value)});
  if(r.error){$("#dgrid").innerHTML="<span class='muted'>"+r.error+"</span>";return;}
  $("#dgrid").innerHTML=r.candidates.map(c=>`<div class="mol" onclick='pickMol(${JSON.stringify(c.smiles)})'>
    <div class="d">${c.svg}</div>
    <div class="m">score <b>${c.score.toFixed(2)}</b> · QED <b>${c.qed}</b><br>sim <b>${c.tanimoto_to_query}</b> · MW <b>${c.mol_weight}</b></div></div>`).join("");
}
async function runCrispr(){
  $("#guidetbl").innerHTML="<span class='muted'>scanning…</span>";
  const d=await jget("/api/crispr?dna="+encodeURIComponent($("#dna").value.trim()));
  if(d.error){$("#guidetbl").innerHTML="<span class='muted'>"+d.error+"</span>";return;}
  $("#guidetbl").innerHTML=`<p class="muted">${d.n_guides} candidate guides</p><table>
   <tr><th>protospacer</th><th>PAM</th><th>strand</th><th class="num">on-target</th></tr>`+
   d.top.map(g=>`<tr><td><code>${g.protospacer}</code></td><td>${g.pam}</td><td>${g.strand}</td><td class="num">${g.on_target}</td></tr>`).join("")+"</table>";
}
async function runPerceive(){
  $("#pcard").textContent="perceiving…";
  const d=await jget("/api/perceive?obj="+encodeURIComponent($("#pq").value.trim()));
  $("#pcard").textContent=d.error?d.error:d.card;
}
async function runLeaderboard(){
  $("#lb_out").textContent="running… (real-model agents may take a minute)";
  const r=await jpost("/api/leaderboard",{agents:$("#lagents").value.split(",").map(s=>s.trim()).filter(Boolean),
    envs:$("#lenvs").value.split(",").map(s=>s.trim()).filter(Boolean),seeds:[0],difficulty:"low"});
  for(let i=0;i<600;i++){const j=await jget("/api/job/"+r.job_id);
    if(j.status!=="running"){$("#lb_out").textContent=j.error||j.result.table;return;}
    $("#lb_out").textContent="running… ("+i+"s)";await new Promise(x=>setTimeout(x,1000));}
}
(async()=>{try{const e=await jget("/api/envs");$("#stat").textContent=e.length+" environments · 3D · design · CRISPR · perception · RAG";}catch(_){}})();
loadMol();
</script></body></html>"""
