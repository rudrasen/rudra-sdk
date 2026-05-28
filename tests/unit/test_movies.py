"""
Unit tests for MoviesResource.

Uses the `responses` library to intercept requests.Session — zero real
network calls. All response data is loaded from tests/fixtures/.

Assumption: BASE_URL matches the constant in lotr_sdk/client.py.
Assumption: query-param verification inspects responses.calls[0].request.url
  because the `responses` library does not filter by params by default —
  it matches the base URL and lets any params through. We verify params were
  sent by inspecting the recorded call.

TestMoviesFilterOperatorIntegration exercises the full path:
  FilterOptions → to_query_params() → HTTPClient._request() → URL in the wire.
  These are mock-HTTP tests, not real API calls.
"""

from urllib.parse import parse_qs, urlparse

import pytest
import responses as resp

from lotr_sdk.exceptions import NotFoundError
from lotr_sdk.models import FilterOperator, FilterOptions, ListResponse, Movie, Quote
from lotr_sdk.resources.movies import MoviesResource

BASE_URL = "https://the-one-api.dev/v2"
MOVIES_URL = f"{BASE_URL}/movie"
MOVIE_ID = "5cd95395de30eff6ebccde5d"  # The Return of the King — from fixture
MOVIE_GET_URL = f"{MOVIES_URL}/{MOVIE_ID}"
MOVIE_QUOTES_URL = f"{MOVIE_GET_URL}/quote"


