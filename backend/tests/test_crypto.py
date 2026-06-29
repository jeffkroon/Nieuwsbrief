"""Unit-tests voor SecretCipher (geen DB/Docker nodig)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.services.crypto import SecretCipher


@pytest.fixture
def cipher() -> SecretCipher:
    return SecretCipher(Fernet.generate_key().decode())


def test_encrypt_decrypt_roundtrip(cipher: SecretCipher) -> None:
    plaintext = "xkeysib-abc123-brevo-key"
    token = cipher.encrypt(plaintext)
    assert token != plaintext
    assert cipher.decrypt(token) == plaintext


def test_ciphertext_is_not_deterministic(cipher: SecretCipher) -> None:
    # Fernet bevat een IV: twee keer versleutelen geeft verschillende tokens.
    assert cipher.encrypt("zelfde") != cipher.encrypt("zelfde")


def test_empty_plaintext_rejected(cipher: SecretCipher) -> None:
    with pytest.raises(ValueError):
        cipher.encrypt("")


def test_invalid_key_rejected() -> None:
    with pytest.raises(ValueError):
        SecretCipher("dit-is-geen-geldige-fernet-key")


def test_decrypt_with_wrong_key_fails() -> None:
    a = SecretCipher(Fernet.generate_key().decode())
    b = SecretCipher(Fernet.generate_key().decode())
    token = a.encrypt("geheim")
    with pytest.raises(ValueError):
        b.decrypt(token)


def test_decrypt_tampered_token_fails(cipher: SecretCipher) -> None:
    token = cipher.encrypt("geheim")
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    with pytest.raises(ValueError):
        cipher.decrypt(tampered)
