"""
Tool Registry — all tools for the agent, with workspace isolation.

Each tool is a plain function. The registry maps tool names to functions.
All file operations are scoped to the workspace directory.
"""

import os
import subprocess
import fnmatch

# Workspace root — agent can only operate within this directory
WORKSPACE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workspace")
WORKSPACE = os.path.normpath(WORKSPACE)


def get_workspace() -> str:
    """Return the current workspace path."""
    return WORKSPACE


def set_workspace(path: str):
    """Change the workspace (use with caution)."""
    global WORKSPACE
    WORKSPACE = os.path.normpath(path)


def _resolve(path: str) -> str:
    """Resolve a path relative to workspace, preventing traversal attacks."""
    full = os.path.normpath(os.path.join(WORKSPACE, path))
    # Security: ensure the resolved path is inside workspace
    if not full.startswith(WORKSPACE):
        raise ValueError(f"Path traversal blocked: {path}")
    return full


# ---- Tool Implementations ----

def read(path: str) -> str:
    """Read file contents."""
    full = _resolve(path)
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return f"ERROR: File not found — {path}"
    except PermissionError:
        return f"ERROR: Permission denied — {path}"
    except Exception as e:
        return f"ERROR: {e}"


def write(path: str, content: str) -> str:
    """Write content to a file."""
    full = _resolve(path)
    try:
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"ERROR: {e}"


def patch(path: str, old: str, new: str) -> str:
    """Apply a targeted string replacement."""
    full = _resolve(path)
    try:
        with open(full, "r", encoding="utf-8") as f:
            data = f.read()
        if old not in data:
            return f"ERROR: Old string not found in {path}"
        count = data.count(old)
        if count > 1:
            return f"WARNING: Old string found {count}x — patch ambiguous. Be more specific."
        data = data.replace(old, new, 1)
        with open(full, "w", encoding="utf-8") as f:
            f.write(data)
        return f"Patched {path} (1 occurrence replaced)"
    except Exception as e:
        return f"ERROR: {e}"


def search(query: str, directory: str = ".") -> str:
    """Search file contents for a string."""
    search_dir = _resolve(directory)
    results = []
    for root, dirs, files in os.walk(search_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
            "node_modules", "__pycache__", ".git", "venv", "memory_store"
        )]
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if query.lower() in line.lower():
                            rel = os.path.relpath(fpath, WORKSPACE)
                            results.append(f"{rel}:{i}: {line.strip()}")
                            if len(results) >= 50:
                                return "\n".join(results) + "\n... (truncated at 50 matches)"
            except Exception:
                continue
    return "\n".join(results) if results else f"No matches for '{query}'"


def search_files(pattern: str, directory: str = ".") -> str:
    """Search file names by glob pattern."""
    search_dir = _resolve(directory)
    matches = []
    for root, dirs, files in os.walk(search_dir):
        for name in files + dirs:
            if fnmatch.fnmatch(name, pattern):
                matches.append(os.path.relpath(os.path.join(root, name), WORKSPACE))
    return "\n".join(matches) if matches else f"No files matching '{pattern}'"


def list_dir(path: str = ".") -> str:
    """List directory contents with type indicators."""
    full = _resolve(path)
    try:
        entries = []
        for entry in sorted(os.listdir(full)):
            entry_path = os.path.join(full, entry)
            if os.path.isdir(entry_path):
                entries.append(f"  {entry}/")
            else:
                try:
                    size = os.path.getsize(entry_path)
                    entries.append(f"  {entry}  ({size}b)")
                except OSError:
                    entries.append(f"  {entry}")
        header = f"{path}/" if path != "." else "workspace/"
        return header + "\n" + "\n".join(entries) if entries else f"{header}(empty)"
    except FileNotFoundError:
        return f"ERROR: Directory not found — {path}"
    except Exception as e:
        return f"ERROR: {e}"


def list_dir_safe(path: str = None) -> str:
    """Safe list_dir that doesn't raise (for context building)."""
    try:
        return list_dir(path or ".")
    except Exception as e:
        return f"Cannot list directory: {e}"


def run(cmd: str, timeout: int = 30) -> str:
    """Execute a shell command in the workspace."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=WORKSPACE,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("STDERR: " + result.stderr) if output else result.stderr
        if not output:
            output = "(no output)"
        return output
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


def add_note(note: str) -> str:
    """Save a note to project memory."""
    from memory.memory import save_memory
    save_memory("note", {"action": "add_note", "args": {"note": note}}, note)
    return f"Note saved: {note[:80]}"


# ---- Registry ----

TOOLS = {
    "read": read,
    "write": write,
    "patch": patch,
    "search": search,
    "search_files": search_files,
    "list_dir": list_dir,
    "run": run,
    "add_note": add_note,
}


def execute_tool_action(tool_name: str, args: dict):
    """Execute a tool by name with the given args."""
    if tool_name not in TOOLS:
        return f"ERROR: Unknown tool '{tool_name}'. Available: {list(TOOLS.keys())}"
    try:
        return TOOLS[tool_name](**args)
    except TypeError as e:
        return f"ERROR: Bad arguments for '{tool_name}': {e}"
    except Exception as e:
        return f"ERROR: Tool '{tool_name}' failed: {e}"