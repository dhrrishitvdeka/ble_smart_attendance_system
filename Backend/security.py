"""Password hashing helpers shared by seed data and login."""
import hashlib
import secrets

PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
        if not 120_000 <= iterations <= 1_000_000 or len(parts[2]) != 32 or len(parts[3]) != 64:
            return False
        bytes.fromhex(parts[2])
        bytes.fromhex(parts[3])
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), parts[2].encode("ascii"), iterations)
        return secrets.compare_digest(dk.hex(), parts[3])
    except (ValueError, UnicodeError):
        return False
