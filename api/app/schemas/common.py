"""Response models shared across routers."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper.

    Attributes:
        items: The current page of results.
        total: Total number of records across all pages.
        page: Current page number (1-indexed).
        page_size: Number of items per page.
    """

    items: list[T]
    total: int
    page: int
    page_size: int


class MessageResponse(BaseModel):
    """Simple success message response."""

    message: str


class ErrorResponse(BaseModel):
    """Standard error response body."""

    detail: str
