"""
MoviesResource — wraps the /movie family of endpoints.

Deliberately thin: no business logic. All HTTP via HTTPClient._request();
all response validation via parse_response(). An unknown movie_id returns
HTTP 404 from the API, which HTTPClient maps to NotFoundError.

filters passed to quotes() apply to the quote list, not the movie lookup.
"""

from __future__ import annotations

from typing import Any

from lotr_sdk.exceptions import NotFoundError
from lotr_sdk.http import HTTPClient, parse_response
from lotr_sdk.models import FilterOptions, ListResponse, Movie, Quote

__all__ = ["MoviesResource"]

_ENDPOINT_LIST = "/movie"
_ENDPOINT_GET = "/movie/{id}"
_ENDPOINT_QUOTES = "/movie/{id}/quote"


class MoviesResource:
    """Namespaced resource for the /movie family of endpoints.

    Accessed via ``client.movies`` — never instantiated directly by callers.
    """

    def __init__(self, http: HTTPClient) -> None:
        self._http = http

    def list(self, filters: FilterOptions | None = None) -> ListResponse[Movie]:
        """Return all movies, with optional pagination / filtering.

        Args:
            filters: Optional FilterOptions controlling pagination, sort, and
                     field filters. Pass ``None`` (default) for no constraints.

        Returns:
            ListResponse[Movie] — paginated envelope with docs, total, pages, etc.

        Raises:
            AuthError:        API key is missing or invalid.
            RateLimitError:   Too many requests; check retry_after.
            APIError:         Network failure, server error, or malformed JSON.
            ValidationError:  Response shape did not match Movie schema.
        """
        params: dict[str, Any] | None = (
            filters.to_query_params() or None if filters is not None else None
        )
        data = self._http._request("GET", _ENDPOINT_LIST, params=params)
        return parse_response(ListResponse[Movie], data)

    def get(self, movie_id: str) -> Movie:
        """Fetch a single movie by its API ID.

        Args:
            movie_id: The One API document ID, e.g. ``"5cd95395de30eff6ebccde5b"``.

        Returns:
            Movie — frozen Pydantic model for the matched document.

        Raises:
            NotFoundError:    movie_id does not exist in the API.
            AuthError:        API key is missing or invalid.
            RateLimitError:   Too many requests; check retry_after.
            APIError:         Network failure, server error, or malformed JSON.
            ValidationError:  Response shape did not match Movie schema.

        """
        endpoint = _ENDPOINT_GET.format(id=movie_id)
        data = self._http._request("GET", endpoint)
        # Single-item responses use the same {"docs": [...]} envelope as list endpoints.
        envelope = parse_response(ListResponse[Movie], data)
        if not envelope.docs:
            raise NotFoundError(
                f"Resource not found: no document returned for ID {movie_id!r}",
                resource_id=movie_id,
            )
        return envelope.docs[0]

    def quotes(
        self,
        movie_id: str,
        filters: FilterOptions | None = None,
    ) -> ListResponse[Quote]:
        """Return quotes for a given movie, with optional filtering.

        **API limitation:** The One API only stores quotes for the three core
        Lord of the Rings trilogy films. Calling this method with any other
        movie ID (e.g. The Hobbit films) returns an empty ``docs`` list rather
        than a 404 — the API accepts the request but has no quote data for it.

        Trilogy movie IDs with quote data:

        +-----------------------------------------+------------------------------+
        | Movie                                   | ID                           |
        +=========================================+==============================+
        | The Fellowship of the Ring              | 5cd95395de30eff6ebccde5c     |
        +-----------------------------------------+------------------------------+
        | The Two Towers                          | 5cd95395de30eff6ebccde5b     |
        +-----------------------------------------+------------------------------+
        | The Return of the King                  | 5cd95395de30eff6ebccde5d     |
        +-----------------------------------------+------------------------------+

        Args:
            movie_id: The One API document ID of the movie.
            filters:  Optional FilterOptions for pagination / sort / field filter.

        Returns:
            ListResponse[Quote] — paginated quote envelope. ``docs`` will be
            empty for non-trilogy movies.

        Raises:
            NotFoundError:    movie_id does not exist.
            AuthError:        API key is missing or invalid.
            RateLimitError:   Too many requests; check retry_after.
            APIError:         Network failure, server error, or malformed JSON.
            ValidationError:  Response shape did not match Quote schema.
        """
        endpoint = _ENDPOINT_QUOTES.format(id=movie_id)
        params: dict[str, Any] | None = (
            filters.to_query_params() or None if filters is not None else None
        )
        data = self._http._request("GET", endpoint, params=params)
        return parse_response(ListResponse[Quote], data)
