"""
Orchestrator — the CEO of the v11 system.

Single authority that controls the entire execution lifecycle:
  INIT -> PLAN -> VALIDATE -> EXECUTE -> VERIFY -> (PATCH -> EXECUTE)* -> DONE

Everything flows through this. No agent acts independently.

Now instrumented with:
  - Transaction Engine (atomic change sets with rollback)
  - Tracer (per-task latency spans and metrics)
"""

import json
import time
from core.state_machine import StateMachine, State, TransitionError
from core.event_bus import bus
from core.models import ModelRouter
from core.key_manager import KeyManager
from core.model_registry import ModelRegistry
from core.model_client import ModelClient
from core.transactions import TransactionManager
from core.tracer import Tracer


class Orchestrator:
    """Master controller for the v11 AI execution runtime.

    Responsibilities:
    - Enforce state machine transitions
    - Assign models to agent roles (with fallback)
    - Prevent illegal tool calls (via Execution Guard in CoderAgent)
    - Wrap file modifications in transactions (atomic rollback)
    - Trace every operation for observability
    - Resolve model disagreements (critic wins)
    - Control execution lifecycle
    - Emit events for UI/streaming/diff sync
    """

    def __init__(
        self,
        key_manager: KeyManager = None,
        registry: ModelRegistry = None,
        max_retries: int = 3,
    ):
        self.km = key_manager or KeyManager()
        self.registry = registry or ModelRegistry()
        self.client = ModelClient(self.km, self.registry)
        self.router = ModelRouter(self.km, self.registry)
        self.sm = StateMachine(max_retries=max_retries)
        self.tx = TransactionManager()
        self.tracer = Tracer()

        # Import agents here to avoid circular imports
        from agents.planner import PlannerAgent
        from agents.coder import CoderAgent
        from agents.critic import CriticAgent

        self.planner = PlannerAgent(self.router, bus)
        self.coder = CoderAgent(self.router, bus)
        self.critic = CriticAgent(self.router, bus)

    def run(self, task: str) -> dict:
        """Execute the full controlled pipeline for a task.

        Returns a result dict with the final output and execution trace.
        """
        self.sm.reset()

        # Start trace and transaction
        trace = self.tracer.start(task)
        tx = self.tx.begin()

        trace_span = trace.root

        trace_data = {
            "task": task,
            "steps": [],
            "start_time": time.time(),
            "status": "running",
            "transaction_id": tx.tx_id,
        }

        bus.emit("agent.start", {"task": task, "tx_id": tx.tx_id})

        try:
            # ---- INIT -> PLAN ----
            self.sm.transition(State.PLAN)
            bus.emit("state.change", {"state": "plan"})

            plan_span = trace.span("planner")
            plan_span.set_attr("model", "nemotron")
            plan_span.start()

            plan = self.planner.run(task)
            plan_span.finish()

            trace_data["steps"].append({"phase": "plan", "output": plan, "duration_ms": plan_span.duration_ms})
            bus.emit("plan.generated", {"plan": str(plan)[:500]})

            # ---- PLAN -> VALIDATE ----
            self.sm.transition(State.VALIDATE)
            bus.emit("state.change", {"state": "validate"})

            validate_span = trace.span("critic.validate")
            validate_span.set_attr("model", "nemotron")
            validate_span.start()

            validated = self.critic.validate_plan(plan)
            validate_span.finish()

            trace_data["steps"].append({"phase": "validate", "output": validated, "duration_ms": validate_span.duration_ms})

            if not validated.get("valid", True):
                validate_span.set_attr("result", "rejected")
                bus.emit("plan.rejected", {"reason": validated.get("reason", "")})
                # Re-plan
                self.sm.transition(State.PLAN)
                plan = self.planner.run(task + f"\nPrevious plan was rejected: {validated.get('reason', '')}")
                trace_data["steps"].append({"phase": "replan", "output": plan})
                bus.emit("plan.regenerated", {"plan": str(plan)[:500]})

                # Re-validate
                self.sm.transition(State.VALIDATE)
                validated = self.critic.validate_plan(plan)
                trace_data["steps"].append({"phase": "revalidate", "output": validated})

            validate_span.set_attr("result", "approved")
            bus.emit("plan.validated", {"valid": True})

            # ---- VALIDATE -> EXECUTE ----
            self.sm.transition(State.EXECUTE)
            bus.emit("state.change", {"state": "execute"})

            execute_span = trace.span("coder.execute")
            execute_span.start()

            # Snapshot files before execution (for transaction rollback)
            # The coder agent's execution will modify files within this transaction
            result = self.coder.run(plan)
            execute_span.finish()

            trace_data["steps"].append({"phase": "execute", "output": str(result)[:1000], "duration_ms": execute_span.duration_ms})
            bus.emit("execution.done", {"result": str(result)[:500]})

            # ---- EXECUTE -> VERIFY ----
            self.sm.transition(State.VERIFY)
            bus.emit("state.change", {"state": "verify"})

            verify_span = trace.span("critic.verify")
            verify_span.start()

            verification = self.critic.check_result(result)
            verify_span.finish()

            trace_data["steps"].append({"phase": "verify", "output": verification, "duration_ms": verify_span.duration_ms})

            # ---- VERIFY -> PATCH or DONE ----
            while not verification.get("ok", True) and not self.sm.is_done:
                try:
                    self.sm.transition(State.PATCH)
                    bus.emit("state.change", {"state": "patch"})

                    patch_span = trace.span("critic.patch")
                    patch_span.start()

                    patch_plan = self.critic.suggest_fix(result, verification)
                    patch_span.finish()

                    trace_data["steps"].append({"phase": "patch", "output": patch_plan, "duration_ms": patch_span.duration_ms})
                    bus.emit("patch.suggested", {"patch": str(patch_plan)[:500]})

                    self.sm.transition(State.EXECUTE)
                    bus.emit("state.change", {"state": "execute"})

                    reexecute_span = trace.span("coder.reexecute")
                    reexecute_span.start()

                    result = self.coder.run(patch_plan)
                    reexecute_span.finish()

                    trace_data["steps"].append({"phase": "reexecute", "output": str(result)[:1000], "duration_ms": reexecute_span.duration_ms})

                    self.sm.transition(State.VERIFY)

                    reverify_span = trace.span("critic.reverify")
                    reverify_span.start()

                    verification = self.critic.check_result(result)
                    reverify_span.finish()

                    trace_data["steps"].append({"phase": "reverify", "output": verification, "duration_ms": reverify_span.duration_ms})

                except TransitionError as e:
                    # Max retries exceeded — rollback transaction
                    bus.emit("retries.exhausted", {"error": str(e)})

                    rollback_result = self.tx.rollback_active()
                    bus.emit("transaction.auto_rollback", {"result": rollback_result})
                    trace_data["rollback"] = rollback_result

                    self.tracer.finish("failed")
                    trace_data["status"] = "failed_with_rollback"
                    trace_data["end_time"] = time.time()
                    trace_data["duration"] = trace_data["end_time"] - trace_data["start_time"]
                    trace_data["state_transitions"] = self.sm.history

                    return {
                        "status": "failed",
                        "error": str(e),
                        "trace": trace_data,
                        "rollback": rollback_result,
                        "task_trace": self._render_trace(trace),
                    }

            # ---- -> DONE ----
            # Verification passed — commit the transaction
            tx.commit()
            self.sm.transition(State.DONE)
            bus.emit("state.change", {"state": "done"})

            trace_data["status"] = "completed"
            trace_data["end_time"] = time.time()
            trace_data["duration"] = trace_data["end_time"] - trace_data["start_time"]
            trace_data["state_transitions"] = self.sm.history
            trace_data["transaction"] = tx.summary()

            self.tracer.finish("ok")

            bus.emit("task.done", {"result": str(result)[:500]})
            return {
                "status": "completed",
                "result": result,
                "trace": trace_data,
                "task_trace": self._render_trace(trace),
            }

        except TransitionError as e:
            # State machine violation — rollback
            rollback_result = self.tx.rollback_active()
            trace_data["status"] = "failed"
            trace_data["error"] = str(e)
            trace_data["state_transitions"] = self.sm.history
            trace_data["rollback"] = rollback_result

            self.tracer.finish("error")
            bus.emit("task.failed", {"error": str(e)})
            return {
                "status": "failed",
                "error": str(e),
                "trace": trace_data,
                "rollback": rollback_result,
                "task_trace": self._render_trace(trace),
            }

        except Exception as e:
            # Unexpected error — rollback
            rollback_result = self.tx.rollback_active()
            trace_data["status"] = "error"
            trace_data["error"] = str(e)
            trace_data["state_transitions"] = self.sm.history
            trace_data["rollback"] = rollback_result

            self.tracer.finish("error")
            bus.emit("task.error", {"error": str(e)})
            return {
                "status": "error",
                "error": str(e),
                "trace": trace_data,
                "rollback": rollback_result,
                "task_trace": self._render_trace(trace),
            }

    @staticmethod
    def _render_trace(trace) -> str:
        """Render the trace tree as a readable string."""
        try:
            return trace.render()
        except Exception:
            return ""