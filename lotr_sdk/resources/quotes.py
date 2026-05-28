"""
QuotesResource — wraps the /quote family of endpoints.

Deliberately thin: no business logic. All HTTP via HTTPClient._request();
all response validation via parse_response(). An unknown quote_id returns
HTTP 404 from the API, which HTTPClient maps to NotFoundError.
"""

from __future__ import annotations

from typing import Any

from lotr_sdk.exceptions import NotFoundError
from lotr_sdk.http import HTTPClient, parse_response
from lotr_sdk.models import FilterOptions, ListResponse, Quote

__all__ = ["QuotesResource"]

_ENDPOINT_LIST = "/quote"
_ENDPOINT_GET = "/quote/{id}"


class QuotesResource:
    """Namespaced resource for the /quote family of endpoints.

    Accessed via ``client.quotes`` — never instantiated directly by callers.
    """

    def __init__(self, http: HTTPClient) -> None:
        self._http = http

    def list(self, filters: FilterOptions | None = None) -> ListResponse[Quote]:
        """Return all quotes, with optional pagination / sorting / filtering.

        Args:
            filters: Optional FilterOptions controlling pagination, sort, and
                     field filters. Pass ``None`` (default) for no constraints.

        Returns:
            ListResponse[Quote] — paginated envelope with docs, total, pages, etc.

        Raises:
            AuthError:        API key is missing or invalid.
            RateLimitError:   Too many requests; check retry_after.
            APIError:         Network failure, server error, or malformed JSON.
            ValidationError:  Response shape did not match Quote schema.
        """
        params: dict[str, Any] | None = (
            filters.to_query_params() or None if filters is not None else None
        )
        data = self._http._request("GET", _ENDPOINT_LIST, params=params)
        return parse_response(ListResponse[Quote], data)

    def get(self, quote_id: str) -> Quote:
        """Fetch a single quote by its API ID.

        Args:
            quote_id: The One API document ID, e.g. ``"5cd96e05de30eff6ebcce7e9"``.

        Returns:
            Quote — frozen Pydantic model for the matched document.

        Raises:
            NotFoundError:    quote_id does not exist in the API.
            AuthError:        API key is missing or invalid.
            RateLimitError:   Too many requests; check retry_after.
            APIError:         Network failure, server error, or malformed JSON.
            ValidationError:  Response shape did not match Quote schema.

        """
        endpoint = _ENDPOINT_GET.format(id=quote_id)
        data = self._http._request("GET", endpoint)
        # Single-item responses use the same {"docs": [...]} envelope as list endpoints.
        envelope = parse_response(ListResponse[Quote], data)
        if not envelope.docs:
            raise NotFoundError(
                f"Resource not found: no document returned for ID {quote_id!r}",
                resource_id=quote_id,
            )
        return envelope.docs[0]
