"""Password hashing on the standard library.

scrypt is in hashlib, so this needs no dependency and no native build. The
parameters are the ones RFC 7914 suggests for interactive logins; they cost
roughly 100ms and 64MB per attempt, which is the point.
"""

import hashlib
import hmac
import secrets

_N = 2**14
_R = 8
_P = 1
_DK_LEN = 32


# Accounts created through Google or Facebook have no password. This goes in
# the column instead: verify_password rejects it because it is not a scrypt
# record, so there is no password to guess.
UNUSABLE_PASSWORD = "!"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DK_LEN
    )
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(digest_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    # Constant time, so a wrong password cannot be narrowed down by timing.
    return hmac.compare_digest(digest.hex(), digest_hex)
