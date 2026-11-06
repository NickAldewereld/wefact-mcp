"""Smoke tests for the MCP tool layer (FastMCP routing + JSON serialisation)."""

from __future__ import annotations

import base64
import json

import pytest
import respx
from mcp.server.fastmcp import Image

from wefact_mcp import server


def _unwrap(tool_obj):
    """FastMCP tools may be either raw callables or wrappers with .fn / .func."""
    for attr in ("fn", "func", "__wrapped__"):
        inner = getattr(tool_obj, attr, None)
        if callable(inner):
            return inner
    if callable(tool_obj):
        return tool_obj
    raise TypeError(f"Cannot unwrap tool: {tool_obj!r}")


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    server._client = None
    yield
    server._client = None


@respx.mock
async def test_whoami_returns_summary(endpoint: str) -> None:
    respx.post(endpoint).respond(
        200,
        json={
            "status": "success",
            "totalresults": 1,
            "debtors": [{"DebtorCode": "DB1"}],
        },
    )
    out = await _unwrap(server.whoami)()
    parsed = json.loads(out)
    assert parsed["status"] == "success"
    assert parsed["first_debtor_code"] == "DB1"


@respx.mock
async def test_list_debtors_passes_search_params(endpoint: str) -> None:
    route = respx.post(endpoint).respond(
        200,
        json={
            "status": "success",
            "totalresults": 1,
            "debtors": [{"DebtorCode": "DB7", "EmailAddress": "x@example.com"}],
        },
    )
    out = await _unwrap(server.list_debtors)(
        search_at="EmailAddress",
        search_for="x@example.com",
        limit_pages=1,
    )
    parsed = json.loads(out)
    assert parsed["status"] == "success"

    sent = json.loads(route.calls.last.request.content)
    assert sent["controller"] == "debtor"
    assert sent["action"] == "list"
    assert sent["searchat"] == "EmailAddress"
    assert sent["searchfor"] == "x@example.com"


@respx.mock
async def test_get_invoice_requires_identifier_or_code(endpoint: str) -> None:
    out = await _unwrap(server.get_invoice)()
    parsed = json.loads(out)
    assert parsed["status"] == "error"


@respx.mock
async def test_create_invoice_routes_through_request(endpoint: str) -> None:
    route = respx.post(endpoint).respond(
        200,
        json={
            "status": "success",
            "invoice": {
                "InvoiceCode": "[concept]0001",
                "DebtorCode": "DB1",
            },
        },
    )
    out = await _unwrap(server.create_invoice)(
        debtor_code="DB1",
        invoice_lines=[
            {"Description": "Test line", "PriceExcl": 100, "Number": 1},
        ],
    )
    parsed = json.loads(out)
    assert parsed["invoice"]["DebtorCode"] == "DB1"

    sent = json.loads(route.calls.last.request.content)
    assert sent["controller"] == "invoice"
    assert sent["action"] == "add"
    assert sent["DebtorCode"] == "DB1"
    assert sent["InvoiceLines"][0]["Description"] == "Test line"


@respx.mock
async def test_wefact_request_is_a_pure_passthrough(endpoint: str) -> None:
    route = respx.post(endpoint).respond(
        200,
        json={"status": "success", "products": [{"ProductCode": "P1"}]},
    )
    out = await _unwrap(server.wefact_request)(
        controller="product",
        action="list",
        params={"limit": 5},
    )
    parsed = json.loads(out)
    assert parsed["status"] == "success"

    sent = json.loads(route.calls.last.request.content)
    assert sent["controller"] == "product"
    assert sent["action"] == "list"
    assert sent["limit"] == 5


@respx.mock
async def test_error_propagates_as_json(endpoint: str) -> None:
    respx.post(endpoint).respond(
        200,
        json={
            "status": "error",
            "errors": ["Permission denied"],
        },
    )
    out = await _unwrap(server.list_debtors)(limit_pages=1)
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert "Permission denied" in parsed["errors"]


@respx.mock
async def test_mark_invoice_paid(endpoint: str) -> None:
    route = respx.post(endpoint).respond(
        200,
        json={"status": "success", "invoice": {"InvoiceCode": "202401001"}},
    )
    out = await _unwrap(server.mark_invoice_paid)(
        invoice_code="202401001",
        pay_date="2026-05-01",
        payment_method="wire",
    )
    parsed = json.loads(out)
    assert parsed["invoice"]["InvoiceCode"] == "202401001"

    sent = json.loads(route.calls.last.request.content)
    assert sent["controller"] == "invoice"
    assert sent["action"] == "markaspaid"
    assert sent["InvoiceCode"] == "202401001"
    assert sent["PayDate"] == "2026-05-01"
    assert sent["PaymentMethod"] == "wire"


