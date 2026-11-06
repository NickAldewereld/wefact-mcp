# AI-bonnenextractie in wefact-mcp — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** wefact-mcp uitbreiden zodat Claude de ruwe bijlage-bestanden van een creditinvoice (inkoop/onkosten) kan ophalen als vision-leesbare beelden, extraheren, en — na goedkeuring — terugschrijven.

**Architecture:** Drie nieuwe FastMCP-tools in `wefact_mcp/server.py` + een `attachments.py`-helper voor PDF→PNG. Bestaande patronen: WeFact-veldnamen verbatim, JSON-strings via `_result()`, tools roepen `_get_client().request(controller, action, params)` aan. TDD met `respx`-gemockte API.

**Tech Stack:** Python ≥3.10, FastMCP (`mcp>=1.0`), httpx, respx (tests), PyMuPDF (nieuw, PDF-render).

## Global Constraints

- **Test-runner:** `python -m pytest` (venv: `.venv/bin/python -m pytest`). CI = `.github/workflows/ci.yml` (ruff + pytest) moet groen blijven.
- **WeFact API:** JSON-over-POST naar `https://api.mijnwefact.nl/v2/`, body `{controller, action, api_key, ...params}`. Client: `WeFactClient.request(controller, action, params) -> dict`. Nooit tegen productie-API-key testen — alle tests mocken via `respx` (zie `tests/conftest.py`: `WEFACT_API_KEY=test-key`).
- **WeFact-veldnamen verbatim** (zoals de hele codebase), zodat developer.wefact.com bruikbaar blijft.
- **Human-in-the-loop:** `update_credit_invoice` schrijft pas terug ná expliciete goedkeuring; nooit auto-schrijven. (Dit is een gedrags-instructie in de tool-docstring + server-instructions, geen code-gate.)
- **Content:** afbeeldingen/PDF-pagina's teruggeven als `mcp.server.fastmcp.Image(data=<png_bytes>, format="png")`. JSON-tools blijven `_result()`-strings.
- **Commits:** geen Co-Authored-By / Claude-attributie (Nick enige auteur). Kleine commits per taak.
- **Branch:** `feat/ai-bonnenextractie`. NIET naar `main`/PyPI publiceren tot af + akkoord.

---

## Task 1: PyMuPDF-dependency + `attachments.py` render-helper

**Files:**
- Modify: `pyproject.toml` (voeg `pymupdf` toe aan `dependencies`)
- Create: `wefact_mcp/attachments.py`
- Create: `tests/test_attachments.py`

**Interfaces:**
- Produces: `attachment_to_images(data: bytes, mime: str, *, max_pages: int = 5) -> list[tuple[bytes, str]]` — retourneert lijst van `(image_bytes, format)`. `image/*` → passthrough `[(data, <subtype>)]`; `application/pdf` → per pagina PNG; anders `ValueError`.

- [ ] **Step 1: Failing test**

Create `tests/test_attachments.py`:
```python
"""Tests for attachment → vision-image conversion."""
from __future__ import annotations

import pymupdf
import pytest

from wefact_mcp.attachments import attachment_to_images


def _one_page_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Bon: EUR 12,34")
    return doc.tobytes()


def test_pdf_renders_to_png_pages() -> None:
    images = attachment_to_images(_one_page_pdf(), "application/pdf")
    assert len(images) >= 1
    data, fmt = images[0]
    assert fmt == "png"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


def test_image_is_passed_through() -> None:
    fake_png = b"\x89PNG\r\n\x1a\n" + b"rest"
    images = attachment_to_images(fake_png, "image/png")
    assert images == [(fake_png, "png")]


def test_jpeg_passthrough_format() -> None:
    images = attachment_to_images(b"\xff\xd8\xff", "image/jpeg")
    assert images[0][1] in ("jpeg", "jpg")


def test_unknown_mime_raises() -> None:
    with pytest.raises(ValueError, match="ondersteun"):
        attachment_to_images(b"data", "application/zip")


def test_pdf_respects_max_pages() -> None:
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    images = attachment_to_images(doc.tobytes(), "application/pdf", max_pages=2)
    assert len(images) == 2
```

- [ ] **Step 2: Run — verify it fails**

Run: `.venv/bin/python -m pytest tests/test_attachments.py -q`
Expected: FAIL (ModuleNotFoundError: wefact_mcp.attachments / pymupdf not installed).

- [ ] **Step 3: Install pymupdf + add to pyproject**

In `pyproject.toml` `dependencies` array (naast `mcp>=1.0`, `httpx`): voeg toe `"pymupdf>=1.24"`. Installeer in de venv: `.venv/bin/python -m pip install "pymupdf>=1.24"`.

- [ ] **Step 4: Implement `wefact_mcp/attachments.py`**

