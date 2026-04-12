"""Unit tests for FernetVault (FOUND-06) + scrubber auto-registration."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.security.fernet import FernetVault, InvalidFernetKey
from app.security.log_scrubber import REGISTRY


@pytest.fixture
def tmp_fernet_key() -> str:
    """A freshly-generated Fernet key as a UTF-8 string."""
    return Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Clear registry literals before and after each test."""
    REGISTRY.clear_literals()
    yield
    REGISTRY.clear_literals()


def test_from_env_missing_raises():
    with pytest.raises(InvalidFernetKey, match="required"):
        FernetVault.from_env("")


def test_from_env_malformed_raises():
    with pytest.raises(InvalidFernetKey, match="not a valid Fernet key"):
        FernetVault.from_env("not-a-key")


def test_roundtrip_encrypt_decrypt(tmp_fernet_key):
    vault = FernetVault.from_env(tmp_fernet_key)
    token = vault.encrypt("hello")
    assert isinstance(token, bytes)
    assert vault.decrypt(token) == "hello"


def test_decrypt_wrong_key_raises(tmp_fernet_key):
    vault_a = FernetVault.from_env(tmp_fernet_key)
    token = vault_a.encrypt("secret-data-wrong-key")

    other_key = Fernet.generate_key().decode()
    vault_b = FernetVault.from_env(other_key)

    with pytest.raises(InvalidFernetKey, match="may have changed"):
        vault_b.decrypt(token)


def test_decrypt_auto_registers_with_scrubber(tmp_fernet_key):
    vault = FernetVault.from_env(tmp_fernet_key)
    sentinel = "auto-reg-sentinel-xyz"
    token = vault.encrypt(sentinel)
    # Clear and re-register only via decrypt to prove decrypt does it.
    REGISTRY.clear_literals()
    REGISTRY.add_literal(tmp_fernet_key)  # keep master key registered
    assert vault.decrypt(token) == sentinel
    assert (
        REGISTRY.scrub(f"contains {sentinel} inside")
        == "contains ***REDACTED*** inside"
    )


def test_from_env_registers_master_key():
    key = Fernet.generate_key().decode()
    FernetVault.from_env(key)
    assert REGISTRY.scrub(f"FERNET_KEY={key}") != f"FERNET_KEY={key}"
    assert "***REDACTED***" in REGISTRY.scrub(f"FERNET_KEY={key}")