@respx.mock
async def test_list_creditinvoice_attachments_returns_array(endpoint: str) -> None:
    respx.post(endpoint).respond(
        200,
        json={
            "status": "success",
            "creditinvoice": {
                "Identifier": "42",
                "CreditInvoiceCode": "CI42",
                "Attachments": [
                    {"Identifier": "7", "Filename": "bon.pdf"},
                    {"Identifier": "8", "Filename": "foto.jpg"},
                ],
            },
        },
    )
    out = await _unwrap(server.list_creditinvoice_attachments)(identifier=42)
    parsed = json.loads(out)
    assert parsed["status"] == "success"
    assert parsed["totalresults"] == 2
    assert parsed["attachments"][0]["Filename"] == "bon.pdf"


@respx.mock
async def test_list_creditinvoice_attachments_requires_id(endpoint: str) -> None:
    out = await _unwrap(server.list_creditinvoice_attachments)()
    parsed = json.loads(out)
    assert parsed["status"] == "error"


@respx.mock
async def test_download_attachment_pdf_returns_images(endpoint: str) -> None:
    import pymupdf
    doc = pymupdf.open(); doc.new_page()
    pdf_b64 = base64.b64encode(doc.tobytes()).decode()
    respx.post(endpoint).respond(
        200,
        json={"status": "success", "attachment": {
            "Filename": "bon.pdf", "Base64": pdf_b64, "MIME": "application/pdf"}},
    )
    out = await _unwrap(server.download_creditinvoice_attachment)(
        attachment_identifier=7, credit_invoice_identifier=42)
    assert isinstance(out, list) and len(out) >= 1
    assert isinstance(out[0], Image)


@respx.mock
async def test_download_attachment_image_passthrough(endpoint: str) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"body"
    respx.post(endpoint).respond(
        200,
        json={"status": "success", "attachment": {
            "Filename": "foto.png", "Base64": base64.b64encode(png).decode(), "MIME": "image/png"}},
    )
    out = await _unwrap(server.download_creditinvoice_attachment)(
        attachment_identifier=8, credit_invoice_identifier=42)
    assert isinstance(out[0], Image)


@respx.mock
async def test_download_attachment_sends_correct_params(endpoint: str) -> None:
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    route = respx.post(endpoint).respond(
        200, json={"status": "success", "attachment": {"Filename": "f.png", "Base64": png, "MIME": "image/png"}})
    await _unwrap(server.download_creditinvoice_attachment)(
        attachment_identifier=7, credit_invoice_code="CI42")
    sent = json.loads(route.calls.last.request.content)
    assert sent["controller"] == "attachment"
    assert sent["action"] == "download"
    assert sent["Type"] == "creditinvoice"
    assert sent["Identifier"] == 7
    assert sent["CreditInvoiceCode"] == "CI42"


@respx.mock
async def test_download_attachment_requires_attachment_identifier_or_filename(
    endpoint: str,
) -> None:
    with pytest.raises(ValueError):
        await _unwrap(server.download_creditinvoice_attachment)(
            credit_invoice_identifier=42
        )


@respx.mock
async def test_download_attachment_requires_credit_invoice_identifier_or_code(
    endpoint: str,
) -> None:
    with pytest.raises(ValueError):
        await _unwrap(server.download_creditinvoice_attachment)(
            attachment_identifier=7
        )


@respx.mock
async def test_update_credit_invoice_sends_edit(endpoint: str) -> None:
    route = respx.post(endpoint).respond(200, json={"status": "success", "creditinvoice": {"Identifier": "42"}})
    out = await _unwrap(server.update_credit_invoice)(
        identifier=42, fields={"AmountExcl": "12.34", "Description": "Lunch"})
    parsed = json.loads(out)
    assert parsed["status"] == "success"
    sent = json.loads(route.calls.last.request.content)
    assert sent["controller"] == "creditinvoice"
    assert sent["action"] == "edit"
    assert sent["Identifier"] == 42
    assert sent["AmountExcl"] == "12.34"


@respx.mock
async def test_update_credit_invoice_requires_id(endpoint: str) -> None:
    out = await _unwrap(server.update_credit_invoice)(fields={"x": 1})
    assert json.loads(out)["status"] == "error"
