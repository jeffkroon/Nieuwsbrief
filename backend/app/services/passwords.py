"""Wachtwoord-hashing voor per-bedrijf logins (stdlib, geen extra dependency).

PBKDF2-HMAC-SHA256 met een willekeurige salt per wachtwoord. Opslagformaat:
"pbkdf2$<iteraties>$<salt-hex>$<hash-hex>", zodat het aantal iteraties later
verhoogd kan worden zonder bestaande hashes te breken.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ITERATIONS = 200_000
_SCHEME = "pbkdf2"


def hash_password(password: str) -> str:
    if not password or len(password) < 8:
        raise ValueError("wachtwoord moet minimaal 8 tekens zijn")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS
    ).hex()
    return f"{_SCHEME}${_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str | None) -> bool:
    if not password or not stored:
        return False
    try:
        scheme, iterations_raw, salt, digest = stored.split("$")
        iterations = int(iterations_raw)
    except ValueError:
        return False
    if scheme != _SCHEME:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), iterations
    ).hex()
    return hmac.compare_digest(candidate, digest)
