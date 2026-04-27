"""
Hot Reload Watcher — monitors plugin directory for changes.

When a plugin's files change, the watcher triggers a reload.
No restart needed. This is what makes OpenVS feel like a
modern dev tool (similar to VS Code extension development).

Uses a simple polling approach (watchdog optional).
Falls back gracefully if watchdog is not installed.
"""

import os
import time
import threading
from pathlib import Path
from typing import Optional, Callable


PLUGIN_DIR = Path.home() / ".openvs" / "plugins"

# Polling interval in seconds
POLL_INTERVAL = 2.0


class PluginWatcher:
    """Watches ~/.openvs/plugins/ for file changes and triggers reloads.

    Two modes:
    1. watchdog-based (if installed) — filesystem events
    2. Polling-based (fallback) — checks mtimes every 2s
    """

    def __init__(self, on_reload: Callable):
        self._on_reload = on_reload
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._observer = None
        self._file_mtimes: dict[str, float] = {}
        self._last_scan = 0.0

    def start(self):
        """Start watching for plugin changes."""
        if self._running:
            return

        # Try watchdog first
        if self._try_watchdog():
            return

        # Fallback to polling
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop watching."""
        self._running = False

        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:
                pass
            self._observer = None

        if self._thread:
            self._thread = None

    def _try_watchdog(self) -> bool:
        """Try to start watchdog-based watching. Returns True if successful."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class Handler(FileSystemEventHandler):
                def __init__(self, callback):
                    super().__init__()
                    self._callback = callback

                def on_modified(self, event):
                    if event.is_directory:
                        return
                    if event.src_path.endswith((".py", ".json")):
                        self._callback()

                def on_created(self, event):
                    if event.is_directory:
                        return
                    if event.src_path.endswith((".py", ".json")):
                        self._callback()

            self._observer = Observer()
            handler = Handler(self._on_reload)
            self._observer.schedule(handler, str(PLUGIN_DIR), recursive=True)
            self._observer.start()
            self._running = True
            return True

        except ImportError:
            return False

    def _poll_loop(self):
        """Polling fallback — checks file modification times."""
        self._scan_mtimes()

        while self._running:
            time.sleep(POLL_INTERVAL)
            try:
                if self._detect_changes():
                    self._on_reload()
                    self._scan_mtimes()
            except Exception:
                pass

    def _scan_mtimes(self):
        """Record current modification times of all plugin files."""
        self._file_mtimes.clear()

        if not PLUGIN_DIR.exists():
            return

        for plugin_dir in PLUGIN_DIR.iterdir():
            if not plugin_dir.is_dir():
                continue
            for f in plugin_dir.rglob("*"):
                if f.is_file() and f.suffix in (".py", ".json"):
                    try:
                        self._file_mtimes[str(f)] = f.stat().st_mtime
                    except Exception:
                        pass

    def _detect_changes(self) -> bool:
        """Check if any plugin files have changed since last scan."""
        if not PLUGIN_DIR.exists():
            return False

        for plugin_dir in PLUGIN_DIR.iterdir():
            if not plugin_dir.is_dir():
                continue
            for f in plugin_dir.rglob("*"):
                if f.is_file() and f.suffix in (".py", ".json"):
                    path_str = str(f)
                    try:
                        mtime = f.stat().st_mtime
                        if path_str not in self._file_mtimes:
                            return True  # new file
                        if mtime != self._file_mtimes[path_str]:
                            return True  # modified file
                    except Exception:
                        pass

        # Check for deleted files
        current_files = set()
        for plugin_dir in PLUGIN_DIR.iterdir():
            if not plugin_dir.is_dir():
                continue
            for f in plugin_dir.rglob("*"):
                if f.is_file() and f.suffix in (".py", ".json"):
                    current_files.add(str(f))

        if current_files != set(self._file_mtimes.keys()):
            return True  # files added or removed

        return False

    @property
    def is_running(self) -> bool:
        return self._running

    def stats(self) -> dict:
        return {
            "running": self._running,
            "mode": "watchdog" if self._observer else "polling",
            "watched_files": len(self._file_mtimes),
            "plugin_dir": str(PLUGIN_DIR),
        }
