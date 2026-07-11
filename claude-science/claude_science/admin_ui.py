"""Single-page admin UI served by admin.py (kept separate for readability)."""

ADMIN_HTML = r"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Science — Admin Console</title>
<style>
  :root{--bg:#f4f7f7;--panel:#fff;--panel2:#eef3f2;--ink:#0f1e20;--soft:#46595b;
    --faint:#7d9092;--line:#dbe6e4;--accent:#0f9c8e;--accent2:#0b7a6f;--good:#2f8a4e;
    --warn:#b7822a;--crit:#bd4436;--mono:ui-monospace,Menlo,Consolas,monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;}
  @media(prefers-color-scheme:dark){:root{--bg:#0c1415;--panel:#121e1f;--panel2:#182726;
    --ink:#e4efed;--soft:#a5b8b8;--faint:#6f8384;--line:#24393a;--accent:#2bc4b2;
    --accent2:#1a9488;--good:#4fb06b;--warn:#d29a3f;--crit:#e0685a;}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5}
  .wrap{max-width:1080px;margin:0 auto;padding:26px 22px 60px}
  header{display:flex;align-items:center;gap:13px;border-bottom:1px solid var(--line);
    padding-bottom:16px;margin-bottom:22px}
  .mark{width:34px;height:34px;border-radius:9px;flex:none;
    background:radial-gradient(120% 120% at 30% 20%,var(--accent),#0a5f57)}
  h1{font-size:18px;margin:0;font-weight:650}
  .sub{color:var(--faint);font-size:12px}
  .tabs{display:flex;gap:6px;margin-bottom:20px;flex-wrap:wrap}
  .tab{font-family:var(--mono);font-size:12px;padding:8px 14px;border-radius:8px;
    border:1px solid var(--line);background:var(--panel);color:var(--soft);cursor:pointer}
  .tab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    padding:20px;box-shadow:0 1px 2px rgba(15,30,32,.05),0 8px 22px rgba(15,30,32,.05);margin-bottom:16px}
  .panel h2{font-size:14px;margin:0 0 3px}
  .panel .d{color:var(--faint);font-size:12px;margin:0 0 16px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
  label{font-family:var(--mono);font-size:10px;letter-spacing:.09em;text-transform:uppercase;
    color:var(--faint);display:block;margin-bottom:5px}
  input,select{width:100%;font-family:var(--sans);font-size:13px;color:var(--ink);
    background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
  button.go{margin-top:14px;font-family:var(--mono);font-size:12px;font-weight:600;
    background:var(--accent);color:#fff;border:none;border-radius:8px;padding:10px 18px;cursor:pointer}
  button.go:hover{background:var(--accent2)}
  .out{margin-top:16px;background:#0f1e20;color:#d7efec;border-radius:9px;padding:14px;
    font-family:var(--mono);font-size:11.5px;white-space:pre-wrap;overflow-x:auto;max-height:440px;overflow-y:auto}
  .hidden{display:none}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line)}
  th{font-family:var(--mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint)}
  td.num{font-family:var(--mono);text-align:right;font-variant-numeric:tabular-nums}
  .pill{font-family:var(--mono);font-size:10px;padding:2px 8px;border-radius:999px}
  .pass{background:rgba(47,138,78,.15);color:var(--good)} .fail{background:rgba(189,68,54,.15);color:var(--crit)}
  .run{background:rgba(183,130,42,.15);color:var(--warn)}
  .note{font-size:11.5px;color:var(--faint);margin-top:10px}
  code{font-family:var(--mono)}
</style></head><body>
<div class="wrap">
  <header><div class="mark"></div>
    <div><h1>Claude Science — Admin Console</h1>
    <div class="sub">Launch benchmarks · rank models · build RL datasets · audit scoring — all live</div></div>
  </header>

  <div class="tabs">
    <div class="tab active" data-t="bench">Benchmark</div>
    <div class="tab" data-t="leaderboard">Leaderboard</div>
    <div class="tab" data-t="dataset">RL dataset</div>
    <div class="tab" data-t="inspect">Task inspector</div>
    <div class="tab" data-t="runs">Runs &amp; transcripts</div>
    <div class="tab" data-t="jobs">Jobs</div>
  </div>

  <section id="bench" class="panel">
    <h2>Run a benchmark</h2><p class="d">Score one agent on the environment suite.</p>
    <div class="grid">
      <div><label>Agent</label><select id="b_agent"></select></div>
      <div><label>Environments</label><input id="b_envs" placeholder="all (blank) or admet,ic50"></div>
      <div><label>Seeds</label><input id="b_seeds" value="0"></div>
      <div><label>Difficulty</label><select id="b_diff"><option>low</option><option>medium</option><option>high</option></select></div>
    </div>
    <button class="go" onclick="runBench()">▶ Run benchmark</button>
    <div class="out hidden" id="b_out"></div>
    <div class="note">Model agents need <code>OPENROUTER_API_KEY</code>/<code>ANTHROPIC_API_KEY</code> in the server env.</div>
  </section>

  <section id="leaderboard" class="panel hidden">
    <h2>Model leaderboard</h2><p class="d">Rank several agents/models head-to-head.</p>
    <div class="grid">
      <div style="grid-column:1/-1"><label>Agents (comma-separated specs)</label>
        <input id="l_agents" value="heuristic,random,openrouter:tencent/hy3:free"></div>
      <div><label>Environments</label><input id="l_envs" placeholder="all or variant,ic50"></div>
      <div><label>Seeds</label><input id="l_seeds" value="0"></div>
      <div><label>Difficulty</label><select id="l_diff"><option>low</option><option>medium</option><option>high</option></select></div>
    </div>
    <button class="go" onclick="runLeaderboard()">▶ Run leaderboard</button>
    <div class="out hidden" id="l_out"></div>
  </section>

  <section id="dataset" class="panel hidden">
    <h2>Build a verifiable-task dataset</h2><p class="d">Generate self-grading tasks and RL export files for a training session.</p>
    <div class="grid">
      <div><label>Static tasks</label><input id="d_n" value="120"></div>
      <div><label>Seed</label><input id="d_seed" value="0"></div>
      <div><label>Rollouts (SFT+DPO)</label><select id="d_roll"><option value="true">yes</option><option value="false">no</option></select></div>
    </div>
    <button class="go" onclick="runDataset()">▶ Build dataset</button>
    <div class="out hidden" id="d_out"></div>
  </section>

  <section id="inspect" class="panel hidden">
    <h2>Task inspector — audit the scoring</h2>
    <p class="d">Sample tasks with their gold answers and confirm each gold scores as passing.</p>
    <button class="go" onclick="loadSample()">↻ Sample 12 tasks</button>
    <div id="i_out" style="margin-top:16px;overflow-x:auto"></div>
  </section>

  <section id="runs" class="panel hidden">
    <h2>Runs &amp; transcripts</h2>
    <p class="d">Saved runs persist under <code>runs/</code> across restarts. Open a
      leaderboard run to inspect <em>how</em> each model reasoned — the tools it
      called and where it went wrong — not just its score.</p>
    <button class="go" onclick="loadRuns()">↻ Refresh runs</button>
    <div id="r_list" style="margin-top:16px;overflow-x:auto"></div>
    <div id="r_detail" style="margin-top:20px"></div>
    <div id="r_trace" style="margin-top:16px"></div>
  </section>

  <section id="jobs" class="panel hidden">
    <h2>Jobs</h2><p class="d">All runs this session.</p>
    <button class="go" onclick="loadJobs()">↻ Refresh</button>
    <div id="j_out" style="margin-top:16px;overflow-x:auto"></div>
  </section>
</div>
<script>
const $=s=>document.querySelector(s);
document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));
  t.classList.add("active");
  ["bench","leaderboard","dataset","inspect","runs","jobs"].forEach(id=>$("#"+id).classList.add("hidden"));
  $("#"+t.dataset.t).classList.remove("hidden");
  if(t.dataset.t==="runs") loadRuns();
});
async function jget(u){return (await fetch(u)).json();}
async function jpost(u,b){return (await fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)})).json();}
function ints(s){return s.split(",").map(x=>x.trim()).filter(Boolean).map(Number);}
function csv(s){return s.split(",").map(x=>x.trim()).filter(Boolean);}

