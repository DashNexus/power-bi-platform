"""Fernet encryption, bcrypt password hashing, and TOTP.

The single place any of the three happen. TOTP secrets and OAuth client secrets are
Fernet-encrypted at rest; API keys deliberately use SHA-256 instead (see
`services/api_keys.py` for why a work factor is wrong for high-entropy input).
"""

from __future__ import annotations

import bcrypt as _bcrypt
import pyotp
from cryptography.fernet import Fernet

from app.config import settings


def encrypt(plaintext: str, key: str | None = None) -> str:
    """Fernet-encrypt a plaintext string.

    Args:
        plaintext: The string to encrypt.
        key: Optional Fernet key (base64-urlsafe). Defaults to
            settings.totp_encryption_key.

    Returns:
        Base64 URL-safe encrypted string.
    """
    fernet_key = (key or settings.totp_encryption_key).encode()
    f = Fernet(fernet_key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str | bytes, key: str | None = None) -> str:
    """Fernet-decrypt a previously encrypted string.

    Accepts both str and bytes so the function works whether the caller
    passes the raw string returned by encrypt() or bytes read back from a
    LargeBinary database column (SQLAlchemy returns bytes for LargeBinary).

    Args:
        ciphertext: Fernet token — either the str returned by encrypt() or
            the bytes read from a LargeBinary column.
        key: Optional Fernet key. Defaults to settings.totp_encryption_key.

    Returns:
        Original plaintext string.
    """
    fernet_key = (key or settings.totp_encryption_key).encode()
    f = Fernet(fernet_key)
    token = ciphertext if isinstance(ciphertext, bytes) else ciphertext.encode()
    return f.decrypt(token).decode()


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt.

    Args:
        password: The plaintext password.

    Returns:
        bcrypt hash string.
    """
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.

    Args:
        password: The plaintext password to check.
        hashed: The stored bcrypt hash.

    Returns:
        True if the password matches, False otherwise.
    """
    return _bcrypt.checkpw(password.encode(), hashed.encode())


def generate_totp_secret() -> str:
    """Generate a random base32 TOTP secret.

    Returns:
        A random base32-encoded secret string.
    """
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str, issuer: str = "BI Platform") -> str:
    """Build an otpauth:// provisioning URI for QR code generation.

    Args:
        secret: The base32 TOTP secret.
        email: The user's email address (used as the account name).
        issuer: Display name shown in the authenticator app.

    Returns:
        The otpauth:// URI string.
    """
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code against the given secret.

    Allows a drift of one time step (30 seconds) in either direction to
    account for clock skew between server and authenticator app.

    Args:
        secret: The base32 TOTP secret.
        code: The 6-digit code submitted by the user.

    Returns:
        True if the code is valid within the allowed window.
    """
    totp = pyotp.TOTP(secret)
    # valid_window=1 allows one 30-second step of drift in each direction.
    return totp.verify(code, valid_window=1)
