"""
Shared pytest configuration.

Integration tests are gated behind --integration and require LOTR_API_KEY.
Without the flag, all tests marked @pytest.mark.integration are skipped
automatically — no env var needed to run the unit suite.
"""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register --integration CLI flag."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests against the live API (requires LOTR_API_KEY)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip @pytest.mark.integration tests unless --integration is passed."""
    if config.getoption("--integration"):
        return
    skip = pytest.mark.skip(
        reason="Integration tests require --integration flag and LOTR_API_KEY env var"
    )
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip)