```python
"""Convert WeFact attachment bytes into vision-readable images.

Images are passed through; PDFs are rendered to PNG per page (PyMuPDF).
The MCP download tool hands the resulting PNGs to Claude as Image content.
"""
from __future__ import annotations

import pymupdf

_PDF_DPI = 170
_IMAGE_SUBTYPES = {"png": "png", "jpeg": "jpeg", "jpg": "jpeg", "webp": "webp", "gif": "gif"}


def attachment_to_images(data: bytes, mime: str, *, max_pages: int = 5) -> list[tuple[bytes, str]]:
    """Return a list of (image_bytes, format) for a downloaded attachment.

    - image/* → passthrough as a single item.
    - application/pdf → one PNG per page (capped at max_pages).
    - anything else → ValueError.
    """
    mime = (mime or "").split(";")[0].strip().lower()

    if mime.startswith("image/"):
        subtype = mime.split("/", 1)[1]
        return [(data, _IMAGE_SUBTYPES.get(subtype, subtype))]

    if mime == "application/pdf":
        pages: list[tuple[bytes, str]] = []
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            for page in doc:
                if len(pages) >= max_pages:
                    break
                pix = page.get_pixmap(dpi=_PDF_DPI)
                pages.append((pix.tobytes("png"), "png"))
        return pages

    raise ValueError(f"Bestandstype wordt niet ondersteund voor vision-extractie: {mime!r}")
```

- [ ] **Step 5: Run — verify pass**

Run: `.venv/bin/python -m pytest tests/test_attachments.py -q`
Expected: PASS (5 tests), output pristine.

- [ ] **Step 6: Commit**
```bash
git add pyproject.toml wefact_mcp/attachments.py tests/test_attachments.py
git commit -m "feat: attachment→image helper (PDF→PNG via PyMuPDF)"
```

---

## Task 2: `list_creditinvoice_attachments` tool

**Files:**
- Modify: `wefact_mcp/server.py` (nieuwe tool na `get_credit_invoice`)
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `_get_client().request("creditinvoice", "show", params)`, `_result()`.
- Produces: MCP-tool `list_creditinvoice_attachments(identifier: int | None = None, creditinvoice_code: str | None = None) -> str` — retourneert JSON met de `Attachments`-array uit `creditinvoice/show`.

- [ ] **Step 1: Failing test**

Add to `tests/test_server.py`:
```python
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
```

- [ ] **Step 2: Run — verify fail**

Run: `.venv/bin/python -m pytest tests/test_server.py -k attachments -q`
Expected: FAIL (AttributeError: module 'server' has no attribute 'list_creditinvoice_attachments').

- [ ] **Step 3: Implement the tool**

In `wefact_mcp/server.py`, after `get_credit_invoice` (~line 497):
```python
@mcp.tool()
async def list_creditinvoice_attachments(
    identifier: int | None = None,
    creditinvoice_code: str | None = None,
) -> str:
    """List the attachments (receipt files) on a credit invoice (purchase/expense).

    Returns each attachment's Identifier and Filename so you can then call
    download_creditinvoice_attachment to read the actual file.
    """
    if identifier is None and creditinvoice_code is None:
        return _result({"status": "error", "errors": ["Provide identifier or creditinvoice_code."]})
    params: dict[str, Any] = {}
    if identifier is not None:
        params["Identifier"] = identifier
    if creditinvoice_code is not None:
        params["CreditInvoiceCode"] = creditinvoice_code
    try:
        data = await _get_client().request("creditinvoice", "show", params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    ci = data.get("creditinvoice", data)
    attachments = ci.get("Attachments", []) or []
    return _result({"status": "success", "totalresults": len(attachments), "attachments": attachments})
```

- [ ] **Step 4: Run — verify pass**

Run: `.venv/bin/python -m pytest tests/test_server.py -k attachments -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add wefact_mcp/server.py tests/test_server.py
git commit -m "feat: list_creditinvoice_attachments tool"
```

---

## Task 3: `download_creditinvoice_attachment` tool (base64 → vision Images)

**Files:**
- Modify: `wefact_mcp/server.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `_get_client().request("attachment", "download", params)`, `attachment_to_images()` (Task 1), `mcp.server.fastmcp.Image`.
- Produces: MCP-tool `download_creditinvoice_attachment(attachment_identifier=None, filename=None, creditinvoice_identifier=None, creditinvoice_code=None) -> list[Image]` — de bon als vision-leesbare beelden.

> **Open punt (verifiëren):** exacte respons-keys van `attachment`/`download`. De doc toont waarden voor Identifier/Filename/Base64/MIME. Implementatie leest defensief (`Base64`/`base64`, `MIME`/`MimeType`/`ContentType`, `Filename`). Bevestig tegen een echte respons of de doc en pas de key-lijst aan.

- [ ] **Step 1: Failing test**

Add to `tests/test_server.py` (top: `import base64`, `from mcp.server.fastmcp import Image`):
```python
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
        attachment_identifier=7, creditinvoice_identifier=42)
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
        attachment_identifier=8, creditinvoice_identifier=42)
    assert isinstance(out[0], Image)


