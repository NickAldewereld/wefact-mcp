"""
WeFact MCP server.

Exposes the WeFact JSON API as MCP tools so any MCP-compatible client
(Claude Desktop, Claude Code, Cursor, etc.) can read and modify your
WeFact administration.

Design notes:
  * The thin layer is `wefact_request`, which lets you call any
    controller/action combination — useful for endpoints we haven't
    wrapped yet, and as a safety valve when WeFact ships new ones.
  * Higher-level tools wrap the most common operations (list/get/create
    for debtors, invoices, products, subscriptions, credit invoices)
    with parameter names that match the WeFact docs verbatim. We keep
    the WeFact field names rather than translating to Pythonic ones,
    so the docs at developer.wefact.com remain directly usable.
  * Pagination: list tools default to fetching all pages. Pass
    `limit_pages=1` if you only want the first page (faster, useful
    for exploration).
  * Modified-since filtering: WeFact supports a `modified` filter on
    most list endpoints, which is critical for incremental sync.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp.server.fastmcp import FastMCP

from .client import WeFactClient, WeFactError

logger = logging.getLogger("wefact-mcp")

# Single client instance for the lifetime of the server process. Created
# lazily on first use so importing this module (e.g. for tests) doesn't
# require WEFACT_API_KEY to be set.
_client: WeFactClient | None = None


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[None]:
    global _client
    try:
        yield
    finally:
        if _client is not None:
            await _client.close()
            _client = None


mcp = FastMCP(
    "wefact",
    instructions=(
        "Tools for reading and modifying a WeFact administration via the v2 API. "
        "Use `wefact_request` for any endpoint not covered by a dedicated tool. "
        "All tools return parsed JSON from WeFact; errors are raised with the "
        "messages WeFact returned."
    ),
    lifespan=_lifespan,
)


def _get_client() -> WeFactClient:
    global _client
    if _client is None:
        _client = WeFactClient()
    return _client


def _result(data: Any) -> str:
    """Serialise tool output. MCP returns text; JSON keeps it round-trippable."""
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# --------------------------------------------------------------------------
# Generic escape hatch
# --------------------------------------------------------------------------


@mcp.tool()
async def wefact_request(
    controller: str,
    action: str,
    params: dict[str, Any] | None = None,
) -> str:
    """Call any WeFact controller/action directly.

    Use this for endpoints not covered by the dedicated tools below, or to
    pass parameters that the dedicated tools don't expose.

    Args:
        controller: WeFact controller name (e.g. "debtor", "invoice",
            "subscription", "creditinvoice", "product", "ticket", "group").
        action: Action on that controller (e.g. "list", "show", "add",
            "edit", "delete", "send", "credit", "markaspaid").
        params: Extra parameters as a dict. Field names match the WeFact
            docs at developer.wefact.com (e.g. "DebtorCode", "Identifier",
            "InvoiceLines"). Do NOT include the api_key.

    Returns:
        JSON-encoded response from WeFact.
    """
    client = _get_client()
    try:
        data = await client.request(controller, action, params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors, "request": {"controller": controller, "action": action}})
    return _result(data)


# --------------------------------------------------------------------------
# Debtors
# --------------------------------------------------------------------------


@mcp.tool()
async def list_debtors(
    search_at: str | None = None,
    search_for: str | None = None,
    modified_since: str | None = None,
    limit_pages: int | None = None,
) -> str:
    """List all debtors (customers).

    Args:
        search_at: Field to search in (e.g. "EmailAddress", "CompanyName",
            "DebtorCode"). Optional.
        search_for: Value to search for. Required if search_at is given.
        modified_since: ISO date or datetime. Only return debtors modified
            after this point. Critical for incremental sync.
        limit_pages: If set, fetch at most this many pages (each ~100 items).
            Default fetches all pages.
    """
    extra: dict[str, Any] = {}
    if search_at and search_for:
        extra["searchat"] = search_at
        extra["searchfor"] = search_for
    if modified_since:
        extra["modified"] = {"from": modified_since}
    client = _get_client()
    try:
        if limit_pages == 1:
            data = await client.request("debtor", "list", {"limit": 100, **extra})
            return _result(data)
        items = await client.list_all(
            "debtor",
            max_pages=limit_pages or 1000,
            extra_params=extra,
        )
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result({"status": "success", "totalresults": len(items), "debtors": items})


@mcp.tool()
async def get_debtor(debtor_code: str | None = None, identifier: int | None = None) -> str:
    """Fetch a single debtor by DebtorCode (e.g. 'DB10000') or Identifier."""
    if not debtor_code and not identifier:
        return _result({"status": "error", "errors": ["Provide debtor_code or identifier."]})
    params: dict[str, Any] = {}
    if debtor_code:
        params["DebtorCode"] = debtor_code
    if identifier:
        params["Identifier"] = identifier
    client = _get_client()
    try:
        data = await client.request("debtor", "show", params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result(data)


@mcp.tool()
async def create_debtor(fields: dict[str, Any]) -> str:
    """Create a new debtor.

    Args:
        fields: Dict of WeFact debtor fields. Common ones: CompanyName,
            Initials, SurName, EmailAddress, Address, ZipCode, City,
            Country, TaxNumber, Sex. See developer.wefact.com for the full list.
    """
    client = _get_client()
    try:
        data = await client.request("debtor", "add", fields)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result(data)


@mcp.tool()
async def update_debtor(debtor_code: str, fields: dict[str, Any]) -> str:
    """Update an existing debtor. Only fields you provide are changed."""
    params = {"DebtorCode": debtor_code, **fields}
    client = _get_client()
    try:
        data = await client.request("debtor", "edit", params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result(data)


# --------------------------------------------------------------------------
# Invoices (sales invoices)
# --------------------------------------------------------------------------


@mcp.tool()
async def list_invoices(
    status: int | None = None,
    debtor_code: str | None = None,
    modified_since: str | None = None,
    limit_pages: int | None = None,
) -> str:
    """List invoices.

    Args:
        status: WeFact invoice status (0=concept, 1=sent, 2=partly paid,
            3=paid, 4=expired, 5=summation, 6=collection). Optional filter.
        debtor_code: Filter to a specific debtor.
        modified_since: ISO date for incremental sync.
        limit_pages: Cap on pages (1 = first page only).
    """
    extra: dict[str, Any] = {}
    if status is not None:
        extra["Status"] = status
    if debtor_code:
        extra["DebtorCode"] = debtor_code
    if modified_since:
        extra["modified"] = {"from": modified_since}
    client = _get_client()
    try:
        if limit_pages == 1:
            data = await client.request("invoice", "list", {"limit": 100, **extra})
            return _result(data)
        items = await client.list_all("invoice", max_pages=limit_pages or 1000, extra_params=extra)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result({"status": "success", "totalresults": len(items), "invoices": items})


@mcp.tool()
async def get_invoice(invoice_code: str | None = None, identifier: int | None = None) -> str:
    """Fetch one invoice by InvoiceCode (e.g. '202401001') or Identifier."""
    if not invoice_code and not identifier:
        return _result({"status": "error", "errors": ["Provide invoice_code or identifier."]})
    params: dict[str, Any] = {}
    if invoice_code:
        params["InvoiceCode"] = invoice_code
    if identifier:
        params["Identifier"] = identifier
    client = _get_client()
    try:
        data = await client.request("invoice", "show", params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result(data)


@mcp.tool()
async def create_invoice(
    debtor_code: str,
    invoice_lines: list[dict[str, Any]],
    extra_fields: dict[str, Any] | None = None,
) -> str:
    """Create a draft invoice.

    Args:
        debtor_code: e.g. 'DB10000'.
        invoice_lines: list of line dicts. Each can have ProductCode, or
            free-form Description + PriceExcl + Number + TaxCode etc.
        extra_fields: any other invoice-level fields (Date, Term, Discount,
            ReferenceNumber, Comment, ...).
    """
    params: dict[str, Any] = {
        "DebtorCode": debtor_code,
        "InvoiceLines": invoice_lines,
    }
    if extra_fields:
        params.update(extra_fields)
    client = _get_client()
    try:
        data = await client.request("invoice", "add", params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result(data)


@mcp.tool()
async def send_invoice(invoice_code: str, send_method: str | None = None) -> str:
    """Send an existing draft invoice to the debtor.

    Args:
        invoice_code: e.g. '[concept]0001' for a draft.
        send_method: optional, e.g. 'email' or 'mail'. Omit for the
            debtor's default.
    """
    params: dict[str, Any] = {"InvoiceCode": invoice_code}
    if send_method:
        params["SendMethod"] = send_method
    client = _get_client()
    try:
        data = await client.request("invoice", "send", params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result(data)


@mcp.tool()
async def credit_invoice(invoice_code: str | None = None, identifier: int | None = None) -> str:
    """Credit (reverse) an existing invoice."""
    params: dict[str, Any] = {}
    if invoice_code:
        params["InvoiceCode"] = invoice_code
    if identifier:
        params["Identifier"] = identifier
    if not params:
        return _result({"status": "error", "errors": ["Provide invoice_code or identifier."]})
    client = _get_client()
    try:
        data = await client.request("invoice", "credit", params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result(data)


@mcp.tool()
async def mark_invoice_paid(
    invoice_code: str,
    pay_date: str | None = None,
    payment_method: str | None = None,
) -> str:
    """Mark an invoice as paid.

    Args:
        invoice_code: e.g. '202401001'.
        pay_date: ISO date. Defaults to today.
        payment_method: e.g. 'cash', 'banktransfer', 'directdebit'.
    """
    params: dict[str, Any] = {"InvoiceCode": invoice_code}
    if pay_date:
        params["PayDate"] = pay_date
    if payment_method:
        params["PaymentMethod"] = payment_method
    client = _get_client()
    try:
        data = await client.request("invoice", "markaspaid", params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result(data)


# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------


@mcp.tool()
async def list_products(
    modified_since: str | None = None,
    limit_pages: int | None = None,
) -> str:
    """List all products."""
    extra: dict[str, Any] = {}
    if modified_since:
        extra["modified"] = {"from": modified_since}
    client = _get_client()
    try:
        if limit_pages == 1:
            data = await client.request("product", "list", {"limit": 100, **extra})
            return _result(data)
        items = await client.list_all("product", max_pages=limit_pages or 1000, extra_params=extra)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result({"status": "success", "totalresults": len(items), "products": items})


@mcp.tool()
async def get_product(product_code: str | None = None, identifier: int | None = None) -> str:
    """Fetch a single product."""
    params: dict[str, Any] = {}
    if product_code:
        params["ProductCode"] = product_code
    if identifier:
        params["Identifier"] = identifier
    if not params:
        return _result({"status": "error", "errors": ["Provide product_code or identifier."]})
    client = _get_client()
    try:
        data = await client.request("product", "show", params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result(data)


# --------------------------------------------------------------------------
# Subscriptions
# --------------------------------------------------------------------------


@mcp.tool()
async def list_subscriptions(
    debtor_code: str | None = None,
    modified_since: str | None = None,
    limit_pages: int | None = None,
) -> str:
    """List subscriptions."""
    extra: dict[str, Any] = {}
    if debtor_code:
        extra["DebtorCode"] = debtor_code
    if modified_since:
        extra["modified"] = {"from": modified_since}
    client = _get_client()
    try:
        if limit_pages == 1:
            data = await client.request("subscription", "list", {"limit": 100, **extra})
            return _result(data)
        items = await client.list_all("subscription", max_pages=limit_pages or 1000, extra_params=extra)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result({"status": "success", "totalresults": len(items), "subscriptions": items})


@mcp.tool()
async def get_subscription(identifier: int | None = None, subscription_code: str | None = None) -> str:
    """Fetch a single subscription."""
    params: dict[str, Any] = {}
    if identifier:
        params["Identifier"] = identifier
    if subscription_code:
        params["SubscriptionCode"] = subscription_code
    if not params:
        return _result({"status": "error", "errors": ["Provide identifier or subscription_code."]})
    client = _get_client()
    try:
        data = await client.request("subscription", "show", params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result(data)


# --------------------------------------------------------------------------
# Credit invoices (purchase invoices / inkoopfacturen)
# --------------------------------------------------------------------------


@mcp.tool()
async def list_credit_invoices(
    creditor_code: str | None = None,
    modified_since: str | None = None,
    limit_pages: int | None = None,
) -> str:
    """List purchase invoices (inkoopfacturen)."""
    extra: dict[str, Any] = {}
    if creditor_code:
        extra["CreditorCode"] = creditor_code
    if modified_since:
        extra["modified"] = {"from": modified_since}
    client = _get_client()
    try:
        if limit_pages == 1:
            data = await client.request("creditinvoice", "list", {"limit": 100, **extra})
            return _result(data)
        items = await client.list_all("creditinvoice", max_pages=limit_pages or 1000, extra_params=extra)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result({"status": "success", "totalresults": len(items), "creditinvoices": items})


@mcp.tool()
async def get_credit_invoice(
    credit_invoice_code: str | None = None, identifier: int | None = None
) -> str:
    """Fetch a single purchase invoice."""
    params: dict[str, Any] = {}
    if credit_invoice_code:
        params["CreditInvoiceCode"] = credit_invoice_code
    if identifier:
        params["Identifier"] = identifier
    if not params:
        return _result({"status": "error", "errors": ["Provide credit_invoice_code or identifier."]})
    client = _get_client()
    try:
        data = await client.request("creditinvoice", "show", params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result(data)


# --------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------


@mcp.tool()
async def whoami() -> str:
    """Sanity-check the API connection. Returns a tiny debtor list response."""
    client = _get_client()
    try:
        data = await client.request("debtor", "list", {"limit": 1})
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    summary = {
        "endpoint": client.endpoint,
        "status": data.get("status"),
        "totalresults": data.get("totalresults"),
        "first_debtor_code": (data.get("debtors") or [{}])[0].get("DebtorCode"),
    }
    return _result(summary)


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------


@mcp.prompt()
def export_to_nixfact() -> str:
    """Walk through exporting a full WeFact administration to NIXFact / ERPNext.

    Use this when you want a structured, repeatable migration plan.
    """
    return (
        "I want to export my WeFact administration to NIXFact (Frappe/ERPNext-based). "
        "Please:\n"
        "1. Use `whoami` to confirm the connection works.\n"
        "2. Use `list_debtors` (with limit_pages=1 first) to inspect the field shape.\n"
        "3. Then page through all debtors, products, invoices, credit invoices, and "
        "subscriptions, saving each batch as JSON.\n"
        "4. Map each WeFact resource to its NIXFact DocType, flagging fields that "
        "don't have a 1:1 equivalent.\n"
        "5. Produce a migration script (Python) that takes the JSON and creates the "
        "Frappe records via bench / REST API.\n"
        "6. Note any features I'd need to build into NIXFact to fully replicate WeFact "
        "(reminder ladders, summation/collection states, custom email templates, etc).\n"
    )


@mcp.prompt()
def feature_audit() -> str:
    """Audit the live WeFact account to inventory every feature in use."""
    return (
        "Audit my live WeFact account to inventory which features I actually use. "
        "Steps:\n"
        "1. Sample debtors, invoices, subscriptions, credit invoices, products.\n"
        "2. Identify all distinct values of: Status, SubStatus, PaymentMethod, "
        "TaxCode, InvoiceMethod, AuthorisationStatus, CostCategory, Currency.\n"
        "3. Detect which optional features I use: discounts, periodic billing, "
        "summations, collections, attachments, multi-currency, multi-language.\n"
        "4. Output a feature-coverage table comparing WeFact-used-by-me vs "
        "NIXFact-already-supports vs NIXFact-needs-to-build.\n"
    )


def run() -> None:
    """Entrypoint: start the MCP server over stdio."""
    mcp.run()
