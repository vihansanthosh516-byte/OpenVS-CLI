"""
Master CLI v13 — FastAPI backend.

Routes:
POST /run Start an agent task
GET /status Check task status
GET /memory View session memory
POST /memory/reset Clear memory
GET /memory/search Search memory
GET /models List registered models
GET /keys Show API key status
GET /events Event bus history (in-memory)
GET /events/store Event store query (durable)
GET /events/stats Event store stats
GET /guard/violations Recent guard violations
GET /model/log Model fallback call log
POST /model/call Direct model call
POST /swarm/execute Execute task via swarm coordination
GET /swarm/dags List active DAGs
GET /swarm/dags/{id} Get specific DAG
GET /swarm/stats Swarm statistics
POST /consensus/vote Run consensus round
GET /consensus/history Recent consensus results
GET /consensus/stats Consensus statistics
GET /policy/roles List role scopes
POST /policy/token Issue capability token
GET /policy/denied Denied actions audit
GET /policy/stats Policy statistics
GET /fabric/workers Worker fabric status
POST /fabric/register Register worker node
POST /fabric/deregister/{id} Deregister worker
GET /fabric/health Worker health check
GET /router/stats Task router statistics
GET /router/history Routing history
GET /actor/stats Actor protocol statistics
GET /actor/messages Recent actor messages
WS /ws Real-time event stream
GET /dashboard Web dashboard
"""

import sys
import os
import json
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.key_manager import KeyManager
from core.model_registry import ModelRegistry
from core.event_bus import bus
from core.guard import ExecutionGuard
from memory.memory import load_all_memory, reset_memory, search_memory

app = FastAPI(title="Master CLI v13", version="13.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Models ----

class TaskRequest(BaseModel):
    task: str

class ModelCallRequest(BaseModel):
    role: str
    messages: list

# ---- State ----

latest_result = {"status": "idle", "task": None, "output": None}

# ---- Guard (shared instance) ----

guard = ExecutionGuard()

# ---- WS clients ----

ws_clients: list[WebSocket] = []

# Subscribe the WS broadcaster to all events
def _ws_broadcast(event: dict):
    """Forward events to all connected WebSocket clients."""
    import asyncio
    for ws in ws_clients[:]:
        try:
            asyncio.get_event_loop().create_task(ws.send_text(json.dumps(event)))
        except Exception:
            ws_clients.remove(ws)

bus.on_any(_ws_broadcast)


# ---- Agent Routes ----

@app.post("/run")
def run_task(req: TaskRequest):
    """Start an agent task via the orchestrator."""
    global latest_result
    latest_result = {"status": "running", "task": req.task, "output": None}

    def _run():
        global latest_result
        from core.orchestrator import Orchestrator
        import io

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            orch = Orchestrator()
            result = orch.run(req.task)
            sys.stdout = old_stdout
            output = buf.getvalue()
            latest_result = {
                "status": result.get("status", "unknown"),
                "task": req.task,
                "output": output,
                "result": result,
            }
        except Exception as e:
            sys.stdout = old_stdout
            latest_result = {
                "status": "error",
                "task": req.task,
                "output": f"ERROR: {e}",
            }

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"status": "started", "task": req.task}


@app.get("/status")
def status():
    return latest_result


@app.get("/memory")
def get_memory():
    return load_all_memory()


@app.post("/memory/reset")
def reset_mem():
    reset_memory()
    return {"status": "memory reset"}


@app.get("/memory/search")
def search_mem(q: str = "", k: int = 5):
    results = search_memory(q, k)
    return {"results": results}


@app.get("/models")
def list_models():
    reg = ModelRegistry()
    return reg.to_dict()


@app.get("/keys")
def list_keys():
    km = KeyManager()
    return km.status()


@app.get("/events")
def get_events(limit: int = 50, type: str = None):
    """In-memory event bus history."""
    return bus.history(event_type=type, limit=limit)


@app.get("/events/store")
def get_store_events(event_type: str = None, task_id: str = None,
                     since: float = None, limit: int = 100):
    """Durable event store query (survives restarts)."""
    return bus.query_store(
        event_type=event_type,
        task_id=task_id,
        since=since,
        limit=limit,
    )


@app.get("/events/stats")
def event_store_stats():
    """Event store statistics."""
    return bus.store_stats()


# ---- Guard Routes ----

