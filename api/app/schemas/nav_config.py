"""Request and response models for the admin-authored portal navigation.

A nav item is either a **link** (a label and an href) or a **dropdown** (a label
and a list of child links). The whole navigation is saved and returned as one
list — there is no per-item endpoint, because order is part of the value.

Every href is validated rather than stored verbatim. The saved value is rendered
straight into an anchor for every user in the organisation, so an unchecked
``javascript:`` href would be stored XSS that an admin could hand to themselves
by pasting a link — and a scheme allow-list is the only reliable way to stop it.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

#: How many items a navigation may hold. Not a security boundary — a nav bar
#: with fifty entries is already unusable — but it keeps one org from storing
#: an unbounded blob that is read on every page load.
MAX_ITEMS = 50
MAX_CHILDREN = 50

# An internal route ("/dashboard/12") or an absolute http(s) URL. Anything else
# is refused: `javascript:` and `data:` execute, and a protocol-relative
# "//example.com" is an off-site link that reads like a local path.
_INTERNAL = re.compile(r"^/(?!/)[\w\-./~%?#&=+:@!$'()*,;\[\]]*$")
_EXTERNAL = re.compile(r"^https?://", re.IGNORECASE)

_HREF_HELP = (
    "A link must be an internal path starting with '/' (for example "
    "'/dashboard/12') or an absolute http:// or https:// URL."
)


def _validate_href(value: str) -> str:
    """Return the trimmed href, or raise if it is neither internal nor http(s)."""
    href = value.strip()
    if not href:
        raise ValueError("A link needs a target.")
    if _EXTERNAL.match(href) or _INTERNAL.match(href):
        return href
    raise ValueError(_HREF_HELP)


class NavLink(BaseModel):
    """One entry inside a dropdown."""

    label: str = Field(min_length=1, max_length=100)
    href: str = Field(max_length=1024)

    @field_validator("href")
    @classmethod
    def _check_href(cls, value: str) -> str:
        return _validate_href(value)

    @field_validator("label")
    @classmethod
    def _trim_label(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("A link needs a label.")
        return trimmed


class NavItem(BaseModel):
    """A top-level navigation entry: a link, or a dropdown of links."""

    type: Literal["link", "dropdown"]
    label: str = Field(min_length=1, max_length=100)
    href: str | None = Field(default=None, max_length=1024)
    items: list[NavLink] | None = Field(default=None, max_length=MAX_CHILDREN)

    @field_validator("label")
    @classmethod
    def _trim_label(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("A navigation item needs a label.")
        return trimmed

    @field_validator("href")
    @classmethod
    def _check_href(cls, value: str | None) -> str | None:
        return None if value is None else _validate_href(value)

    @model_validator(mode="after")
    def _shape_matches_type(self) -> NavItem:
        """Reject an item whose fields do not match its type.

        A link with no href renders as an anchor to nowhere and a dropdown with
        no children opens onto an empty menu — both look like the nav is broken
        rather than like the item was saved half-finished.
        """
        if self.type == "link":
            if not self.href:
                raise ValueError(f"'{self.label}' is a link, so it needs a target. {_HREF_HELP}")
            if self.items:
                raise ValueError(f"'{self.label}' is a link, so it cannot also hold items.")
            return self
        if not self.items:
            raise ValueError(f"'{self.label}' is a dropdown, so it needs at least one item.")
        if self.href:
            raise ValueError(
                f"'{self.label}' is a dropdown, so it cannot also have its own target."
            )
        return self


class NavConfigRequest(BaseModel):
    """Body for saving the organisation's navigation.

    An empty list means "go back to the default navigation" and is stored as
    NULL, so there is one representation of the default rather than two.
    """

    items: list[NavItem] = Field(default_factory=list, max_length=MAX_ITEMS)


class NavConfigResponse(BaseModel):
    """The organisation's saved navigation, empty when the defaults are in use."""

    items: list[NavItem]
