"""
HTTP API Server — openvs serve

Exposes OpenVS engine as an HTTP/WebSocket API for external integrations.
Endpoints:
  POST /run          — Execute a prompt
  GET  /status       — System status
  GET  /plugins      — List plugins
  POST /hooks/emit   — Fire a hook
  WS   /ws/stream    — WebSocket streaming
"""

import json
import time
from typing import Optional


class OpenVSAPIApp:
    """FastAPI application for OpenVS HTTP API."""

    def __init__(self):
        self._routes = {}
        self._started_at: Optional[float] = None

    def create_app(self):
        """Create and configure the FastAPI app."""
        try:
            from fastapi import FastAPI
            from fastapi.responses import JSONResponse
        except ImportError:
            return None

        app = FastAPI(title="OpenVS API", version="1.0.0")
        self._started_at = time.time()

        @app.get("/status")
        async def get_status():
            from openvs.core.runtime import get_system_stats
            return get_system_stats()

        @app.post("/run")
        async def run_prompt(body: dict):
            prompt = body.get("prompt", "")
            if not prompt:
                return JSONResponse({"error": "prompt required"}, status_code=400)
            # Would normally call runtime.run_prompt
            return {"status": "queued", "prompt": prompt}

        @app.get("/plugins")
        async def list_plugins():
            try:
                from openvs.plugins.runtime import plugin_runtime
                if not plugin_runtime._loaded:
                    plugin_runtime.load()
                return {"plugins": plugin_runtime.list_plugins()}
            except Exception as e:
                return {"plugins": [], "error": str(e)}

        @app.post("/hooks/emit")
        async def emit_hook(body: dict):
            hook = body.get("hook", "")
            payload = body.get("payload", {})
            try:
                from openvs.plugins.runtime import plugin_runtime
                if not plugin_runtime._loaded:
                    plugin_runtime.load()
                result = plugin_runtime.emit_hook(hook, payload)
                return result
            except Exception as e:
                return {"error": str(e)}

        @app.get("/metrics")
        async def get_metrics():
            from openvs.observability.metrics import metrics
            return metrics.snapshot()

        @app.get("/health")
        async def health():
            return {"status": "ok", "uptime": time.time() - (self._started_at or time.time())}

        return app

    def run(self, host: str = "0.0.0.0", port: int = 8420):
        """Start the API server."""
        app = self.create_app()
        if app is None:
            print("Error: fastapi not installed. Run: pip install fastapi uvicorn")
            return

        try:
            import uvicorn
            uvicorn.run(app, host=host, port=port)
        except ImportError:
            print("Error: uvicorn not installed. Run: pip install uvicorn")


def create_app():
    """Create the FastAPI app (for use with uvicorn externally)."""
    api = OpenVSAPIApp()
    return api.create_app()