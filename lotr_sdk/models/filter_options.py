"""
FilterOptions — caller-facing model for pagination, sorting, and field filtering.

NOT frozen: users construct this incrementally, e.g.:
    opts = FilterOptions(limit=10)
    opts.sort_by = "budgetInMillions"   # mutating before passing to a resource

The One API query-param conventions (assumption — derived from API docs + fixtures):
    Pagination : ?limit=N&page=N&offset=N
    Sorting    : ?sort=<field>:<asc|desc>   e.g. ?sort=budgetInMillions:desc
    Filtering  : ?<field>=<value>           e.g. ?name=The Two Towers
                 (simple equality only; regex / operator variants are out of v1 scope)

Assumption: if sort_by is given without sort_order, "asc" is used as the default.
Assumption: if filter_value is given without filter_field, the filter is silently
  dropped — there is no safe default field to filter on. Callers should always
  supply both together.
Assumption: all values are serialised to str in the returned dict so they can be
  passed directly as requests params= without further coercion.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

__all__ = ["FilterOptions"]


class FilterOptions(BaseModel):
    # Not frozen — mutable by design; callers build these incrementally.
    model_config = ConfigDict(populate_by_name=True)

    limit: Optional[int] = None
    page: Optional[int] = None
    offset: Optional[int] = None
    sort_by: Optional[str] = None
    sort_order: Optional[Literal["asc", "desc"]] = None
    filter_field: Optional[str] = None
    filter_value: Optional[str] = None

    def to_query_params(self) -> dict[str, str | int]:
        """Return a dict ready to pass as ``params=`` to requests.

        Only non-None values are included.  Sorting is collapsed into the
        single ``sort=field:order`` form the API expects.
        """
        params: dict[str, str | int] = {}

        if self.limit is not None:
            params["limit"] = self.limit
        if self.page is not None:
            params["page"] = self.page
        if self.offset is not None:
            params["offset"] = self.offset

        if self.sort_by is not None:
            order = self.sort_order or "asc"
            params["sort"] = f"{self.sort_by}:{order}"

        if self.filter_field is not None and self.filter_value is not None:
            params[self.filter_field] = self.filter_value

        return params
