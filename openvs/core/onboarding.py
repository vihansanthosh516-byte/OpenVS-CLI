"""
Onboarding — first-run experience for OpenVS CLI.

When a user runs `openvs` for the first time, we:
1. Detect if config exists
2. Guide them through provider selection
3. Save their API key
4. Validate connectivity
5. Show a welcome message
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


ONBOARDING_STATE_FILE = os.path.join(os.path.expanduser("~"), ".openvs", "onboarded")


def is_onboarded() -> bool:
    """Check if the user has completed onboarding."""
    return os.path.exists(ONBOARDING_STATE_FILE)


def mark_onboarded():
    """Mark onboarding as complete."""
    os.makedirs(os.path.dirname(ONBOARDING_STATE_FILE), exist_ok=True)
    with open(ONBOARDING_STATE_FILE, "w") as f:
        f.write("openvs_cli_onboarded=1\n")


def get_onboarding_steps() -> list[dict]:
    """Return the onboarding steps for the UI to display."""
    return [
        {
            "id": "welcome",
            "title": "Welcome to OpenVS CLI",
            "message": (
                "OpenVS is an AI operating system for software development.\n"
                "It uses multi-agent swarm orchestration to plan, code,\n"
                "review, and test — all from your terminal.\n\n"
                "Let's get you set up."
            ),
        },
        {
            "id": "provider",
            "title": "Configure Model Provider",
            "message": (
                "Choose your primary AI provider:\n\n"
                "  [1] NVIDIA NIM (nemotron, qwen, gemma)\n"
                "  [2] OpenAI (gpt-4, o1)\n"
                "  [3] Local Server (any OpenAI-compatible endpoint)\n"
                "  [4] Skip — configure later via .env\n\n"
                "Enter 1-4:"
            ),
            "action": "select_provider",
        },
        {
            "id": "apikey",
            "title": "Enter API Key",
            "message": "Enter your API key (or press Enter to skip):",
            "action": "enter_key",
        },
        {
            "id": "validate",
            "title": "Validate Connection",
            "message": "Testing connection to model provider...",
            "action": "validate",
        },
        {
            "id": "complete",
            "title": "Setup Complete",
            "message": (
                "OpenVS CLI is ready.\n\n"
                "Quick start:\n"
                "  Type any prompt to start coding\n"
                "  /help for available commands\n"
                "  TAB to switch modes\n"
                "  CTRL+M to switch models\n"
                "  /swarm on to enable multi-agent mode\n\n"
                "Run /doctor anytime to check system health."
            ),
        },
    ]


def process_provider_choice(choice: str) -> dict:
    """Process the user's provider selection."""
    providers = {
        "1": {"name": "nvidia", "env_key": "NVIDIA_API_KEY", "env_url": "NVIDIA_BASE_URL"},
        "2": {"name": "openai", "env_key": "OPENAI_API_KEY", "env_url": "OPENAI_BASE_URL"},
        "3": {"name": "local", "env_key": "LOCAL_API_KEY", "env_url": "LOCAL_API_URL"},
        "4": {"name": "skip"},
    }

    if choice.strip() in providers:
        return providers[choice.strip()]
    return {"name": "unknown", "error": f"Invalid choice: {choice}"}


def save_api_key(provider: str, key: str) -> dict:
    """Save an API key to the .env file."""
    if not key.strip():
        return {"status": "skipped", "message": "No key provided, skipped."}

    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    provider_keys = {
        "nvidia": ("NVIDIA_API_KEY", "NVIDIA_BASE_URL"),
        "openai": ("OPENAI_API_KEY", "OPENAI_BASE_URL"),
        "local": ("LOCAL_API_KEY", "LOCAL_API_URL"),
    }

    if provider not in provider_keys:
        return {"status": "error", "message": f"Unknown provider: {provider}"}

    key_name, url_name = provider_keys[provider]

    # Read existing .env or create new
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()

    # Update or add the key
    key_found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key_name}="):
            lines[i] = f"{key_name}={key}\n"
            key_found = True
            break
    if not key_found:
        lines.append(f"{key_name}={key}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)

    # Reload the key manager
    try:
        from core.key_manager import KeyManager
        KeyManager._instance = None  # force reload
    except Exception:
        pass

    return {"status": "ok", "message": f"Saved {key_name} to .env"}
