"""
LOTR SDK — Python client for The One API (Lord of the Rings).
"""

from lotr_sdk.cache import CacheConfig, CacheProtocol, InMemoryCache
from lotr_sdk.client import LotRClient
from lotr_sdk.exceptions import (
    APIError,
    AuthError,
    LotRError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from lotr_sdk.http import RetryConfig
from lotr_sdk.models import FilterOperator, FilterOptions, ListResponse, Movie, Quote

__all__ = [
    "LotRClient",
    # cache
    "CacheConfig",
    "CacheProtocol",
    "InMemoryCache",
    # retry
    "RetryConfig",
    # exceptions
    "LotRError",
    "AuthError",
    "NotFoundError",
    "RateLimitError",
    "APIError",
    "ValidationError",
    # models
    "FilterOptions",
    "FilterOperator",
    "ListResponse",
    "Movie",
    "Quote",
]
