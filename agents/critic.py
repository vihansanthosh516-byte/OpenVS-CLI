"""
Critic Agent — validates plans, verifies results, suggests fixes.

Role: The final authority. When models disagree, critic wins.
Model: nemotron (reasoning-heavy)
"""

import json
from core.event_bus import bus
from core.models import ModelRouter


CRITIC_VALIDATE_SYSTEM = """You are a plan validator. Check if this plan is safe and logical.

Return JSON:
{"valid": true/false, "reason": "explanation", "suggestions": ["fix1", ...]}

CHECK FOR:
- Missing file reads before edits
- Ambiguous patches (old string not specific enough)
- Dangerous shell commands (rm -rf, etc.)
- Illogical step ordering
- Missing error handling

Return JSON only:"""


CRITIC_VERIFY_SYSTEM = """You are a result verifier. Check if the execution output is correct.

Return JSON:
{"ok": true/false, "issues": ["issue1", ...], "severity": "low/medium/high"}

CHECK FOR:
- Error messages in output
- Missing expected results
- Partial completion
- Unexpected side effects

Return JSON only:"""


CRITIC_FIX_SYSTEM = """You are a fix planner. Given a failed result, suggest corrections.

Return JSON:
{
  "fix_steps": [
    {"tool": "...", "args": {...}}
  ],
  "reason": "why this fix should work"
}

Return JSON only:"""


class CriticAgent:
    """Validates plans, verifies results, and suggests fixes.

    The critic is the FINAL AUTHORITY in the v11 system.
    When models disagree, the critic decides.
    """

    def __init__(self, model_router: ModelRouter, event_bus=None):
        self.router = model_router
        self.bus = event_bus or bus

    def validate_plan(self, plan: dict) -> dict:
        """Validate a plan before execution. Returns {valid, reason, suggestions}."""
        self.bus.emit("critic.validate_start", {"plan": str(plan)[:300]})

        # Quick structural checks (no model call needed)
        structural = self._structural_checks(plan)
        if not structural["valid"]:
            self.bus.emit("critic.validate_done", {"valid": False, "reason": structural["reason"]})
            return structural

        # Model-based validation
        response = self.router.call("critic", [
            {"role": "system", "content": CRITIC_VALIDATE_SYSTEM},
            {"role": "user", "content": f"PLAN:\n{json.dumps(plan, indent=2)}"},
        ])

        result = self._parse_validation(response)
        self.bus.emit("critic.validate_done", result)
        return result

    def check_result(self, result: dict) -> dict:
        """Verify execution results. Returns {ok, issues, severity}."""
        self.bus.emit("critic.verify_start", {})

        # Quick checks first
        quick = self._quick_result_checks(result)
        if not quick["ok"]:
            self.bus.emit("critic.verify_done", quick)
            return quick

        # Model-based verification
        response = self.router.call("critic", [
            {"role": "system", "content": CRITIC_VERIFY_SYSTEM},
            {"role": "user", "content": f"RESULT:\n{json.dumps(result, indent=2)[:2000]}"},
        ])

        verification = self._parse_verification(response)
        self.bus.emit("critic.verify_done", verification)
        return verification

    def suggest_fix(self, result: dict, verification: dict) -> dict:
        """Suggest a fix for a failed result."""
        self.bus.emit("critic.fix_start", {})

        response = self.router.call("critic", [
            {"role": "system", "content": CRITIC_FIX_SYSTEM},
            {"role": "user", "content": (
                f"FAILED RESULT:\n{json.dumps(result, indent=2)[:1500]}\n\n"
                f"VERIFICATION:\n{json.dumps(verification, indent=2)[:500]}\n\n"
                "Suggest fix steps:"
            )},
        ])

        fix = self._parse_fix(response)
        self.bus.emit("critic.fix_done", fix)
        return fix

    def _structural_checks(self, plan: dict) -> dict:
        """Fast structural validation without model calls."""
        if not isinstance(plan, dict):
            return {"valid": False, "reason": "Plan is not a dict", "suggestions": []}

        steps = plan.get("steps", plan.get("actions", []))
        if not steps:
            # A plan with no steps might just be a summary
            if plan.get("summary") or plan.get("raw"):
                return {"valid": True, "reason": "raw/text plan", "suggestions": []}
            return {"valid": False, "reason": "Plan has no steps", "suggestions": ["Add execution steps"]}

        # Check for dangerous commands
        for step in steps:
            cmd = step.get("args", {}).get("cmd", "")
            if any(danger in cmd for danger in ["rm -rf", "del /s", "format ", "mkfs"]):
                return {
                    "valid": False,
                    "reason": f"Dangerous command detected: {cmd[:50]}",
                    "suggestions": ["Remove destructive commands"],
                }

        return {"valid": True, "reason": "Structural checks passed", "suggestions": []}

    def _quick_result_checks(self, result: dict) -> dict:
        """Fast result checks without model calls."""
        if isinstance(result, dict):
            # Check for errors in results
            results_list = result.get("results", [])
            for r in results_list:
                rtext = str(r.get("result", ""))
                if rtext.startswith("ERROR:"):
                    return {
                        "ok": False,
                        "issues": [f"Tool error: {rtext[:100]}"],
                        "severity": "high",
                    }

            # Check if any steps executed
            if result.get("steps_executed", 0) == 0:
                return {
                    "ok": False,
                    "issues": ["No steps were executed"],
                    "severity": "medium",
                }

        return {"ok": True, "issues": [], "severity": "none"}

    def _parse_validation(self, response: dict) -> dict:
        """Parse model validation response."""
        text = self._extract_text(response)
        try:
            data = json.loads(text)
            if "valid" in data:
                return data
        except json.JSONDecodeError:
            pass
        # Default to valid if we can't parse (don't block on model failure)
        return {"valid": True, "reason": "validation parse fallback", "suggestions": []}

    def _parse_verification(self, response: dict) -> dict:
        """Parse model verification response."""
        text = self._extract_text(response)
        try:
            data = json.loads(text)
            if "ok" in data:
                return data
        except json.JSONDecodeError:
            pass
        return {"ok": True, "issues": [], "severity": "none"}

    def _parse_fix(self, response: dict) -> dict:
        """Parse model fix suggestion response."""
        text = self._extract_text(response)
        try:
            data = json.loads(text)
            if "fix_steps" in data:
                return data
        except json.JSONDecodeError:
            pass
        return {"fix_steps": [], "reason": "fix parse fallback"}

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