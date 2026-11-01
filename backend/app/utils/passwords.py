"""Password hashing for locally registered accounts (scrypt, standard library).

Stored format: ``scrypt$<n>$<r>$<p>$<salt hex>$<hash hex>``. The parameters are
kept with each hash so they can be raised later without invalidating old ones.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1
_KEY_LENGTH = 32
_MAX_MEMORY = 64 * 1024 * 1024


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_KEY_LENGTH, maxmem=_MAX_MEMORY)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${_derive(password, salt, _N, _R, _P).hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(hash_hex)
        actual = _derive(password, bytes.fromhex(salt_hex), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


#: Verified against when the email is unknown, so a missing account takes as
#: long to reject as a wrong password.
DUMMY_HASH = hash_password(secrets.token_hex(16))
