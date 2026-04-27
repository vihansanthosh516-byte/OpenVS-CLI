"""
Security Signing — cryptographic plugin verification.

Wraps the platform signing module with additional security checks
and integration into the plugin loading pipeline.
"""

from openvs.platform.signing import PluginSigner, verify_plugin

__all__ = ["PluginSigner", "verify_plugin_signature"]


def verify_plugin_signature(plugin_name: str) -> dict:
    """Verify a plugin's signature. Returns validation result."""
    return verify_plugin(plugin_name)
