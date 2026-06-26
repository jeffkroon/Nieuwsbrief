"""Symmetrische versleuteling voor tenant-secrets (Brevo API-keys).

Gebruikt Fernet (AES-128-CBC + HMAC). De master key komt uit
`SECRET_ENCRYPTION_KEY` en staat nooit in de database. Ciphertext is wat we
opslaan in `mail.tenant_secrets.value_encrypted`.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SecretCipher:
    def __init__(self, key: str) -> None:
        # Fernet valideert de sleutel; een ongeldige key faalt hier direct.
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            raise ValueError("Kan geen lege waarde versleutelen")
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError(
                "Kon secret niet ontsleutelen (ongeldige ciphertext of verkeerde master key)"
            ) from exc