@app.get("/guard/violations")
def get_guard_violations():
    """Recent guard violations (blocked actions)."""
    return {"violations": guard.get_violations()}


@app.post("/guard/validate")
def validate_action(action: dict):
    """Test-validate an action against the guard (dry run)."""
    try:
        guard.validate(action)
        return {"valid": True, "action": action}
    except Exception as e:
        return {"valid": False, "reason": str(e)}


# ---- Model Call Routes ----

@app.post("/model/call")
def model_call(req: ModelCallRequest):
    """Direct model call through the arbitration layer with fallback."""
    from core.models import ModelRouter
    router = ModelRouter()
    try:
        return router.call(req.role, req.messages)
    except Exception as e:
        return {"error": str(e)}


@app.get("/model/log")
def model_call_log(role: str = None, limit: int = 50):
    """Model fallback call history."""
    from core.models import ModelRouter
    router = ModelRouter()
    return {"calls": router.get_call_log(role=role, limit=limit)}


@app.get("/model/fallback-chains")
def fallback_chains():
    """Show the fallback chain for each role."""
    from core.model_fallback import FALLBACK_CHAINS
    return FALLBACK_CHAINS


# ---- Transaction Routes ----

@app.get("/transactions")
def list_transactions(limit: int = 20):
    """List recent transactions."""
    from core.transactions import tx_manager
    return {"transactions": tx_manager.history(limit=limit)}


@app.get("/transactions/stats")
def transaction_stats():
    """Transaction manager statistics."""
    from core.transactions import tx_manager
    return tx_manager.stats()


@app.post("/transactions/rollback/{tx_id}")
def rollback_transaction(tx_id: str):
    """Roll back a specific transaction (undo file changes)."""
    from core.transactions import tx_manager
    result = tx_manager.rollback_to(tx_id)
    return result


# ---- Tracer Routes ----

@app.get("/traces")
def list_traces(limit: int = 20):
    """List recent task traces."""
    from core.tracer import tracer
    return {"traces": tracer.list_traces(limit=limit)}


@app.get("/traces/{task_id}")
def get_trace(task_id: str):
    """Load a specific trace (full span tree)."""
    from core.tracer import tracer
    trace = tracer.load_trace(task_id)
    if trace is None:
        return {"error": f"Trace {task_id} not found"}
    return trace.to_dict()


# ---- Scheduler / Job Routes ----

@app.post("/jobs/submit")
def submit_job(req: TaskRequest, priority: str = "normal"):
    """Submit a job for immediate execution."""
    from core.scheduler import scheduler
    job_id = scheduler.submit(req.task, priority=priority)
    scheduler.tick()
    return {"job_id": job_id, "status": "queued"}

class ScheduleRequest(BaseModel):
    task: str
    run_at: float
    priority: str = "normal"

@app.post("/jobs/schedule")
def schedule_job(req: ScheduleRequest):
    """Schedule a job for future execution."""
    from core.scheduler import scheduler
    job_id = scheduler.schedule(req.task, req.run_at, priority=req.priority)
    return {"job_id": job_id, "status": "scheduled", "run_at": req.run_at}

class RecurringRequest(BaseModel):
    task: str
    interval: str
    priority: str = "background"

@app.post("/jobs/recurring")
def recurring_job(req: RecurringRequest):
    """Submit a recurring job."""
    from core.scheduler import scheduler
    job_id = scheduler.recurring(req.task, req.interval, priority=req.priority)
    return {"job_id": job_id, "status": "recurring", "interval": req.interval}

@app.get("/jobs")
def list_jobs(status: str = None, limit: int = 50):
    """List all jobs."""
    from core.scheduler import scheduler
    return {"jobs": scheduler.list_jobs(status=status, limit=limit)}

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    """Get a specific job's status."""
    from core.scheduler import scheduler
    result = scheduler.get_job(job_id)
    if result is None:
        return {"error": f"Job {job_id} not found"}
    return result

@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    """Cancel a job."""
    from core.scheduler import scheduler
    return scheduler.cancel_job(job_id)

@app.get("/scheduler/stats")
def scheduler_stats():
    """Scheduler, pool, and queue statistics."""
    from core.scheduler import scheduler
    return scheduler.stats()

@app.post("/scheduler/start")
def start_scheduler(pool_size: int = 4):
    """Start the scheduler with worker pool."""
    from core.scheduler import scheduler
    scheduler.pool.size = pool_size
    scheduler.start()
    return {"status": "started", "pool_size": pool_size}

