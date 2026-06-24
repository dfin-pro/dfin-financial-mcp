---
name: dfin-research
description: >-
  Research stocks, funds, and companies with dfin.pro's source-grounded financial data. Use when the user wants to analyze a company, compare peers, pull financial statements, ratios, or stock context, screen stocks on fundamentals, get ETF or fund movers and high/low analytics, or find evidence in SEC filings. Resolves names to tickers via the dfin.pro MCP tools and grounds every figure in retrieved results.
---

# dfin.pro Research

Answer financial questions with source-grounded data from the dfin.pro MCP: company SEC filings, financial statements, ratios, stock context, fund and ETF analytics, and a fundamentals screener.

This skill summarizes dfin.pro's analysis methodology; the full playbook — ticker tiebreakers, search tactics, verification checks, and citations — lives in the `dfin://docs/methodology` resource. The essentials below let you act if the resource is unavailable.

## Before you start

Confirm the dfin.pro tools are available: `search_securities`, `search_filings`, `get_stock_context`, `get_financial_single_statement`, `get_financial_stitched_statements`, `get_financial_ratios`, `get_screener_options`, `run_screener_basic`, `run_screener_advanced`, `get_fund_movers`, `get_fund_highlow`.

If they are not connected, tell the user to get an API key at https://www.dfin.pro and connect the dfin.pro MCP — a bearer token (`Authorization: Bearer <api_key>`) for Claude Code, Codex, Hermes Agent, or the `https://www.dfin.pro/mcp/<api_key>` URL for clients that cannot send custom headers.

## Core rules (always)

- **Read the methodology first.** For anything beyond a trivial lookup, read the `dfin://docs/methodology` resource before you start and follow it. The rules below are the essentials and a fallback, not a replacement.
- **Resolve the ticker first.** Use `search_securities` to turn a company name into an exchange-qualified `ticker.exchange` (for example `MSFT.US`) before calling any ticker tool. If several candidates are plausible, ask rather than guess.
- **Ground every figure in tool results.** Never state a financial number, quote, or date from memory; cite the filing and period, or the statement source.
- **Verify before presenting.** Recheck figures and calculations, confirm scope (segment vs. consolidated, period, currency, units), and never mix GAAP and non-GAAP figures.
- **Beat/miss is vs. management guidance only.** These tools carry no market or analyst consensus, so never imply a comparison to expectations.
- **Clarify scope when ambiguous** — company vs. product vs. segment, and fiscal vs. calendar period.

## Workflow

1. **Resolve** the company to a ticker with `search_securities`.
2. **Gather** evidence with the right tool:
   - `search_filings` for source-text evidence — try a few wordings; if a search is empty, broaden terms and relax fiscal filters before concluding the data is unavailable.
   - the financial statement and ratio tools for exact reported numbers. Prefer `source=as_reported` for a single company (it matches how the company filed) and `standardized` when comparing companies (same basis for all); if standardized is missing, fall back to `as_reported`. These cover annual (FY) core statements (income statement, balance sheet, cash flow) for covered companies only — for a quarter, a company they do not cover, or a company-reported KPI or custom metric, use `search_filings` to pull it from the filings (repeat across years for a trend).
   - `get_stock_context` for a single-company overview.
   - `get_screener_options`, then `run_screener_basic` / `run_screener_advanced`, to find candidates.
   - `get_fund_movers` and `get_fund_highlow` for ETF/fund movers and high/low analytics (resolve the fund ticker with `search_securities` first).
3. **Analyze** — ground claims in results; for comparisons, competition, or M&A, gather evidence from every company involved before concluding.
4. **Verify** — scope, units and currency, GAAP vs. non-GAAP; recompute derived values.
5. **Present** — lead with a direct answer, default to tables (periods as columns, metrics as rows), use charts for trends where the environment supports them, and cite a source for every figure.

## Common requests

- **Single company** → `search_securities` → `get_stock_context` → statements/ratios → `search_filings` for narrative.
- **Peer comparison** → resolve each ticker → pull parallel data → comparison table.
- **Screen for candidates** → `get_screener_options` → `run_screener_basic` / `run_screener_advanced` → research the short list.
- **Filing or earnings question** → `search_filings` with `ticker`, `fiscal_year`, or `filing_type` filters.

When in doubt about how to use a specific tool, read `dfin://docs/methodology` and the `dfin://docs/api/v1/agent-hints` resource.
