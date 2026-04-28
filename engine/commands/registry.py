from engine.errors import CommandError


class CommandRegistry:
    def __init__(self):
        self._commands = {}
        self._aliases = {}

    def register(self, name, handler, description="", aliases=None):
        if name in self._commands:
            raise CommandError(f"command already registered: {name}", command=name)

        entry = {
            "name": name,
            "handler": handler,
            "description": description,
            "aliases": aliases or [],
        }
        self._commands[name] = entry

        if aliases:
            for alias in aliases:
                self._aliases[alias] = name

    def unregister(self, name):
        if name in self._commands:
            for alias in self._commands[name].get("aliases", []):
                self._aliases.pop(alias, None)
            del self._commands[name]

    def resolve(self, input_string):
        if not input_string or not input_string.startswith("/"):
            return None

        parts = input_string.strip().split()
        cmd_name = parts[0].lower()
        cmd_args = parts[1:]

        if cmd_name in self._aliases:
            cmd_name = self._aliases[cmd_name]

        entry = self._commands.get(cmd_name)
        if not entry:
            return None

        return {
            "name": cmd_name,
            "handler": entry["handler"],
            "args": cmd_args,
            "description": entry["description"],
        }

    def execute(self, input_string, orchestrator):
        resolved = self.resolve(input_string)
        if not resolved:
            cmd_name = input_string.strip().split()[0].lower() if input_string.strip() else "unknown"
            return {
                "status": "error",
                "output": f"unknown command: {cmd_name}\nType /help for available commands.",
            }

        try:
            output = resolved["handler"](resolved["args"], orchestrator)
            return {"status": "ok", "output": output}
        except CommandError as e:
            return {"status": "error", "output": str(e)}
        except Exception as e:
            return {"status": "error", "output": f"command error: {e}"}

    def list_commands(self):
        return [
            {
                "name": entry["name"],
                "description": entry["description"],
                "aliases": entry["aliases"],
            }
            for entry in self._commands.values()
        ]

    def help_text(self):
        lines = ["Available Commands:"]
        for entry in self._commands.values():
            aliases = ""
            if entry["aliases"]:
                aliases = f" (aliases: {', '.join(entry['aliases'])})"
            lines.append(f"  {entry['name']:14s} {entry['description']}{aliases}")
        return "\n".join(lines)


registry = CommandRegistry()