@app.post("/scheduler/stop")
def stop_scheduler():
    """Stop the scheduler."""
    from core.scheduler import scheduler
    scheduler.stop()
    return {"status": "stopped"}

@app.post("/scheduler/tick")
def scheduler_tick():
    """Manually dispatch one round of jobs."""
    from core.scheduler import scheduler
    dispatched = scheduler.tick()
    return {"dispatched": dispatched}

# ---- Watcher Routes ----

class WatcherRequest(BaseModel):
    path: str
    condition: str
    task: str
    priority: str = "background"
    cooldown: float = 60.0

@app.post("/watchers/register")
def register_watcher(req: WatcherRequest):
    """Register a filesystem watcher."""
    from core.watchdog import watchdog
    watcher_id = watchdog.register(
        watcher_id=f"watch_{int(time.time())}",
        path=req.path,
        condition=req.condition,
        task=req.task,
        priority=req.priority,
        cooldown=req.cooldown,
    )
    return {"watcher_id": watcher_id, "status": "registered"}

@app.get("/watchers")
def list_watchers():
    """List all registered watchers."""
    from core.watchdog import watchdog
    return {"watchers": watchdog.list_watchers()}

@app.get("/watchers/stats")
def watcher_stats():
    """Watchdog statistics."""
    from core.watchdog import watchdog
    return watchdog.stats()

@app.post("/watchers/start")
def start_watchdog():
    """Start the watchdog polling loop."""
    from core.watchdog import watchdog
    watchdog.start()
    return {"status": "started"}

@app.post("/watchers/stop")
def stop_watchdog():
    """Stop the watchdog."""
    from core.watchdog import watchdog
    watchdog.stop()
    return {"status": "stopped"}


# ---- Swarm / DAG Routes (v13) ----

class SwarmTaskRequest(BaseModel):
    task: str
    mode: str = "parallel"

@app.post("/swarm/execute")
def swarm_execute(req: SwarmTaskRequest):
    """Execute a task using swarm coordination."""
    from core.swarm_coordinator import swarm
    result = swarm.execute(req.task, mode=req.mode)
    return result

@app.get("/swarm/dags")
def swarm_list_dags():
    """List all active delegation DAGs."""
    from core.swarm_coordinator import swarm
    return {"dags": swarm.list_dags()}

@app.get("/swarm/dags/{dag_id}")
def swarm_get_dag(dag_id: str):
    """Get a specific delegation DAG."""
    from core.swarm_coordinator import swarm
    dag = swarm.get_dag(dag_id)
    if dag is None:
        return {"error": f"DAG {dag_id} not found"}
    return dag.to_dict()

@app.get("/swarm/stats")
def swarm_stats():
    """Swarm coordinator statistics."""
    from core.swarm_coordinator import swarm
    return swarm.stats()


# ---- Consensus Routes (v13) ----

class ConsensusRequest(BaseModel):
    proposal: str
    agent_votes: dict[str, str]
    strategy: str = "weighted"

@app.post("/consensus/vote")
def consensus_vote(req: ConsensusRequest):
    """Run a consensus round on a proposal."""
    from core.consensus import consensus, ConsensusStrategy
    strategy = ConsensusStrategy(req.strategy)
    result = consensus.quick_vote(req.proposal, req.agent_votes, strategy)
    return result.to_dict()

@app.get("/consensus/history")
def consensus_history(limit: int = 20):
    """Recent consensus results."""
    from core.consensus import consensus
    return {"history": consensus.history(limit=limit)}

@app.get("/consensus/stats")
def consensus_stats():
    """Consensus engine statistics."""
    from core.consensus import consensus
    return consensus.stats()


# ---- Policy Engine Routes (v13) ----

@app.get("/policy/roles")
def policy_list_roles():
    """List all role scope definitions."""
    from core.policy_engine import policy
    return policy.list_roles()

class TokenRequest(BaseModel):
    agent_role: str
    task_id: str
    expires_in: float = None

@app.post("/policy/token")
def policy_issue_token(req: TokenRequest):
    """Issue a capability token for an agent role."""
    from core.policy_engine import policy
    token = policy.issue_token(req.agent_role, req.task_id, expires_in=req.expires_in)
    return token.to_dict()

@app.get("/policy/denied")
def policy_denied_actions(limit: int = 50):
    """Recent denied actions (audit log)."""
    from core.policy_engine import policy
    return {"denied": policy.get_denied_actions(limit=limit)}

