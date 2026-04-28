import asyncio
import inspect
from engine.errors import HookError


class HookSystem:
    def __init__(self, event_bus=None):
        self._hooks = {}
        self._event_bus = event_bus

    def register(self, event_name, callback, priority=100):
        if event_name not in self._hooks:
            self._hooks[event_name] = []
        entry = {"callback": callback, "priority": priority}
        self._hooks[event_name].append(entry)
        self._hooks[event_name].sort(key=lambda h: h["priority"])

        if self._event_bus:
            self._event_bus.on(event_name, lambda e, d: self._execute(event_name, d))

    def unregister(self, event_name, callback=None):
        if event_name not in self._hooks:
            return
        if callback is None:
            del self._hooks[event_name]
        else:
            self._hooks[event_name] = [
                h for h in self._hooks[event_name] if h["callback"] != callback
            ]

    def _execute(self, event_name, data):
        hooks = self._hooks.get(event_name, [])
        for entry in hooks:
            try:
                result = entry["callback"](event_name, data)
                if inspect.isawaitable(result):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(result)
                    except RuntimeError:
                        asyncio.run(result)
            except Exception as e:
                raise HookError(
                    f"hook failed on '{event_name}': {e}",
                    event_name=event_name,
                    hook=entry["callback"].__name__,
                ) from e

    def list_hooks(self, event_name=None):
        if event_name:
            return [
                {"callback": h["callback"].__name__, "priority": h["priority"]}
                for h in self._hooks.get(event_name, [])
            ]
        return {
            k: [{"callback": h["callback"].__name__, "priority": h["priority"]} for h in v]
            for k, v in self._hooks.items()
        }

    def stats(self):
        return {
            "total_hooks": sum(len(v) for v in self._hooks.values()),
            "events_with_hooks": len(self._hooks),
            "events": {k: len(v) for k, v in self._hooks.items()},
        }
