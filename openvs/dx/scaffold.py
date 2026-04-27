"""
Scaffold Generator — `openvs create plugin` scaffolding tool.

Generates a complete plugin directory structure:
  ~/.openvs/plugins/<name>/
  ├── plugin.json
  ├── index.py
  ├── commands.py
  ├── hooks.py
  └── tools.py
"""

import json
import time
from pathlib import Path


PLUGIN_DIR = Path.home() / ".openvs" / "plugins"

TEMPLATE_PLUGIN_JSON = """{
  "name": "{name}",
  "version": "1.0.0",
  "description": "{description}",
  "author": "{author}",
  "entry": "index.py",
  "commands": [
    {{
      "name": "/{cmd_name}",
      "description": "{cmd_description}",
      "handler": "handle_{cmd_name}"
    }}
  ],
  "hooks": ["after_run"],
  "tools": [],
  "permissions": []
}"""

TEMPLATE_INDEX_PY = '''"""{name} — {description}"""


def handle_{cmd_name}(args, ctx):
    """Handle the /{cmd_name} command."""
    ctx.send_message("{cmd_name} executed!")
    return {{"status": "ok"}}


def after_run(ctx, payload):
    """Hook: fires after every prompt execution."""
    pass  # Add your hook logic here
'''

TEMPLATE_COMMANDS_PY = '''"""{name} — additional command handlers."""

# Add more command handlers here.
# Each handler takes (args, ctx) and returns a dict.
'''

TEMPLATE_HOOKS_PY = '''"""{name} — hook handlers."""

# Available hooks:
# before_run, after_run, before_model_call, after_model_call,
# before_patch, after_patch, on_job_start, on_job_complete,
# on_worker_spawn, on_worker_fail, on_consensus_vote,
# on_diff_accept, on_diff_reject

# def before_run(ctx, payload):
#     ctx.send_message("About to execute...")
'''

TEMPLATE_TOOLS_PY = '''"""{name} — tool implementations."""

# Add tool implementations here.
# Tools are registered in plugin.json under "tools".
# Each tool takes (args, ctx) and returns a dict.
'''


class ScaffoldGenerator:
    """Generates plugin scaffold directories."""

    def create_plugin(self, name: str, description: str = "", author: str = "",
                      command_name: str = None, command_description: str = "") -> dict:
        """Create a new plugin scaffold."""
        cmd_name = command_name or name.replace("-", "_").replace(" ", "_")
        cmd_desc = command_description or f"Run {name} action"
        desc = description or f"{name} plugin for OpenVS"

        plugin_path = PLUGIN_DIR / name
        plugin_path.mkdir(parents=True, exist_ok=True)

        # Generate plugin.json
        manifest = TEMPLATE_PLUGIN_JSON.format(
            name=name, description=desc, author=author,
            cmd_name=cmd_name, cmd_description=cmd_desc,
        )
        (plugin_path / "plugin.json").write_text(manifest, encoding="utf-8")

        # Generate index.py
        index = TEMPLATE_INDEX_PY.format(
            name=name, description=desc,
            cmd_name=cmd_name,
        )
        (plugin_path / "index.py").write_text(index, encoding="utf-8")

        # Generate optional files
        (plugin_path / "commands.py").write_text(
            TEMPLATE_COMMANDS_PY.format(name=name), encoding="utf-8")
        (plugin_path / "hooks.py").write_text(
            TEMPLATE_HOOKS_PY.format(name=name), encoding="utf-8")
        (plugin_path / "tools.py").write_text(
            TEMPLATE_TOOLS_PY.format(name=name), encoding="utf-8")

        return {
            "status": "created",
            "plugin": name,
            "path": str(plugin_path),
            "files": ["plugin.json", "index.py", "commands.py", "hooks.py", "tools.py"],
        }


scaffold_generator = ScaffoldGenerator()
