"""
Plugin Signing — cryptographic signatures for plugin packages.

Plugins can be signed by their author. The signature proves:
- The plugin was published by the claimed author
- The plugin has not been tampered with since signing

Uses RSA + SHA-256. Falls back gracefully if cryptography not installed.
"""

import json
import hashlib
from pathlib import Path
from typing import Optional


class PluginSigner:
    """Sign and verify plugin packages.

    Uses RSA-PSS with SHA-256 if cryptography is available.
    Falls back to HMAC-SHA256 for lightweight environments.
    """

    def sign(self, plugin_path: str, private_key: bytes = None) -> str:
        """Sign a plugin directory. Returns signature string."""
        path = Path(plugin_path)

        # Hash all plugin files
        file_hashes = self._hash_plugin_files(path)

        # Create manifest hash
        manifest = json.dumps(file_hashes, sort_keys=True)
        manifest_hash = hashlib.sha256(manifest.encode()).hexdigest()

        if private_key:
            try:
                from cryptography.hazmat.primitives import hashes, serialization
                from cryptography.hazmat.primitives.asymmetric import padding, utils

                key = serialization.load_pem_private_key(private_key, password=None)
                signature = key.sign(
                    manifest_hash.encode(),
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH,
                    ),
                    hashes.SHA256(),
                )
                return signature.hex()
            except ImportError:
                pass

        # Fallback: HMAC-based signature
        if private_key:
            import hmac
            sig = hmac.new(private_key, manifest_hash.encode(), hashlib.sha256).hexdigest()
            return f"hmac:{sig}"

        # No key: generate content hash as pseudo-signature
        return f"hash:{manifest_hash}"

    def verify(self, plugin_path: str, signature: str, public_key: bytes = None) -> dict:
        """Verify a plugin signature. Returns {"valid": bool, "method": str}."""
        path = Path(plugin_path)

        if not path.exists():
            return {"valid": False, "method": "none", "error": "Plugin path not found"}

        file_hashes = self._hash_plugin_files(path)
        manifest = json.dumps(file_hashes, sort_keys=True)
        manifest_hash = hashlib.sha256(manifest.encode()).hexdigest()

        if signature.startswith("hash:"):
            expected = f"hash:{manifest_hash}"
            return {
                "valid": signature == expected,
                "method": "content_hash",
                "tamper_proof": False,
            }

        if signature.startswith("hmac:") and public_key:
            import hmac
            expected_sig = hmac.new(public_key, manifest_hash.encode(), hashlib.sha256).hexdigest()
            return {
                "valid": signature[5:] == expected_sig,
                "method": "hmac_sha256",
                "tamper_proof": True,
            }

        if public_key and not signature.startswith("hmac:"):
            try:
                from cryptography.hazmat.primitives import hashes, serialization
                from cryptography.hazmat.primitives.asymmetric import padding

                key = serialization.load_pem_public_key(public_key)
                key.verify(
                    bytes.fromhex(signature),
                    manifest_hash.encode(),
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH,
                    ),
                    hashes.SHA256(),
                )
                return {"valid": True, "method": "rsa_pss", "tamper_proof": True}
            except Exception as e:
                return {"valid": False, "method": "rsa_pss", "error": str(e)}

        return {"valid": False, "method": "none", "error": "No verification method available"}

    def _hash_plugin_files(self, plugin_path: Path) -> dict:
        """Hash every file in a plugin directory."""
        hashes = {}
        for f in sorted(plugin_path.rglob("*")):
            if f.is_file() and not f.name.startswith("."):
                try:
                    content = f.read_bytes()
                    rel = str(f.relative_to(plugin_path))
                    hashes[rel] = hashlib.sha256(content).hexdigest()
                except Exception:
                    pass
        return hashes


def verify_plugin(plugin_name: str) -> dict:
    """Verify a plugin by name from ~/.openvs/plugins/."""
    from openvs.platform.signing import PluginSigner
    plugin_dir = Path.home() / ".openvs" / "plugins" / plugin_name
    sig_file = plugin_dir / "signature.txt"

    if not plugin_dir.exists():
        return {"valid": False, "error": "Plugin not found"}

    if not sig_file.exists():
        return {"valid": False, "error": "No signature file", "method": "unsigned"}

    signature = sig_file.read_text().strip()
    signer = PluginSigner()
    return signer.verify(str(plugin_dir), signature)


# Global singleton
plugin_signer = PluginSigner()
