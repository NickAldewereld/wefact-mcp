# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-01

Initial public release.

### Added

- `WeFactClient` — async HTTP client for the WeFact v2 JSON-over-POST
  API with retry + exponential backoff.
- `wefact_request` — generic escape hatch for any WeFact controller /
  action.
- `whoami` — connection sanity check.
- Debtor tools: `list_debtors`, `get_debtor`, `create_debtor`,
  `update_debtor`.
- Invoice tools: `list_invoices`, `get_invoice`, `create_invoice`,
  `send_invoice`, `credit_invoice`, `mark_invoice_paid`.
- Product tools: `list_products`, `get_product`.
- Subscription tools: `list_subscriptions`, `get_subscription`.
- Credit-invoice tools: `list_credit_invoices`, `get_credit_invoice`.
- Prompts: `export_to_nixfact`, `feature_audit`.
- Test suite (28 tests, respx-mocked HTTP).
- Dual licensing: AGPL-3.0-or-later + commercial license.
- PyPI Trusted Publishing workflow on tag push.