@respx.mock
async def test_download_attachment_sends_correct_params(endpoint: str) -> None:
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    route = respx.post(endpoint).respond(
        200, json={"status": "success", "attachment": {"Filename": "f.png", "Base64": png, "MIME": "image/png"}})
    await _unwrap(server.download_creditinvoice_attachment)(
        attachment_identifier=7, creditinvoice_code="CI42")
    sent = json.loads(route.calls.last.request.content)
    assert sent["controller"] == "attachment"
    assert sent["action"] == "download"
    assert sent["Type"] == "creditinvoice"
    assert sent["Identifier"] == 7
    assert sent["CreditInvoiceCode"] == "CI42"
```

- [ ] **Step 2: Run — verify fail**

Run: `.venv/bin/python -m pytest tests/test_server.py -k download_attachment -q`
Expected: FAIL (tool undefined).

- [ ] **Step 3: Implement the tool**

Add imports at top of `server.py`: `import base64` and `from mcp.server.fastmcp import FastMCP, Image`.
Then add the tool after `list_creditinvoice_attachments`:
```python
@mcp.tool()
async def download_creditinvoice_attachment(
    attachment_identifier: int | None = None,
    filename: str | None = None,
    creditinvoice_identifier: int | None = None,
    creditinvoice_code: str | None = None,
) -> list[Image]:
    """Download a credit-invoice attachment (receipt) and return it as image(s)
    you can read with vision. PDFs are rendered to one image per page.

    Use this to read the actual receipt when WeFact's own field extraction is
    incomplete: read the image, extract the missing fields, show them to the
    accountant for approval, then write them back with update_credit_invoice.
    """
    if attachment_identifier is None and filename is None:
        raise ValueError("Provide attachment_identifier or filename.")
    if creditinvoice_identifier is None and creditinvoice_code is None:
        raise ValueError("Provide creditinvoice_identifier or creditinvoice_code.")

    params: dict[str, Any] = {"Type": "creditinvoice"}
    if attachment_identifier is not None:
        params["Identifier"] = attachment_identifier
    if filename is not None:
        params["Filename"] = filename
    if creditinvoice_identifier is not None:
        params["ReferenceIdentifier"] = creditinvoice_identifier
    if creditinvoice_code is not None:
        params["CreditInvoiceCode"] = creditinvoice_code

    data = await _get_client().request("attachment", "download", params)
    att = data.get("attachment", data)
    b64 = att.get("Base64") or att.get("base64") or ""
    mime = att.get("MIME") or att.get("MimeType") or att.get("ContentType") or ""
    if not b64:
        raise ValueError("WeFact returned no file content for this attachment.")

    raw = base64.b64decode(b64)
    images = attachment_to_images(raw, mime)  # raises ValueError on unsupported type
    return [Image(data=img, format=fmt) for img, fmt in images]
```
Add the import near the top: `from .attachments import attachment_to_images`.

> **Open punt (verifiëren):** dat FastMCP een `list[Image]`-return omzet naar meerdere ImageContent-blokken bij de doel-clients. Zo niet: val terug op één beeld (eerste pagina) + een tekstnotitie met paginacount, of plak PDF-pagina's verticaal tot één PNG. Bevestigen met een echte MCP-client (Claude Desktop/Code).

- [ ] **Step 4: Run — verify pass**

Run: `.venv/bin/python -m pytest tests/test_server.py -k download_attachment -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add wefact_mcp/server.py tests/test_server.py
git commit -m "feat: download_creditinvoice_attachment tool (base64 → vision images)"
```

---

## Task 4: `update_credit_invoice` tool (write-back)

**Files:**
- Modify: `wefact_mcp/server.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `_get_client().request("creditinvoice", "edit", params)`, `_result()`.
- Produces: MCP-tool `update_credit_invoice(identifier=None, creditinvoice_code=None, fields=dict) -> str`.

