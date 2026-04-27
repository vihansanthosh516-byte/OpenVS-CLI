"""
Key Manager — secure central registry for API keys and endpoints.

Loads from .env file at project root. No keys are hardcoded.
"""

import os
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    # Load from project root explicitly
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=_env_path)
except ImportError:
    pass  # dotenv is optional; env vars still work


class KeyManager:
    """Central registry for API keys and base URLs.

    Access:
        km = KeyManager()
        key = km.get_key("nvidia")
        url = km.get_url("nvidia")
    """

    def __init__(self):
        self._keys = {
            "nvidia":  os.getenv("NVIDIA_API_KEY", ""),
            "openai":  os.getenv("OPENAI_API_KEY", ""),
            "local":   os.getenv("LOCAL_API_KEY", ""),
        }
        self._urls = {
            "nvidia":  os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            "openai":  os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "local":   os.getenv("LOCAL_API_URL", "http://127.0.0.1:3001/v1"),
        }

    def get_key(self, provider: str) -> Optional[str]:
        """Get the API key for a provider."""
        return self._keys.get(provider)

    def get_url(self, provider: str) -> Optional[str]:
        """Get the base URL for a provider."""
        return self._urls.get(provider)

    def has_key(self, provider: str) -> bool:
        """Check if a provider has a non-empty API key configured."""
        key = self._keys.get(provider, "")
        return bool(key and key.strip())

    def list_providers(self) -> list[str]:
        """List all configured providers."""
        return list(self._keys.keys())

    def list_configured(self) -> list[str]:
        """List only providers that have API keys set."""
        return [p for p in self._keys if self.has_key(p)]

    def status(self) -> dict:
        """Return a summary of which providers are configured (keys masked)."""
        return {
            provider: {
                "has_key": self.has_key(provider),
                "key_prefix": (key[:4] + "..." if key and len(key) > 4 else "not set"),
                "url": url,
            }
            for provider, (key, url) in zip(
                self._keys,
                zip(self._keys.values(), self._urls.values()),
            )
        }