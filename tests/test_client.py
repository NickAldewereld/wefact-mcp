"""Tests for WeFactClient against a respx-mocked WeFact API."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from wefact_mcp.client import WeFactClient, WeFactError


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_init_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEFACT_API_KEY", "abc")
    c = WeFactClient()
    assert c.api_key == "abc"
    assert c.endpoint.endswith("/v2/")


def test_init_explicit_key() -> None:
    c = WeFactClient(api_key="explicit")
    assert c.api_key == "explicit"


def test_init_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEFACT_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API key"):
        WeFactClient()


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


@respx.mock
async def test_request_includes_api_key_and_body(endpoint: str) -> None:
    route = respx.post(endpoint).respond(
        200, json={"status": "success", "totalresults": 0, "debtors": []}
    )
    async with WeFactClient() as c:
        await c.request("debtor", "list", {"limit": 10})

    sent = json.loads(route.calls.last.request.content)
    assert sent == {
        "api_key": "test-key",
        "controller": "debtor",
        "action": "list",
        "limit": 10,
    }


@respx.mock
async def test_request_returns_parsed_json_on_success(endpoint: str) -> None:
    respx.post(endpoint).respond(
        200,
        json={
            "status": "success",
            "totalresults": 1,
            "debtors": [{"DebtorCode": "DB1"}],
        },
    )
    async with WeFactClient() as c:
        data = await c.request("debtor", "list", {"limit": 1})
    assert data["status"] == "success"
    assert data["debtors"][0]["DebtorCode"] == "DB1"


@respx.mock
async def test_request_raises_on_error_status(endpoint: str) -> None:
    respx.post(endpoint).respond(
        200,
        json={
            "status": "error",
            "errors": ["Debtor not found"],
        },
    )
    async with WeFactClient() as c:
        with pytest.raises(WeFactError) as ei:
            await c.request("debtor", "show", {"DebtorCode": "DB99"})
    assert "Debtor not found" in str(ei.value)
    assert ei.value.errors == ["Debtor not found"]


@respx.mock
async def test_request_redacts_api_key_from_logged_payload(endpoint: str) -> None:
    """On error, the WeFactError payload should not contain the api_key."""
    respx.post(endpoint).respond(
        200,
        json={"status": "error", "errors": ["nope"]},
    )
    async with WeFactClient() as c:
        try:
            await c.request("debtor", "list")
        except WeFactError as e:
            assert e.payload.get("request", {}).get("api_key") == "***"


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


@respx.mock
async def test_retries_on_transient_then_succeeds(endpoint: str) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="upstream down")
        return httpx.Response(200, json={"status": "success", "debtors": []})

    respx.post(endpoint).mock(side_effect=handler)

    async with WeFactClient() as c:
        data = await c.request("debtor", "list")
    assert data["status"] == "success"
    assert calls["n"] == 3


@respx.mock
async def test_exhausts_retries_then_raises(endpoint: str) -> None:
    respx.post(endpoint).respond(503, text="still down")
    async with WeFactClient() as c:
        with pytest.raises(httpx.HTTPError):
            await c.request("debtor", "list")


# ---------------------------------------------------------------------------
# list_all pagination
# ---------------------------------------------------------------------------


@respx.mock
async def test_list_all_paginates(endpoint: str) -> None:
    page1 = [{"DebtorCode": f"DB{i}"} for i in range(100)]
    page2 = [{"DebtorCode": f"DB{i}"} for i in range(100, 142)]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        offset = body.get("offset", 0)
        if offset == 0:
            return httpx.Response(200, json={"status": "success", "debtors": page1})
        if offset == 100:
            return httpx.Response(200, json={"status": "success", "debtors": page2})
        return httpx.Response(200, json={"status": "success", "debtors": []})

    respx.post(endpoint).mock(side_effect=handler)

    async with WeFactClient() as c:
        items = await c.list_all("debtor", page_size=100)
    assert len(items) == 142
    assert items[-1]["DebtorCode"] == "DB141"


@respx.mock
async def test_list_all_falls_back_when_plural_missing(endpoint: str) -> None:
    """If the response doesn't have a controller-plural key, use the first list."""
    respx.post(endpoint).respond(
        200,
        json={
            "status": "success",
            "totalresults": 1,
            "items": [{"name": "weird endpoint"}],
        },
    )
    async with WeFactClient() as c:
        items = await c.list_all("oddly", page_size=100)
    assert items == [{"name": "weird endpoint"}]
