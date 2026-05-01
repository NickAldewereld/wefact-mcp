# wefact-mcp

[![PyPI version](https://img.shields.io/pypi/v/wefact-mcp.svg)](https://pypi.org/project/wefact-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/wefact-mcp.svg)](https://pypi.org/project/wefact-mcp/)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)

An [MCP](https://modelcontextprotocol.io) server for the Dutch invoicing
platform [WeFact](https://www.wefact.nl). Lets any MCP-compatible client
(Claude Desktop, Claude Code, Cursor, Zed, …) read and modify your
WeFact administration via natural language.

> **Stop typing in WeFact. Just tell Claude what to do.**
>
> Looking for the polished install + EULA + email support? Buy a
> commercial license: <https://easeo.nl/diensten/wefact-mcp>.

## Quick start

### 1. Install

```bash
pip install wefact-mcp
```

### 2. Get a WeFact API key

In WeFact: **Instellingen → API**. Generate a key and **whitelist your
machine's IPv4 address** (the API does not yet support IPv6).

### 3. Configure your MCP client

#### Claude Code

```bash
claude mcp add wefact -e WEFACT_API_KEY=your-key-here -- wefact-mcp
```

#### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "wefact": {
      "command": "wefact-mcp",
      "env": { "WEFACT_API_KEY": "your-key-here" }
    }
  }
}
```

Restart your MCP client and the WeFact tools should appear. Try:

> Use the wefact-mcp `whoami` tool.

## Tools

### Generic escape hatch

| Tool | Purpose |
|---|---|
| `wefact_request(controller, action, params)` | Call any WeFact endpoint. |
| `whoami()` | Sanity-check the connection. |

### Debtors (klanten)

`list_debtors`, `get_debtor`, `create_debtor`, `update_debtor`

### Invoices (verkoopfacturen)

`list_invoices`, `get_invoice`, `create_invoice`, `send_invoice`,
`credit_invoice`, `mark_invoice_paid`

### Products

`list_products`, `get_product`

### Subscriptions (abonnementen)

`list_subscriptions`, `get_subscription`

### Credit invoices (inkoopfacturen)

`list_credit_invoices`, `get_credit_invoice`

### Prompts

| Prompt | Purpose |
|---|---|
| `export_to_nixfact` | Walk through migrating a WeFact administration to a Frappe/ERPNext successor. |
| `feature_audit` | Inventory which WeFact features your account actually uses. |

## Field names

Tools that take `fields` or `params` use the **WeFact field names verbatim**
(`DebtorCode`, `InvoiceLines`, `PriceExcl`, …). The docs at
[developer.wefact.com](https://developer.wefact.com) stay directly
applicable — copy parameter names from the docs without translation.

## Pagination & filtering

List tools fetch all pages by default. Pass `limit_pages=1` for the
first page only (useful while exploring). Pass
`modified_since="2026-01-01"` for incremental sync.

## Limitations

- WeFact's API is IPv4 only. Hosting this MCP behind an IPv6-only
  proxy will fail.
- WeFact rate-limits the API. The client retries on transient
  failures with exponential backoff; persistent 429s surface as
  errors.
- The API is not RESTful: every call is a POST to a single endpoint.
- Some `list` endpoints return a flat list rather than the
  controller-plural key; the client falls back to the first
  list-valued field. If you hit an oddity, fall back to
  `wefact_request` and parse the response yourself.

## Security model

- The MCP server runs **on your machine**. No data passes through
  external servers.
- The WeFact API key stays in your local environment (or your MCP
  client's config) — never in our hands.
- No telemetry, no usage tracking, no phone-home.
- Source available for audit (see [Repository](https://github.com/NickAldewereld/wefact-mcp)).
- Independently reviewed for SQL injection, auth bypass, and
  credential leak vectors.

## License

`wefact-mcp` is **dual-licensed**:

- **[AGPL-3.0-or-later](LICENSE)** — free for AGPL-compatible use. If
  you run a modified version on a server that interacts with users
  over a network, you must offer those users the source code (per
  AGPL §13).
- **[Commercial license](LICENSE-COMMERCIAL.md)** — €197/year or €497
  lifetime, ex VAT. For proprietary integrations, closed-source
  products, or hosted services that don't meet AGPL §13. Includes
  email support and 12 months of updates. Buy at
  <https://easeo.nl/diensten/wefact-mcp>.

For agency, white-label or platform partnerships — including a
WeFact-side official integration — email
[nick@easeo.nl](mailto:nick@easeo.nl).

## Disclaimer

This project is not affiliated with or endorsed by WeFact B.V.
"WeFact" is a trademark of WeFact B.V. Use of this MCP server
requires a valid WeFact account and API key, and is bound by
[WeFact's terms of service](https://www.wefact.nl/algemene-voorwaarden).
