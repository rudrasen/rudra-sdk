"""
Movie model — maps the /movie and /movie/{id} response shape.

Assumption: all numeric fields from the API are always present (no Optional).
  Evidence: all 8 movies in the fixtures carry every field.
  If a future API change omits a field, Pydantic will raise ValidationError
  and the SDK will surface it as lotr_sdk.ValidationError (mapped in http.py).

Assumption: runtimeInMinutes / academyAward* are always integers in the API.
  budgetInMillions and boxOfficeRevenueInMillions can be float (e.g. 958.4),
  so all numeric fields are typed float to allow Pydantic's int→float coercion.

Field aliasing: API uses camelCase (_id, runtimeInMinutes …).
  Python attributes use snake_case. populate_by_name=True allows callers to
  construct Movie(id=...) in tests without needing the underscore alias.
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
