"""The participant-facing ESM app (PRD Module B): consent, the 5-second prompt,
and idle-gap attribution. Served as one mobile-friendly page by the API at
/esm-app?token=...  All calls use the participant's bearer token.
"""

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Activity Check-in</title>
<style>
:root{--navy:#1E2761;--blue:#2E5EAA;--ice:#CADCFC;--light:#EAF1FB;--green:#2E7D5B;}
*{box-sizing:border-box;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
body{margin:0;background:#F4F8FE;color:#1A2238}
.wrap{max-width:480px;margin:0 auto;padding:18px}
h1{color:var(--navy);font-size:22px;margin:8px 0}
.card{background:#fff;border:1px solid var(--ice);border-radius:14px;padding:18px;margin:14px 0;box-shadow:0 2px 10px rgba(30,39,97,.06)}
label{font-weight:600;color:var(--navy);display:block;margin:10px 0 6px}
select,button{font-size:16px;border-radius:10px}
select{width:100%;padding:12px;border:1px solid var(--ice)}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.chip{padding:9px 14px;border:1px solid var(--ice);border-radius:999px;background:#fff;cursor:pointer;user-select:none}
.chip.on{background:var(--navy);color:#fff;border-color:var(--navy)}
.btn{width:100%;padding:14px;background:var(--navy);color:#fff;border:none;margin-top:16px;cursor:pointer;font-weight:600}
.btn.green{background:var(--green)}
.gap{border:1px solid var(--ice);border-radius:10px;padding:12px;margin:10px 0}
.gapbtns{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.gapbtns button{flex:1;min-width:80px;padding:10px;background:var(--light);color:var(--navy);border:1px solid var(--ice);cursor:pointer}
.muted{color:#667085;font-size:13px}
.ok{color:var(--green);font-weight:600}
.hide{display:none}
</style></head>
<body><div class="wrap">
<h1>Activity Check-in</h1>
<div id="status" class="muted">Loading…</div>

<div id="consent" class="card hide">
  <label>Before we start</label>
  <p class="muted">This study measures activity at <b>role level only</b>. Your individual data is
  never used for performance review or discipline, only app/meeting metadata is collected (no
  keystrokes, no screen content), and raw data is deleted after the study. You can withdraw anytime.</p>
  <button class="btn green" onclick="giveConsent()">I understand and consent</button>
</div>

<div id="gaps" class="card hide">
  <label>You were away — what was that?</label>
  <div id="gaplist"></div>
</div>

<div id="esm" class="card hide">
  <label>What are you working on right now?</label>
  <select id="activity"></select>
  <label>Is this…</label>
  <div class="chips">
    <div class="chip" data-k="rework">Redoing / fixing</div>
    <div class="chip" data-k="waiting">Waiting on someone</div>
    <div class="chip" data-k="new">A new request</div>
  </div>
  <button class="btn" onclick="submitEsm()">Submit (5 sec)</button>
  <div id="done" class="ok hide">Thanks — logged.</div>
</div>
</div>

<script>
const params=new URLSearchParams(location.search);
const token=params.get("token");
const H={"Authorization":"Bearer "+token,"Content-Type":"application/json"};
const flags={rework:false,waiting:false,new:false};
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{const k=c.dataset.k;flags[k]=!flags[k];c.classList.toggle("on");});

async function init(){
  if(!token){document.getElementById("status").textContent="Missing access link.";return;}
  try{
    const me=await (await fetch("/me",{headers:H})).json();
    document.getElementById("status").textContent="Signed in as "+me.pseudonym;
    if(me.consent_status!=="given"){show("consent");return;}
    await loadCandidates(); await loadGaps(); show("esm");
  }catch(e){document.getElementById("status").textContent="Could not load. Check your link.";}
}
function show(id){document.getElementById(id).classList.remove("hide");}
async function giveConsent(){
  await fetch("/consent",{method:"POST",headers:H,body:JSON.stringify({given:true})});
  document.getElementById("consent").classList.add("hide");
  await loadCandidates(); await loadGaps(); show("esm");
}
async function loadCandidates(){
  const acts=await (await fetch("/esm/candidates",{headers:H})).json();
  const sel=document.getElementById("activity");
  sel.innerHTML=acts.map(a=>`<option value="${a.id}">${a.name}</option>`).join("");
}
async function loadGaps(){
  const gaps=await (await fetch("/esm/pending-gaps",{headers:H})).json();
  if(!gaps.length)return;
  const opts=["meeting","briefing","break","phone_call","other"];
  document.getElementById("gaplist").innerHTML=gaps.slice(0,5).map(g=>`
    <div class="gap" id="gap-${g.event_id}">
      <div>${g.start.slice(11,16)}–${g.end.slice(11,16)} (${g.minutes} min)</div>
      <div class="gapbtns">${opts.map(o=>`<button onclick="attr(${g.event_id},'${o}')">${o.replace('_',' ')}</button>`).join("")}</div>
    </div>`).join("");
  show("gaps");
}
async function attr(id,choice){
  await fetch("/esm/attribute",{method:"POST",headers:H,body:JSON.stringify({event_id:id,choice})});
  document.getElementById("gap-"+id).remove();
  if(!document.getElementById("gaplist").children.length)document.getElementById("gaps").classList.add("hide");
}
async function submitEsm(){
  const activity_id=document.getElementById("activity").value;
  await fetch("/esm",{method:"POST",headers:H,body:JSON.stringify({
    activity_id,is_rework:flags.rework,is_waiting:flags.waiting,is_new_request:flags.new})});
  const d=document.getElementById("done");d.classList.remove("hide");setTimeout(()=>d.classList.add("hide"),2500);
  Object.keys(flags).forEach(k=>flags[k]=false);
  document.querySelectorAll(".chip").forEach(c=>c.classList.remove("on"));
}
init();
</script>
</body></html>"""
