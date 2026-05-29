"""
Unit tests for QuotesResource.

Uses the `responses` library to intercept requests.Session — zero real
network calls. All response data is loaded from tests/fixtures/.

Assumption: BASE_URL matches the constant in lotr_sdk/client.py.
Assumption: QuotesResource.get() unwraps the list envelope and returns
  docs[0], same pattern as MoviesResource.get().
"""

from urllib.parse import parse_qs, urlparse

import pytest
import responses as resp

from lotr_sdk.exceptions import NotFoundError
from lotr_sdk.models import FilterOperator, FilterOptions, ListResponse, Quote
from lotr_sdk.resources.quotes import QuotesResource

BASE_URL = "https://the-one-api.dev/v2"
QUOTES_URL = f"{BASE_URL}/quote"
QUOTE_ID = "5cd96e05de30eff6ebcce7e9"  # from quote_single.json fixture
QUOTE_GET_URL = f"{QUOTES_URL}/{QUOTE_ID}"
MOVIE_ID = "5cd95395de30eff6ebccde5d"  # The Return of the King (foreign key in quotes)


class TestQuotesResourceList:
    @resp.activate
    def test_list_success_returns_list_response(
        self, quotes_resource: QuotesResource, quotes_list_data: dict
    ) -> None:
        resp.add(resp.GET, QUOTES_URL, json=quotes_list_data, status=200)
        result = quotes_resource.list()
        assert isinstance(result, ListResponse)
        assert result.total == 2383
        assert result.limit == 10
        assert len(result.docs) == 10

    @resp.activate
    def test_list_docs_are_quote_instances(
        self, quotes_resource: QuotesResource, quotes_list_data: dict
    ) -> None:
        resp.add(resp.GET, QUOTES_URL, json=quotes_list_data, status=200)
        result = quotes_resource.list()
        for doc in result.docs:
            assert isinstance(doc, Quote)

    @resp.activate
    def test_list_first_doc_fields(
        self, quotes_resource: QuotesResource, quotes_list_data: dict
    ) -> None:
        resp.add(resp.GET, QUOTES_URL, json=quotes_list_data, status=200)
        result = quotes_resource.list()
        first = result.docs[0]
        assert first.id == QUOTE_ID
        assert first.dialog == "Deagol!!"
        assert first.movie_id == MOVIE_ID

    @resp.activate
    def test_list_with_filters_sends_query_params(
        self, quotes_resource: QuotesResource, quotes_list_data: dict
    ) -> None:
        resp.add(resp.GET, QUOTES_URL, json=quotes_list_data, status=200)
        filters = FilterOptions(limit=10, page=3)
        quotes_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["limit"] == ["10"]
        assert params["page"] == ["3"]
        assert "sort" not in params

    @resp.activate
    def test_list_with_field_filter_sends_correct_param(
        self, quotes_resource: QuotesResource, quotes_list_data: dict
    ) -> None:
        resp.add(resp.GET, QUOTES_URL, json=quotes_list_data, status=200)
        filters = FilterOptions(filter_field="character", filter_value="some-char-id")
        quotes_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["character"] == ["some-char-id"]

    @resp.activate
    def test_list_no_filters_sends_no_query_string(
        self, quotes_resource: QuotesResource, quotes_list_data: dict
    ) -> None:
        resp.add(resp.GET, QUOTES_URL, json=quotes_list_data, status=200)
        quotes_resource.list()

        parsed = urlparse(resp.calls[0].request.url)
        assert parsed.query == ""


class TestQuotesResourceGet:
    @resp.activate
    def test_get_success_returns_quote(
        self, quotes_resource: QuotesResource, quote_single_data: dict
    ) -> None:
        resp.add(resp.GET, QUOTE_GET_URL, json=quote_single_data, status=200)
        quote = quotes_resource.get(QUOTE_ID)
        assert isinstance(quote, Quote)

    @resp.activate
    def test_get_success_correct_fields(
        self, quotes_resource: QuotesResource, quote_single_data: dict
    ) -> None:
        resp.add(resp.GET, QUOTE_GET_URL, json=quote_single_data, status=200)
        quote = quotes_resource.get(QUOTE_ID)
        assert quote.id == QUOTE_ID
        assert quote.dialog == "Deagol!!"
        assert quote.movie_id == MOVIE_ID
        assert quote.character_id == "5cd99d4bde30eff6ebccfe9e"

    @resp.activate
    def test_get_404_raises_not_found_error(
        self, quotes_resource: QuotesResource
    ) -> None:
        resp.add(resp.GET, QUOTE_GET_URL, status=404)
        with pytest.raises(NotFoundError) as exc_info:
            quotes_resource.get(QUOTE_ID)
        assert exc_info.value.resource_id == QUOTE_ID

    @resp.activate
    def test_get_404_resource_id_matches_requested_id(
        self, quotes_resource: QuotesResource
    ) -> None:
        bad_id = "nonexistent-quote-id"
        resp.add(resp.GET, f"{QUOTES_URL}/{bad_id}", status=404)
        with pytest.raises(NotFoundError) as exc_info:
            quotes_resource.get(bad_id)
        assert exc_info.value.resource_id == bad_id

    @resp.activate
    def test_get_empty_docs_raises_not_found_error(
        self, quotes_resource: QuotesResource
    ) -> None:
        empty = {"docs": [], "total": 0, "limit": 1, "offset": 0, "page": 1, "pages": 0}
        resp.add(resp.GET, QUOTE_GET_URL, json=empty, status=200)
        with pytest.raises(NotFoundError) as exc_info:
            quotes_resource.get(QUOTE_ID)
        assert exc_info.value.resource_id == QUOTE_ID