(async()=>{const a=await jget("/api/agents");$("#b_agent").innerHTML=a.map(x=>`<option>${x}</option>`).join("");})();

async function poll(jid,el){
  el.classList.remove("hidden");el.textContent="running…";
  for(let i=0;i<600;i++){
    const j=await jget("/api/job/"+jid);
    if(j.status==="running"){el.textContent="running… ("+i+"s)";await new Promise(r=>setTimeout(r,1000));continue;}
    el.textContent=j.error?("ERROR\n"+j.error):(j.result.scorecard||j.result.table||JSON.stringify(j.result,null,2));
    return;
  }
}
async function runBench(){const r=await jpost("/api/bench",{agent:$("#b_agent").value,
  envs:csv($("#b_envs").value),seeds:ints($("#b_seeds").value),difficulty:$("#b_diff").value});
  poll(r.job_id,$("#b_out"));}
async function runLeaderboard(){const r=await jpost("/api/leaderboard",{agents:csv($("#l_agents").value),
  envs:csv($("#l_envs").value),seeds:ints($("#l_seeds").value),difficulty:$("#l_diff").value});
  poll(r.job_id,$("#l_out"));}
async function runDataset(){const r=await jpost("/api/dataset",{n_static:Number($("#d_n").value),
  seed:Number($("#d_seed").value),rollouts:$("#d_roll").value==="true"});poll(r.job_id,$("#d_out"));}
