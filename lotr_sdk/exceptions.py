"""
SDK-specific exception hierarchy for the LOTR SDK.

Dependency: none — this module imports nothing outside the stdlib.
It is a leaf node; every other SDK module may import from it.

Callers can catch LotRError to handle all SDK exceptions in one block,
or catch specific subclasses for targeted handling.

HTTP status → exception mapping is NOT here; it lives exclusively in
http.py so that all mapping logic is auditable in one place.
"""

from __future__ import annotations

__all__ = [
    "LotRError",
    "AuthError",
    "NotFoundError",
    "RateLimitError",
    "APIError",
    "ValidationError",
]


class LotRError(Exception):
    """Base class for all LOTR SDK exceptions.

    Catch this type to handle any SDK error without caring about
    the specific cause::

        try:
            movie = client.movies.get("some-id")
        except LotRError as exc:
            logger.error("SDK error: %s", exc)
    """


class AuthError(LotRError):
    """Raised when the API returns HTTP 401 (Unauthorized).

    Cause: the Bearer token is missing, malformed, or revoked.

    This exception is never retried — the same credential produces
    the same 401 on every attempt. Resolve by providing a valid
    LOTR_API_KEY before constructing the client.
    """


class NotFoundError(LotRError):
    """Raised when the API returns HTTP 404 (Not Found).

    Cause: the requested resource does not exist at the given ID.

    This exception is never retried — the resource will not appear
    on a subsequent attempt with the same ID.

    Attributes:
        resource_id: The ID that was requested and not found.
            Assumption: callers always have the ID they requested,
            so this attribute is required (no default).
    """

    def __init__(self, message: str, resource_id: str) -> None:
        super().__init__(message)
        self.resource_id: str = resource_id


class RateLimitError(LotRError):
    """Raised when the API returns HTTP 429 (Too Many Requests).

    The SDK will attempt retries according to RetryConfig if one is
    configured, backing off for at least ``retry_after`` seconds.

    Attributes:
        retry_after: Seconds to wait before retrying, sourced from
            the ``Retry-After`` response header.
            Assumption: defaults to 0 when the header is absent;
            callers should treat 0 as "wait an unspecified duration"
            rather than "retry immediately".
    """

    def __init__(self, message: str, retry_after: int = 0) -> None:
        super().__init__(message)
        self.retry_after: int = retry_after


class APIError(LotRError):
    """Raised for HTTP 5xx responses and unexpected 4xx responses.

    5xx indicates a server-side failure; unexpected 4xx indicates a
    request the SDK sent that the API rejected for an unmapped reason.

    Attributes:
        status_code: The HTTP status code returned by the API.
            Stored here for callers that need to branch on specific
            codes (e.g. distinguish 500 from 503 in retry logic).
            Assumption: always an integer; never None.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code: int = status_code


class ValidationError(LotRError):
    """Raised when an API response cannot be parsed into a Pydantic model.

    Indicates that the API returned a shape the SDK does not recognise —
    typically caused by an undocumented API change or a new optional field.

    The underlying ``pydantic.ValidationError`` is attached as ``__cause__``
    when raised with ``raise lotr_sdk.ValidationError(...) from pydantic_exc``,
    and is accessible via ``exc.__cause__`` for detailed field-level diagnostics.

    Note: this is ``lotr_sdk.exceptions.ValidationError``, distinct from
    ``pydantic.ValidationError``. They are not related by inheritance.
    """
