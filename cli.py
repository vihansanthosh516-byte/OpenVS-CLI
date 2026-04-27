"""
Master CLI v13 - Distributed Swarm Agent Operating Environment.

Usage:
python cli.py "task" Run a task through the orchestrator
python cli.py --serve Launch the API server
python cli.py --status Show system status
python cli.py --models List configured models
python cli.py --fallback Show model fallback chains
python cli.py --keys Show API key status
python cli.py --events Show recent event bus history
python cli.py --store Show event store stats
python cli.py --guard Show execution guard violations
python cli.py --transactions Show transaction history
python cli.py --traces Show recent task traces
python cli.py --trace <id> Show a specific trace span tree
python cli.py --jobs List all jobs
python cli.py --queue Show queue stats
python cli.py --workers Show worker pool status
python cli.py --watchers Show registered watchers
python cli.py --swarm <task> Run task via swarm coordination
python cli.py --swarm-stats Show swarm coordinator stats
python cli.py --dags List active delegation DAGs
python cli.py --agents List policy role scopes
python cli.py --consensus Show consensus engine stats
python cli.py --cluster Show worker fabric status
python cli.py --test Run the regression test suite
python cli.py --reset Clear session memory
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    arg = sys.argv[1]

    if arg == "--serve":
        _serve()
    elif arg == "--status":
        _status()
    elif arg == "--models":
        _models()
    elif arg == "--fallback":
        _fallback()
    elif arg == "--keys":
        _keys()
    elif arg == "--events":
        _events()
    elif arg == "--store":
        _store()
    elif arg == "--guard":
        _guard()
    elif arg == "--transactions":
        _transactions()
    elif arg == "--traces":
        _traces()
    elif arg == "--trace":
        if len(sys.argv) < 3:
            print("Usage: python cli.py --trace <task_id>")
        else:
            _show_trace(sys.argv[2])
    elif arg == "--jobs":
        _jobs()
    elif arg == "--queue":
        _queue()
    elif arg == "--workers":
        _workers()
    elif arg == "--watchers":
        _watchers()
    elif arg == "--swarm":
        if len(sys.argv) < 3:
            print("Usage: python cli.py --swarm <task> [--mode parallel|pipeline|debate|map_reduce]")
        else:
            _swarm()
    elif arg == "--swarm-stats":
        _swarm_stats()
    elif arg == "--dags":
        _dags()
    elif arg == "--agents":
        _agents()
    elif arg == "--consensus":
        _consensus()
    elif arg == "--cluster":
        _cluster()
    elif arg == "--test":
        _test()
    elif arg == "--reset":
        _reset()
    else:
        task = " ".join(sys.argv[1:])
        _run_task(task)


def _run_task(task: str):
    from core.orchestrator import Orchestrator
    orchestrator = Orchestrator()
    result = orchestrator.run(task)

    status = result.get("status", "unknown")
    if status == "completed":
        print(f"\n{'='*55}")
        print(f" COMPLETED")
        print(f"{'='*55}")
        if isinstance(result.get("result"), dict):
            r = result["result"]
            print(f" Steps executed: {r.get('steps_executed', '?')}")
            print(f" Steps blocked: {r.get('steps_blocked', 0)}")
            for step in r.get("results", []):
                print(f" {step.get('tool', '?')}: {str(step.get('result', ''))[:100]}")
            for blocked in r.get("blocked", []):
                print(f" BLOCKED: {blocked.get('reason', '?')}")
        task_trace = result.get("task_trace", "")
        if task_trace:
            print(f"\n Trace:")
            for line in task_trace.split("\n"):
                print(f" {line}")
        print()
    else:
        print(f"\n{'='*55}")
        print(f" {status.upper()}: {result.get('error', 'unknown error')}")
        rollback = result.get("rollback", {})
        if rollback:
            print(f" Rollback: {rollback.get('total_files', 0)} files restored")
        print(f"{'='*55}\n")


def _serve():
    import uvicorn
    print("\n Master CLI v13 - Starting server on http://127.0.0.1:8000")
    print(" Dashboard: http://127.0.0.1:8000/dashboard")
    print(" API docs: http://127.0.0.1:8000/docs\n")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)


def _status():
    from core.key_manager import KeyManager
    from core.model_registry import ModelRegistry
    from core.event_bus import bus
    from core.transactions import tx_manager
    from core.tracer import tracer
    from core.scheduler import scheduler
    from core.watchdog import watchdog
    from core.swarm_coordinator import swarm
    from core.policy_engine import policy
    from core.distributed_workers import fabric
    from memory.memory import load_all_memory

    km = KeyManager()
    reg = ModelRegistry()
    mem = load_all_memory()
    store_stats = bus.store_stats()
    tx_stats = tx_manager.stats()
    sched_stats = scheduler.stats()
    wd_stats = watchdog.stats()
    swarm_stats = swarm.stats()
    policy_stats = policy.stats()
    fabric_stats = fabric.stats()

    print("\n Master CLI v13 - System Status")
    print("=" * 55)
    print(f" Configured providers: {km.list_configured() or ['none']}")
    print(f" Available models: {reg.list_models()}")
    print(f" Memory entries: {len(mem)}")
    print(f" Event bus (memory): {len(bus.history())}")
    print(f" Event store (disk): {store_stats.get('total_events', 0)} events")
    print(f" Guard violations: {len(bus.history(event_type='guard.blocked', limit=1000))}")
    print(f" Transactions: {tx_stats['total_transactions']} total, "
          f"{tx_stats['committed']} committed, {tx_stats['rolled_back']} rolled back")
    print(f" Jobs: {sched_stats['queue']['total_jobs']} total, "
          f"{sched_stats['queue']['by_status'].get('queued', 0)} queued, "
          f"{sched_stats['pool']['active_jobs']} running")
    print(f" Workers: {sched_stats['pool']['idle_workers']}/{sched_stats['pool']['size']} idle")
    print(f" Watchers: {wd_stats['watchers']} registered")
    print(f" Swarm DAGs: {swarm_stats['active_dags']} active | Tokens: {swarm_stats['tokens_issued']}")
    print(f" Policy: {policy_stats['tokens_issued']} tokens | {policy_stats['denied_actions']} denied")
    print(f" Fabric: {fabric_stats['total_workers']} workers | {fabric_stats['available']} available")
    print()


def _models():
    from core.model_registry import ModelRegistry
    reg = ModelRegistry()
    print("\n Model Registry")
    print("=" * 65)
    for name, config in reg.to_dict().items():
        print(f" {name:12s} | {config['provider']:8s} | {config['model_id']:40s} | role: {config['role']}")
    print()


def _fallback():
    from core.model_fallback import FALLBACK_CHAINS
    print("\n Model Fallback Chains")
    print("=" * 55)
    print(" Role | Primary | Fallback | Safe Mode")
    print(" ----------|-----------|-----------|----------")
    for role, chain in FALLBACK_CHAINS.items():
        primary = chain[0] if len(chain) > 0 else "-"
        fallback = chain[1] if len(chain) > 1 else "-"
        safe = chain[2] if len(chain) > 2 else "-"
        print(f" {role:9s} | {primary:9s} | {fallback:9s} | {safe}")
    print()


def _keys():
    from core.key_manager import KeyManager
    km = KeyManager()
    print("\n API Key Status")
    print("=" * 55)
    for provider, info in km.status().items():
        key_display = info.get("key_prefix", "not set")
        has_key = "Y" if info.get("has_key") else "N"
        print(f" [{has_key}] {provider:8s} | key: {key_display:12s} | url: {info.get('url', 'not set')}")
    print()


def _events():
    from core.event_bus import bus
    events = bus.history(limit=20)
    print(f"\n Event Bus - Recent {len(events)} events")
    print("=" * 60)
    for e in events:
        data_str = str(e.get("data", ""))[:80]
        print(f" {e.get('type', '?'):30s} | {data_str}")
    print()


def _store():
    from core.event_bus import bus
    stats = bus.store_stats()
    print(f"\n Event Store Stats")
    print("=" * 45)
    print(f" Enabled: {stats.get('enabled', False)}")
    print(f" Total events: {stats.get('total_events', 0)}")
    print(f" Log size: {stats.get('log_size_bytes', 0)} bytes")
    types = stats.get("event_types", {})
    if types:
        print(f"\n Event Type Breakdown:")
        for t, count in sorted(types.items(), key=lambda x: -x[1])[:15]:
            print(f" {t:30s} {count}")
    print()


def _guard():
    from core.guard import ExecutionGuard
    guard = ExecutionGuard()
    violations = guard.get_violations()
    print(f"\n Execution Guard - Violations")
    print("=" * 55)
    if violations:
        for v in violations:
            print(f" BLOCKED: {v.get('reason', '?')}")
            print(f" Action: {str(v.get('action', ''))[:100]}")
    else:
        print(" No violations recorded this session.")
    print()


def _transactions():
    from core.transactions import tx_manager
    stats = tx_manager.stats()
    history = tx_manager.history(limit=15)
    print(f"\n Transaction History")
    print("=" * 60)
    print(f" Total: {stats['total_transactions']} Committed: {stats['committed']} "
          f"Rolled back: {stats['rolled_back']} Active: {stats['active']}")
    print()
    if history:
        print(f" {'TX ID':25s} | {'Files':6s} | {'Ops':4s} | {'Status':10s} | {'Duration':10s}")
        print(f" {'-'*25}-+-{'-'*6}-+-{'-'*4}-+-{'-'*10}-+-{'-'*10}")
        for tx in history:
            status = "committed" if tx["committed"] else ("rolled_back" if tx["rolled_back"] else "active")
            print(f" {tx['tx_id']:25s} | {tx['files_snapshotted']:6d} | {tx['operations']:4d} | "
                  f"{status:10s} | {tx['duration_ms']:>8.1f}ms")
    else:
        print(" No transactions recorded.")
    print()


def _traces():
    from core.tracer import tracer
    traces = tracer.list_traces(limit=15)
    print(f"\n Task Traces")
    print("=" * 70)
    if traces:
        print(f" {'Task ID':25s} | {'Status':8s} | {'Duration':10s} | Task")
        print(f" {'-'*25}-+-{'-'*8}-+-{'-'*10}-+-{'-'*25}")
        for t in traces:
            dur = f"{t['duration_ms']:.0f}ms" if t.get("duration_ms") else "..."
            print(f" {t['task_id']:25s} | {t.get('status', '?'):8s} | {dur:10s} | {t.get('task', '')[:25]}")
    else:
        print(" No traces recorded yet.")
    print()


def _show_trace(task_id: str):
    from core.tracer import tracer
    trace = tracer.load_trace(task_id)
    if trace is None:
        print(f"\n Trace '{task_id}' not found.\n")
        return
    print(f"\n Trace: {task_id}")
    print(f" Task: {trace.task}")
    print("=" * 60)
    print(trace.render())
    print()


def _jobs():
    from core.scheduler import scheduler
    jobs = scheduler.list_jobs(limit=30)
    print(f"\n Jobs ({len(jobs)} total)")
    print("=" * 80)
    if jobs:
        print(f" {'Job ID':22s} | {'Status':10s} | {'Priority':8s} | {'Worker':10s} | Task")
        print(f" {'-'*22}-+-{'-'*10}-+-{'-'*8}-+-{'-'*10}-+-{'-'*25}")
        for j in jobs:
            print(f" {j['id']:22s} | {j['status']:10s} | {j['priority']:8s} | "
                  f"{j.get('worker_id', '-') or '-':10s} | {j['task'][:25]}")
    else:
        print(" No jobs.")
    print()


def _queue():
    from core.queue_manager import queue as q
    stats = q.stats()
    print(f"\n Queue Stats")
    print("=" * 45)
    print(f" Total jobs: {stats['total_jobs']}")
    print(f" Queued: {stats['queued']}")
    for status, count in stats.get("by_status", {}).items():
        print(f" {status:15s} {count}")
    print()


def _workers():
    from core.scheduler import scheduler
    stats = scheduler.stats()
    pool = stats["pool"]
    print(f"\n Worker Pool")
    print("=" * 60)
    print(f" Size: {pool['size']} Idle: {pool['idle_workers']} Active: {pool['active_jobs']}")
    print(f" Completed: {pool['total_completed']} Failed: {pool['total_failed']}")
    print()
    for w in pool.get("workers", []):
        status = "BUSY" if w["busy"] else "idle"
        current = w.get("current_job") or "-"
        print(f" {w['id']:12s} | {status:4s} | completed={w['jobs_completed']} failed={w['jobs_failed']} | job={current}")
    print()


def _watchers():
    from core.watchdog import watchdog
    watchers = watchdog.list_watchers()
    stats = watchdog.stats()
    print(f"\n Watchers ({len(watchers)} registered)")
    print("=" * 70)
    print(f" Running: {stats['running']} Total triggers: {stats['total_triggers']}")
    print()
    if watchers:
        print(f" {'ID':15s} | {'Path':20s} | {'Condition':8s} | {'Triggers':8s} | Task")
        print(f" {'-'*15}-+-{'-'*20}-+-{'-'*8}-+-{'-'*8}-+-{'-'*25}")
        for w in watchers:
            print(f" {w['id']:15s} | {w['path']:20s} | {w['condition']:8s} | "
                  f"{w['trigger_count']:8d} | {w['task'][:25]}")
    else:
        print(" No watchers registered.")
    print()


def _swarm():
    from core.swarm_coordinator import swarm
    args = sys.argv[2:]
    mode = "parallel"
    task_parts = []
    for a in args:
        if a.startswith("--mode="):
            mode = a.split("=", 1)[1]
        elif a == "--mode" and len(args) > args.index(a) + 1:
            mode = args[args.index(a) + 1]
        else:
            if not a.startswith("--"):
                task_parts.append(a)
    task = " ".join(task_parts)
    if not task:
        print("Usage: python cli.py --swarm <task> [--mode parallel|pipeline|debate|map_reduce]")
        return

    print(f"\n Swarm Execute — mode: {mode}")
    print("=" * 55)
    result = swarm.execute(task, mode=mode)

    print(f" Status: {result['status']}")
    print(f" Duration: {result['duration_ms']}ms")
    dag = result.get("dag", {})
    progress = dag.get("progress", {})
    print(f" DAG: {progress.get('total', 0)} nodes | {progress.get('completed', 0)} completed | "
          f"{progress.get('failed', 0)} failed")

    consensus = result.get("consensus")
    if consensus:
        print(f" Consensus: {consensus.get('decision', '?')} ({consensus.get('strategy', '?')})")
        print(f" Reasoning: {consensus.get('reasoning', '?')}")

    merge = result.get("merge", {})
    if merge:
        print(f" Merge: {merge.get('status', '?')} | Conflicts: {merge.get('total_conflicts', 0)}")
    print()


def _swarm_stats():
    from core.swarm_coordinator import swarm
    stats = swarm.stats()
    print(f"\n Swarm Coordinator Stats")
    print("=" * 45)
    print(f" Active DAGs: {stats['active_dags']}")
    print(f" Tokens issued: {stats['tokens_issued']}")
    print(f" Consensus strategy: {stats['consensus_strategy']}")
    policy_s = stats.get("policy_stats", {})
    print(f" Policy tokens: {policy_s.get('tokens_issued', 0)} | Denied: {policy_s.get('denied_actions', 0)}")
    consensus_s = stats.get("consensus_stats", {})
    print(f" Consensus rounds: {consensus_s.get('total_rounds', 0)} | "
          f"Approved: {consensus_s.get('approved', 0)} | Rejected: {consensus_s.get('rejected', 0)}")
    print()


def _dags():
    from core.swarm_coordinator import swarm
    dags = swarm.list_dags()
    print(f"\n Active Delegation DAGs ({len(dags)})")
    print("=" * 70)
    if dags:
        for d in dags:
            p = d.get("progress", {})
            print(f" {d['id']:20s} | Nodes: {p.get('total', 0)} | "
                  f"Done: {p.get('completed', 0)} | Failed: {p.get('failed', 0)} | {d['root_task'][:30]}")
    else:
        print(" No active DAGs.")
    print()


def _agents():
    from core.policy_engine import policy
    roles = policy.list_roles()
    print(f"\n Agent Role Scopes ({len(roles)} roles)")
    print("=" * 80)
    print(f" {'Role':18s} | {'Permissions':30s} | {'Denied':20s} | Delegate")
    print(f" {'-'*18}-+-{'-'*30}-+-{'-'*20}-+-{'-'*7}")
    for role, scope in roles.items():
        perms = ", ".join(scope["permissions"])[:30]
        denied = ", ".join(scope["denied"])[:20]
        delegate = "Y" if scope["can_delegate"] else "N"
        print(f" {role:18s} | {perms:30s} | {denied:20s} | {delegate}")
    print(f"\n Descriptions:")
    for role, scope in roles.items():
        print(f" {role:18s} — {scope['description']}")
    print()


def _consensus():
    from core.consensus import consensus, ROLE_WEIGHTS
    stats = consensus.stats()
    print(f"\n Consensus Engine Stats")
    print("=" * 45)
    print(f" Total rounds: {stats['total_rounds']}")
    print(f" Approved: {stats['approved']} | Rejected: {stats['rejected']}")
    print(f" Default strategy: {stats['default_strategy']}")
    print(f"\n Role Weights:")
    for role, weight in ROLE_WEIGHTS.items():
        print(f" {role:18s} = {weight}")
    if stats["total_rounds"] > 0:
        print(f"\n Recent History:")
        for h in consensus.history(limit=10):
            print(f" [{h['strategy']}] {h['decision']} — {h['reasoning'][:60]}")
    print()


def _cluster():
    from core.distributed_workers import fabric
    from core.task_router import task_router
    fabric_stats = fabric.stats()
    router_stats = task_router.stats()
    health = fabric.check_health()

    print(f"\n Worker Fabric")
    print("=" * 55)
    print(f" Total workers: {fabric_stats['total_workers']}")
    print(f" Available: {fabric_stats['available']}")
    print(f" Active jobs: {fabric_stats['total_active_jobs']}")
    print(f" Completed: {fabric_stats['total_completed']} | Failed: {fabric_stats['total_failed']}")
    print(f" Health: {health['healthy']} healthy | {health['stale']} stale")
    if health['stale_ids']:
        print(f" Stale workers: {', '.join(health['stale_ids'])}")

    print(f"\n Worker Nodes:")
    for w in fabric_stats.get("workers", []):
        status = w["state"]
        print(f" {w['id']:15s} | {status:8s} | caps={w['capabilities']} | "
              f"done={w['completed']} fail={w['failed']} | util={w['utilization']:.0%}")

    print(f"\n Task Router")
    print(f" Strategy: {router_stats['strategy']}")
    print(f" Total routes: {router_stats['total_routes']}")
    if router_stats["worker_performance"]:
        print(f" Worker Performance:")
        for wid, perf in router_stats["worker_performance"].items():
            total = perf["successes"] + perf["failures"]
            rate = perf["successes"] / total * 100 if total > 0 else 0
            print(f" {wid:15s} | {perf['successes']} ok / {perf['failures']} fail ({rate:.0f}%)")
    print()


def _test():
    import subprocess
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests")
    print("\n Running regression tests...")
    print("=" * 50)

    for test_file in ["test_guard.py", "test_scheduler.py", "test_swarm.py"]:
        path = os.path.join(test_dir, test_file)
        if not os.path.exists(path):
            continue
        print(f"\n [{test_file}]")
        try:
            result = subprocess.run(
                [sys.executable, path],
                capture_output=True, text=True, timeout=120,
            )
            print(result.stdout)
            if result.stderr:
                print(result.stderr[:500])
        except Exception as e:
            print(f" ERROR: {e}")
    print()


def _reset():
    from memory.memory import reset_memory
    reset_memory()
    print("Memory reset.")


if __name__ == "__main__":
    main()
