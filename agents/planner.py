"""
Planner Agent — decides what to do using the planner model.

Role: Analyze task + context, output a structured action plan.
Model: nemotron (reasoning-heavy)
"""

import json
from core.event_bus import bus
from core.models import ModelRouter


PLANNER_SYSTEM = """You are an autonomous coding planner. Return ONLY valid JSON.

Analyze the task and current project state. Output a step-by-step plan.

OUTPUT FORMAT:
{
  "steps": [
    {"tool": "read", "args": {"path": "<file>"}},
    {"tool": "patch", "args": {"path": "<file>", "old": "...", "new": "..."}},
    ...
  ],
  "summary": "one-line plan description"
}

AVAILABLE TOOLS: read, write, patch, search, search_files, list_dir, run, add_note

STRATEGY:
- Explore first (list_dir, read) before editing.
- Use patch for targeted edits, write for new files.
- Use search to find code across the project.
- Break complex tasks into small steps.

Return JSON only:"""


class PlannerAgent:
    """Plans the execution strategy for a task."""

    def __init__(self, model_router: ModelRouter, event_bus=None):
        self.router = model_router
        self.bus = event_bus or bus

    def run(self, task: str) -> dict:
        """Generate an execution plan for the given task."""
        self.bus.emit("planner.start", {"task": task[:200]})

        # Build context from project state
        context = self._build_context()
        prompt = f"{PLANNER_SYSTEM}\n\nPROJECT CONTEXT:\n{context}\n\nTASK: {task}\n\nReturn JSON:"

        response = self.router.call("planner", [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": f"PROJECT CONTEXT:\n{context}\n\nTASK: {task}"},
        ])

        plan = self._parse_plan(response)
        self.bus.emit("planner.done", {"plan": str(plan)[:500]})
        return plan

    def _build_context(self) -> str:
        """Build a snapshot of the current project state."""
        from tools.registry import list_dir_safe, get_workspace
        workspace = get_workspace()

        try:
            tree = list_dir_safe(workspace)
            return f"Workspace: {workspace}\nFiles:\n{tree}"
        except Exception:
            return f"Workspace: {workspace}"

    def _parse_plan(self, response: dict) -> dict:
        """Parse model response into a structured plan."""
        text = self._extract_text(response)

        # Try direct JSON parse
        try:
            plan = json.loads(text)
            if "steps" in plan or "action" in plan:
                return plan
        except json.JSONDecodeError:
            pass

        # Find embedded JSON
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                plan = json.loads(text[start:end])
                if "steps" in plan or "action" in plan:
                    return plan
            except json.JSONDecodeError:
                pass

        # Fallback: treat entire response as a single-step plan
        return {
            "steps": [{"tool": "run", "args": {"cmd": f"echo '{text[:200]}'"}}],
            "summary": text[:200],
            "raw": True,
        }

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