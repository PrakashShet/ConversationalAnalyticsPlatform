"""OS keychain wrapper for secrets."""

import keyring

SERVICE_NAME = "conv-analytics"


def get_secret(key: str) -> str | None:
    """Read a secret from the OS keychain."""
    return keyring.get_password(SERVICE_NAME, key)


def set_secret(key: str, value: str) -> None:
    """Store a secret in the OS keychain."""
    keyring.set_password(SERVICE_NAME, key, value)


def delete_secret(key: str) -> None:
    """Remove a secret from the OS keychain."""
    try:
        keyring.delete_password(SERVICE_NAME, key)
    except keyring.errors.PasswordDeleteError:
        pass
