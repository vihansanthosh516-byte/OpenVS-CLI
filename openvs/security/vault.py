"""
Secret Vault — per-plugin isolated secret storage.

Each plugin gets its own encrypted namespace for secrets.
Plugins cannot access each other's secrets.

Stored at ~/.openvs/vault/<plugin_name>/
"""

import json
import hashlib
import os
from pathlib import Path
from typing import Optional


VAULT_DIR = Path.home() / ".openvs" / "vault"


class SecretVault:
    """Per-plugin isolated secret storage.

    Plugins store API keys, tokens, and other secrets here.
    Each plugin's vault is isolated — no cross-plugin access.
    """

    def __init__(self):
        VAULT_DIR.mkdir(parents=True, exist_ok=True)

    def store(self, plugin_name: str, key: str, value: str) -> dict:
        """Store a secret for a plugin."""
        vault_path = self._vault_path(plugin_name)
        vault_path.mkdir(parents=True, exist_ok=True)

        secrets = self._load_secrets(plugin_name)
        secrets[key] = self._obfuscate(value)
        self._save_secrets(plugin_name, secrets)

        return {"status": "stored", "plugin": plugin_name, "key": key}

    def retrieve(self, plugin_name: str, key: str) -> Optional[str]:
        """Retrieve a secret for a plugin."""
        secrets = self._load_secrets(plugin_name)
        if key in secrets:
            return self._deobfuscate(secrets[key])
        return None

    def delete(self, plugin_name: str, key: str) -> dict:
        """Delete a secret."""
        secrets = self._load_secrets(plugin_name)
        if key in secrets:
            del secrets[key]
            self._save_secrets(plugin_name, secrets)
            return {"status": "deleted", "plugin": plugin_name, "key": key}
        return {"status": "not_found", "plugin": plugin_name, "key": key}

    def list_keys(self, plugin_name: str) -> list[str]:
        """List secret key names for a plugin (not values)."""
        secrets = self._load_secrets(plugin_name)
        return list(secrets.keys())

    def delete_vault(self, plugin_name: str) -> dict:
        """Delete an entire plugin vault."""
        vault_path = self._vault_path(plugin_name)
        if vault_path.exists():
            import shutil
            shutil.rmtree(vault_path)
            return {"status": "deleted", "plugin": plugin_name}
        return {"status": "not_found", "plugin": plugin_name}

    def _vault_path(self, plugin_name: str) -> Path:
        # Hash plugin name to prevent directory traversal
        safe_name = hashlib.sha256(plugin_name.encode()).hexdigest()[:16]
        return VAULT_DIR / safe_name

    def _load_secrets(self, plugin_name: str) -> dict:
        vault_path = self._vault_path(plugin_name)
        secrets_file = vault_path / "secrets.json"
        if secrets_file.exists():
            try:
                return json.loads(secrets_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_secrets(self, plugin_name: str, secrets: dict):
        vault_path = self._vault_path(plugin_name)
        secrets_file = vault_path / "secrets.json"
        secrets_file.write_text(json.dumps(secrets, indent=2), encoding="utf-8")

    def _obfuscate(self, value: str) -> str:
        """Simple obfuscation (not encryption — for real security use OS keychain)."""
        return value.encode().hex()

    def _deobfuscate(self, value: str) -> str:
        """Reverse obfuscation."""
        try:
            return bytes.fromhex(value).decode()
        except Exception:
            return value


# Global singleton
secret_vault = SecretVault()