> **Open punt (verifiëren):** exacte edit-action voor creditinvoice (aangenomen `creditinvoice`/`edit`, consistent met WeFact's `edit`-conventie voor andere controllers). Bevestig op developer.wefact.com; anders `wefact_request`-fallback.

- [ ] **Step 1: Failing test**
```python
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
```

- [ ] **Step 2: Run — verify fail**

Run: `.venv/bin/python -m pytest tests/test_server.py -k update_credit_invoice -q` → FAIL.

- [ ] **Step 3: Implement**
```python
@mcp.tool()
async def update_credit_invoice(
    identifier: int | None = None,
    creditinvoice_code: str | None = None,
    fields: dict[str, Any] | None = None,
) -> str:
    """Write corrected fields back to a credit invoice (purchase/expense).

    Only call this AFTER a human has approved the extracted values — never
    write financial data back automatically. Field names are WeFact field
    names (see developer.wefact.com/creditinvoice).
    """
    if identifier is None and creditinvoice_code is None:
        return _result({"status": "error", "errors": ["Provide identifier or creditinvoice_code."]})
    if not fields:
        return _result({"status": "error", "errors": ["Provide fields to update."]})
    params: dict[str, Any] = dict(fields)
    if identifier is not None:
        params["Identifier"] = identifier
    if creditinvoice_code is not None:
        params["CreditInvoiceCode"] = creditinvoice_code
    try:
        data = await _get_client().request("creditinvoice", "edit", params)
    except WeFactError as e:
        return _result({"status": "error", "errors": e.errors})
    return _result(data)
```

- [ ] **Step 4: Run — verify pass**

Run: `.venv/bin/python -m pytest tests/test_server.py -k update_credit_invoice -q` → PASS.

- [ ] **Step 5: Commit**
```bash
git add wefact_mcp/server.py tests/test_server.py
git commit -m "feat: update_credit_invoice tool (human-approved write-back)"
```

---

## Task 5: Server-instructions, docs, versie + volledige suite

**Files:**
- Modify: `wefact_mcp/server.py` (FastMCP `instructions=` uitbreiden met de bonnen-flow)
- Modify: `README.md` (headline-feature + korte flow-uitleg)
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml` (`version` 0.1.0 → 0.2.0)
- Modify: `wefact_mcp/client.py` (`DEFAULT_USER_AGENT` → 0.2.0)

- [ ] **Step 1: Update server instructions**

In `mcp = FastMCP("wefact", instructions=(...))`, voeg een zin toe:
```
"Voor onkosten/inkoop met een matige veld-extractie: gebruik "
"list_creditinvoice_attachments + download_creditinvoice_attachment om de bon "
"met vision te lezen, toon de accountant een voorstel, en schrijf pas na "
"goedkeuring terug met update_credit_invoice."
```

- [ ] **Step 2: README headline + flow**

Voeg een sectie toe (bijv. onder de quick start): "### AI leest je bonnen" — 3 zinnen wat het doet + de 5-staps flow (list → download → extract → approve → write). Noem dat PDF's automatisch naar beeld worden gerenderd.

- [ ] **Step 3: CHANGELOG + versie-bump**

`CHANGELOG.md`: nieuwe `## [0.2.0]`-sectie met de 3 tools + PyMuPDF-dep. `pyproject.toml`: `version = "0.2.0"`. `client.py`: `DEFAULT_USER_AGENT = "wefact-mcp/0.2.0 (+https://github.com/NickAldewereld/wefact-mcp)"`.

- [ ] **Step 4: Volledige suite + lint**

Run: `.venv/bin/python -m pytest -q` → alle tests groen (bestaand + nieuw), output pristine.
Run: `.venv/bin/ruff check .` (indien ruff in CI) → schoon.
Run: `.venv/bin/python -c "import wefact_mcp.server"` → importeert zonder error (sanity op de nieuwe imports).

- [ ] **Step 5: Commit**
```bash
git add wefact_mcp/server.py wefact_mcp/client.py README.md CHANGELOG.md pyproject.toml
git commit -m "docs+chore: bonnen-feature in instructions/README/CHANGELOG; bump 0.2.0"
```

---

## Eind-verificatie (na alle taken)

- [ ] `.venv/bin/python -m pytest -q` volledig groen; geen warnings/noise.
- [ ] `ruff` schoon (CI-pariteit).
- [ ] `import wefact_mcp.server` werkt; de 3 nieuwe tools staan in `mcp` geregistreerd.
- [ ] Geen productie-API-calls in tests (alles `respx`-gemockt).
- [ ] 4 open punten uit de spec afgevinkt of expliciet als bekend-risico genoteerd (edit-action, Attachments-keys, base64-respons-shape, FastMCP multi-Image).
- [ ] Geen Co-Authored-By in de commits.
- [ ] **Niet publiceren naar PyPI** tot Nick akkoord; release verloopt via `.github/workflows/publish.yml` op een tag.

## Handmatige integratie-check (aanbevolen vóór release, buiten TDD)

Tegen een **echte** WeFact-testadministratie (of Matthews Neno-omgeving als design-partner), niet Nick's productie: één inkoopfactuur met PDF-bon → in Claude Desktop/Code: list → download (bevestig dat Claude de bon als beeld ziet) → extract → approve → update. Dit valideert de 4 open punten end-to-end (echte API-key-namen + FastMCP-Image-rendering) die unit-tests met mocks niet dekken.
