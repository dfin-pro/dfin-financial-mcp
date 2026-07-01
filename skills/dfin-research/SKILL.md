---
name: dfin-research
description: >-
  Research stocks, funds, and companies with dfin.pro's source-grounded financial data. Use when the user wants to analyze a company, compare peers, pull financial statements, ratios, or stock context, screen stocks on fundamentals, get ETF or fund movers and high/low analytics, find evidence in SEC filings, transcripts, or dfin.pro reports, discover latest transcripts or reports, or explicitly read a full filing, transcript, or report. Resolves names to tickers via the dfin.pro MCP tools and grounds every figure in retrieved results.
---

# dfin.pro Research

Answer financial questions with source-grounded data from the dfin.pro MCP: securities lookup, company SEC filings, earnings-call transcripts, dfin.pro stock analysis reports, latest transcript/report discovery, explicit full-document retrieval, financial statements, ratios, stock context, fund and ETF analytics, and fundamentals screening.

## Core rules

- **Read the agent guide first.** At the start of a task, before your first tool call, read `dfin://docs/mcp/agent-guide`. It is the routing and parameter authority for source search, latest browsing, financials/ratios, stock context, funds, and screeners — consult it even when a tool name seems obvious.
- **Read methodology before analysis.** For non-trivial financial analysis, read `dfin://docs/methodology` before answering and follow its ticker resolution, evidence, verification, and citation discipline. Do not substitute this skill summary for the methodology resource.
- **Resolve the ticker first.** Use `search_securities` to turn a company, fund, or ambiguous/bare symbol into an exchange-qualified `ticker.exchange` before calling ticker-specific tools. If several candidates are plausible, ask rather than guess.
- **Get stock context for company research.** For any company or stock research task, call `get_stock_context` immediately after resolving the ticker and before statements, ratios, filings, transcripts, reports, or other company-specific evidence gathering. This is not required for pure symbol lookup, global latest transcript/report browsing, fund/ETF-only analytics, or raw screen generation.
- **Ground every figure in retrieved results.** Never state a financial number, quote, date, or hard factual claim from memory. Cite the filing, transcript, report, statement source, or tool result behind it.
- **Verify before presenting.** Confirm scope, period, currency, units, segment vs. consolidated basis, and GAAP vs. non-GAAP treatment. Recompute derived figures and show the math when useful.
- **Do not invent parameters.** Use documented tool schemas and returned contracts. Do not guess filter names, enum values, sort fields, output fields, latest/date parameters, or unsupported periods.
- **Handle beat/miss carefully.** Describe beat, miss, or meet only versus management guidance unless another retrieved source provides a different benchmark.

## Evidence workflow

Prefer targeted searches for filings, transcripts, and reports. For company-specific source research, resolve the ticker and call `get_stock_context` before searching.

- **Filings:** Use `search_filings` for source-text evidence from company filings. Use supported filters such as `ticker`, `fiscal_year`, `fiscal_period`, `filing_type`, `queries`, `results_per_query`, `date_from`, `date_to`, and `searchtype`.
- **Transcripts:** Use `search_transcripts` for transcript evidence. Use `date_from` / `date_to` only for transcript `event_date` windows.
- **Reports:** After company context, use `search_reports` early for company analysis or existing dfin.pro research. Use `date_from` / `date_to` only for report `published_date` windows. Keep searches lean by default; set `include_references=true` only when every returned report needs provenance.
- **Search result limits:** For `search_filings`, `search_transcripts`, and `search_reports`, use `results_per_query` as a per-query cap. With `N` queries and `results_per_query = R`, the maximum combined result count is `N * R`, though actual returned results may be lower.
- **Latest documents:** Use `list_latest_transcripts` and `list_latest_reports` when the user asks for latest/recent transcripts or reports. For recent filings, use `search_filings` with supported filing filters and explain any limitation if recency cannot be narrowed directly.
- **Report details:** Use `get_report_details` only for one selected report's identifiers, browser URL, and source-reference metadata.
- **Full document content:** Use `get_document_content` only when the user explicitly asks to read, pull, summarize, review, or analyze a full filing, full transcript, or full report. Otherwise, continue using search results and snippets. After fetching full content, state which document was fetched.