class TestMoviesResourceList:
    @resp.activate
    def test_list_success_returns_list_response(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        result = movies_resource.list()
        assert isinstance(result, ListResponse)
        assert result.total == 8
        assert result.limit == 1000
        assert len(result.docs) == 8

    @resp.activate
    def test_list_docs_are_movie_instances(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        result = movies_resource.list()
        for doc in result.docs:
            assert isinstance(doc, Movie)

    @resp.activate
    def test_list_first_doc_fields(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        result = movies_resource.list()
        first = result.docs[0]
        assert first.id == "5cd95395de30eff6ebccde56"
        assert first.name == "The Lord of the Rings Series"
        assert first.runtime_in_minutes == 558
        assert first.budget_in_millions == 281
        assert first.academy_award_wins == 17

    @resp.activate
    def test_list_with_filters_sends_query_params(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        filters = FilterOptions(limit=5, page=2)
        movies_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["limit"] == ["5"]
        assert params["page"] == ["2"]
        assert "sort" not in params

    @resp.activate
    def test_list_with_field_filter_sends_field_param(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        filters = FilterOptions(filter_field="name", filter_value="The Two Towers")
        movies_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["name"] == ["The Two Towers"]

    @resp.activate
    def test_list_empty_docs_returns_valid_response(
        self, movies_resource: MoviesResource
    ) -> None:
        empty_payload = {
            "docs": [],
            "total": 0,
            "limit": 1000,
            "offset": 0,
            "page": 1,
            "pages": 0,
        }
        resp.add(resp.GET, MOVIES_URL, json=empty_payload, status=200)
        result = movies_resource.list()
        assert result.docs == []
        assert result.total == 0


class TestMoviesResourceValidation:
    @resp.activate
    def test_malformed_response_raises_validation_error(
        self, movies_resource: MoviesResource
    ) -> None:
        from lotr_sdk.exceptions import ValidationError

        resp.add(resp.GET, MOVIES_URL, json={"unexpected": "shape"}, status=200)
        with pytest.raises(ValidationError):
            movies_resource.list()

    @resp.activate
    def test_get_empty_docs_raises_not_found_error(
        self, movies_resource: MoviesResource
    ) -> None:
        empty = {"docs": [], "total": 0, "limit": 1000, "offset": 0, "page": 1, "pages": 0}
        resp.add(resp.GET, MOVIE_GET_URL, json=empty, status=200)
        with pytest.raises(NotFoundError) as exc_info:
            movies_resource.get(MOVIE_ID)
        assert exc_info.value.resource_id == MOVIE_ID


class TestMoviesResourceGet:
    @resp.activate
    def test_get_success_returns_movie(
        self, movies_resource: MoviesResource, movie_single_data: dict
    ) -> None:
        resp.add(resp.GET, MOVIE_GET_URL, json=movie_single_data, status=200)
        movie = movies_resource.get(MOVIE_ID)
        assert isinstance(movie, Movie)

    @resp.activate
    def test_get_success_correct_fields(
        self, movies_resource: MoviesResource, movie_single_data: dict
    ) -> None:
        resp.add(resp.GET, MOVIE_GET_URL, json=movie_single_data, status=200)
        movie = movies_resource.get(MOVIE_ID)
        assert movie.id == MOVIE_ID
        assert movie.name == "The Return of the King"
        assert movie.runtime_in_minutes == 201
        assert movie.budget_in_millions == 94
        assert movie.box_office_revenue_in_millions == 1120
        assert movie.academy_award_nominations == 11
        assert movie.academy_award_wins == 11
        assert movie.rotten_tomatoes_score == 95

    @resp.activate
    def test_get_404_raises_not_found_error(
        self, movies_resource: MoviesResource
    ) -> None:
        resp.add(resp.GET, MOVIE_GET_URL, status=404)
        with pytest.raises(NotFoundError) as exc_info:
            movies_resource.get(MOVIE_ID)
        # resource_id is extracted from the second path segment in http.py
        assert exc_info.value.resource_id == MOVIE_ID

    @resp.activate
    def test_get_404_resource_id_is_the_requested_id(
        self, movies_resource: MoviesResource
    ) -> None:
        bad_id = "nonexistent-movie-id"
        resp.add(resp.GET, f"{MOVIES_URL}/{bad_id}", status=404)
        with pytest.raises(NotFoundError) as exc_info:
            movies_resource.get(bad_id)
        assert exc_info.value.resource_id == bad_id


class TestMoviesResourceQuotes:
    @resp.activate
    def test_quotes_success_returns_list_response(
        self, movies_resource: MoviesResource, movie_quotes_data: dict
    ) -> None:
        resp.add(resp.GET, MOVIE_QUOTES_URL, json=movie_quotes_data, status=200)
        result = movies_resource.quotes(MOVIE_ID)
        assert isinstance(result, ListResponse)
        assert result.total == 872
        assert result.limit == 10
        assert len(result.docs) == 10

    @resp.activate
    def test_quotes_docs_are_quote_instances(
        self, movies_resource: MoviesResource, movie_quotes_data: dict
    ) -> None:
        resp.add(resp.GET, MOVIE_QUOTES_URL, json=movie_quotes_data, status=200)
        result = movies_resource.quotes(MOVIE_ID)
        for doc in result.docs:
            assert isinstance(doc, Quote)

    @resp.activate
    def test_quotes_first_doc_fields(
        self, movies_resource: MoviesResource, movie_quotes_data: dict
    ) -> None:
        resp.add(resp.GET, MOVIE_QUOTES_URL, json=movie_quotes_data, status=200)
        result = movies_resource.quotes(MOVIE_ID)
        first = result.docs[0]
        assert first.id == "5cd96e05de30eff6ebcce7e9"
        assert first.dialog == "Deagol!!"
        assert first.movie_id == MOVIE_ID

    @resp.activate
    def test_quotes_with_filters_sends_query_params(
        self, movies_resource: MoviesResource, movie_quotes_data: dict
    ) -> None:
        resp.add(resp.GET, MOVIE_QUOTES_URL, json=movie_quotes_data, status=200)
        filters = FilterOptions(limit=10, page=1)
        movies_resource.quotes(MOVIE_ID, filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["limit"] == ["10"]
        assert params["page"] == ["1"]


class TestMoviesFilterOperatorIntegration:
    """Mock-HTTP integration: FilterOptions operators → correct URL wire format.

    Each test sends a request through the full resource→HTTP stack and asserts
    the URL sent to the (mocked) API contains the correct query parameter key
    and value encoding. parse_qs decodes percent-encoded chars so assertions
    work on the logical values, not the encoded form.
    """

    @resp.activate
    def test_negation_operator_sends_bang_key(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        """NEQ → key is 'field!' so the URL reads ?field!=value."""
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        filters = FilterOptions(
            filter_field="name",
            filter_operator=FilterOperator.NEQ,
            filter_value="The Return of the King",
        )
        movies_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["name!"] == ["The Return of the King"]

    @resp.activate
    def test_lt_operator_sends_angle_bracket_key(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        """LT → key is 'field<' (< URL-encoded as %3C, decoded by parse_qs)."""
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        filters = FilterOptions(
            filter_field="runtimeInMinutes",
            filter_operator=FilterOperator.LT,
            filter_value="200",
        )
        movies_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["runtimeInMinutes<"] == ["200"]

    @resp.activate
    def test_gte_operator_sends_gte_key(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        """GTE → key is 'field>=' (encoded as %3E%3D, decoded by parse_qs)."""
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        filters = FilterOptions(
            filter_field="runtimeInMinutes",
            filter_operator=FilterOperator.GTE,
            filter_value="160",
        )
        movies_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["runtimeInMinutes>="] == ["160"]

    @resp.activate
    def test_exists_operator_sends_field_with_empty_value(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        """EXISTS → key 'field' with empty-string value."""
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        filters = FilterOptions(
            filter_field="name",
            filter_operator=FilterOperator.EXISTS,
        )
        movies_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        assert "name" in params
        assert params["name"] == [""]

    @resp.activate
    def test_not_exists_operator_sends_bang_prefix_key(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        """NOT_EXISTS → key '!field' (%21 URL-encoded, decoded by parse_qs)."""
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        filters = FilterOptions(
            filter_field="name",
            filter_operator=FilterOperator.NOT_EXISTS,
        )
        movies_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        assert "!name" in params
        assert params["!name"] == [""]

    @resp.activate
    def test_regex_operator_sends_field_with_regex_value(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        """REGEX → same key as EQ; value is the /pattern/flags string."""
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        filters = FilterOptions(
            filter_field="name",
            filter_operator=FilterOperator.REGEX,
            filter_value="/king/i",
        )
        movies_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["name"] == ["/king/i"]

    @resp.activate
    def test_bson_id_eq_sends_correct_param(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        """Object-ID lookup via EQ — primary-key filter."""
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        filters = FilterOptions(
            filter_field="_id",
            filter_value="5cd95395de30eff6ebccde5c",
        )
        movies_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["_id"] == ["5cd95395de30eff6ebccde5c"]
