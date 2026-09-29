"""Holdings import integrations: OCR pipeline, providers, normalizer.

Import capability is decoupled from PortfolioService via the
HoldingImportProvider protocol (MVP spec 3.7). Providers convert different
inputs into a unified "pending draft"; only explicit user confirmation ever
writes to the authoritative portfolio_position table.

Deliberately import-free: `screenshot_provider` needs `fund_service` to turn a
name into a fund, so a package-level re-export would close that cycle the
moment anything on the service side imported from here. Import the submodule
you want.
"""