class TestQuotesFilterOperatorIntegration:
    """Mock-HTTP integration: FilterOptions operators → correct URL wire format.

    Tests the full QuotesResource → HTTPClient path with mocked HTTP.
    parse_qs decodes percent-encoded characters so assertions use logical values.
    """

    @resp.activate
    def test_movie_id_foreign_key_filter(
        self, quotes_resource: QuotesResource, quotes_list_data: dict
    ) -> None:
        """EQ on 'movie' field — typical foreign-key lookup."""
        resp.add(resp.GET, QUOTES_URL, json=quotes_list_data, status=200)
        filters = FilterOptions(
            filter_field="movie",
            filter_value=MOVIE_ID,
        )
        quotes_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["movie"] == [MOVIE_ID]

    @resp.activate
    def test_negation_on_dialog_field(
        self, quotes_resource: QuotesResource, quotes_list_data: dict
    ) -> None:
        """NEQ → key is 'dialog!' so the URL reads ?dialog!=value."""
        resp.add(resp.GET, QUOTES_URL, json=quotes_list_data, status=200)
        filters = FilterOptions(
            filter_field="dialog",
            filter_operator=FilterOperator.NEQ,
            filter_value="Deagol!!",
        )
        quotes_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["dialog!"] == ["Deagol!!"]

    @resp.activate
    def test_regex_on_dialog_field(
        self, quotes_resource: QuotesResource, quotes_list_data: dict
    ) -> None:
        """REGEX → same key as EQ; value is /pattern/flags."""
        resp.add(resp.GET, QUOTES_URL, json=quotes_list_data, status=200)
        filters = FilterOptions(
            filter_field="dialog",
            filter_operator=FilterOperator.REGEX,
            filter_value="/ring/i",
        )
        quotes_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert params["dialog"] == ["/ring/i"]

    @resp.activate
    def test_exists_on_character_field(
        self, quotes_resource: QuotesResource, quotes_list_data: dict
    ) -> None:
        """EXISTS → key 'character' with empty value."""
        resp.add(resp.GET, QUOTES_URL, json=quotes_list_data, status=200)
        filters = FilterOptions(
            filter_field="character",
            filter_operator=FilterOperator.EXISTS,
        )
        quotes_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        assert "character" in params
        assert params["character"] == [""]

    @resp.activate
    def test_not_exists_on_dialog_field(
        self, quotes_resource: QuotesResource, quotes_list_data: dict
    ) -> None:
        """NOT_EXISTS → key '!dialog' (%21 URL-encoded, decoded by parse_qs)."""
        resp.add(resp.GET, QUOTES_URL, json=quotes_list_data, status=200)
        filters = FilterOptions(
            filter_field="dialog",
            filter_operator=FilterOperator.NOT_EXISTS,
        )
        quotes_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        assert "!dialog" in params

    @resp.activate
    def test_comma_csv_negation_exclusion(
        self, quotes_resource: QuotesResource, quotes_list_data: dict
    ) -> None:
        """NEQ with comma-separated value → exclusion array matching."""
        resp.add(resp.GET, QUOTES_URL, json=quotes_list_data, status=200)
        filters = FilterOptions(
            filter_field="movie",
            filter_operator=FilterOperator.NEQ,
            filter_value=f"{MOVIE_ID},5cd95395de30eff6ebccde5c",
        )
        quotes_resource.list(filters=filters)

        parsed = urlparse(resp.calls[0].request.url)
        params = parse_qs(parsed.query)
        assert "movie!" in params
        assert MOVIE_ID in params["movie!"][0]
