"""
Generic pagination wrapper — maps the outer envelope returned by every
list endpoint: /movie, /quote, /movie/{id}/quote.

Envelope shape (from fixtures):
    {
        "docs":   [...],   # the actual items
        "total":  8,       # total items matching the query (before pagination)
        "limit":  1000,    # max items per page as requested
        "offset": 0,       # number of items skipped
        "page":   1,       # current page number (1-based)
        "pages":  1        # total number of pages
    }

Assumption: all pagination fields are always integers and always present.
  If the API ever omits one, Pydantic raises ValidationError → lotr_sdk.ValidationError.

Usage:
    ListResponse[Movie].model_validate(raw_dict)
    ListResponse[Quote].model_validate(raw_dict)
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

__all__ = ["ListResponse"]

T = TypeVar("T")


class ListResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(frozen=True)

    docs: list[T]
    total: int
    limit: int
    offset: int
    page: int
    pages: int
