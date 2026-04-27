"""
OpenVS CLI entry point.

Usage:
  openvs              Launch interactive terminal UI
  openvs --version    Show version
  openvs --doctor     Run health checks
  openvs --doctor --export  Export diagnostic bundle
  openvs --demo       Run canned swarm demo
  openvs --help       Show help
"""

import sys


def run():
    # Handle CLI flags before launching the TUI
    if len(sys.argv) > 1:
        flag = sys.argv[1]

        if flag == "--version" or flag == "-v":
            from openvs import __version__
            print(f"OpenVS CLI v{__version__}")
            return

        if flag == "--doctor":
            if "--export" in sys.argv:
                _run_doctor_export()
            else:
                _run_doctor()
            return

        if flag == "--demo":
            _run_demo()
            return

        if flag == "--help" or flag == "-h":
            print(__doc__)
            return

    # Launch the Textual TUI
    from openvs.ui.app import OpenVSApp
    app = OpenVSApp()
    app.run()


def _run_doctor():
    """Run doctor health checks in non-interactive mode."""
    try:
        from openvs.core.doctor import run_doctor
        result = run_doctor()
        checks = result["checks"]
        summary = result["summary"]

        print()
        print("  OpenVS CLI Doctor")
        print("=" * 50)
        print()

        for name, check in checks.items():
            icon = {"ok": "+", "warn": "!", "fail": "X"}[check["status"]]
            print(f"  [{icon}] {name:15s} - {check['message']}")

        print()
        print("=" * 50)
        if summary["healthy"]:
            print(f"  All {summary['total']} checks passed")
        else:
            print(f"  {summary['passed']}/{summary['total']} passed, "
                  f"{summary['failed']} failed, {summary['warned']} warnings")
        print()

    except Exception as e:
        print(f"Doctor error: {e}")


def _run_doctor_export():
    """Export a full diagnostic bundle for bug reports."""
    try:
        from openvs.core.session import export_diagnostics
        result = export_diagnostics()
        path = result.get("_export_path", "unknown")
        print()
        print("  OpenVS CLI — Diagnostic Export")
        print("=" * 50)
        print(f"  Bundle written to: {path}")
        print(f"  Doctor checks: {result.get('doctor', {}).get('summary', {}).get('total', '?')}")
        print(f"  Crash entries: {len(result.get('crashes', []))}")
        print(f"  Session: {'included' if result.get('session') else 'none'}")
        print()
        print("  Share this file for bug reports.")
        print()
    except Exception as e:
        print(f"Export error: {e}")


def _run_demo():
    """Run a canned swarm demo — no API keys needed."""
    import time

    print()
    print("  OpenVS CLI — Swarm Demo")
    print("=" * 50)
    print()

    # Simulate the swarm pipeline
    stages = [
        ("orchestrator", "Planning task decomposition..."),
        ("planner", "Analyzing: Fix race condition in auth module"),
        ("coder", "Implementing patch for auth.py..."),
        ("critic", "Reviewing patch for safety and correctness..."),
        ("tester", "Running regression tests..."),
        ("consensus", "Voting: approve (4/5) — critic override: accept"),
        ("merge", "Merging results: 0 conflicts"),
    ]

    for role, msg in stages:
        print(f"  [{role:14s}] {msg}")
        time.sleep(0.3)

    print()
    print("  Result: completed")
    print(f"  Duration: {int(time.time() * 1000) % 500 + 200}ms")
    print("  DAG nodes: 5 total, 5 completed")
    print("  Consensus: approved (weighted)")
    print()
    print("  Demo complete. Run `openvs` to start the full CLI.")
    print()


if __name__ == "__main__":
    run()
