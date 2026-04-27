"""
Command Palette Overlay — Ctrl+P for OpenVS CLI.

A Textual modal screen that drops in center with:
- Fuzzy search input
- Categorized commands with badges
- Recent + Suggested sections
- Power mode (> prefix for admin commands)
- AI action suggestions
- Keyboard: ↑↓ navigate, Enter execute, Esc close, Tab autocomplete
"""

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.binding import Binding
from textual.widgets import Static, Input
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual import events

from openvs.core.command_palette import (
    get_all_commands,
    search_commands,
    get_suggestions,
    command_history,
    PaletteCategory,
)
from openvs.core.app_state import app_state


class PaletteItem(Static):
    """A single command row in the palette."""

    def __init__(self, label: str, category: str, badge: str = "", action: str = "", is_power: bool = False):
        super().__init__("", classes="palette-item")
        self.label_text = label
        self.category = category
        self.badge = badge
        self.action = action
        self.is_power = is_power
        self.highlighted = False

    def set_highlighted(self, val: bool):
        self.highlighted = val
        self._update_render()

    def _update_render(self):
        if self.highlighted:
            style = "bold white on $primary"
        else:
            style = "$text on $surface"

        badge_color = {
            "[Task]": "cyan",
            "[Model]": "magenta",
            "[Swarm]": "green",
            "[Debug]": "yellow",
            "[File]": "blue",
            "[AI]": "bright_magenta",
            "[Power]": "bright_red",
            "[Suggested]": "bright_green",
            "[Recent]": "dim",
        }.get(self.badge, "white")

        badge_str = f"[{badge_color}]{self.badge}[/]" if self.badge else ""
        text = f"  {badge_str:16s} {self.label_text}"
        self.update(f"[{style}]{text}[/]")


class CommandPaletteScreen(ModalScreen):
    """Modal command palette overlay — Ctrl+P."""

    CSS = """
    CommandPaletteScreen {
        align: center middle;
    }

    #palette-container {
        width: 72;
        max-height: 28;
        background: $surface;
        border: round $primary;
        padding: 0;
    }

    #palette-header {
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 2;
        content-align: center middle;
    }

    #palette-input {
        dock: top;
        height: 3;
        padding: 0 1;
    }

    #palette-input Input {
        width: 100%;
    }

    #palette-results {
        height: 1fr;
        padding: 0 1;
        scrollbar-size: 1 1;
    }

    #palette-footer {
        dock: bottom;
        height: 1;
        background: $surface-darken-1;
        color: $text-disabled;
        padding: 0 2;
        content-align: center middle;
    }

    .palette-item {
        height: 1;
        padding: 0 1;
    }

    .palette-category-header {
        height: 1;
        padding: 0 1;
        color: $primary;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("escape", "close_palette", "Close", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "execute_selected", "Execute", show=False),
        Binding("tab", "autocomplete", "Autocomplete", show=False),
    ]

    selected_index: reactive[int] = reactive(0)
    query: reactive[str] = reactive("")

    def __init__(self):
        super().__init__()
        self._items: list[dict] = []  # list of {label, category, badge, action, is_power}
        self._widget_items: list[PaletteItem] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-container"):
            yield Static("[bold] OPENVS COMMAND PALETTE [/]", id="palette-header")
            yield Input(
                placeholder="Type to search... (> for power commands)",
                id="palette-input",
            )
            yield VerticalScroll(id="palette-results")
            yield Static("↑↓ navigate  Enter select  Esc close  / commands  > power", id="palette-footer")

    def on_mount(self) -> None:
        self._build_results("")

    def on_input_changed(self, event: Input.Changed) -> None:
        """React to search input changes."""
        self.query = event.value
        self._build_results(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter on input — execute selected."""
        self.action_execute_selected()

    def on_key(self, event: events.Key) -> None:
        """Handle key events for navigation."""
        if event.key == "up":
            self.action_move_up()
            event.prevent_default()
        elif event.key == "down":
            self.action_move_down()
            event.prevent_default()

    def _build_results(self, query: str):
        """Build the filtered command list."""
        results = self._palette_results()

        scroll = self.query_one("#palette-results", VerticalScroll)
        # Remove old items
        for child in list(scroll.children):
            child.remove()

        self._items = []
        self._widget_items = []

        include_power = query.startswith(">")

        # Recent section (when no query)
        if not query:
            recent = command_history.as_palette_items(limit=3)
            if recent:
                header = Static("  Recent", classes="palette-category-header")
                scroll.mount(header)
                for item in recent:
                    self._add_item(scroll, item.label, "Recent", item.badge, item.action)

            # Context-aware suggestions
            suggestions = get_suggestions({"status": app_state.system_status.value})
            if suggestions:
                header = Static("  Suggested", classes="palette-category-header")
                scroll.mount(header)
                for item in suggestions:
                    self._add_item(scroll, item.label, item.category, item.badge, item.action, item.is_power)

        # Searched commands
        commands = search_commands(query, include_power=include_power) if query else get_all_commands()

        # Group by category
        categories_order = [
            PaletteCategory.RUNTIME,
            PaletteCategory.MODELS,
            PaletteCategory.SWARM,
            PaletteCategory.DEBUG,
            PaletteCategory.WORKSPACE,
            PaletteCategory.AI,
            PaletteCategory.POWER,
        ]

        groups: dict[str, list] = {}
        for cmd in commands:
            groups.setdefault(cmd.category, []).append(cmd)

        for cat in categories_order:
            if cat not in groups:
                continue
            header = Static(f"  {cat}", classes="palette-category-header")
            scroll.mount(header)
            for cmd in groups[cat]:
                self._add_item(scroll, cmd.label, cmd.category, cmd.badge, cmd.action, cmd.is_power)

        self.selected_index = 0
        self._highlight_selected()

    def _add_item(self, scroll, label, category, badge, action, is_power=False):
        item_data = {
            "label": label,
            "category": category,
            "badge": badge,
            "action": action,
            "is_power": is_power,
        }
        self._items.append(item_data)

        widget = PaletteItem(label, category, badge, action, is_power)
        scroll.mount(widget)
        self._widget_items.append(widget)

    def _highlight_selected(self):
        for i, widget in enumerate(self._widget_items):
            widget.set_highlighted(i == self.selected_index)

        # Scroll to selected
        if 0 <= self.selected_index < len(self._widget_items):
            self._widget_items[self.selected_index].scroll_visible()

    def _palette_results(self):
        return []

    def action_close_palette(self):
        self.dismiss(None)

    def action_move_up(self):
        if self.selected_index > 0:
            self.selected_index -= 1
            self._highlight_selected()

    def action_move_down(self):
        if self.selected_index < len(self._items) - 1:
            self.selected_index += 1
            self._highlight_selected()

    def action_execute_selected(self):
        if not self._items:
            return
        item = self._items[self.selected_index]
        action = item["action"]
        command_history.record(action)
        self.dismiss(action)

    def action_autocomplete(self):
        """Tab: fill the input with the selected item's action."""
        if self._items:
            item = self._items[self.selected_index]
            action = item["action"]
            if action.startswith("/"):
                input_widget = self.query_one("#palette-input", Input)
                input_widget.value = action + " "
                input_widget.cursor_at_end = True
