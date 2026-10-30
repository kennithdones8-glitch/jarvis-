"""Secret lookup. Secrets live in the macOS Keychain, never in config files, prompts or logs.

Store a key on the Mac with:
    security add-generic-password -s jarvis -a <secret-name> -w
(``-w`` with no value prompts for it, so it never lands in shell history.)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Protocol

SERVICE = "jarvis"


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...


class KeychainSecrets:
    def get(self, name: str) -> str | None:
        if not shutil.which("security"):
            return None
        proc = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", name, "-w"],
                              capture_output=True, text=True, timeout=10)
        return proc.stdout.strip() or None if proc.returncode == 0 else None


class EnvSecrets:
    """Development fallback: ``JARVIS_SECRET_<NAME>`` environment variables."""

    def get(self, name: str) -> str | None:
        return os.environ.get(f"JARVIS_SECRET_{name.upper()}") or None


class ChainSecrets:
    def __init__(self, *stores: SecretStore):
        self.stores = stores

    def get(self, name: str) -> str | None:
        for store in self.stores:
            if value := store.get(name):
                return value
        return None


def default_secrets() -> SecretStore:
    return ChainSecrets(KeychainSecrets(), EnvSecrets()) if sys.platform == "darwin" else EnvSecrets()
