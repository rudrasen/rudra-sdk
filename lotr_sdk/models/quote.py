"""
Quote model — maps the /quote and /movie/{id}/quote response shape.

Assumption: the API returns BOTH "_id" and "id" for every quote, and they
  are always identical (observed in all quote fixtures).
  With populate_by_name=True, both "_id" (alias) and "id" (field name) resolve
  to the same Python attribute. Pydantic v2 accepts duplicate keys pointing to
  the same field; last-seen value wins (values are identical so this is safe).

Assumption: "movie" and "character" are always opaque ID strings, never
  expanded nested objects, for the endpoints in scope (/quote, /movie/{id}/quote).
  They are surfaced as movie_id / character_id to avoid shadowing Python builtins
  and to signal clearly that they are foreign-key references, not full objects.

Assumption: "dialog" is always a non-empty string. Blank dialog lines are not
  filtered — that is the caller's responsibility.
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
