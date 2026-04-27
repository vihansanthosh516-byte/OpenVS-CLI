"""
Unified Model Client — one interface for all model providers.

Handles API format differences, auth, and error recovery.
Both sync and async interfaces provided.
"""

import json
import requests
import httpx
from typing import Optional

from core.key_manager import KeyManager
from core.model_registry import ModelRegistry


class ModelClient:
    """Unified client for calling any registered model.

    Sync:  client.call_sync("nemotron", messages)
    Async: await client.call("nemotron", messages)
    """

    def __init__(self, key_manager: KeyManager = None, registry: ModelRegistry = None):
        self.km = key_manager or KeyManager()
        self.registry = registry or ModelRegistry()

    def call_sync(
        self,
        model_name: str,
        messages: list,
        temperature: float = 0.5,
        max_tokens: int = None,
    ) -> dict:
        """Synchronous model call. Returns raw API response dict."""
        config = self.registry.require(model_name)
        provider = config.provider
        url = self.km.get_url(provider)
        key = self.km.get_key(provider)

        if not url:
            return {"error": f"No URL configured for provider '{provider}'"}

        # Build request payload (OpenAI-compatible format)
        payload = {
            "model": config.model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or config.max_tokens,
            "stream": False,
        }

        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"

        # Route to appropriate endpoint
        endpoint = self._resolve_endpoint(url, provider)

        try:
            resp = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.ConnectionError:
            # Try local fallback
            if provider != "local":
                return self._try_local_fallback(messages, temperature)
            return {"error": f"Cannot reach model API at {endpoint}"}

        except requests.exceptions.HTTPError as e:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}

        except Exception as e:
            return {"error": f"Model call failed: {e}"}

    async def call(
        self,
        model_name: str,
        messages: list,
        temperature: float = 0.5,
        max_tokens: int = None,
    ) -> dict:
        """Async model call using httpx."""
        config = self.registry.require(model_name)
        provider = config.provider
        url = self.km.get_url(provider)
        key = self.km.get_key(provider)

        if not url:
            return {"error": f"No URL configured for provider '{provider}'"}

        payload = {
            "model": config.model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or config.max_tokens,
            "stream": False,
        }

        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"

        endpoint = self._resolve_endpoint(url, provider)

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(endpoint, headers=headers, json=payload)
                resp.raise_for_status()
                return resp.json()

        except httpx.ConnectError:
            if provider != "local":
                return self._try_local_fallback(messages, temperature)
            return {"error": f"Cannot reach model API at {endpoint}"}

        except Exception as e:
            return {"error": f"Async model call failed: {e}"}

    async def stream(
        self,
        model_name: str,
        messages: list,
        temperature: float = 0.5,
    ):
        """Async streaming model call. Yields token strings."""
        config = self.registry.require(model_name)
        provider = config.provider
        url = self.km.get_url(provider)
        key = self.km.get_key(provider)

        payload = {
            "model": config.model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": config.max_tokens,
            "stream": True,
        }

        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"

        endpoint = self._resolve_endpoint(url, provider)

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", endpoint, headers=headers, json=payload) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                token = delta.get("content", "")
                                if token:
                                    yield token
                            except json.JSONDecodeError:
                                pass
        except Exception as e:
            yield f"[ERROR: {e}]"

    def _try_local_fallback(self, messages: list, temperature: float) -> dict:
        """Fall back to local model if remote is unreachable."""
        local_url = self.km.get_url("local")
        if not local_url:
            return {"error": "No local fallback available"}

        # Try the local /v1/responses endpoint
        try:
            prompt = messages[-1]["content"] if messages else ""
            resp = requests.post(
                f"{local_url}/responses",
                json={"input": prompt},
                headers={"Content-Type": "application/json"},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            # Normalize to OpenAI format
            text = self._extract_text(data)
            return {
                "choices": [{
                    "message": {"role": "assistant", "content": text}
                }]
            }
        except Exception:
            return {"error": "Local fallback also failed"}

    @staticmethod
    def _resolve_endpoint(base_url: str, provider: str) -> str:
        """Build the full API endpoint URL."""
        base = base_url.rstrip("/")
        if provider == "local":
            # Local server uses /v1/responses
            return f"{base}/responses"
        # All other providers use OpenAI-compatible chat completions
        return f"{base}/chat/completions"

    @staticmethod
    def _extract_text(data: dict) -> str:
        """Extract text from various response shapes."""
        if isinstance(data, dict):
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
            if "output" in data:
                content = data["output"][0].get("content", [])
                if isinstance(content, list) and len(content) > 0:
                    return content[0].get("text", "")
        return str(data)