@app.get("/policy/stats")
def policy_stats():
    """Policy engine statistics."""
    from core.policy_engine import policy
    return policy.stats()


# ---- Merge Engine Routes (v13) ----

@app.get("/merge/stats")
def merge_stats():
    """Merge engine statistics."""
    from core.merge_engine import merge_engine
    return {"status": "available"}


# ---- Worker Fabric Routes (v13) ----

@app.get("/fabric/workers")
def fabric_list_workers():
    """List all worker nodes in the fabric."""
    from core.distributed_workers import fabric
    return fabric.stats()

class RegisterWorkerRequest(BaseModel):
    worker_id: str
    capabilities: list[str] = None
    max_concurrent: int = 1

@app.post("/fabric/register")
def fabric_register_worker(req: RegisterWorkerRequest):
    """Register a new worker node."""
    from core.distributed_workers import fabric
    worker = fabric.register_worker(req.worker_id, req.capabilities, req.max_concurrent)
    return worker.stats()

@app.post("/fabric/deregister/{worker_id}")
def fabric_deregister_worker(worker_id: str):
    """Deregister a worker node."""
    from core.distributed_workers import fabric
    return fabric.deregister_worker(worker_id)

@app.get("/fabric/health")
def fabric_health():
    """Worker fabric health check."""
    from core.distributed_workers import fabric
    return fabric.check_health()


# ---- Task Router Routes (v13) ----

@app.get("/router/stats")
def router_stats():
    """Task router statistics."""
    from core.task_router import task_router
    return task_router.stats()

@app.get("/router/history")
def router_history(limit: int = 50):
    """Recent routing decisions."""
    from core.task_router import task_router
    return {"decisions": task_router.history(limit=limit)}


# ---- Actor Protocol Routes (v13) ----

@app.get("/actor/stats")
def actor_stats():
    """Actor protocol statistics."""
    from core.actor_protocol import protocol
    return protocol.stats()

@app.get("/actor/messages")
def actor_messages(limit: int = 100, msg_type: str = None):
    """Recent actor messages."""
    from core.actor_protocol import protocol, MessageType
    mt = MessageType(msg_type) if msg_type else None
    return {"messages": protocol.message_log(limit=limit, msg_type=mt)}


# ---- WebSocket ----

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data) if data.startswith("{") else {}
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        ws_clients.remove(ws)


# ---- Dashboard ----

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