async function loadSample(){const s=await jget("/api/dataset/sample?n=12");
  $("#i_out").innerHTML="<table><tr><th>task</th><th>domain</th><th>judge</th><th>gold</th><th>gold verifies</th></tr>"+
   s.map(t=>`<tr><td><code>${t.task_id}</code></td><td>${t.domain}</td><td>${t.judge}</td>
     <td><code>${String(t.gold).slice(0,26)}</code></td>
     <td><span class="pill ${t.gold_scores_pass?'pass':'fail'}">${t.gold_scores_pass?'PASS '+t.reward:'FAIL'}</span></td></tr>`).join("")+"</table>";}
const ESC=s=>String(s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
async function loadRuns(){const r=await jget("/api/runs");
  $("#r_detail").innerHTML="";$("#r_trace").innerHTML="";
  if(!r.length){$("#r_list").innerHTML="<p class='d'>No saved runs yet. Run a leaderboard first.</p>";return;}
  $("#r_list").innerHTML="<table><tr><th>id</th><th>kind</th><th>status</th><th>summary</th><th></th></tr>"+
    r.map(x=>`<tr><td><code>${x.id}</code></td><td>${x.kind}</td>
      <td><span class="pill ${x.status==='done'?'pass':x.status==='error'?'fail':'run'}">${x.status}</span></td>
      <td>${ESC(x.summary||'')}</td>
      <td><button class="go" style="padding:4px 10px" onclick="openRun('${x.id}')">open</button></td></tr>`).join("")+"</table>";}
async function openRun(id){const d=await jget("/api/run/"+id);const res=d.result||{};
  $("#r_trace").innerHTML="";
  if(!res.ranking){$("#r_detail").innerHTML="<pre class='out'>"+ESC(JSON.stringify(res,null,2).slice(0,2000))+"</pre>";return;}
  const caps=[...new Set(res.ranking.flatMap(r=>Object.keys(r.by_capability||{})))];
  let h="<h3 style='font-size:13px;margin:0 0 10px'>Leaderboard "+ESC(id)+"</h3>";
  h+="<table><tr><th>#</th><th>agent / model</th><th>overall</th>"+caps.map(c=>`<th class="num">${c.slice(0,5)}</th>`).join("")+"</tr>";
  res.ranking.forEach((r,i)=>{h+=`<tr><td>${i+1}</td><td><code>${ESC(r.spec)}</code></td>
    <td class="num"><b>${r.overall.toFixed(3)}</b></td>`+
    caps.map(c=>`<td class="num">${(r.by_capability[c]??0).toFixed(2)}</td>`).join("")+"</tr>";});
  h+="</table>";
  if(res.errors&&Object.keys(res.errors).length)
    h+="<p class='d' style='margin-top:10px'>skipped: "+Object.entries(res.errors).map(([s,e])=>ESC(s)).join(", ")+"</p>";
  const tr=res.transcripts||{};
  if(Object.keys(tr).length){
    h+="<h3 style='font-size:13px;margin:18px 0 8px'>Inspect an episode</h3><div style='display:flex;gap:8px;flex-wrap:wrap'>";
    for(const spec of Object.keys(tr))for(const ep of tr[spec])
      h+=`<button class="tab" onclick='showTrace(${JSON.stringify(spec)},${JSON.stringify(ep.task_id)},"${id}")'>
        ${ESC(spec.replace('openrouter:',''))} · ${ESC(ep.env)}
        <span class="pill ${ep.score>=0.8?'pass':ep.score>0?'run':'fail'}">${ep.score.toFixed(2)}</span></button>`;
    h+="</div>";
  }
  $("#r_detail").innerHTML=h;window._run=d;}
function showTrace(spec,task,id){const d=window._run;const ep=(d.result.transcripts[spec]||[]).find(e=>e.task_id===task);
  if(!ep)return;
  const kindColor={message:"var(--soft)",tool_call:"var(--accent)",observation:"var(--faint)",final:"var(--ink)"};
  let h=`<div class="out"><b>${ESC(spec)}</b> on <b>${ESC(ep.env)}</b> — score ${ep.score.toFixed(2)}, ${ep.n_tool_calls} tool calls\n\n`;
  ep.steps.forEach((s,i)=>{const c=typeof s.content==="object"?JSON.stringify(s.content):String(s.content);
    h+=`<span style="color:${kindColor[s.kind]||'var(--soft)'}">${String(i).padStart(2,'0')} ${s.kind.padEnd(11)}</span> ${ESC(c.slice(0,600))}\n`;});
  h+="</div>";$("#r_trace").innerHTML=h;$("#r_trace").scrollIntoView({behavior:"smooth"});}
async function loadJobs(){const j=await jget("/api/jobs");
  $("#j_out").innerHTML="<table><tr><th>id</th><th>kind</th><th>status</th><th>started</th></tr>"+
   j.map(x=>`<tr><td><code>${x.id}</code></td><td>${x.kind}</td>
     <td><span class="pill ${x.status==='done'?'pass':x.status==='error'?'fail':'run'}">${x.status}</span></td>
     <td>${new Date(x.started*1000).toLocaleTimeString()}</td></tr>`).join("")+"</table>";}
</script></body></html>"""
