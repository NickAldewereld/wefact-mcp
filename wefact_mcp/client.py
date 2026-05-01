"""
Thin async HTTP client for the WeFact API v2.

The WeFact API is not RESTful: every call is a POST to a single endpoint
(https://api.mijnwefact.nl/v2/) with a JSON body containing:

    {
        "controller": "debtor",
        "action": "show",
        "api_key": "...",
        ...params
    }

Responses are JSON with at minimum a `status` field ("success" or "error").
On error, an `errors` array is included.

This client is intentionally low-level. It does not model individual
resources — that is left to the higher-level MCP tool layer (and to
`wefact_request` for ad-hoc calls). This keeps the surface area small
and lets us add conveniences only where they earn their keep.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://api.mijnwefact.nl/v2/"
DEFAULT_TIMEOUT = 30.0
DEFAULT_USER_AGENT = "wefact-mcp/0.1.0 (+https://github.com/NickAldewereld/wefact-mcp)"


class WeFactError(Exception):
    """Raised when WeFact returns status != 'success'."""

    def __init__(self, message: str, *, errors: list[str] | None = None, payload: dict | None = None):
        super().__init__(message)
        self.errors = errors or []
        self.payload = payload or {}


class WeFactClient:
    """Async client for the WeFact JSON-over-POST API."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: float = DEFAULT_TIMEOUT,
        user_agent: str = DEFAULT_USER_AGENT,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key or os.environ.get("WEFACT_API_KEY")
        if not self.api_key:
            raise ValueError(
                "No WeFact API key provided. Set WEFACT_API_KEY env var "
                "or pass api_key to WeFactClient."
            )
        self.endpoint = endpoint
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "WeFactClient":
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent, "Content-Type": "application/json"},
        )
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        controller: str,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a single POST call to the WeFact API.

        Returns the parsed JSON response on success. Raises WeFactError on
        a status of 'error' (with the messages WeFact returned).
        """
        if self._client is None:
            # Allow ad-hoc usage without a context manager.
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent, "Content-Type": "application/json"},
            )

        body = {
            "api_key": self.api_key,
            "controller": controller,
            "action": action,
        }
        if params:
            body.update(params)

        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self.max_retries:
            try:
                resp = await self._client.post(self.endpoint, json=body)
                resp.raise_for_status()
                data = resp.json()
                break
            except (httpx.HTTPError, ValueError) as e:
                last_exc = e
                attempt += 1
                if attempt > self.max_retries:
                    raise
                # Exponential backoff: 0.5s, 1s, 2s ...
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
        else:  # pragma: no cover
            raise last_exc  # type: ignore[misc]

        status = data.get("status")
        if status == "success":
            return data

        errors = data.get("errors") or []
        msg = "; ".join(str(e) for e in errors) if errors else f"WeFact error (no message): {data}"
        # Redact api_key from logged payloads.
        safe_body = {**body, "api_key": "***"}
        logger.warning("WeFact error: controller=%s action=%s errors=%s", controller, action, errors)
        raise WeFactError(msg, errors=[str(e) for e in errors], payload={"request": safe_body, "response": data})

    async def list_all(
        self,
        controller: str,
        *,
        action: str = "list",
        page_size: int = 100,
        max_pages: int = 1000,
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Iterate `controller`/`action` pages and return all items.

        WeFact uses `offset` + `limit` parameters and returns a list keyed by
        the plural of the controller (e.g. 'debtors', 'invoices'). When the
        plural cannot be guessed, we fall back to the first list-valued field.
        """
        items: list[dict[str, Any]] = []
        offset = 0
        for _ in range(max_pages):
            params = {"offset": offset, "limit": page_size, **(extra_params or {})}
            data = await self.request(controller, action, params)
            page = _extract_list(data, controller)
            if not page:
                break
            items.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return items

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _extract_list(data: dict[str, Any], controller: str) -> list[dict[str, Any]]:
    """Find the list of items in a WeFact list response.

    WeFact pluralises most controllers naively (debtor -> debtors).
    Subscriptions, products etc. follow the same pattern, but a few don't,
    so we fall back to the first list-valued top-level field.
    """
    candidates = [
        f"{controller}s",
        controller,
        # Common irregulars
        "debtors", "creditors", "invoices", "creditinvoices", "products",
        "subscriptions", "tickets", "groups", "items",
    ]
    for key in candidates:
        v = data.get(key)
        if isinstance(v, list):
            return v
    # Last resort: any list-valued field that isn't 'errors'/'success'.
    for k, v in data.items():
        if k in {"errors", "success"}:
            continue
        if isinstance(v, list):
            return v
    return []
