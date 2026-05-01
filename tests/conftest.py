"""Shared pytest fixtures for wefact-mcp tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default env so WeFactClient() constructs without arguments."""
    monkeypatch.setenv("WEFACT_API_KEY", "test-key")


@pytest.fixture
def endpoint() -> str:
    return "https://api.mijnwefact.nl/v2/"
