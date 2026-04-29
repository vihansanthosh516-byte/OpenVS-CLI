import json
import os
import time
import urllib.request
import urllib.error

try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    load_dotenv(dotenv_path=_env_path)
except ImportError:
    pass


MODELS = {
    "qwen": {
        "provider": "nvidia",
        "model_id": "qwen/qwen3-coder-480b-a35b-instruct",
        "role": "coder",
        "max_tokens": 8192,
    },
    "deepseek": {
        "provider": "nvidia",
        "model_id": "deepseek-ai/deepseek-v4-pro",
        "role": "reasoner",
        "max_tokens": 8192,
    },
    "deepseek-flash": {
        "provider": "nvidia",
        "model_id": "deepseek-ai/deepseek-v4-flash",
        "role": "fast",
        "max_tokens": 4096,
    },
    "glm": {
        "provider": "nvidia",
        "model_id": "z-ai/glm-5.1",
        "role": "fast",
        "max_tokens": 4096,
    },
    "gemma": {
        "provider": "nvidia",
        "model_id": "google/gemma-4-31b-it",
        "role": "vision",
        "max_tokens": 4096,
    },
    "gpt-oss": {
        "provider": "nvidia",
        "model_id": "openai/gpt-oss-120b",
        "role": "general",
        "max_tokens": 8192,
    },
    "nemotron": {
        "provider": "nvidia",
        "model_id": "nvidia/nemotron-3-super-120b-a12b",
        "role": "planner",
        "max_tokens": 8192,
    },
    "local": {
        "provider": "local",
        "model_id": "local-model",
        "role": "fallback",
        "max_tokens": 4096,
    },
}

PROVIDER_URLS = {
    "nvidia": os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
    "openai": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    "local": os.getenv("LOCAL_API_URL", "http://127.0.0.1:3001/v1"),
}

_config_dir = os.getenv("OPENVS_CONFIG_DIR", os.path.join(os.path.expanduser("~"), ".openvs"))
_config_path = os.path.join(_config_dir, "config.json")


def _load_api_keys():
    keys = {}
    for provider in PROVIDER_URLS:
        env_key = f"{provider.upper()}_API_KEY"
        env_val = os.getenv(env_key, "")
        if env_val:
            keys[provider] = env_val

    try:
        with open(_config_path, "r") as f:
            cfg = json.load(f)
        stored = cfg.get("api_keys", {})
        for provider, key in stored.items():
            if key and provider not in keys:
                keys[provider] = key
    except Exception:
        pass

    return keys


PROVIDER_KEYS = _load_api_keys()


def reload_keys():
    global PROVIDER_KEYS
    PROVIDER_KEYS = _load_api_keys()


class ModelClient:
    def __init__(self):
        self.available = self._check_connectivity()
        self._last_error = None

    def call(self, model_name, messages, temperature=0.5, max_tokens=None):
        if model_name not in MODELS:
            return {"error": f"unknown model: {model_name}", "available": list(MODELS.keys())}

        config = MODELS[model_name]
        provider = config["provider"]
        key = PROVIDER_KEYS.get(provider, "")
        base_url = PROVIDER_URLS.get(provider, "")

        if not key and provider != "local":
            self._last_error = f"no API key for {provider}"
            return {
                "error": self._last_error,
                "stub": True,
                "model": model_name,
                "provider": provider,
                "fix": f"run: /config set-key {provider} <your-key>",
            }

        url = f"{base_url}/chat/completions"
        model_id = config["model_id"]
        tokens = max_tokens or config.get("max_tokens", 4096)

        body = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": tokens,
        }

        req_start = time.time()
        try:
            data = json.dumps(body).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
            }
            if key:
                headers["Authorization"] = f"Bearer {key}"

            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                response_body = resp.read().decode("utf-8")
                result = json.loads(response_body)

            elapsed = time.time() - req_start
            return self._parse_response(result, model_name, elapsed)

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")[:500]
            except Exception:
                pass
            self._last_error = f"HTTP {e.code}: {error_body}"
            return {"error": self._last_error, "model": model_name, "provider": provider}

        except urllib.error.URLError as e:
            self._last_error = f"network error: {str(e)[:200]}"
            return {"error": self._last_error, "model": model_name, "provider": provider}

        except Exception as e:
            self._last_error = f"request failed: {str(e)[:200]}"
            return {"error": self._last_error, "model": model_name, "provider": provider}

    def call_stream(self, model_name, messages, temperature=0.5, max_tokens=None):
        config = MODELS.get(model_name)
        if not config:
            return {"error": f"unknown model: {model_name}"}

        provider = config["provider"]
        key = PROVIDER_KEYS.get(provider, "")
        base_url = PROVIDER_URLS.get(provider, "")

        if not key and provider != "local":
            return {"error": f"no API key for {provider}", "stub": True}

        url = f"{base_url}/chat/completions"
        model_id = config["model_id"]
        tokens = max_tokens or config.get("max_tokens", 4096)

        body = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": tokens,
            "stream": True,
        }

        try:
            data = json.dumps(body).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
            }
            if key:
                headers["Authorization"] = f"Bearer {key}"

            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            resp = urllib.request.urlopen(req, timeout=120)

            tokens_yielded = []
            for line in resp:
                line = line.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token_text = delta.get("content", "")
                    if token_text:
                        tokens_yielded.append(token_text)
                except json.JSONDecodeError:
                    continue

            full_text = "".join(tokens_yielded)
            return {
                "choices": [{"message": {"content": full_text}}],
                "model": model_name,
                "streamed": True,
                "tokens": len(tokens_yielded),
            }

        except Exception as e:
            return {"error": f"stream failed: {str(e)[:200]}", "model": model_name}

    def _parse_response(self, result, model_name, elapsed):
        content = self._extract_content(result)
        usage = result.get("usage", {})

        return {
            "choices": result.get("choices", []),
            "model": result.get("model", model_name),
            "content": content,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "elapsed_s": round(elapsed, 3),
        }

    @staticmethod
    def _extract_content(response):
        if "choices" in response:
            try:
                return response["choices"][0]["message"]["content"]
            except (KeyError, IndexError):
                pass
        if "output" in response:
            try:
                content = response["output"][0].get("content", [])
                if isinstance(content, list) and content:
                    return content[0].get("text", "")
            except (KeyError, IndexError, TypeError):
                pass
        return None

    def list_models(self):
        return list(MODELS.keys())

    def model_info(self, model_name):
        info = MODELS.get(model_name)
        if not info:
            return None
        provider = info["provider"]
        key_available = bool(PROVIDER_KEYS.get(provider, ""))
        return {
            **info,
            "key_configured": key_available,
        }

    def all_models_info(self):
        return {name: self.model_info(name) for name in MODELS}

    def _check_connectivity(self):
        return any(PROVIDER_KEYS.get(p, "") for p in PROVIDER_KEYS)

    @property
    def last_error(self):
        return self._last_error
