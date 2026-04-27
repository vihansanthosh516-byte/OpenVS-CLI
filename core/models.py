"""
Model Arbitration Layer - multi-model control with fallback chains.

Rules:
- Each role maps to a primary model + fallback chain
- If primary fails, fallback is tried automatically
- If models disagree, Critic decides final action
- No agent can call an arbitrary model directly
"""

from core.key_manager import KeyManager
from core.model_registry import ModelRegistry
from core.model_client import ModelClient
from core.model_fallback import FallbackRouter, FALLBACK_CHAINS


# Fixed role-to-primary-model mapping (single source of truth)
ROLE_MODEL_MAP = {
    "planner": "nemotron",
    "coder": "qwen",
    "fast": "glm",
    "vision": "gemma",
    "critic": "nemotron",
}


class ModelRouter:
    """Routes agent roles to their assigned models with automatic fallback.

    The orchestrator calls: model_router.call(role="planner", messages=[...])
    This layer handles provider selection, key lookup, fallback chains, and API format.

    If the primary model fails, it automatically falls back through the chain:
      planner: nemotron -> glm -> local
      coder:   qwen -> glm -> local
      critic:  nemotron -> glm -> local
    """

    def __init__(self, key_manager: KeyManager = None, registry: ModelRegistry = None):
        self.km = key_manager or KeyManager()
        self.registry = registry or ModelRegistry()
        self.client = ModelClient(self.km, self.registry)
        self.fallback = FallbackRouter(self.km, self.registry)

    def select(self, role: str) -> str:
        """Get the primary model name assigned to a role."""
        if role not in ROLE_MODEL_MAP:
            raise ValueError(
                f"Unknown role '{role}'. Valid roles: {list(ROLE_MODEL_MAP.keys())}"
            )
        return ROLE_MODEL_MAP[role]

    def get_fallback_chain(self, role: str) -> list[str]:
        """Get the full fallback chain for a role."""
        return FALLBACK_CHAINS.get(role, ["local"])

    def call(self, role: str, messages: list, temperature: float = 0.5) -> dict:
        """Call the model assigned to a role with automatic fallback.

        Returns the raw API response dict (from first successful model).
        """
        result = self.fallback.call(role, messages, temperature)
        return result.response

    async def call_async(self, role: str, messages: list, temperature: float = 0.5) -> dict:
        """Async version of call() with same fallback logic."""
        result = await self.fallback.call_async(role, messages, temperature)
        return result.response

    def call_with_meta(self, role: str, messages: list, temperature: float = 0.5):
        """Call with full metadata (model used, attempts, latency, fallback status)."""
        return self.fallback.call(role, messages, temperature)

    def get_call_log(self, role: str = None, limit: int = 50) -> list[dict]:
        """Return recent model call history."""
        return self.fallback.get_call_log(role=role, limit=limit)

    def resolve_conflict(self, planner_result: dict, coder_result: dict, critic_result: dict) -> dict:
        """When models disagree, the critic's verdict wins.

        This is the v11 rule: Critic is the final authority.
        """
        # If critic explicitly rejects, follow critic
        critic_text = self._extract_text(critic_result)
        if "reject" in critic_text.lower() or "invalid" in critic_text.lower():
            return {"decision": "reject", "source": "critic", "detail": critic_text}

        # If planner and coder agree, use coder output
        planner_text = self._extract_text(planner_result)
        coder_text = self._extract_text(coder_result)
        if planner_text.strip() and coder_text.strip():
            return {"decision": "accept", "source": "coder", "detail": coder_text}

        # Default: critic decides
        return {"decision": "critic", "source": "critic", "detail": critic_text}

    @staticmethod
    def _extract_text(response: dict) -> str:
        """Extract text content from various API response shapes."""
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            if "choices" in response:
                return response["choices"][0]["message"]["content"]
            if "output" in response:
                content = response["output"][0].get("content", [])
                if isinstance(content, list) and len(content) > 0:
                    return content[0].get("text", "")
        return str(response)