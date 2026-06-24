---
name: dfin-research
description: >-
  Research stocks, funds, and companies with dfin.pro's source-grounded financial data. Use when the user wants to analyze a company, compare peers, pull financial statements, ratios, or stock context, screen stocks on fundamentals, get ETF or fund movers and high/low analytics, or find evidence in SEC filings. Resolves names to tickers via the dfin.pro MCP tools and grounds every figure in retrieved results.
---

# dfin.pro Research

Answer financial questions with source-grounded data from the dfin.pro MCP: company SEC filings, financial statements, ratios, stock context, fund and ETF analytics, and a fundamentals screener.

This skill summarizes dfin.pro's analysis methodology; the full playbook — ticker tiebreakers, search tactics, verification checks, and citations — lives in the `dfin://docs/methodology` resource. The essentials below let you act if the resource is unavailable.

## Documentation

For human-readable docs, start at https://www.dfin.pro/docs/. Use https://www.dfin.pro/docs/mcp/ for MCP setup and response conventions, https://www.dfin.pro/docs/mcp/agent-guide/ for MCP tool selection, and https://www.dfin.pro/docs/api/v1/ only when detailed REST API contracts are needed.

For agent-readable MCP resources, start with `dfin://docs` for the documentation map. Use `dfin://docs/mcp/agent-guide` to choose MCP tools, `dfin://docs/mcp` for MCP setup and response conventions, `dfin://docs/methodology` for analysis workflow and verification discipline, and `dfin://docs/api/v1` only when detailed REST API contracts are needed.

## Before you start

Confirm the dfin.pro MCP server is connected and inspect its live tool list and documentation resources before choosing calls. Tool names and schemas can change over time, so treat the connected MCP server and `dfin://docs/mcp/agent-guide` as the source of truth instead of relying on a static list in this skill.

If they are not connected, tell the user to get an API key at https://www.dfin.pro and connect the dfin.pro MCP — a bearer token (`Authorization: Bearer <api_key>`) for Claude Code, Codex, Hermes Agent, or the `https://www.dfin.pro/mcp/<api_key>` URL for clients that cannot send custom headers.

## Core rules (always)

- **Read the methodology first.** For anything beyond a trivial lookup, read the `dfin://docs/methodology` resource before you start and follow it. The rules below are the essentials and a fallback, not a replacement.
- **Resolve the ticker first.** Use `search_securities` to turn a company name into an exchange-qualified `ticker.exchange` (for example `MSFT.US`) before calling any ticker tool. If several candidates are plausible, ask rather than guess.
- **Ground every figure in tool results.** Never state a financial number, quote, or date from memory; cite the filing and period, or the statement source.
- **Verify before presenting.** Recheck figures and calculations, confirm scope (segment vs. consolidated, period, currency, units), and never mix GAAP and non-GAAP figures.
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
5. **Present** — lead with a direct answer, then support it with retrieved data, calculations, and citations.

## Presentation style

Be concise, source-grounded, and explicit about uncertainty. Present information like a financial analyst: use tables for quantitative answers where useful, with periods as columns, metrics as rows, and units clearly labeled. Use charts for trends and comparisons when the environment supports them. Separate reported figures from calculations, show the math for derived values, and avoid promotional or overly confident language when retrieved data is incomplete.

## Common requests

- **Single company** → `search_securities` → `get_stock_context` → statements/ratios → `search_filings` for narrative.
- **Peer comparison** → resolve each ticker → pull parallel data → comparison table.
- **Screen for candidates** → `get_screener_options` → `run_screener_basic` / `run_screener_advanced` → research the short list.
- **Filing or earnings question** → `search_filings` with `ticker`, `fiscal_year`, or `filing_type` filters.
- **Transcript or earnings-call question** → use `search_transcripts` for source-text evidence from earnings-call transcripts.
- **Existing dfin.pro research or report question** → use `search_reports` first, then `get_report_details` when one report's identifiers, browser URL, or references are needed.

When in doubt about how to use a specific tool, read `dfin://docs/mcp/agent-guide`. For non-trivial financial analysis, read `dfin://docs/methodology` before answering.
