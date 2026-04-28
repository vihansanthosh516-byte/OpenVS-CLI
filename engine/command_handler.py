from engine.commands.registry import registry
from engine.commands.builtin import register_default_commands

register_default_commands()


def handle_command(command, orchestrator):
    return registry.execute(command, orchestrator)
