import os

try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    load_dotenv(dotenv_path=_env_path)
except ImportError:
    pass


MODELS = {
    "qwen": {"provider": "nvidia", "model_id": "qwen3.5-122b-a10b", "role": "coder", "max_tokens": 8192},
    "nemotron": {"provider": "nvidia", "model_id": "nvidia/nemotron-3-super-120b-a12b", "role": "planner", "max_tokens": 8192},
    "glm": {"provider": "nvidia", "model_id": "glm-4.7", "role": "fast", "max_tokens": 4096},
    "gemma": {"provider": "nvidia", "model_id": "gemma-4-31b-it", "role": "vision", "max_tokens": 4096},
    "local": {"provider": "local", "model_id": "local-model", "role": "fallback", "max_tokens": 4096},
}

PROVIDER_URLS = {
    "nvidia": os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
    "openai": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    "local": os.getenv("LOCAL_API_URL", "http://127.0.0.1:3001/v1"),
}

PROVIDER_KEYS = {
    "nvidia": os.getenv("NVIDIA_API_KEY", ""),
    "openai": os.getenv("OPENAI_API_KEY", ""),
    "local": os.getenv("LOCAL_API_KEY", ""),
}


class ModelClient:
    def __init__(self):
        self.available = self._check_connectivity()

    def call(self, model_name, messages, temperature=0.5):
        if model_name not in MODELS:
            return {"error": f"unknown model: {model_name}"}

        config = MODELS[model_name]
        provider = config["provider"]
        key = PROVIDER_KEYS.get(provider, "")
        url = PROVIDER_URLS.get(provider, "")

        if not key and provider != "local":
            return {
                "error": f"no API key for {provider}",
                "stub": True,
                "model": model_name,
            }

        return {
            "stub": True,
            "model": model_name,
            "message": f"model_client stub: {model_name} call would go to {provider}",
        }

    def list_models(self):
        return list(MODELS.keys())

    def _check_connectivity(self):
        return any(PROVIDER_KEYS.get(p, "") for p in PROVIDER_KEYS)