DASHBOARD_HTML = """<!DOCTYPE html>
<html><head>
<title>Master CLI v13</title>
<style>
*{margin:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;padding:1.5rem}
h1{color:#58a6ff;font-size:1.3rem;margin-bottom:.5rem}
h2{color:#8b949e;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;margin:1rem 0 .4rem}
.grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1rem}
.full{grid-column:1/-1}
input,textarea{width:100%;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:6px;padding:.5rem;font-size:.9rem}
button{background:#238636;color:#fff;border:none;border-radius:6px;padding:.5rem 1rem;cursor:pointer;font-size:.85rem;margin-right:.4rem;margin-top:.4rem}
button:hover{background:#2ea043}
button.danger{background:#da3633}
button.secondary{background:#30363d;color:#c9d1d9}
pre{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:.6rem;font-size:.78rem;white-space:pre-wrap;max-height:250px;overflow-y:auto}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:.4rem}
.idle{background:#8b949e}.running{background:#d29922;animation:p 1s infinite}.done{background:#238636}.error{background:#f85149}
@keyframes p{0%,100%{opacity:1}50%{opacity:.4}}
.state-flow{display:flex;gap:.3rem;align-items:center;flex-wrap:wrap}
.state-flow span{background:#30363d;padding:.2rem .6rem;border-radius:4px;font-size:.7rem;color:#8b949e}
.state-flow span.active{background:#238636;color:#fff}
.state-flow span.failed{background:#da3633;color:#fff}
.badge{display:inline-block;padding:.1rem .4rem;border-radius:3px;font-size:.65rem;margin-left:.3rem}
.badge.green{background:#238636;color:#fff}
.badge.red{background:#da3633;color:#fff}
.badge.yellow{background:#d29922;color:#000}
.badge.blue{background:#1f6feb;color:#fff}
select{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:6px;padding:.4rem;font-size:.85rem}
</style></head><body>
<h1>Master CLI v13 — Distributed Swarm Runtime</h1>
<p style="color:#8b949e;margin-bottom:1rem">
Orchestrator + Swarm + Consensus + Policy Engine + Merge Engine + Worker Fabric
</p>

<div class="grid">
<div class="card full">
<h2>Submit Task</h2>
<div style="display:flex;gap:.5rem;align-items:center">
<input id="task" placeholder='e.g. "Add error handling to app.py"' style="flex:1"/>
<select id="mode">
<option value="parallel">Parallel</option>
<option value="pipeline">Pipeline</option>
<option value="debate">Debate</option>
<option value="map_reduce">Map-Reduce</option>
</select>
<button onclick="runTask()">Run</button>
<button onclick="runSwarm()">Swarm</button>
<button class="secondary" onclick="pollStatus()">Refresh</button>
</div>
</div>

<div class="card">
<h2>State Flow</h2>
<div class="state-flow" id="state-flow">
<span>INIT</span>&rarr;<span>PLAN</span>&rarr;<span>VALIDATE</span>&rarr;<span>EXECUTE</span>&rarr;<span>VERIFY</span>&rarr;<span>DONE</span>
</div>
<h2>Status</h2>
<p><span id="dot" class="dot idle"></span><span id="status-text">idle</span></p>
<pre id="output">No output yet.</pre>
</div>

<div class="card">
<h2>Models <span class="badge green" id="model-badge">live</span></h2>
<pre id="models">Loading...</pre>
<h2>Fallback Chains</h2>
<pre id="chains">Loading...</pre>
</div>

<div class="card">
<h2>Execution Guard <span class="badge red" id="guard-badge">0 blocked</span></h2>
<pre id="guard">No violations.</pre>
</div>

<div class="card">
<h2>Memory</h2>
<pre id="memory">Loading...</pre>
<button class="danger" onclick="resetMem()">Reset Memory</button>
</div>

<div class="card">
<h2>Keys</h2>
<pre id="keys">Loading...</pre>
</div>

<div class="card full">
<h2>Swarm <span class="badge blue" id="swarm-badge">0 DAGs</span></h2>
<div style="display:flex;gap:1rem">
<div style="flex:1"><h2>Active DAGs</h2><pre id="swarm-dags">No active DAGs.</pre></div>
<div style="flex:1"><h2>Consensus</h2><pre id="consensus-stats">Loading...</pre></div>
<div style="flex:1"><h2>Policy</h2><pre id="policy-stats">Loading...</pre></div>
</div>
</div>

<div class="card full">
<h2>Worker Fabric <span class="badge green" id="fabric-badge">0 workers</span></h2>
<div style="display:flex;gap:1rem">
<div style="flex:1"><pre id="fabric-workers">No workers.</pre></div>
<div style="flex:1"><h2>Router</h2><pre id="router-stats">Loading...</pre></div>
</div>
</div>

<div class="card full">
<h2>Event Bus <span class="badge yellow" id="store-badge">store</span></h2>
<pre id="events">Connecting...</pre>
</div>
</div>

<script>
const B = location.origin;

async function runTask(){
const t=document.getElementById('task').value;if(!t)return;
document.getElementById('output').textContent='Running...';
document.getElementById('dot').className='dot running';
document.getElementById('status-text').textContent='running';
await fetch(B+'/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task:t})});
pollStatus();
}

async function runSwarm(){
const t=document.getElementById('task').value;if(!t)return;
const mode=document.getElementById('mode').value;
document.getElementById('output').textContent='Swarm running...';
document.getElementById('dot').className='dot running';
document.getElementById('status-text').textContent='swarm:'+mode;
const r=await(await fetch(B+'/swarm/execute',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task:t,mode:mode})})).json();
document.getElementById('output').textContent=JSON.stringify(r,null,2);
document.getElementById('dot').className='dot done';
document.getElementById('status-text').textContent=r.status;
loadSwarm();loadConsensus();loadPolicy();
}

async function pollStatus(){
const r=await(await fetch(B+'/status')).json();
document.getElementById('dot').className='dot '+r.status;
document.getElementById('status-text').textContent=r.status+(r.task?' - '+r.task:'');
if(r.output)document.getElementById('output').textContent=r.output;
if(r.status==='running')setTimeout(pollStatus,1000);
else{loadModels();loadChains();loadGuard();loadMemory();loadKeys();loadEvents();loadStoreStats();loadSwarm();loadConsensus();loadPolicy();loadFabric();loadRouter();}
}

async function loadModels(){document.getElementById('models').textContent=JSON.stringify(await(await fetch(B+'/models')).json(),null,2)}
async function loadChains(){document.getElementById('chains').textContent=JSON.stringify(await(await fetch(B+'/model/fallback-chains')).json(),null,2)}
async function loadKeys(){document.getElementById('keys').textContent=JSON.stringify(await(await fetch(B+'/keys')).json(),null,2)}
async function loadMemory(){document.getElementById('memory').textContent=JSON.stringify(await(await fetch(B+'/memory')).json(),null,2).substring(0,2000)}
async function loadGuard(){
const r=await(await fetch(B+'/guard/violations')).json();
const v=r.violations||[];
document.getElementById('guard-badge').textContent=v.length+' blocked';
document.getElementById('guard').textContent=v.length?v.map(x=>x.reason).join('\\n'):'No violations.';
}
async function loadEvents(){
const r=await(await fetch(B+'/events?limit=30')).json();
document.getElementById('events').textContent=r.map(e=>e.type+' | '+String(e.data||'').substring(0,80)).join('\\n');
}
async function loadStoreStats(){
const r=await(await fetch(B+'/events/stats')).json();
document.getElementById('store-badge').textContent=r.enabled?'store: '+r.total_events:'store: off';
}
async function resetMem(){await fetch(B+'/memory/reset',{method:'POST'});loadMemory();}
async function loadSwarm(){
try{const r=await(await fetch(B+'/swarm/stats')).json();
document.getElementById('swarm-badge').textContent=r.active_dags+' DAGs';
const dags=await(await fetch(B+'/swarm/dags')).json();
document.getElementById('swarm-dags').textContent=JSON.stringify(dags,null,2).substring(0,1500);
}catch{}
}
async function loadConsensus(){
try{const r=await(await fetch(B+'/consensus/stats')).json();
document.getElementById('consensus-stats').textContent='Rounds: '+r.total_rounds+' | Approved: '+r.approved+' | Rejected: '+r.rejected+' | Strategy: '+r.default_strategy;
}catch{}
}
async function loadPolicy(){
try{const r=await(await fetch(B+'/policy/stats')).json();
document.getElementById('policy-stats').textContent='Tokens: '+r.tokens_issued+' | Denied: '+r.denied_actions;
}catch{}
}
async function loadFabric(){
try{const r=await(await fetch(B+'/fabric/workers')).json();
document.getElementById('fabric-badge').textContent=r.total_workers+' workers';
document.getElementById('fabric-workers').textContent='Total: '+r.total_workers+' | Available: '+r.available+' | Active jobs: '+r.total_active_jobs+' | Completed: '+r.total_completed;
}catch{}
}
async function loadRouter(){
try{const r=await(await fetch(B+'/router/stats')).json();
document.getElementById('router-stats').textContent='Routes: '+r.total_routes+' | Strategy: '+r.strategy+' | Workers tracked: '+r.workers_tracked;
}catch{}
}

let ws;
function connectWS(){
ws=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/ws');
ws.onmessage=e=>{
const log=document.getElementById('events');
try{const m=JSON.parse(e.data);
log.textContent=m.type+' | '+String(m.data||'').substring(0,80)+'\\n'+log.textContent;
if(m.type==='state.change'){updateStateFlow(m.data.state);}
if(m.type==='guard.blocked'){loadGuard();}
if(m.type==='model.error'||m.type==='model.success'){loadChains();}
if(m.type.startsWith('swarm.')||m.type.startsWith('consensus.')||m.type.startsWith('fabric.')){loadSwarm();loadConsensus();loadPolicy();loadFabric();}
}catch{}
};
ws.onclose=()=>setTimeout(connectWS,3000);
}
function updateStateFlow(current){
const states=['INIT','PLAN','VALIDATE','EXECUTE','VERIFY','PATCH','DONE'];
const el=document.getElementById('state-flow');
el.innerHTML=states.map(s=>`<span class="${s.toLowerCase()===current?'active':''}">${s}</span>`).join('&rarr;');
}

connectWS();loadModels();loadChains();loadGuard();loadMemory();loadKeys();loadEvents();loadStoreStats();loadSwarm();loadConsensus();loadPolicy();loadFabric();loadRouter();
</script>
</body></html>"""
