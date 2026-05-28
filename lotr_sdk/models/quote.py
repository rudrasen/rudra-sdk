"""
Quote model — maps the /quote and /movie/{id}/quote response shape.

frozen=True: API responses are immutable facts; frozen models are hashable
for v2 cache key construction.

The API returns both "_id" and "id" for every quote (always identical).
With populate_by_name=True, both resolve to the same field; Pydantic v2
accepts duplicate keys pointing to the same field — last-seen wins, safe
because values are identical.

"movie" and "character" are always opaque ID strings for the in-scope
endpoints; they are surfaced as movie_id / character_id to signal that
they are foreign-key references, not resolved nested objects.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Quote"]


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    id: str = Field(alias="_id")
    dialog: str
    movie_id: str = Field(alias="movie")
    character_id: str = Field(alias="character")
