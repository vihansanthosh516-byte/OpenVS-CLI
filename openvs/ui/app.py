"""
OpenVS CLI — Main Terminal Application.

Built on Textual. This is the primary user-facing interface.
Layout: header bar | main workspace + side panel | input bar
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
import os
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Static, Input, RichLog
from textual.reactive import reactive
from textual import work

from openvs.core.app_state import app_state, AppMode, SystemStatus, AgentState
from openvs.core.commands import handle_command
from openvs.core.runtime import run_prompt
from openvs.core.session import save_session, load_session, has_session, session_age_hours
from openvs.core.updater import startup_check
from openvs.ui.components.command_palette import CommandPaletteScreen


class StatusBar(Static):
    """Top system status bar showing model, swarm, workers, session."""

    def __init__(self):
        super().__init__("", id="status-bar")

    def on_mount(self):
        self.update_text()

    def update_text(self):
        from datetime import datetime
        now = datetime.now().strftime("%I:%M %p")
        status_icons = {
            SystemStatus.IDLE: "[dim]idle[/]",
            SystemStatus.THINKING: "[yellow]thinking[/]",
            SystemStatus.PLANNING: "[cyan]planning[/]",
            SystemStatus.EXECUTING: "[green]executing[/]",
            SystemStatus.STREAMING: "[bright_blue]streaming[/]",
            SystemStatus.DIFF_VIEW: "[yellow]diff[/]",
            SystemStatus.ERROR: "[red]error[/]",
        }
        swarm_state = "[green]ON[/]" if app_state.swarm.enabled else "[dim]OFF[/]"
        status_text = status_icons.get(app_state.system_status, "?")
        self.update(
            f" [bold cyan]OpenVS CLI[/] v1.0  "
            f"│ [dim]model:[/] [bold]{app_state.model}[/]  "
            f"│ [dim]swarm:[/] {swarm_state}  "
            f"│ [dim]workers:[/] {app_state.worker_count}  "
            f"│ [dim]mode:[/] {app_state.mode.value}  "
            f"│ {status_text}  "
            f"│ [dim]{now}[/]"
        )


class ModeSidebar(Static):
    """Left sidebar showing mode selector."""

    MODES = ["chat", "diff", "swarm", "trace", "jobs"]

    def __init__(self):
        super().__init__("", id="mode-sidebar")

    def on_mount(self):
        self.render_modes()

    def render_modes(self):
        lines = []
        for mode in self.MODES:
            is_active = mode == app_state.mode.value
            if is_active:
                lines.append(f" [bold green]▸ {mode}[/]")
            else:
                lines.append(f" [dim]  {mode}[/]")
        self.update("\n".join(lines))


class SwarmPanel(Static):
    """Right panel showing swarm agent graph."""

    def __init__(self):
        super().__init__("", id="swarm-panel")

    def on_mount(self):
        self.render_graph()

    def render_graph(self):
        if not app_state.swarm.enabled:
            self.update(" [dim]Swarm: OFF[/]")
            return

        state_icons = {
            AgentState.IDLE: "[dim]○[/]",
            AgentState.RUNNING: "[yellow]●[/]",
            AgentState.SUCCESS: "[green]●[/]",
            AgentState.FAILED: "[red]●[/]",
        }

        lines = [" [bold]Swarm Graph[/]", ""]
        for agent in app_state.swarm.agents:
            icon = state_icons.get(agent.state, "?")
            task = f" — {agent.current_task[:25]}" if agent.current_task and agent.state == AgentState.RUNNING else ""
            lines.append(f" {icon} {agent.name}{task}")

        lines.extend([
            "",
            f" [dim]DAGs: {app_state.swarm.active_dags}[/]",
            f" [dim]Mode: {app_state.swarm.mode}[/]",
        ])
        self.update("\n".join(lines))


class MainWorkspace(RichLog):
    """Center panel — streaming output, diffs, traces, job list."""

    def __init__(self):
        super().__init__(id="workspace", highlight=True, markup=True)
        self.auto_scroll = True


class InputBar(Input):
    """Bottom input bar for prompts and commands."""

    def __init__(self):
        super().__init__(
            placeholder="> Ask anything... (/help for commands)",
            id="input-bar",
        )


class OpenVSApp(App):
    """OpenVS CLI — AI Operating System Terminal."""

    TITLE = "OpenVS CLI"
    CSS = """
    Screen {
        layout: vertical;
    }

    #status-bar {
        dock: top;
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }

    #main-container {
        height: 1fr;
    }

    #mode-sidebar {
        width: 12;
        background: $surface;
        color: $text;
        padding: 1;
        border-right: solid $primary;
    }

    #workspace {
        height: 1fr;
        background: $surface;
        color: $text;
        padding: 0 1;
    }

    #swarm-panel {
        width: 28;
        background: $surface;
        color: $text;
        padding: 1;
        border-left: solid $primary;
    }

    #input-bar {
        dock: bottom;
        height: 3;
        background: $surface;
        border-top: solid $primary;
    }
    """

    BINDINGS = [
        Binding("tab", "cycle_mode", "Cycle mode", show=False),
        Binding("ctrl+m", "model_select", "Model selector", show=False),
        Binding("ctrl+p", "command_palette", "Commands", show=False),
        Binding("ctrl+s", "toggle_swarm", "Toggle swarm", show=False),
        Binding("ctrl+l", "clear_chat", "Clear chat", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield StatusBar()
        with Horizontal(id="main-container"):
            yield ModeSidebar()
            yield MainWorkspace()
            yield SwarmPanel()
        yield InputBar()

    def on_mount(self):
        workspace = self.query_one("#workspace", MainWorkspace)

        # Check first-run onboarding
        from openvs.core.onboarding import is_onboarded, get_onboarding_steps
        if not is_onboarded():
            steps = get_onboarding_steps()
            workspace.write("[bold cyan]OpenVS CLI v1.0[/] — AI Operating System Terminal")
            workspace.write("")
            workspace.write("[bold yellow]First Run Setup[/]")
            workspace.write("")
            for step in steps:
                if step.get("action"):
                    workspace.write(f"[bold]{step['title']}[/]")
                    workspace.write(step["message"])
                    workspace.write("")
                    break  # show only first actionable step
                else:
                    workspace.write(step.get("message", ""))

            from openvs.core.onboarding import mark_onboarded
            mark_onboarded()
            workspace.write("[dim]Run /doctor to check system health. Type /help for all commands.[/]")
        else:
            workspace.write("[bold cyan]OpenVS CLI v1.0[/] — AI Operating System Terminal")

            # Session restore notification
            if has_session():
                session = load_session()
                age = session_age_hours()
                if session and age is not None and age < 24:
                    msg_count = len(session.get("messages", []))
                    model = session.get("model", "qwen")
                    workspace.write(f"[dim]Previous session found ({msg_count} msgs, {model}, {age:.1f}h ago). Run /session load to restore.[/]")

            workspace.write("[dim]Type a prompt or /help for commands. TAB to switch modes. Ctrl+P for palette.[/]")

        workspace.write("")

        # Silent update check on startup
        try:
            update_info = startup_check()
            if update_info:
                workspace.write(f"[yellow]Update available: v{update_info['latest']} (current v{update_info['current']}). Run /update[/]")
        except Exception:
            pass

        # Subscribe to state changes
        app_state.on_change(self._on_state_change)

    def _on_state_change(self, key: str, value):
        """React to state changes by updating UI components."""
        try:
            if key == "stream_token":
                # Don't re-render on every token — too expensive
                pass
            elif key in ("mode", "status", "model", "swarm_enabled"):
                self._refresh_status_bar()
                self._refresh_sidebar()
                self._refresh_swarm_panel()
            elif key.startswith("agent_"):
                self._refresh_swarm_panel()
            elif key == "message":
                msg = value
                workspace = self.query_one("#workspace", MainWorkspace)
                if msg.role == "user":
                    workspace.write(f"[bold green]> {msg.content}[/]")
                elif msg.role == "assistant":
                    workspace.write(f"[cyan]{msg.content}[/]")
                elif msg.role == "system":
                    workspace.write(f"[dim]{msg.content}[/]")
                elif msg.role == "error":
                    workspace.write(f"[red]{msg.content}[/]")
        except Exception:
            pass

    def _refresh_status_bar(self):
        try:
            bar = self.query_one("#status-bar", StatusBar)
            bar.update_text()
        except Exception:
            pass

    def _refresh_sidebar(self):
        try:
            sidebar = self.query_one("#mode-sidebar", ModeSidebar)
            sidebar.render_modes()
        except Exception:
            pass

    def _refresh_swarm_panel(self):
        try:
            panel = self.query_one("#swarm-panel", SwarmPanel)
            panel.render_graph()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted):
        """Handle user input — either command or prompt."""
        text = event.value.strip()
        if not text:
            return

        input_bar = self.query_one("#input-bar", InputBar)
        input_bar.value = ""

        if text.startswith("/"):
            result = handle_command(text)
            workspace = self.query_one("#workspace", MainWorkspace)
            workspace.write(f"[dim]$ {text}[/]")
            workspace.write(f"{result}")
            workspace.write("")
            self._refresh_status_bar()
            self._refresh_sidebar()
            return

        # Natural language prompt — run through engine
        self._run_prompt(text)

    @work(exclusive=True)
    async def _run_prompt(self, prompt: str):
        """Execute a prompt with streaming output."""
        workspace = self.query_one("#workspace", MainWorkspace)
        workspace.write(f"[bold green]> {prompt}[/]")

        # Show thinking state
        self._refresh_status_bar()
        self._refresh_swarm_panel()

        stream_text = ""
        async for token in run_prompt(prompt):
            stream_text += token

        # Write final result
        workspace.write(f"[cyan]{stream_text}[/]")
        workspace.write("")

        self._refresh_status_bar()
        self._refresh_sidebar()
        self._refresh_swarm_panel()

    # ---- Key bindings ----

    def action_cycle_mode(self):
        next_mode = app_state.mode_cycle()
        workspace = self.query_one("#workspace", MainWorkspace)
        workspace.write(f"[dim]Mode: {next_mode.value}[/]")
        self._refresh_sidebar()

    def action_model_select(self):
        models = ["qwen", "nemotron", "gemma", "glm", "local"]
        current = app_state.model
        idx = models.index(current) if current in models else 0
        next_idx = (idx + 1) % len(models)
        app_state.set_model(models[next_idx])
        workspace = self.query_one("#workspace", MainWorkspace)
        workspace.write(f"[dim]Model → {models[next_idx]}[/]")
        self._refresh_status_bar()

    def action_command_palette(self):
        self.push_screen(CommandPaletteScreen(), self._on_palette_result)

    def _on_palette_result(self, action: str | None):
        """Handle command palette selection."""
        if action is None:
            return

        workspace = self.query_one("#workspace", MainWorkspace)

        # Internal actions (prefixed with __)
        if action.startswith("__"):
            self._execute_internal_action(action)
            return

        # Slash commands
        if action.startswith("/"):
            result = handle_command(action)
            workspace.write(f"[dim]$ {action}[/]")
            workspace.write(f"{result}")
            workspace.write("")
            self._refresh_status_bar()
            self._refresh_sidebar()
            return

        # Default: just run it as a command
        workspace.write(f"[dim]$ {action}[/]")
        workspace.write(handle_command(action))
        workspace.write("")

    def _execute_internal_action(self, action: str):
        """Handle internal palette actions (prefixed with __)."""
        workspace = self.query_one("#workspace", MainWorkspace)

        if action == "__switch_diff":
            app_state.set_mode(AppMode.DIFF)
            workspace.write("[dim]Mode → diff[/]")
            self._refresh_sidebar()
        elif action == "__switch_swarm":
            app_state.set_mode(AppMode.SWARM)
            workspace.write("[dim]Mode → swarm[/]")
            self._refresh_sidebar()
        elif action == "__run_tests":
            workspace.write("[dim]Running tests...[/]")
            try:
                import subprocess
                result = subprocess.run(
                    ["python", "-m", "pytest", "tests/", "-v", "--tb=short"],
                    capture_output=True, text=True, timeout=60, cwd=os.path.join(os.path.dirname(__file__), "..", "..")
                )
                workspace.write(result.stdout[-2000:] if result.stdout else result.stderr[-2000:])
            except Exception as e:
                workspace.write(f"[red]Test runner error: {e}[/]")
        elif action == "__search":
            workspace.write("[dim]File search: use /status or your system grep[/]")
        elif action.startswith("__ai_"):
            ai_actions = {
                "__ai_explain_trace": "Analyzing latest trace... (connect a model to enable AI analysis)",
                "__ai_optimize_routing": "Optimizing worker routing... (connect a model to enable)",
                "__ai_review_patch": "Reviewing current patch... (connect a model to enable)",
                "__ai_suggest_fix": "Suggesting fix... (connect a model to enable)",
            }
            msg = ai_actions.get(action, "Unknown AI action")
            workspace.write(f"[bright_magenta]{msg}[/]")
        elif action == "__force_rollback":
            workspace.write("[bright_red]Power: Force rollback requires confirmation. Use /trace last first.[/]")
        elif action == "__dump_events":
            workspace.write("[dim]Power: Dumping event bus...[/]")
            try:
                from core.event_bus import bus
                stats = bus.store_stats()
                workspace.write(str(stats))
            except Exception as e:
                workspace.write(f"[red]Error: {e}[/]")
        elif action == "__show_fallback":
            workspace.write("[dim]Power: Model fallback chains:[/]")
            try:
                from core.model_fallback import ModelFallback
                fb = ModelFallback()
                workspace.write(str(fb.list_chains()))
            except Exception as e:
                workspace.write(f"[yellow]Fallback info: {e}[/]")
        elif action == "__benchmark":
            workspace.write("[dim]Power: Benchmark requires running models. Use /status to check model health.[/]")
        else:
            workspace.write(f"[dim]Action: {action}[/]")

    def action_toggle_swarm(self):
        app_state.set_swarm_enabled(not app_state.swarm.enabled)
        state = "ON" if app_state.swarm.enabled else "OFF"
        workspace = self.query_one("#workspace", MainWorkspace)
        workspace.write(f"[dim]Swarm: {state}[/]")
        self._refresh_status_bar()
        self._refresh_swarm_panel()

    def action_clear_chat(self):
        app_state.messages.clear()
        workspace = self.query_one("#workspace", MainWorkspace)
        workspace.clear()
        workspace.write("[dim]Chat cleared.[/]")

    def on_exit(self) -> None:
        """Save session on exit."""
        try:
            save_session({
                "model": app_state.model,
                "mode": app_state.mode.value,
                "swarm_enabled": app_state.swarm.enabled,
                "swarm_mode": app_state.swarm.mode,
                "worker_count": app_state.worker_count,
                "messages": [{"role": m.role, "content": m.content} for m in app_state.messages],
                "command_history": [],
            })
        except Exception:
            pass
