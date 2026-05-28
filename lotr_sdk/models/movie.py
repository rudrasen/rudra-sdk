"""
Movie model — maps the /movie and /movie/{id} response shape.

frozen=True: API responses are immutable facts. Frozen models are also
hashable, which is required for cache key construction in v2.

All numeric fields are typed float to allow Pydantic's int→float coercion
(e.g. budgetInMillions can be 958.4). If the API omits a field in a future
response, Pydantic raises ValidationError → lotr_sdk.ValidationError.

populate_by_name=True allows tests to construct Movie(id=...) without
the underscore alias.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Movie"]


class Movie(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    id: str = Field(alias="_id")
    name: str
    runtime_in_minutes: float = Field(alias="runtimeInMinutes")
    budget_in_millions: float = Field(alias="budgetInMillions")
    box_office_revenue_in_millions: float = Field(alias="boxOfficeRevenueInMillions")
    academy_award_nominations: int = Field(alias="academyAwardNominations")
    academy_award_wins: int = Field(alias="academyAwardWins")
    rotten_tomatoes_score: float = Field(alias="rottenTomatoesScore")
