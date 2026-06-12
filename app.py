import sys
import os
import threading
import json
import queue
import pandas as pd
from flask import Flask, request
from bot_state import stop_event

app = Flask(__name__)
app.config["SECRET_KEY"] = "jobbot2024"

bot_running = False
stats = {"applied": 0, "skipped": 0, "errors": 0, "platform": ""}
log_queue = queue.Queue()

class QueueLogger:
    def write(self, message):
        if message.strip():
            log_queue.put(message.strip())
    def flush(self):
        pass

def run_bot(platform):
    global bot_running, stats
    bot_running = True
    stop_event.clear()
    stats = {"applied": 0, "skipped": 0, "errors": 0, "platform": platform}
    old_stdout = sys.stdout
    sys.stdout = QueueLogger()
    try:
        sys.path.insert(0, os.path.expanduser("~/job-applier"))
        if platform == "linkedin":
            from linkedin import run_linkedin_bot
            count = run_linkedin_bot()
            stats["applied"] = count
        elif platform == "dice":
            from dice import run_dice_bot
            count = run_dice_bot()
            stats["applied"] = count
        elif platform == "both":
            from linkedin import run_linkedin_bot
            from dice import run_dice_bot
            c1 = 0
            try:
                c1 = run_linkedin_bot()
            except Exception as e:
                log_queue.put(f"⚠️ LinkedIn error: {e} — continuing with Dice")
            if not stop_event.is_set():
                try:
                    c2 = run_dice_bot()
                except Exception as e:
                    log_queue.put(f"⚠️ Dice error: {e}")
                    c2 = 0
            else:
                c2 = 0
            stats["applied"] = c1 + c2
    except Exception as e:
        log_queue.put(f"❌ Error: {e}")
    finally:
        sys.stdout = old_stdout
        bot_running = False
        log_queue.put(f"__DONE__{json.dumps(stats)}")

