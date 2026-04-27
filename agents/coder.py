"""
Coder Agent — executes the plan using the coder model.

Role: Take a validated plan and produce code/tool actions.
Model: qwen (code-focused)

All tool calls pass through the Execution Guard before reaching the OS.
All file-modifying tools are wrapped in Transaction snapshots.
"""

import json
from core.event_bus import bus
from core.models import ModelRouter
from core.guard import ExecutionGuard, GuardViolation
from core.transactions import tx_manager
from tools.registry import execute_tool_action


# Tools that modify the filesystem (need transaction snapshots)
MUTATING_TOOLS = {"write", "patch"}


CODER_SYSTEM = """You are a coding executor. Given a plan, output the exact tool calls needed.

OUTPUT FORMAT - return a JSON object:
{
  "actions": [
    {"tool": "read", "args": {"path": "<file>"}},
    {"tool": "patch", "args": {"path": "<file>", "old": "<exact string>", "new": "<replacement>"}},
    {"tool": "write", "args": {"path": "<file>", "content": "<full file content>"}}
  ],
  "summary": "what this does"
}

AVAILABLE TOOLS: read, write, patch, search, search_files, list_dir, run, add_note

RULES:
- Use patch for targeted edits (safer than write).
- Use write only for new files.
- Provide exact old strings for patches (character-perfect).
- Return JSON only."""


class CoderAgent:
    """Executes plans by producing and running tool actions.

    Every tool call MUST pass through the Execution Guard.
    Every file modification MUST be snapshot'd by the Transaction Manager.
    This ensures: unsafe actions are blocked, and broken edits can be rolled back.
    """

    def __init__(self, model_router: ModelRouter, event_bus=None, guard: ExecutionGuard = None):
        self.router = model_router
        self.bus = event_bus or bus
        self.guard = guard or ExecutionGuard()

    def run(self, plan: dict) -> dict:
        """Execute a plan by generating and running tool actions."""
        self.bus.emit("coder.start", {"plan": str(plan)[:300]})

        # If plan has raw steps, try to execute them directly
        if isinstance(plan, dict) and "steps" in plan:
            result = self._execute_steps(plan["steps"])
            self.bus.emit("coder.done", {"result": str(result)[:500]})
            return result

        # Otherwise, ask the coder model to translate plan into actions
        response = self.router.call("coder", [
            {"role": "system", "content": CODER_SYSTEM},
            {"role": "user", "content": f"PLAN:\n{json.dumps(plan, indent=2)}"},
        ])

        actions = self._parse_actions(response)
        result = self._execute_steps(actions)
        self.bus.emit("coder.done", {"result": str(result)[:500]})
        return result

    def _execute_steps(self, steps: list) -> dict:
        """Execute a list of tool action steps through the Execution Guard
        and Transaction Manager."""
        results = []
        blocked = []

        # Validate ALL actions through the guard first
        valid_steps = self.guard.validate_batch(steps)

        if len(valid_steps) < len(steps):
            blocked = self.guard.get_violations()
            self.bus.emit("guard.blocked", {
                "count": len(blocked),
                "violations": [v["reason"] for v in blocked],
            })
            self.guard.clear_violations()

        for i, step in enumerate(valid_steps):
            tool = step.get("tool", step.get("action", ""))
            args = step.get("args", step.get("arguments", {}))

            if not tool:
                continue

            # Per-action validation
            try:
                self.guard.validate(step)
            except GuardViolation as e:
                blocked.append({"action": step, "reason": str(e)})
                self.bus.emit("guard.blocked", {"step": i + 1, "reason": str(e)})
                continue

            # Snapshot file before mutation (for transaction rollback)
            if tool in MUTATING_TOOLS and "path" in args:
                tx = tx_manager.active
                if tx is not None:
                    tx.snapshot_file(args["path"])
                    tx.record_operation(tool, {"path": args["path"]})
                    self.bus.emit("transaction.snapshot", {
                        "step": i + 1,
                        "path": args["path"],
                        "tx_id": tx.tx_id,
                    })

            self.bus.emit("tool.call", {"step": i + 1, "tool": tool})

            result = execute_tool_action(tool, args)
            results.append({
                "step": i + 1,
                "tool": tool,
                "args": {k: str(v)[:80] for k, v in args.items()},
                "result": str(result)[:500],
                "snapshotted": tool in MUTATING_TOOLS and "path" in args,
            })

            self.bus.emit("tool.result", {"step": i + 1, "result": str(result)[:200]})

        summary = f"Executed {len(results)} tool actions"
        if blocked:
            summary += f", {len(blocked)} blocked by guard"

        return {
            "steps_executed": len(results),
            "steps_blocked": len(blocked),
            "results": results,
            "blocked": blocked,
            "summary": summary,
        }

    def _parse_actions(self, response: dict) -> list:
        """Parse model response into a list of actions."""
        text = self._extract_text(response)

        try:
            data = json.loads(text)
            return data.get("actions", data.get("steps", []))
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                data = json.loads(text[start:end])
                return data.get("actions", data.get("steps", []))
            except json.JSONDecodeError:
                pass

        return []

    @staticmethod
    def _extract_text(response: dict) -> str:
        """Extract text from model response."""
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            if "error" in response:
                return json.dumps(response)
            if "choices" in response:
                return response["choices"][0]["message"]["content"]
            if "output" in response:
                content = response["output"][0].get("content", [])
                if isinstance(content, list) and len(content) > 0:
                    return content[0].get("text", "")
        return str(response)