"""
Integration tests — exercise the live The One API.

ALL tests here are gated behind the --integration pytest flag AND require
LOTR_API_KEY to be set in the environment. They are automatically skipped
when running the unit suite (no flag, no key required).

Gate:  pytest --integration
Key:   export LOTR_API_KEY=your_token_here

Assumption: IDs used here are stable API fixtures that will not disappear
  between test runs. All IDs sourced from tests/fixtures/ which contain
  real API responses (per CLAUDE.md).
  - MOVIE_ID: 5cd95395de30eff6ebccde5d (The Return of the King)
  - QUOTE_ID: 5cd96e05de30eff6ebcce7e9 (first quote from movie_quotes fixture)

Assumption: integration tests are idempotent read-only GET calls.
  Nothing is mutated; running them repeatedly is safe.
"""

import os

import pytest

from lotr_sdk import LotRClient
from lotr_sdk.exceptions import AuthError
from lotr_sdk.models import ListResponse, Movie, Quote

MOVIE_ID = "5cd95395de30eff6ebccde5d"
QUOTE_ID = "5cd96e05de30eff6ebcce7e9"


@pytest.fixture(scope="module")
def client() -> LotRClient:
    """Real LotRClient sourced from LOTR_API_KEY env var.

    Skips the entire module if the key is absent, with a clear message
    rather than an AuthError traceback.
    """
    key = os.environ.get("LOTR_API_KEY")
    if not key:
        pytest.skip("LOTR_API_KEY not set — skipping integration tests")
    return LotRClient(api_key=key)


@pytest.mark.integration
class TestMoviesIntegration:
    def test_movies_list_returns_list_response(self, client: LotRClient) -> None:
        result = client.movies.list()
        assert isinstance(result, ListResponse)
        assert result.total >= 1
        assert len(result.docs) >= 1
        assert all(isinstance(m, Movie) for m in result.docs)

    def test_movies_list_with_limit(self, client: LotRClient) -> None:
        from lotr_sdk.models import FilterOptions

        result = client.movies.list(filters=FilterOptions(limit=3))
        assert len(result.docs) <= 3

    def test_movies_get_known_id(self, client: LotRClient) -> None:
        movie = client.movies.get(MOVIE_ID)
        assert isinstance(movie, Movie)
        assert movie.id == MOVIE_ID
        assert movie.name == "The Return of the King"

    def test_movies_quotes_returns_list_response(self, client: LotRClient) -> None:
        result = client.movies.quotes(MOVIE_ID)
        assert isinstance(result, ListResponse)
        assert result.total >= 1
        assert all(isinstance(q, Quote) for q in result.docs)

    def test_movies_quotes_all_belong_to_movie(self, client: LotRClient) -> None:
        from lotr_sdk.models import FilterOptions

        result = client.movies.quotes(MOVIE_ID, filters=FilterOptions(limit=10))
        for quote in result.docs:
            assert quote.movie_id == MOVIE_ID


@pytest.mark.integration
class TestQuotesIntegration:
    def test_quotes_list_returns_list_response(self, client: LotRClient) -> None:
        result = client.quotes.list()
        assert isinstance(result, ListResponse)
        assert result.total >= 1
        assert all(isinstance(q, Quote) for q in result.docs)

    def test_quotes_list_with_limit(self, client: LotRClient) -> None:
        from lotr_sdk.models import FilterOptions

        result = client.quotes.list(filters=FilterOptions(limit=5))
        assert len(result.docs) <= 5

    def test_quotes_get_known_id(self, client: LotRClient) -> None:
        quote = client.quotes.get(QUOTE_ID)
        assert isinstance(quote, Quote)
        assert quote.id == QUOTE_ID
        assert quote.dialog == "Deagol!!"


@pytest.mark.integration
class TestAuthIntegration:
    def test_invalid_key_raises_auth_error(self) -> None:
        client = LotRClient(api_key="definitely-not-valid-xxxxx")
        with pytest.raises(AuthError):
            client.movies.list()
