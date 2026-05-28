"""
demo.py — LOTR SDK walkthrough.

Demonstrates all five SDK endpoints:
  1. client.movies.list()          — list all movies with pagination
  2. client.movies.get(id)         — fetch a single movie by ID
  3. client.movies.quotes(id)      — quotes for a specific movie (filtered)
  4. client.quotes.list()          — list quotes across all movies (filtered)
  5. client.quotes.get(id)         — fetch a single quote by ID

Run:
    python demo.py

Requires LOTR_API_KEY in environment or a .env file in the project root.
Obtain a free token at https://the-one-api.dev/sign-up
"""

from __future__ import annotations

import sys

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; set LOTR_API_KEY in the shell instead

from lotr_sdk import LotRClient
from lotr_sdk.exceptions import AuthError, LotRError, NotFoundError, RateLimitError
from lotr_sdk.models import FilterOptions

# The One API document ID for The Fellowship of the Ring.
FELLOWSHIP_ID = "5cd95395de30eff6ebccde5c"


def _header(title: str) -> None:
    bar = "=" * 62
    print(f"\n{bar}")
    print(f"  {title}")
    print(f"{bar}")


def demo_all_movies(client: LotRClient) -> None:
    """List every movie with its runtime."""
    _header("All Movies")
    result = client.movies.list()
    print(f"  Total: {result.total} titles\n")
    for movie in result.docs:
        print(f"  {movie.name:<44} {movie.runtime_in_minutes:>5.0f} min")


def demo_single_movie(client: LotRClient) -> None:
    """Fetch one movie by ID and display its details."""
    _header("Single Movie — The Fellowship of the Ring")
    movie = client.movies.get(FELLOWSHIP_ID)
    print(f"  Name:               {movie.name}")
    print(f"  Runtime:            {movie.runtime_in_minutes} min")
    print(f"  Budget:             ${movie.budget_in_millions}M")
    print(f"  Box office:         ${movie.box_office_revenue_in_millions}M")
    print(f"  Academy Award wins: {movie.academy_award_wins}")
    print(f"  Rotten Tomatoes:    {movie.rotten_tomatoes_score}%")


def demo_fellowship_quotes(client: LotRClient) -> None:
    """Fetch the first 5 quotes for Fellowship of the Ring via movies.quotes()."""
    _header("Movie Quotes — The Fellowship of the Ring (limit=5)")

    filters = FilterOptions(limit=5)
    result = client.movies.quotes(FELLOWSHIP_ID, filters=filters)

    print(f"  Showing {len(result.docs)} of {result.total} total quotes\n")
    for i, quote in enumerate(result.docs, start=1):
        dialog = quote.dialog.strip()
        print(f"  {i}. \"{dialog}\"")


def demo_quotes_list(client: LotRClient) -> None:
    """List quotes across all movies using the /quote endpoint."""
    _header("All Quotes — sample (limit=5)")

    filters = FilterOptions(limit=5)
    result = client.quotes.list(filters=filters)

    print(f"  Showing {len(result.docs)} of {result.total} total quotes across all movies\n")
    for i, quote in enumerate(result.docs, start=1):
        dialog = quote.dialog.strip()
        print(f"  {i}. \"{dialog}\"")


def demo_single_quote(client: LotRClient) -> None:
    """Fetch one quote by ID using the /quote/{id} endpoint."""
    _header("Single Quote")
    # A well-known quote from The Return of the King
    quote_id = "5cd96e05de30eff6ebcce7e9"
    quote = client.quotes.get(quote_id)
    print(f"  \"{quote.dialog.strip()}\"")
    print(f"  — character ID: {quote.character_id}")
    print(f"  — movie ID:     {quote.movie_id}")


def main() -> None:

    try:
        client = LotRClient()
    except AuthError as exc:
        print(f"\n[auth error] {exc}", file=sys.stderr)
        print(
            "  Fix: set LOTR_API_KEY in your shell or create a .env file.\n"
            "  Get a free token at https://the-one-api.dev/sign-up",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        demo_all_movies(client)
        demo_single_movie(client)
        demo_fellowship_quotes(client)
        demo_quotes_list(client)
        demo_single_quote(client)
    except AuthError as exc:
        print(f"\n[auth error] Your API token was rejected: {exc}", file=sys.stderr)
        sys.exit(1)
    except NotFoundError as exc:
        print(f"\n[not found] No resource with ID '{exc.resource_id}'.", file=sys.stderr)
        sys.exit(1)
    except RateLimitError as exc:
        wait = f"{exc.retry_after}s" if exc.retry_after else "a moment"
        print(f"\n[rate limit] Too many requests — wait {wait} and retry.", file=sys.stderr)
        sys.exit(1)
    except LotRError as exc:
        print(f"\n[sdk error] {exc}", file=sys.stderr)
        sys.exit(1)

    print("\nDone.\n")


if __name__ == "__main__":
    main()
