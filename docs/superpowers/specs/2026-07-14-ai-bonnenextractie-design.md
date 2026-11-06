# Ontwerp — AI-bonnenextractie in wefact-mcp

**Datum:** 2026-07-14
**Repo:** wefact-mcp (Python, FastMCP, AGPL-3.0 + commercieel)
**Aanleiding:** Inbound van Matthew Elworthy (Product @ Neno): WeFact's eigen extractie uit ge-uploade onkostenbonnen (PDF/afbeelding) is matig; accountants moeten missende velden handmatig aanvullen. Vraag: laat Claude de bon-bestanden zélf lezen (vision), de missende data extraheren, en — ná goedkeuring van de accountant — terugschrijven. Dit wordt de headline-feature die commerciële licenties + support verkoopt en generaliseert naar de bredere MCP-connector-lijn (Moneybird/Exact slaan óók bonnen op).

## Doel & niet-doel

**Doel:** wefact-mcp uitbreiden zodat Claude de ruwe bijlage-bestanden van een creditinvoice (= inkoop/onkosten in WeFact) kan ophalen als vision-leesbare content, de velden kan extraheren, en de gecorrigeerde data kan terugschrijven — met de accountant expliciet in de loop.

**Niet-doel:**
- Geen eigen OCR/ML-code: de extractie ís Claude's vision (dat is juist de meerwaarde t.o.v. WeFact).
- Geen auto-schrijven op financiële productiedata: write-back alleen na expliciete goedkeuring in de chat.
- v1 beperkt tot **creditinvoices** (inkoop/onkosten). Reguliere invoices/andere types = later (het download-endpoint is generiek via `Type`, dus uitbreidbaar).
- Geen feature-gating/licentie-check: ship open in wefact-mcp (AGPL), consistent met het huidige model.

## Architectuur

Drie nieuwe MCP-tools in `wefact_mcp/server.py` + bijbehorende client-methodes in `wefact_mcp/client.py`, plus PDF→afbeelding-rendering. Bestaande patronen volgen: WeFact-veldnamen verbatim, JSON-strings terug (behalve de download-tool die beeld-content teruggeeft), `wefact_request` blijft de escape-valve.

### WeFact API (geverifieerd op developer.wefact.com)

- **Listen:** `creditinvoice`/`show` retourneert een `[Attachments]`-array (per bijlage o.a. `Identifier`, `Filename`). → geen apart list-endpoint nodig.
- **Downloaden:** controller `attachment`, action `download`. Params: (`Identifier` OF `Filename`) EN (`ReferenceIdentifier` = creditinvoice-ID OF `CreditInvoiceCode`) EN `Type: creditinvoice`. Respons bevat `Identifier`, `Filename`, **Base64**-bestandsinhoud en **MIME-type**.
- **Terugschrijven:** creditinvoice-edit — action-naam te bevestigen tijdens build (waarschijnlijk `creditinvoice`/`edit`; anders via `wefact_request`). WeFact-veldnamen verbatim.

### Nieuwe tools

1. **`list_creditinvoice_attachments(identifier: int | None, creditinvoice_code: str | None) -> str`**
   Roept `creditinvoice`/`show` aan, retourneert de `Attachments`-array (JSON) zodat Claude weet welke bestanden er zijn (Identifier + Filename).

