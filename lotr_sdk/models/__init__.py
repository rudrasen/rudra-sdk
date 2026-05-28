"""
Models package — public surface for the LOTR SDK data layer.

Import from here, not from submodules:
    from lotr_sdk.models import Movie, Quote, ListResponse, FilterOptions
"""

from lotr_sdk.models.filter_options import FilterOperator, FilterOptions
from lotr_sdk.models.list_response import ListResponse
from lotr_sdk.models.movie import Movie
from lotr_sdk.models.quote import Quote

__all__ = [
    "Movie",
    "Quote",
    "ListResponse",
    "FilterOptions",
    "FilterOperator",
]
