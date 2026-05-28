"""
Shared fixtures for the unit test suite.

All fixtures here are scoped to 'function' (pytest default) so each test
starts with a fresh HTTPClient and resource instance.

Assumption: FIXTURES_DIR is resolved relative to this conftest, so the path
is correct regardless of the directory from which pytest is invoked.
"""

import json
import pathlib

import pytest

from lotr_sdk.http import HTTPClient
from lotr_sdk.resources.movies import MoviesResource
from lotr_sdk.resources.quotes import QuotesResource

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures"
BASE_URL = "https://the-one-api.dev/v2"
DUMMY_KEY = "unit-test-dummy-key"


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file by filename and return the parsed dict."""
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture()
def http_client() -> HTTPClient:
    """HTTPClient wired with a dummy key and the real base URL."""
    return HTTPClient(api_key=DUMMY_KEY, base_url=BASE_URL)


@pytest.fixture()
def movies_resource(http_client: HTTPClient) -> MoviesResource:
    return MoviesResource(http_client)


@pytest.fixture()
def quotes_resource(http_client: HTTPClient) -> QuotesResource:
    return QuotesResource(http_client)


@pytest.fixture()
def movies_list_data() -> dict:
    return load_fixture("movies_list.json")


@pytest.fixture()
def movie_single_data() -> dict:
    return load_fixture("movie_single.json")


@pytest.fixture()
def movie_quotes_data() -> dict:
    return load_fixture("movie_quotes.json")


@pytest.fixture()
def quotes_list_data() -> dict:
    return load_fixture("quotes_list.json")


@pytest.fixture()
def quote_single_data() -> dict:
    return load_fixture("quote_single.json")
