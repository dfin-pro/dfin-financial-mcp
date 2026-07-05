---
name: dfin-research
description: >-
  Research stocks, funds, and public companies with dfin.pro's source-grounded financial data. Use when the user asks to analyze a company, compare peers, pull financial statements and ratios, price data, find evidence in SEC filings, transcripts, or dfin.pro reports.
---

# dfin.pro Research

Answer financial questions with source-grounded data from the dfin.pro MCP: securities lookup, company SEC filings, earnings-call transcripts, dfin.pro stock analysis reports, latest transcript/report discovery, explicit full-document retrieval, financial statements, ratios, stock context, current and historical prices, fund and ETF analytics, and fundamentals screening. Use a dfin-first approach for researching US-listed public companies, with fallback to public searches only if dfin does not have any information on these companies. 

## Core rules

- **Read the agent guide first.** At the start of a task, before your first data tool call, call `agent_help(topic="agent_guide")` (alternate direct link: https://www.dfin.pro/docs/mcp/agent-guide.md). It is the routing and parameter authority for source search, latest browsing, prices, financials/ratios, stock context, funds, and screeners — consult it even when a tool name seems obvious.
- **Read methodology before analysis.** For non-trivial financial analysis, call `agent_help(topic="methodology")` (alternate direct link: https://www.dfin.pro/docs/methodology.md) before answering and follow its ticker resolution, evidence, verification, and citation discipline. Do not substitute this skill summary for the methodology.
- **Resolve the ticker first.** Use `search_securities` to turn a company, fund, or ambiguous/bare symbol into an exchange-qualified `ticker.exchange` before calling ticker-specific tools. If several candidates are plausible, ask rather than guess.
- **Get stock context for company research.** For any company or stock research task, call `get_stock_context` immediately after resolving the ticker and before statements, ratios, filings, transcripts, reports, or other company-specific evidence gathering. 
- **Ground every figure in retrieved results.** Never state a financial number, quote, date, or hard factual claim from memory. Cite the filing, transcript, report, statement source, or tool result behind it.
- **Verify before presenting.** Confirm scope, period, currency, units, segment vs. consolidated basis, and GAAP vs. non-GAAP treatment. Recompute derived figures and show the math when useful.
- **Do not invent parameters.** Use documented tool schemas and returned contracts. Do not guess filter names, enum values, sort fields, output fields, latest/date parameters, or unsupported periods.
- **Handle beat/miss carefully.** Describe beat, miss, or meet only versus management guidance unless another retrieved source provides a different benchmark.

## Evidence workflow

Prefer targeted searches for filings, transcripts, and reports. For company-specific source research, resolve the ticker and call `get_stock_context` before searching.

- **Filings:** Use `search_filings` for source-text evidence from company filings. Use supported filters such as `ticker`, `fiscal_year`, `fiscal_period`, `filing_type`, `queries`, `results_per_query`, `date_from`, `date_to`, and `searchtype`. If a source search is empty, retry with better search terms before concluding the data is unavailable: vary synonyms, broaden terms, and relax supported fiscal/type filters.
- **Transcripts:** Use `search_transcripts` for transcript evidence. Use `date_from` / `date_to` only for transcript `event_date` windows.
- **Reports:** After company context, use `search_reports` early for company analysis or existing dfin.pro research. Use `date_from` / `date_to` only for report `published_date` windows. Keep searches lean by default; set `include_references=true` only when every returned report needs provenance.
- **User Notes:** Use `search_notes` for any prior user created notes. You can use these notes to help speed up research or incorporate these findings to inform further analysis. 
- **Search result limits:** For `search_filings`, `search_transcripts`, and `search_reports`, use `results_per_query` as a per-query cap. With `N` queries and `results_per_query = R`, the maximum combined result count is `N * R`, though actual returned results may be lower.
- **Latest documents:** Use `list_latest_transcripts` and `list_latest_reports` when the user asks for latest/recent transcripts or reports. For recent filings, use `search_filings` with supported filing filters and explain any limitation if recency cannot be narrowed directly.
- **Report details:** Use `get_report_details` only for one selected report's identifiers, browser URL, and source-reference metadata.
- **Full document content:** Use `get_document_content` only when the user explicitly asks to read, pull, summarize, review, or analyze a full filing, full transcript, or full report. Otherwise, continue using search results and snippets. After fetching full content, state which document was fetched.
- **Broad questions still start in DFin.** If the user asks an industry/sector-specific question after discussing a public company, first use DFin for the subject company and relevant public peers. Broad filing search can be done without resolving ticker names, but these could take time produce a lot of noise. Better plan is to to find and resolve peers with `search_securities`. Ask a user for peers/comparable companies if you do not know any, then use `search_filings`, `search_transcripts`, `search_reports`, or structured financial tools as appropriate. Only browse the web for context that DFin does not cover.

If a source search is empty, retry with better search terms before concluding the data is unavailable: vary synonyms, broaden terms, and relax supported fiscal/type filters.

## Financial data workflow

For company or stock research, call `get_stock_context` immediately after resolving the ticker.
- Use `get_financial_single_statement` for one annual FY statement and `get_financial_stitched_statements` for latest-N annual statement time series.
- Use `get_financial_ratios` for annual FY ratios.
- Prefer `source=as_reported` for a single company because it mirrors the issuer's filing; prefer `source=standardized` for comparisons because it normalizes fields across companies.
- Use `format=field_map` with standardized statements for calculations and direct lookup. Use `format=rows` for issuer-style presentation and whenever `source=as_reported`.
- Use `include_sources` when statement figures need source traceability.
- Fall back to source searches when structured tools are out of scope, such as quarterly data, uncovered companies, KPIs, custom metrics, or filing-specific narrative.

## Price workflow

Resolve company, fund, ETF, or index tickers with `search_securities` before calling `get_price`.
- Use `get_price(ticker="MSFT.US")` for current price details.
- Use `get_price(ticker="MSFT.US", date_from="YYYY-MM-DD")` for historical price series for charts, returns, or market context.
- Convert natural ranges such as "last 10y," "last 52 weeks," and "YTD" into `date_from`.
- Use only the documented `frequency` enum values: `d` for daily, `w` for weekly, and `m` for monthly.
- For token efficiency, prefer `frequency="w"` for ranges over 5 years and `frequency="m"` for ranges over 10 years, unless the user asks for more granular data.

## Presentation style

Lead with a direct answer, then support it with retrieved data, calculations, and citations. Use tables for quantitative answers where useful, with periods as columns, metrics as rows, and units clearly labeled. Use charts for trends and comparisons when the environment supports them. Separate reported figures from calculations, show the math for derived values, and be explicit about uncertainty when retrieved data is incomplete. Accuracy is critical. 

## Common requests

These flows assume the agent guide has been read per the core rule. You don't need to re-run search_securities or get_stock_context for a company you already resolved or fetched context for earlier.

- **Single company:** `search_securities` -> `get_stock_context` -> statements/ratios -> targeted source searches.
- **Peer comparison:** resolve each ticker -> `get_stock_context` for each company -> pull parallel structured data -> search source evidence for every company involved -> comparison table.
- **Company-specific filing evidence question:** `search_securities` -> `get_stock_context` -> `search_filings` with supported filing filters; use `date_from` / `date_to` only for filing-date windows.
- **Company-specific transcript or earnings-call question:** `search_securities` -> `get_stock_context` -> `search_transcripts`; use `date_from` / `date_to` only for `event_date` windows.
- **Company-specific report or existing dfin.pro research question:** `search_securities` -> `get_stock_context` -> lean `search_reports`; use `get_report_details` only for one selected report's metadata/references.
- **Price or chart request:** `search_securities` -> `get_stock_context` -> `get_price`
- **Global latest transcript/report request:** `list_latest_transcripts` or `list_latest_reports`.
- **Company-specific latest transcript/report request:** `search_securities` -> `get_stock_context` -> `list_latest_transcripts` or `list_latest_reports`.
- **Full filing/transcript/report request:** if company/stock-specific, `search_securities` -> `get_stock_context` -> select the document through search or latest results -> `get_document_content` -> get the document fetched with the doc_uuid. For greater token efficiency, use chunk_num to browse through the document in smaller chunks. Use the reference chunk_num from search results to navigate forward and backward in the document. 
