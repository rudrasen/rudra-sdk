"""
Generic pagination envelope returned by every list endpoint.

All pagination fields (total, limit, offset, page, pages) are always
present in API responses. If the API ever omits one, Pydantic raises
ValidationError → lotr_sdk.ValidationError.
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
