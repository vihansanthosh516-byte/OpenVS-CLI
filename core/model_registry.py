"""
Model Registry — single source of truth for all model definitions.

Every model in the system is defined here with its provider,
model ID, and role. Add new models in one place.
"""

from typing import Optional


class ModelConfig:
    """Configuration for a single model."""
    def __init__(self, name: str, provider: str, model_id: str, role: str = "", max_tokens: int = 4096):
        self.name = name
        self.provider = provider
        self.model_id = model_id
        self.role = role
        self.max_tokens = max_tokens

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "provider": self.provider,
            "model_id": self.model_id,
            "role": self.role,
            "max_tokens": self.max_tokens,
        }


class ModelRegistry:
    """Registry of all available models.

    Usage:
        reg = ModelRegistry()
        config = reg.get("nemotron")
        print(config.model_id)  # "nvidia/nemotron-3-super-120b-a12b"
    """

    def __init__(self):
        self._models: dict[str, ModelConfig] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register the default model set."""
        defaults = [
            ModelConfig("nemotron", "nvidia", "nvidia/nemotron-3-super-120b-a12b", "planner/critic", 8192),
            ModelConfig("qwen",     "nvidia", "qwen3.5-122b-a10b",               "coder",        8192),
            ModelConfig("glm",      "nvidia", "glm-4.7",                          "fast",         4096),
            ModelConfig("gemma",    "nvidia", "gemma-4-31b-it",                   "vision",       4096),
            # Local fallback
            ModelConfig("local",    "local",  "local-model",                      "fallback",     4096),
        ]
        for m in defaults:
            self._models[m.name] = m

    def register(self, config: ModelConfig):
        """Add or replace a model in the registry."""
        self._models[config.name] = config

    def get(self, model_name: str) -> Optional[ModelConfig]:
        """Get a model config by name. Returns None if not found."""
        return self._models.get(model_name)

    def require(self, model_name: str) -> ModelConfig:
        """Get a model config, raising if not found."""
        config = self._models.get(model_name)
        if not config:
            raise ValueError(
                f"Unknown model '{model_name}'. Available: {list(self._models.keys())}"
            )
        return config

    def list_models(self) -> list[str]:
        """List all registered model names."""
        return list(self._models.keys())

    def list_by_provider(self, provider: str) -> list[ModelConfig]:
        """List all models for a given provider."""
        return [m for m in self._models.values() if m.provider == provider]

    def list_by_role(self, role: str) -> list[ModelConfig]:
        """List all models assigned to a role."""
        return [m for m in self._models.values() if role in m.role]

    def to_dict(self) -> dict:
        """Export the full registry as a dict."""
        return {name: config.to_dict() for name, config in self._models.items()}