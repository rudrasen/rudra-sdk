"""
HTTPClient — single authenticated session for The One API.

All HTTP status → SDK exception mapping lives in this module exclusively.
All pydantic.ValidationError → lotr_sdk.ValidationError mapping lives in
parse_response() exclusively.
"""

from __future__ import annotations

from typing import Any, TypeVar

import pydantic
import requests
import requests.exceptions

from lotr_sdk.exceptions import (
    APIError,
    AuthError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)

__all__ = ["HTTPClient", "parse_response"]

_T = TypeVar("_T")

# Named constants so status codes never appear as bare integers.
_HTTP_UNAUTHORIZED = 401
_HTTP_NOT_FOUND = 404
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR_MIN = 500
_HTTP_SERVER_ERROR_MAX = 599


class HTTPClient:
    """Single-session authenticated HTTP client for The One API.

    Wraps ``requests.Session`` with Bearer-token auth, timeout enforcement,
    and HTTP status → SDK exception mapping.

    Thread safety: the ``Authorization`` header is set once at construction
    and never modified thereafter. Concurrent reads across threads are safe
    under this constraint — no per-request mutation of session state occurs.

    Network-level failures (DNS, connection refused, read timeout) are caught
    and re-raised as ``APIError(status_code=0)`` so callers only need to catch
    ``LotRError``, not ``requests`` internals.
    """

    def __init__(self, api_key: str, base_url: str, timeout: int = 10) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._session = requests.Session()
        # Set once on the session so every subsequent request carries it.
        self._session.headers.update({"Authorization": f"Bearer {api_key}"})

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one authenticated HTTP request; return the JSON body as a dict.

        Non-2xx responses always raise an SDK exception. JSON-decode failure
        on a 2xx is raised as APIError. Pydantic validation is NOT done here;
        call parse_response() after.

        Raises:
            AuthError:       HTTP 401
            NotFoundError:   HTTP 404
            RateLimitError:  HTTP 429
            APIError:        HTTP 5xx, unexpected 4xx, network failure, bad JSON
        """
        url = f"{self._base_url}{endpoint}"

        try:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                timeout=self._timeout,
            )
        except requests.exceptions.RequestException as exc:
            # Never reached the server — no status code available.
            # status_code=0 is the sentinel for network-level failure.
            raise APIError(
                f"Network error contacting {url!r}: {exc}", status_code=0
            ) from exc

        self._raise_for_status(response, endpoint)

        try:
            return response.json()  # type: ignore[no-any-return]
        except ValueError as exc:
            # 2xx but non-JSON body — treat as a server-side error.
            raise APIError(
                f"Response from {url!r} is not valid JSON: {exc}",
                status_code=response.status_code,
            ) from exc

    def _raise_for_status(
        self, response: requests.Response, endpoint: str
    ) -> None:
        """Map HTTP error status codes to SDK exceptions.

        The only place in the SDK where HTTP status codes are inspected.
        2xx responses return without raising; everything else raises.

        Retry-After is parsed as an integer seconds value. Non-integer values
        (HTTP-date format) fall back to 0; callers should treat retry_after=0
        as "wait an unspecified duration".
        """
        status = response.status_code

        if 200 <= status < 300:
            return

        if status == _HTTP_UNAUTHORIZED:
            raise AuthError(
                f"Authentication failed (HTTP {status}): "
                "check that LOTR_API_KEY is set and valid"
            )

        if status == _HTTP_NOT_FOUND:
            # Extract the resource ID from the endpoint path.
            # /movie/{id}          → parts = ["movie", "{id}"]       → parts[1]
            # /movie/{id}/quote    → parts = ["movie", "{id}", "quote"] → parts[1]
            # /quote/{id}          → parts = ["quote", "{id}"]       → parts[1]
            # /movie (bare list)   → parts = ["movie"]               → parts[0] (fallback)
            parts = endpoint.strip("/").split("/")
            resource_id = parts[1] if len(parts) > 1 else parts[0]
            raise NotFoundError(
                f"Resource not found: {endpoint!r} (HTTP {status})",
                resource_id=resource_id,
            )

        if status == _HTTP_TOO_MANY_REQUESTS:
            retry_after_raw = response.headers.get("Retry-After", "0")
            try:
                retry_after = int(retry_after_raw)
            except ValueError:
                retry_after = 0
            raise RateLimitError(
                f"Rate limit exceeded (HTTP {status}). "
                f"Retry after {retry_after}s.",
                retry_after=retry_after,
            )

        if _HTTP_SERVER_ERROR_MIN <= status <= _HTTP_SERVER_ERROR_MAX:
            raise APIError(
                f"Server error (HTTP {status}): {endpoint!r}",
                status_code=status,
            )

        # Unexpected 4xx — 400, 403, 405, etc. Not mapped to a specific subclass
        # because The One API does not document these for in-scope endpoints.
        raise APIError(
            f"Unexpected client error (HTTP {status}): {endpoint!r}",
            status_code=status,
        )

    def close(self) -> None:
        """Release the underlying connection pool."""
        self._session.close()

    def __enter__(self) -> HTTPClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def parse_response(model_cls: type[_T], data: dict[str, Any]) -> _T:
    """Validate a raw API dict against a Pydantic model; return the model instance.

    The only place in the SDK where ``pydantic.ValidationError`` is caught
    and re-raised as ``lotr_sdk.ValidationError``. Resources must call this
    instead of ``model_cls.model_validate()`` directly.

    Raises:
        lotr_sdk.ValidationError: response shape did not match the model.
            ``exc.__cause__`` holds the original ``pydantic.ValidationError``
            for field-level diagnostics.
    """
    try:
        return model_cls.model_validate(data)  # type: ignore[attr-defined]
    except pydantic.ValidationError as exc:
        raise ValidationError(
            f"API response did not match expected schema for {model_cls!r}: {exc}"
        ) from exc