HTML = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Bot — Sree Nithin</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@400;500;600&display=swap');
:root {
  --bg:#080810; --surface:#0f0f1a; --surface2:#161625;
  --border:#1e1e35; --border2:#2a2a45; --text:#e2e2f0;
  --muted:#9090b0; --accent:#7c6bff; --accent2:#a78bfa;
  --green:#34d399; --orange:#fb923c; --red:#f87171; --blue:#60a5fa;
}
[data-theme="light"] {
  --bg:#dcdaf0; --surface:#ffffff; --surface2:#ededf8;
  --border:#b8b6d8; --border2:#9e9cc8; --text:#08081e; --muted:#3a3a60;
  --accent:#4a38e0; --accent2:#5b4de8;
  --green:#057a50; --orange:#b45309; --red:#b91c1c; --blue:#1d4ed8;
}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;}
header{
  background:rgba(15,15,26,0.9);backdrop-filter:blur(20px);
  border-bottom:1px solid var(--border);
  padding:0 32px;height:64px;
  display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;
}
[data-theme="light"] header{background:rgba(255,255,255,0.9);}
.logo{display:flex;align-items:center;gap:12px;}
.logo-mark{
  width:36px;height:36px;
  background:linear-gradient(135deg,#7c6bff,#a78bfa);
  border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;
}
.logo h1{font-family:'Space Mono',monospace;font-size:15px;font-weight:700;}
.logo p{font-size:11px;color:var(--muted);}
.hright{display:flex;align-items:center;gap:12px;}
.ai-pill{
  display:flex;align-items:center;gap:8px;
  background:var(--surface2);border:1px solid var(--border2);
  border-radius:24px;padding:6px 14px 6px 10px;
}
.ai-lbl{font-size:11px;color:var(--muted);}
.switch{position:relative;width:36px;height:20px;cursor:pointer;display:inline-block;}
.switch input{opacity:0;width:0;height:0;position:absolute;}
.slider{position:absolute;inset:0;background:var(--border2);border-radius:20px;transition:.25s;}
.slider:before{content:"";position:absolute;width:14px;height:14px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.25s;}
input:checked+.slider{background:#7c6bff;}
input:checked+.slider:before{transform:translateX(16px);}
.ai-txt{font-weight:600;font-size:12px;min-width:52px;}
.tbtn{
  width:36px;height:36px;background:var(--surface2);
  border:1px solid var(--border2);border-radius:10px;
  cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;
}
.main{padding:28px 32px;max-width:1440px;margin:0 auto;}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px;}
.stat{
  background:var(--surface);border:1px solid var(--border);
  border-radius:16px;padding:18px 20px;
  display:flex;align-items:center;gap:14px;
  position:relative;overflow:hidden;
}
.stat::before{content:"";position:absolute;top:0;left:0;right:0;height:2px;}
.sg::before{background:#34d399;} .so::before{background:#fb923c;}
.sr::before{background:#f87171;} .sb::before{background:#60a5fa;}
.sico{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:19px;}
.sg .sico{background:rgba(52,211,153,.12);} .so .sico{background:rgba(251,146,60,.12);}
.sr .sico{background:rgba(248,113,113,.12);} .sb .sico{background:rgba(96,165,250,.12);}
.sval{font-family:'Space Mono',monospace;font-size:26px;font-weight:700;line-height:1;}
.slbl{font-size:11px;color:var(--muted);margin-top:4px;}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;}
.card{background:var(--surface);border:1px solid var(--border);border-radius:16px;overflow:hidden;}
.chead{padding:14px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;}
.ctitle{font-size:13px;font-weight:600;}
.cbody{padding:18px 20px;}
.srow{display:flex;align-items:center;gap:8px;}
.sdot{width:8px;height:8px;border-radius:50%;background:var(--muted);}
.sdot.on{background:#34d399;animation:blink 1.2s infinite;}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.stxt{font-size:12px;color:var(--muted);font-family:'Space Mono',monospace;}
.bgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.btn{
  padding:13px 16px;border-radius:12px;border:none;cursor:pointer;
  font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif;
  display:flex;align-items:center;justify-content:center;gap:7px;
  transition:all .2s;
}
.btn:hover{transform:translateY(-1px);opacity:.9;}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none;}
.bli{background:#0a66c2;color:#fff;}
.bdi{background:#f97316;color:#fff;}
.bboth{background:linear-gradient(135deg,#7c6bff,#a78bfa);color:#fff;grid-column:1/-1;}
.bstop{background:#f87171;color:#fff;grid-column:1/-1;}
.logbox{
  background:#06060e;border-radius:10px;padding:14px;
  height:290px;overflow-y:auto;
  font-family:'Space Mono',monospace;font-size:11px;line-height:1.8;
}
[data-theme="light"] .logbox{background:#f0f0fc;border:1px solid var(--border);}
.ll{color:#5a5a7a;}
[data-theme="light"] .ll{color:#4a4a70;}
.ls{color:#34d399;} [data-theme="light"] .ls{color:#057a50;}
.le{color:#f87171;} [data-theme="light"] .le{color:#b91c1c;}
.lk{color:#4a4a6a;} [data-theme="light"] .lk{color:#6060a0;}
.la{color:#a78bfa;} [data-theme="light"] .la{color:#4a38e0;}
.li{color:#60a5fa;} [data-theme="light"] .li{color:#1d4ed8;}
.clr{background:none;border:none;color:var(--muted);cursor:pointer;font-size:11px;}
.rlist{display:flex;flex-direction:column;gap:8px;}
.rrow{
  display:flex;align-items:center;gap:12px;
  background:var(--surface2);border:1px solid var(--border);
  border-radius:10px;padding:11px 14px;
}
.rdot{width:7px;height:7px;border-radius:50%;}
.rrole{font-size:12px;font-weight:600;}
.rfile{font-size:10px;color:var(--muted);font-family:'Space Mono',monospace;}
.tscroll{overflow:auto;max-height:320px;}
table{width:100%;border-collapse:collapse;font-size:11px;}
th{
  padding:10px 14px;text-align:left;color:var(--muted);
  font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;
  border-bottom:1px solid var(--border);white-space:nowrap;
  position:sticky;top:0;background:var(--surface);
}
td{padding:10px 14px;border-bottom:1px solid var(--border);white-space:nowrap;max-width:180px;overflow:hidden;text-overflow:ellipsis;}
tr:last-child td{border-bottom:none;}
tr:hover td{background:var(--surface2);}
.pill{display:inline-block;padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;font-family:'Space Mono',monospace;}
.pa{background:rgba(52,211,153,.15);color:#34d399;}
.pi{background:rgba(96,165,250,.15);color:#60a5fa;}
.pr{background:rgba(248,113,113,.15);color:#f87171;}
[data-theme="light"] .pa{background:#d1fae5;color:#065f46;}
[data-theme="light"] .pi{background:#dbeafe;color:#1e3a8a;}
[data-theme="light"] .pr{background:#fee2e2;color:#991b1b;}
.tlink{color:#7c6bff;text-decoration:none;font-size:10px;}
[data-theme="light"] .tlink{color:#4a38e0;}
.empty{padding:32px;text-align:center;color:var(--muted);font-size:12px;}
.rbtn{background:none;border:none;color:#7c6bff;cursor:pointer;font-size:11px;font-weight:500;}
</style>
</head>
<body>
<header>
  <div class="logo">
    <div class="logo-mark">🤖</div>
    <div>
      <h1>JOB_BOT</h1>
      <p>Sree Nithin M · Salesforce Roles</p>
    </div>
  </div>
  <div class="hright">
    <div class="ai-pill">
      <span class="ai-lbl">AI MODE</span>
      <label class="switch">
        <input type="checkbox" id="aiTog" onchange="toggleAI(this)">
        <span class="slider"></span>
      </label>
      <span class="ai-txt" id="aiTxt">Free</span>
    </div>
    <button class="tbtn" onclick="toggleTheme()"><span id="tIco">☀️</span></button>
  </div>
</header>

<div class="main">
  <div class="stats">
    <div class="stat sg"><div class="sico">✅</div><div><div class="sval" id="sA">0</div><div class="slbl">Applied this run</div></div></div>
    <div class="stat so"><div class="sico">⏭️</div><div><div class="sval" id="sS">0</div><div class="slbl">Skipped</div></div></div>
    <div class="stat sr"><div class="sico">❌</div><div><div class="sval" id="sE">0</div><div class="slbl">Errors</div></div></div>
    <div class="stat sb"><div class="sico">📊</div><div><div class="sval" id="sT">0</div><div class="slbl">Total logged</div></div></div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="chead">
        <div class="ctitle">🎮 Bot Controls</div>
        <div class="srow"><div class="sdot" id="sdot"></div><span class="stxt" id="stxt">IDLE</span></div>
      </div>
      <div class="cbody">
        <div class="bgrid">
          <button class="btn bli" id="bLI" onclick="runBot('linkedin')">🔵 LinkedIn</button>
          <button class="btn bdi" id="bDI" onclick="runBot('dice')">🟠 Dice</button>
          <button class="btn bboth" id="bBoth" onclick="runBot('both')">🚀 Run Both Platforms</button>
          <button class="btn bstop" id="bStop" onclick="stopBot()" disabled>⏹ Stop Bot</button>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="chead"><div class="ctitle">📄 Resume Mapping</div></div>
      <div class="cbody">
        <div class="rlist">
          <div class="rrow"><div class="rdot" style="background:#60a5fa"></div><div><div class="rrole">Salesforce Developer</div><div class="rfile">Sree NithinSF Dev.pdf</div></div></div>
          <div class="rrow"><div class="rdot" style="background:#34d399"></div><div><div class="rrole">Salesforce Admin</div><div class="rfile">SreeNithin SF Admin.pdf</div></div></div>
          <div class="rrow"><div class="rdot" style="background:#fb923c"></div><div><div class="rrole">Salesforce Business Analyst</div><div class="rfile">Sree NithinSF Dev.pdf · AI transformed</div></div></div>
          <div class="rrow"><div class="rdot" style="background:#a78bfa"></div><div><div class="rrole">Agentforce Developer</div><div class="rfile">SreeNithin Dev AgentForce.pdf</div></div></div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="chead">
        <div class="ctitle">📟 Live Logs</div>
        <button class="clr" onclick="clearLogs()">clear</button>
      </div>
      <div class="cbody" style="padding:12px">
        <div class="logbox" id="logBox">
          <div class="ll li">// bot ready — press a button to start</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="chead">
        <div class="ctitle">📊 Recent Applications</div>
        <button class="rbtn" onclick="loadTracker()">↻ refresh</button>
      </div>
      <div class="tscroll">
        <table><thead id="tHead"></thead><tbody id="tBody"><tr><td colspan="6" class="empty">Loading...</td></tr></tbody></table>
      </div>
    </div>
  </div>
</div>

<script>
let applied=0,skipped=0,errors=0,total=0;
let polling=null;

applyAutoTheme();

fetch('/ai_mode').then(r=>r.json()).then(d=>{
  const tog=document.getElementById('aiTog');
  const txt=document.getElementById('aiTxt');
  if(d.mode==='premium'){tog.checked=true;txt.textContent='Premium';txt.style.color='#a78bfa';}
  else{txt.textContent='Free';txt.style.color='#34d399';}
});

function toggleAI(el){
  const mode=el.checked?'premium':'free';
  const txt=document.getElementById('aiTxt');
  fetch('/ai_mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})})
    .then(r=>r.json()).then(()=>{
      txt.textContent=mode==='premium'?'Premium':'Free';
      txt.style.color=mode==='premium'?'#a78bfa':'#34d399';
      addLog('⚡ AI mode → '+mode.toUpperCase(),'i');
    });
}

function applyAutoTheme(){
  const h = new Date().getHours();
  const isDay = h >= 7 && h < 20;
  document.documentElement.setAttribute('data-theme', isDay ? 'light' : 'dark');
  document.getElementById('tIco').textContent = isDay ? '🌙' : '☀️';
}

function toggleTheme(){
  const h=document.documentElement;
  const dark=h.getAttribute('data-theme')==='dark';
  h.setAttribute('data-theme',dark?'light':'dark');
  document.getElementById('tIco').textContent=dark?'🌙':'☀️';
}

function setRunning(on,platform){
  const dot=document.getElementById('sdot');
  const txt=document.getElementById('stxt');
  ['bLI','bDI','bBoth'].forEach(b=>document.getElementById(b).disabled=on);
  document.getElementById('bStop').disabled=!on;
  dot.className='sdot'+(on?' on':'');
  txt.textContent=on?'RUNNING '+platform.toUpperCase():'IDLE';
}

function runBot(platform){
  applied=0;skipped=0;errors=0;updateStats();
  setRunning(true,platform);
  addLog('🚀 Starting '+platform+' bot...','i');
  fetch('/run/'+platform,{method:'POST'}).then(r=>r.json()).then(d=>{
    if(d.status==='already_running'){addLog('⚠️ Already running','e');setRunning(false,'');}
    else{ startPolling(); }
  });
}

function stopBot(){
  fetch('/stop',{method:'POST'});
  addLog('⏹ Stop requested...','e');
  setRunning(false,'');
  stopPolling();
}

function startPolling(){
  polling=setInterval(()=>{
    fetch('/logs').then(r=>r.json()).then(d=>{
      d.logs.forEach(msg=>{
        if(msg.startsWith('__DONE__')){
          const s=JSON.parse(msg.replace('__DONE__',''));
          setRunning(false,'');
          stopPolling();
          addLog('🎉 Done! Applied: '+s.applied,'s');
          loadTracker();
        } else {
          addLog(msg);
        }
      });
    });
  },500);
}

function stopPolling(){
  if(polling){clearInterval(polling);polling=null;}
}

function updateStats(){
  document.getElementById('sA').textContent=applied;
  document.getElementById('sS').textContent=skipped;
  document.getElementById('sE').textContent=errors;
  document.getElementById('sT').textContent=total;
}

function addLog(msg,type){
  const box=document.getElementById('logBox');
  const div=document.createElement('div');
  let cls='ll';
  if(msg.includes('✅')||msg.includes('Applied!')||msg.includes('Logged'))cls+=' ls';
  else if(msg.includes('❌')||msg.includes('Error'))cls+=' le';
  else if(msg.includes('⏭️')||msg.includes('🚫')||msg.includes('skipping')||msg.includes('Not in'))cls+=' lk';
  else if(msg.includes('💼')||msg.includes('Applying'))cls+=' la';
  else if(type==='i'||msg.includes('🔍')||msg.includes('🚀')||msg.includes('Starting'))cls+=' li';
  div.className=cls;
  const t=new Date().toLocaleTimeString('en',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
  div.textContent='['+t+'] '+msg;
  box.appendChild(div);
  box.scrollTop=box.scrollHeight;
  if(msg.includes('Applied!')){applied++;total++;}
  if(msg.includes('skipping')||msg.includes('Not in')||msg.includes('🚫'))skipped++;
  if(msg.includes('❌ Error'))errors++;
  updateStats();
}

function clearLogs(){document.getElementById('logBox').innerHTML='<div class="ll li">// logs cleared</div>';}

function loadTracker(){
  fetch('/tracker').then(r=>r.json()).then(d=>{
    const head=document.getElementById('tHead');
    const body=document.getElementById('tBody');
    if(d.error){body.innerHTML='<tr><td colspan="6" class="empty">'+d.error+'</td></tr>';return;}
    if(!d.rows||!d.rows.length){body.innerHTML='<tr><td colspan="6" class="empty">No applications yet</td></tr>';return;}
    head.innerHTML='<tr>'+d.cols.map(c=>'<th>'+c+'</th>').join('')+'</tr>';
    body.innerHTML=d.rows.slice().reverse().map(function(row){
      return '<tr>'+row.map(function(cell,i){
        if(d.cols[i]==='Status'){
          var cls=cell==='Applied'?'pa':cell==='Interview'?'pi':'pr';
          return '<td><span class="pill '+cls+'">'+(cell||'-')+'</span></td>';
        }
        if(d.cols[i]==='Link'&&cell)return '<td><a class="tlink" href="'+cell+'" target="_blank">↗ view</a></td>';
        return '<td title="'+(cell||'')+'">'+(cell||'-')+'</td>';
      }).join('')+'</tr>';
    }).join('');
  });
}
loadTracker();
</script>
</body>
</html>"""

@app.route("/")
def index():
    from flask import make_response
    resp = make_response(HTML)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp

@app.route("/logs")
def get_logs():
    logs = []
    while not log_queue.empty():
        logs.append(log_queue.get_nowait())
    return json.dumps({"logs": logs}), 200, {"Content-Type": "application/json"}

@app.route("/run/<platform>", methods=["POST"])
def run(platform):
    global bot_running
    if bot_running:
        return json.dumps({"status": "already_running"}), 200, {"Content-Type": "application/json"}
    t = threading.Thread(target=run_bot, args=(platform,))
    t.daemon = True
    t.start()
    return json.dumps({"status": "started"}), 200, {"Content-Type": "application/json"}

@app.route("/stop", methods=["POST"])
def stop():
    global bot_running
    stop_event.set()
    bot_running = False
    return json.dumps({"status": "stopped"}), 200, {"Content-Type": "application/json"}

@app.route("/tracker")
def get_tracker():
    try:
        path = os.path.expanduser("~/Desktop/Salesforce_Job_Application_Tracker.xlsx")
        xl = pd.read_excel(path, sheet_name="Job Applications", header=2)
        xl = xl.dropna(how="all")
        cols = ["Position Name", "Company / End Client", "Status",
                "Submission Date", "Work Model", "Resume Used", "Link"]
        available = [c for c in cols if c in xl.columns]
        df = xl[available].tail(20).fillna("")
        return json.dumps({"rows": df.values.tolist(), "cols": available}), 200, {"Content-Type": "application/json"}
    except Exception as e:
        return json.dumps({"error": str(e)}), 200, {"Content-Type": "application/json"}

@app.route("/ai_mode", methods=["GET", "POST"])
def ai_mode():
    env_path = os.path.expanduser("~/job-applier/.env")
    if request.method == "POST":
        data = json.loads(request.data)
        mode = data.get("mode", "free")
        # Read existing .env, update AI_MODE line
        try:
            with open(env_path, "r") as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []
        new_lines = []
        found = False
        for line in lines:
            if line.startswith("AI_MODE="):
                new_lines.append(f"AI_MODE={mode}\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"AI_MODE={mode}\n")
        with open(env_path, "w") as f:
            f.writelines(new_lines)
        # Also update the live config so current process reflects the change
        import config as cfg
        cfg.AI_MODE = mode
        import ai_agent
        ai_agent.AI_MODE = mode  # update the imported value in ai_agent too
        return json.dumps({"status": "ok", "mode": mode}), 200, {"Content-Type": "application/json"}
    else:
        import config as cfg
        mode = cfg.AI_MODE
        return json.dumps({"mode": mode}), 200, {"Content-Type": "application/json"}

if __name__ == "__main__":
    print("Starting Job Bot UI at http://127.0.0.1:8080")
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)