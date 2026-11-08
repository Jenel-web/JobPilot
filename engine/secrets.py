"""Secrets: the ONLY place in JobPilot that reads or writes API keys and tokens.

Secrets live in Windows Credential Manager (through the ``keyring`` library),
never in files, ``.env`` or git. Values are never logged or printed.

Usage::

    set_secret("hunter_api_key", "abc123")   # once, by you
    key = get_secret("hunter_api_key")       # None if it was never set
"""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "jobpilot"


class SecretsError(Exception):
    """The OS credential store could not be used (the message never contains a secret)."""


def get_secret(name: str) -> str | None:
    """Return the secret called ``name``, or ``None`` if it was never set."""
    _check_name(name)
    try:
        return keyring.get_password(SERVICE, name)
    except KeyringError as exc:
        raise SecretsError(f"Cannot read secret {name!r}: {type(exc).__name__}") from exc


def set_secret(name: str, value: str) -> None:
    """Save (or replace) the secret called ``name``."""
    _check_name(name)
    if not value:
        raise SecretsError("Refusing to save an empty secret")
    try:
        keyring.set_password(SERVICE, name, value)
    except KeyringError as exc:
        raise SecretsError(f"Cannot save secret {name!r}: {type(exc).__name__}") from exc


def delete_secret(name: str) -> bool:
    """Remove a secret. Returns ``False`` if it did not exist."""
    _check_name(name)
    try:
        keyring.delete_password(SERVICE, name)
    except PasswordDeleteError:
        return False
    except KeyringError as exc:
        raise SecretsError(f"Cannot delete secret {name!r}: {type(exc).__name__}") from exc
    return True


def _check_name(name: str) -> None:
    if not name or not name.replace("_", "").isalnum():
        raise SecretsError("Secret names use letters, digits and underscores only")
