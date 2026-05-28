"""
Unit tests for FilterOptions.to_query_params().

No HTTP calls — this is pure model serialisation logic.

Parametrized matrix covers every datatype and operator variant from the
Input Test Matrix spec. Each row asserts the exact dict produced by
to_query_params(); the requests library handles URL-encoding from there.
"""

import pytest
from pydantic import ValidationError as PydanticValidationError

from lotr_sdk.models import FilterOperator, FilterOptions


class TestFilterOptionsEmpty:
    def test_all_none_returns_empty_dict(self) -> None:
        assert FilterOptions().to_query_params() == {}


class TestFilterOptionsPagination:
    def test_limit_only(self) -> None:
        params = FilterOptions(limit=10).to_query_params()
        assert params == {"limit": 10}

    def test_page_only(self) -> None:
        params = FilterOptions(page=3).to_query_params()
        assert params == {"page": 3}

    def test_offset_only(self) -> None:
        params = FilterOptions(offset=20).to_query_params()
        assert params == {"offset": 20}

    def test_all_pagination_fields(self) -> None:
        params = FilterOptions(limit=5, page=2, offset=5).to_query_params()
        assert params == {"limit": 5, "page": 2, "offset": 5}



class TestFilterOptionsFieldFilter:
    def test_field_and_value_both_present(self) -> None:
        params = FilterOptions(
            filter_field="name", filter_value="The Two Towers"
        ).to_query_params()
        assert params == {"name": "The Two Towers"}

    def test_filter_value_without_field_is_silently_dropped(self) -> None:
        # No safe default field → silently dropped.
        params = FilterOptions(filter_value="orphan-value").to_query_params()
        assert len(params) == 0

    def test_filter_field_without_value_is_silently_dropped(self) -> None:
        params = FilterOptions(filter_field="name").to_query_params()
        assert "name" not in params


class TestFilterOptionsAllTogether:
    def test_all_params_serialised(self) -> None:
        opts = FilterOptions(
            limit=10,
            page=1,
            offset=0,
            filter_field="academyAwardWins",
            filter_value="11",
        )
        params = opts.to_query_params()
        assert params == {
            "limit": 10,
            "page": 1,
            "offset": 0,
            "academyAwardWins": "11",
        }


# ---------------------------------------------------------------------------
# Parametrized matrix — every operator/datatype variant from the spec
# ---------------------------------------------------------------------------

_MATRIX = [
    # (id, FilterOptions kwargs, expected key, expected value-in-dict)
    # String — exact match (EQ default)
    (
        "string_eq",
        {"filter_field": "name", "filter_value": "The Return of the King"},
        "name",
        "The Return of the King",
    ),
    # String — negated match
    (
        "string_neq",
        {
            "filter_field": "name",
            "filter_operator": FilterOperator.NEQ,
            "filter_value": "The Return of the King",
        },
        "name!",
        "The Return of the King",
    ),
    # Comma-separated strings — inclusion (EQ with commas)
    (
        "string_in_csv",
        {
            "filter_field": "name",
            "filter_value": "The Hobbit,The Two Towers",
        },
        "name",
        "The Hobbit,The Two Towers",
    ),
    # Comma-separated strings — exclusion (NEQ with commas)
    (
        "string_nin_csv",
        {
            "filter_field": "name",
            "filter_operator": FilterOperator.NEQ,
            "filter_value": "The Hobbit,The Two Towers",
        },
        "name!",
        "The Hobbit,The Two Towers",
    ),
    # Flag — field existence (no value needed)
    (
        "exists",
        {
            "filter_field": "name",
            "filter_operator": FilterOperator.EXISTS,
        },
        "name",
        "",
    ),
    # Flag — field non-existence (!field key, no value)
    (
        "not_exists",
        {
            "filter_field": "name",
            "filter_operator": FilterOperator.NOT_EXISTS,
        },
        "!name",
        "",
    ),
    # Regex — case-insensitive partial match
    (
        "regex",
        {
            "filter_field": "name",
            "filter_operator": FilterOperator.REGEX,
            "filter_value": "/king/i",
        },
        "name",
        "/king/i",
    ),
    # Regex — negated
    (
        "not_regex",
        {
            "filter_field": "name",
            "filter_operator": FilterOperator.NOT_REGEX,
            "filter_value": "/king/i",
        },
        "name!",
        "/king/i",
    ),
    # Integer — exact match
    (
        "int_eq",
        {"filter_field": "runtimeInMinutes", "filter_value": "201"},
        "runtimeInMinutes",
        "201",
    ),
    # Integer — negated
    (
        "int_neq",
        {
            "filter_field": "runtimeInMinutes",
            "filter_operator": FilterOperator.NEQ,
            "filter_value": "201",
        },
        "runtimeInMinutes!",
        "201",
    ),
    # Comma-separated integers — inclusion
    (
        "int_in_csv",
        {"filter_field": "runtimeInMinutes", "filter_value": "178,201"},
        "runtimeInMinutes",
        "178,201",
    ),
    # Integer — less than
    (
        "int_lt",
        {
            "filter_field": "runtimeInMinutes",
            "filter_operator": FilterOperator.LT,
            "filter_value": "200",
        },
        "runtimeInMinutes<",
        "200",
    ),
    # Integer — greater than
    (
        "int_gt",
        {
            "filter_field": "runtimeInMinutes",
            "filter_operator": FilterOperator.GT,
            "filter_value": "200",
        },
        "runtimeInMinutes>",
        "200",
    ),
    # Integer — greater than or equal
    (
        "int_gte",
        {
            "filter_field": "runtimeInMinutes",
            "filter_operator": FilterOperator.GTE,
            "filter_value": "160",
        },
        "runtimeInMinutes>=",
        "160",
    ),
    # Integer — less than or equal
    (
        "int_lte",
        {
            "filter_field": "runtimeInMinutes",
            "filter_operator": FilterOperator.LTE,
            "filter_value": "120",
        },
        "runtimeInMinutes<=",
        "120",
    ),
    # Hex/BSON ID — foreign key lookup (EQ)
    (
        "bson_id_eq",
        {
            "filter_field": "movie",
            "filter_value": "5cd95395de30eff6ebccde5c",
        },
        "movie",
        "5cd95395de30eff6ebccde5c",
    ),
]


