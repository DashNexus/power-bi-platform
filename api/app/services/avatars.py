"""Store and serve user avatar images.

Bytes go to object storage through `storage.py`; the `users.avatar_url` column
holds an app-relative path to the serving endpoint. Same shape as client brand
assets, so caching, the storage backend, and deletion all behave identically.

**No Gravatar, and no other avatar proxy.** Gravatar keys off an MD5 of the
email address, so pointing `<img>` at it would tell a third party the email of
every user in the org, on every page that renders a list of people — and MD5 of
an email is trivially reversible against a wordlist. Initials are drawn client
side instead, which costs nothing and leaks nothing.
"""

from __future__ import annotations

import re
import uuid

# Formats a browser will render inline. SVG is deliberately absent: an SVG can
# carry script, and these are served from our own origin to authenticated users.
ALLOWED_AVATAR_TYPES: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}

MAX_AVATAR_BYTES = 4 * 1024 * 1024

CONTENT_TYPE_BY_EXTENSION: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}

# The serving route only accepts this exact shape, so a path segment can never
# be smuggled into the storage key.
_FILENAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif|webp)$")


class AvatarError(Exception):
    """The uploaded avatar was rejected (maps to HTTP 400/413/415)."""


def storage_key(org_id: int, user_id: int, filename: str) -> str:
    """Return the object-storage key for a user's avatar file."""
    return f"avatars/org_{org_id}/user_{user_id}/{filename}"


def is_valid_filename(filename: str) -> bool:
    """Whether a filename matches the generated form exactly."""
    return bool(_FILENAME_RE.match(filename))


def content_type_for(filename: str) -> str:
    """Return the media type to serve a stored avatar with."""
    extension = filename.rsplit(".", 1)[-1].lower()
    return CONTENT_TYPE_BY_EXTENSION.get(extension, "application/octet-stream")


def build_filename(content_type: str) -> str:
    """Return a new unguessable filename for an accepted content type.

    Raises:
        AvatarError: If the content type is not one of ALLOWED_AVATAR_TYPES.
    """
    extension = ALLOWED_AVATAR_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if extension is None:
        raise AvatarError(
            "Unsupported image type. Use PNG, JPEG, GIF, or WebP."
        )
    return f"{uuid.uuid4().hex}.{extension}"


def avatar_url(user_id: int, filename: str) -> str:
    """Return the app-relative URL stored on the user row."""
    return f"/users/{user_id}/avatar/{filename}"