2. **`download_creditinvoice_attachment(attachment_identifier: int | None, filename: str | None, creditinvoice_identifier: int | None, creditinvoice_code: str | None) -> list[content]`**
   Roept `attachment`/`download` (Type=creditinvoice) aan, decodeert Base64 → bytes. Dan:
   - **afbeelding** (image/*): teruggeven als FastMCP `Image`-content.
   - **PDF** (application/pdf): server-side elke pagina naar PNG renderen (PyMuPDF) en als reeks `Image`-content teruggeven (max N pagina's, configureerbaar; bon is doorgaans 1-2 pagina's).
   - Onbekend/overig: nette foutmelding met MIME-type.
   Claude leest de teruggegeven beelden met vision.

3. **`update_credit_invoice(identifier: int | None, creditinvoice_code: str | None, fields: dict) -> str`**
   Schrijft de gecorrigeerde velden terug naar de creditinvoice (edit-action). Bestaat nog niet; nodig voor de write-back. Human-in-the-loop: Claude roept dit pas aan nadat de accountant in de chat akkoord gaf.

### PDF→afbeelding

**PyMuPDF (`pymupdf`)** — pure wheels, geen system-deps, snel. Render per pagina op ~150-200 DPI naar PNG. Toevoegen als dependency in `pyproject.toml`. Bewuste afweging: één dependency erbij in een nu-lean pakket, gerechtvaardigd omdat onkostenbonnen overwegend PDF zijn en vision-extractie het hele verkoopargument is. (Alternatief document-blob-teruggave verworpen: te client-afhankelijk.)

### Flow (human-in-the-loop by design)

1. Claude: `list_creditinvoice_attachments` → welke bonnen hangen aan de inkoopfactuur.
2. Claude: `download_creditinvoice_attachment` → bon als beeld.
3. Claude leest met vision, extraheert de (missende) velden, **toont een voorstel** aan de accountant in de chat.
4. Accountant keurt goed / corrigeert.
5. Claude: `update_credit_invoice` schrijft de goedgekeurde velden terug. Nooit stap 5 zonder stap 4.

## Verpakking / release

- Open in wefact-mcp (AGPL), zoals de rest. README-headline: "AI leest je bonnen — Claude vult in wat WeFact mist."
- `pyproject.toml`: `pymupdf`-dependency + versie-bump (0.1.0 → 0.2.0, nieuwe feature).
- MCP-server-instructions bijwerken (nieuwe tools noemen). CHANGELOG. PyPI-release via bestaande `.github/workflows/publish.yml`.
- Commerciële licentiepagina (`easeo.nl/diensten/wefact-mcp`) later bijwerken met de feature — buiten deze repo, los.

## Constraints

- **Productiedata:** dit raakt echte WeFact-administraties. Write-back alleen na goedkeuring. Tests tegen mock/fixtures, niet tegen Nick's productie-API-key (zie [[project_nixfact_scope]]). De bestaande test-suite (`tests/test_client.py`, `tests/test_server.py`, `conftest.py`) mockt WeFact; volg dat patroon.
- **WeFact-veldnamen verbatim** (zoals de rest van de codebase), zodat developer.wefact.com direct bruikbaar blijft.
- **Python-stijl:** async, type hints, `_result()` voor JSON-tools, `WeFactError`-afhandeling zoals bestaande tools.
- **Secrets:** `WEFACT_API_KEY` via env, nooit in code/logs (client redigeert de key al in logs).

## Testen

- Client-methodes (`download_attachment`, `list_attachments`, `update_credit_invoice`) unit-getest met gemockte httpx-responses (base64-fixture voor download).
- PDF→afbeelding: test met een kleine sample-PDF-fixture → assert ≥1 PNG-bytes teruggegeven.
- Server-tools: test dat de juiste content-types teruggegeven worden (Image voor afbeelding/PDF, error voor onbekend MIME) met gemockte client.
- Bestaande suite blijft groen. `ruff`/CI (`.github/workflows/ci.yml`) blijft schoon.

## Open punten (bevestigen tijdens build)

1. **Edit-action voor creditinvoice**: exacte controller/action voor terugschrijven (waarschijnlijk `creditinvoice`/`edit`); anders `wefact_request`-fallback. Verifiëren op developer.wefact.com.
2. **`Attachments`-array-velden**: exacte keys per bijlage in `creditinvoice/show` (Identifier/Filename) — bevestigen met een echte respons of de doc.
3. **FastMCP `Image`-content**: bevestigen dat `mcp.server.fastmcp.Image` (of gelijkwaardig) meerdere beelden per tool-return ondersteunt en dat doel-clients (Claude Desktop/Code) ze als vision-input tonen.
4. **Base64-respons-shape**: de doc toont index-achtige velden ([0..3]); exacte JSON-key-namen in de echte respons bevestigen.