@pytest.mark.parametrize(
    "kwargs,expected_key,expected_value",
    [(row[1], row[2], row[3]) for row in _MATRIX],
    ids=[row[0] for row in _MATRIX],
)
class TestFilterOptionsMatrix:
    def test_produces_correct_key(
        self,
        kwargs: dict,
        expected_key: str,
        expected_value: str,
    ) -> None:
        params = FilterOptions(**kwargs).to_query_params()
        assert expected_key in params, (
            f"Expected key {expected_key!r} in params, got keys: {list(params)}"
        )

    def test_produces_correct_value(
        self,
        kwargs: dict,
        expected_key: str,
        expected_value: str,
    ) -> None:
        params = FilterOptions(**kwargs).to_query_params()
        assert params[expected_key] == expected_value

    def test_no_unexpected_filter_keys(
        self,
        kwargs: dict,
        expected_key: str,
        expected_value: str,
    ) -> None:
        """Only the expected key (plus any pagination/sort keys) should appear."""
        params = FilterOptions(**kwargs).to_query_params()
        non_meta_keys = {k for k in params if k not in ("limit", "page", "offset")}
        assert non_meta_keys == {expected_key}


# ---------------------------------------------------------------------------
# Error handling — invalid operator / field-type combinations
# ---------------------------------------------------------------------------


class TestFilterOptionsValidationErrors:
    def test_lt_with_text_value_raises(self) -> None:
        """Applying < to a text field value is structurally invalid."""
        with pytest.raises(PydanticValidationError) as exc_info:
            FilterOptions(
                filter_field="dialog",
                filter_operator=FilterOperator.LT,
                filter_value="hello",
            )
        assert "numeric" in str(exc_info.value).lower()

    def test_gt_with_text_value_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            FilterOptions(
                filter_field="dialog",
                filter_operator=FilterOperator.GT,
                filter_value="Some text value",
            )

    def test_gte_with_text_value_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            FilterOptions(
                filter_field="runtimeInMinutes",
                filter_operator=FilterOperator.GTE,
                filter_value="not-a-number",
            )

    def test_lte_with_text_value_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            FilterOptions(
                filter_field="runtimeInMinutes",
                filter_operator=FilterOperator.LTE,
                filter_value="twohundred",
            )

    def test_lt_with_mixed_csv_raises_on_alpha_part(self) -> None:
        """Comma-separated value where one part is non-numeric should fail."""
        with pytest.raises(PydanticValidationError):
            FilterOptions(
                filter_field="runtimeInMinutes",
                filter_operator=FilterOperator.LT,
                filter_value="abc,123",
            )

    def test_lt_requires_filter_value(self) -> None:
        """Numeric operators with no filter_value should raise at construction."""
        with pytest.raises(PydanticValidationError):
            FilterOptions(
                filter_field="runtimeInMinutes",
                filter_operator=FilterOperator.LT,
            )

    def test_gt_requires_filter_value(self) -> None:
        with pytest.raises(PydanticValidationError):
            FilterOptions(
                filter_field="runtimeInMinutes",
                filter_operator=FilterOperator.GT,
            )

    def test_lt_rejects_csv_even_when_all_parts_are_numeric(self) -> None:
        """LT/GT/GTE/LTE with comma-separated values is semantically nonsensical."""
        with pytest.raises(PydanticValidationError):
            FilterOptions(
                filter_field="runtimeInMinutes",
                filter_operator=FilterOperator.LT,
                filter_value="178,201",
            )

    def test_eq_with_alpha_on_integer_field_does_not_raise(self) -> None:
        """EQ passes alpha values through — field-type validation is the API's job."""
        opts = FilterOptions(filter_field="runtimeInMinutes", filter_value="NotANumber")
        assert opts.to_query_params() == {"runtimeInMinutes": "NotANumber"}

    def test_exists_with_no_value_does_not_raise(self) -> None:
        opts = FilterOptions(
            filter_field="name",
            filter_operator=FilterOperator.EXISTS,
        )
        assert opts.to_query_params() == {"name": ""}

    def test_not_exists_with_no_value_does_not_raise(self) -> None:
        opts = FilterOptions(
            filter_field="name",
            filter_operator=FilterOperator.NOT_EXISTS,
        )
        assert opts.to_query_params() == {"!name": ""}
