"""
Resources package — namespaced wrappers around the API endpoints.

Import from here:
    from lotr_sdk.resources import MoviesResource, QuotesResource
"""

from lotr_sdk.resources.movies import MoviesResource
from lotr_sdk.resources.quotes import QuotesResource

__all__ = ["MoviesResource", "QuotesResource"]
