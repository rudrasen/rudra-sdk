"""
FilterOptions — caller-facing model for pagination and field filtering.

Not frozen: callers may build incrementally.

The One API query-param conventions:
    Pagination : ?limit=N&page=N&offset=N
    Filtering  : key format varies by operator (see table below)

FilterOperator → to_query_params() key format:
    EQ         : {field: value}           → ?field=value
    NEQ        : {f"{field}!": value}     → ?field!=value
    LT         : {f"{field}<": value}     → ?field<value
    GT         : {f"{field}>": value}     → ?field>value
    GTE        : {f"{field}>=": value}    → ?field>=value
    LTE        : {f"{field}<=": value}    → ?field<=value
    EXISTS     : {field: ""}              → ?field=
    NOT_EXISTS : {f"!{field}": ""}        → ?!field=
    REGEX      : {field: value}           → ?field=/pattern/flags
    NOT_REGEX  : {f"{field}!": value}     → ?field!=/pattern/flags

LT/GT/GTE/LTE require a numeric filter_value; validated at construction time.

Known limitation: The One API returns HTTP 500 when a ?sort= parameter is
included in the request. Sorting is therefore not supported in this SDK.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator

__all__ = ["FilterOperator", "FilterOptions"]

_NUMERIC_OPS_REQUIRING_NUMERIC_VALUE = frozenset(["lt", "gt", "gte", "lte"])


class FilterOperator(str, Enum):
    """Comparison operator applied to filter_field when building query params.

    Maps to The One API's URL query filter syntax. See module docstring for the
    exact key format each operator produces in to_query_params().

    Comma-separated filter_value with EQ produces inclusion matching
    (e.g. ``name=The Hobbit,The Two Towers``). The same with NEQ produces
    exclusion matching. No separate IN/NIN operators are needed — the value
    format drives that server-side behaviour.
    """

    EQ = "eq"
    NEQ = "neq"
    LT = "lt"
    GT = "gt"
    GTE = "gte"
    LTE = "lte"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"
    REGEX = "regex"
    NOT_REGEX = "not_regex"


class FilterOptions(BaseModel):
    # Not frozen — mutable by design; callers build these incrementally.
    model_config = ConfigDict(populate_by_name=True)

    limit: Optional[int] = None
    page: Optional[int] = None
    offset: Optional[int] = None
    sort_by: Optional[str] = None
    sort_order: Optional[str] = None  # "asc" | "desc"
    filter_field: Optional[str] = None
    filter_value: Optional[str] = None
    filter_operator: FilterOperator = FilterOperator.EQ

    @model_validator(mode="after")
    def _reject_sort_params(self) -> "FilterOptions":
        """Raise if sort_by or sort_order are set — the API returns HTTP 500 for ?sort=."""
        if self.sort_by is not None or self.sort_order is not None:
            raise ValueError(
                "Sorting is not supported: The One API returns HTTP 500 for ?sort= queries. "
                "Remove sort_by and sort_order from your FilterOptions."
            )
        return self

    @model_validator(mode="after")
    def _validate_numeric_operator_value(self) -> "FilterOptions":
        """Raise if a numeric operator is paired with a non-numeric filter_value.

        LT, GT, GTE, LTE have no meaning on string fields; catching this at
        construction time surfaces misuse before the invalid query reaches the API.
        Each comma-separated part of filter_value is validated independently so
        that multi-value numeric fields (e.g. ``runtimeInMinutes=178,201``) are
        handled correctly for EQ — but those operators do not reach this branch.
        """
        if self.filter_operator.value not in _NUMERIC_OPS_REQUIRING_NUMERIC_VALUE:
            return self
        if self.filter_value is None:
            raise ValueError(
                f"filter_value is required when filter_operator is "
                f"'{self.filter_operator.value}'"
            )
        if "," in self.filter_value:
            raise ValueError(
                f"Operator '{self.filter_operator.value}' does not support "
                "comma-separated values; use EQ or NEQ for multi-value matching"
            )
        try:
            float(self.filter_value.strip())
        except ValueError:
            raise ValueError(
                f"Operator '{self.filter_operator.value}' requires a numeric "
                f"filter_value; got {self.filter_value!r}"
            )
        return self

    def to_query_params(self) -> dict[str, str | int]:
        """Return a dict ready to pass as ``params=`` to requests.

        Only non-None values are included. Filtering key format varies by
        operator — see module docstring for the mapping.
        """
        params: dict[str, str | int] = {}

        if self.limit is not None:
            params["limit"] = self.limit
        if self.page is not None:
            params["page"] = self.page
        if self.offset is not None:
            params["offset"] = self.offset

        if self.filter_field is not None:
            field = self.filter_field
            op = self.filter_operator

            if op == FilterOperator.EXISTS:
                params[field] = ""

            elif op == FilterOperator.NOT_EXISTS:
                params[f"!{field}"] = ""

            elif op in (FilterOperator.EQ, FilterOperator.REGEX):
                # REGEX value is /pattern/flags — same key format as EQ.
                if self.filter_value is not None:
                    params[field] = self.filter_value

            elif op in (FilterOperator.NEQ, FilterOperator.NOT_REGEX):
                # Negation: key becomes field! so the URL reads field!=value.
                # NOT_REGEX value is /pattern/flags — same key format as NEQ.
                if self.filter_value is not None:
                    params[f"{field}!"] = self.filter_value

            elif op == FilterOperator.LT:
                assert self.filter_value is not None  # guaranteed by model_validator
                params[f"{field}<"] = self.filter_value

            elif op == FilterOperator.GT:
                assert self.filter_value is not None  # guaranteed by model_validator
                params[f"{field}>"] = self.filter_value

            elif op == FilterOperator.GTE:
                assert self.filter_value is not None  # guaranteed by model_validator
                params[f"{field}>="] = self.filter_value

            elif op == FilterOperator.LTE:
                assert self.filter_value is not None  # guaranteed by model_validator
                params[f"{field}<="] = self.filter_value

        return params