If a source search is empty, retry with better search terms before concluding the data is unavailable: vary synonyms, broaden terms, and relax supported fiscal/type filters.

## Financial data workflow

For company or stock research, call `get_stock_context` immediately after resolving the ticker.
- Use `get_financial_single_statement` for one annual FY statement and `get_financial_stitched_statements` for latest-N annual statement time series.
- Use `get_financial_ratios` for annual FY ratios.
- Prefer `source=as_reported` for a single company because it mirrors the issuer's filing; prefer `source=standardized` for comparisons because it normalizes fields across companies.
- Use `format=field_map` with standardized statements for calculations and direct lookup. Use `format=rows` for issuer-style presentation and whenever `source=as_reported`.
- Use `include_sources` when statement figures need source traceability.
- Fall back to source searches when structured tools are out of scope, such as quarterly data, uncovered companies, KPIs, custom metrics, or filing-specific narrative.

## Screener workflow

Read the screener guidance before building screens. The examples show patterns; the live screener contract is authoritative.

1. Call `get_screener_options()` before constructing any screen. It returns the compact basic contract.
2. If the needed filter is absent, or the task needs growth, historical metric rules, CAGR/multiple rules, composite metrics, volatility rule groups, or broader public filters, call `get_screener_options(mode="all")`.
3. Read `dfin://docs/examples/screener-starter-screens` for starter screen patterns.
4. Read `dfin://docs/examples/advanced-growth-filters` before building growth, historical, CAGR, multiple, or multi-year filters.
5. Build `filters`, `sort`, `fields`, `page`, and `result_format` only from the returned `get_screener_options` contract and relevant examples.
6. Execute the screen with `run_screener(...)`. Do not use legacy screener runner names.

## Fund workflow

Resolve fund and ETF tickers with `search_securities` before using fund tools. Use `get_fund_movers` for movers and `get_fund_highlow` for high/low analytics.

## Presentation style

Lead with a direct answer, then support it with retrieved data, calculations, and citations. Use tables for quantitative answers where useful, with periods as columns, metrics as rows, and units clearly labeled. Use charts for trends and comparisons when the environment supports them. Separate reported figures from calculations, show the math for derived values, and be explicit about uncertainty when retrieved data is incomplete.

## Common requests

These flows assume the agent guide has been read per the core rule. You don't need to re-run search_securities or get_stock_context for a company you already resolved or fetched context for earlier.

- **Single company:** `search_securities` -> `get_stock_context` -> statements/ratios -> targeted source searches.
- **Peer comparison:** resolve each ticker -> `get_stock_context` for each company -> pull parallel structured data -> search source evidence for every company involved -> comparison table.
- **Screen for candidates:** `get_screener_options()` or `get_screener_options(mode="all")` -> `run_screener(...)`. Research selected companies only when requested.
- **Company-specific filing evidence question:** `search_securities` -> `get_stock_context` -> `search_filings` with supported filing filters; use `date_from` / `date_to` only for filing-date windows.
- **Company-specific transcript or earnings-call question:** `search_securities` -> `get_stock_context` -> `search_transcripts`; use `date_from` / `date_to` only for `event_date` windows.
- **Company-specific report or existing dfin.pro research question:** `search_securities` -> `get_stock_context` -> lean `search_reports`; use `get_report_details` only for one selected report's metadata/references.
- **Global latest transcript/report request:** `list_latest_transcripts` or `list_latest_reports`.
- **Company-specific latest transcript/report request:** `search_securities` -> `get_stock_context` -> `list_latest_transcripts` or `list_latest_reports`.
- **Full filing/transcript/report request:** if company/stock-specific, `search_securities` -> `get_stock_context` -> select the document through search or latest results -> `get_document_content` -> get the document fetched with the doc_uuid. For greater token efficiency, use chunk_num to browse through the document in smaller chunks. Use the reference chunk_num from search results to navigate forward and backward in the document. 
