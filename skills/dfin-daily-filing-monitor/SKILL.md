---
name: dfin-daily-filing-monitor
description: Monitor recent SEC filings for a named topic or corporate event. Use this skill when the user wants to screen, scan, or monitor SEC filings for a specific theme such as management changes, executive appointments, debt restructuring, M&A activity, earnings guidance, or regulatory events. Triggers include "management changes announced today", "morning scan for debt restructuring", "daily M&A filing monitor", "any [topic] filings recently?", "scan recent 8-Ks for [topic]", and "what companies announced [topic] this week?". Do not use it for theme-less filing-news briefings.
---

# Daily Filing Monitor

Before the first DFin call, read `agent_help(topic="agent_guide")` once. Read `methodology_search` before discovery, `methodology_financials` before ratio enrichment, and `output_guidelines` before presenting substantive results.

DFin skill version: 0.1.6, updated 2026-08-07.

Monitor US-listed SEC filers, including foreign private issuers and ADRs. Keep exchange-qualified tickers exactly as returned. Deliver one company card with one nested section per filing bundle, or a concise table when the user requests text.

## Non-negotiable context boundary

- Filing and document searches return artifacts; pass their URLs directly to the local helpers.
- Request dashboard stock context once for all resolved tickers. Pass either its shared artifact URL or its complete compact inline batch directly to the dashboard helper, matching the MCP response mode.
- Treat every capability URL as sensitive. Never quote, log, persist, or share it.
- Download artifacts only into local helpers. Never print, read, or return a complete artifact or chunk to model context.
- Allow only the helper's bounded summaries, selected evidence, and compact statuses into context.
- Never read a generated dashboard back merely to inspect it. Materialize it once only when a host renderer requires complete HTML.

Use the bundled scripts without reading their source during a normal run:

- `scripts/filing_artifact.py`: fetch, group, summarize, and select filing evidence.
- `scripts/build_dashboard.py`: consume inline or artifact stock context, assemble safe DATA, and write the dashboard or compact text rows.

## 1. Route the request

Extract the topic, date window, requested forms, sector filter, and output mode. Require one named event, theme, or evidence target. If this skill is explicitly invoked without one, ask for one monitoring theme and make no DFin calls. Otherwise default to the last two calendar days. Use seven days for “this week” and one day for “today.” Do not ask for clarification when the topic is clear and a reasonable interpretation is safe.

Choose forms:

- Honor explicit forms exactly.
- For a generic cross-company current-event scan, search `8-K` and `6-K` separately.
- Add `10-Q`, `10-K`, or `20-F` only when explicitly requested or directly required by the topic.
- Never combine multiple forms into one `filing_type`; it is scalar.

Use dashboard mode by default. Use text mode when the user says “no dashboard,” “just list them,” “just text,” or equivalent.

## 2. Discover filings efficiently

Create 3–5 short, source-native queries covering plain language, legal terminology, the applicable SEC item, and only the most relevant process or financial terms. Examples:

- Management: `new CEO CFO appointed resigned`, `Item 5.02 appointment departure`, `interim successor effective date`.
- M&A: `merger acquisition definitive agreement`, `purchase price closing conditions`, `Item 1.01 merger`.
- Debt: `credit agreement refinancing restructuring`, `covenant waiver maturity extension`, `Chapter 11 reorganization`.

Call `search_filings` separately per form:

```yaml
date_from: <inclusive filing date>
date_to: <inclusive filing date>
filing_type: <one form>
queries: <3-5 queries>
results_per_query: 5
include_content_head: true
include_content_tail: false
content_preview_chars: 120
```

Expand only a deficient query and never above 10 results without stating why. On an external SEC timeout, wait 30 seconds and retry once unchanged; then narrow one filter or report temporary unavailability.

Pass each returned `results_url` on stdin to the filing helper; never place it in prose:

```text
python3 <skill-dir>/scripts/filing_artifact.py summarize --fetch --save <temporary-json-path>
```

The helper prints no more than 15 accession-level bundle summaries with previews of at most 220 characters, one validated SEC source link per bundle, and explicit remaining-count metadata. Keep the temporary artifact outside the repository and delete it after the scan. If `truncated` is true, request another page with `--offset <offset + shown_count>` only when the first page is deficient or the user requested exhaustive coverage.

### Identity rules

- Use a returned exchange-qualified ticker as the primary company identity without modification.
- Resolve a bare or missing ticker with `search_securities` only when one issuer match is unambiguous.
- If unresolved, keep the filing under its CIK or bundle identity and skip stock/ratio enrichment.
- Use CIK only as a secondary collision key. Never replace a valid ticker with CIK.
- Use CIK plus SEC accession as the bundle identity; fall back to `doc_uuid` when no accession is available.
- Normalize `8-K 10.2` into bundle form `8-K` and document designation `10.2`.

### Classify bundles

Classify from bounded previews before fetching more evidence:

- **Confirmed** — the preview clearly states the requested event. Include `confirmed` in bundle tags.
- **Flagged** — plausible but inconclusive after the permitted second look. Include `flagged`, set `flag: true`, and provide a short reason.
- **Excluded** — clearly unrelated. Do not enrich or render it.

For only the top 3–5 plausible cover-page-only bundles, take one scoped second look. First select the bundle locally:

```text
python3 <skill-dir>/scripts/filing_artifact.py select --artifact <temporary-json-path> --bundle <bundle-id>
```

Use the returned UUID batches in `search_in_documents` with one tight query and `results_per_query: 3`. Never send more than 20 UUIDs. Process that artifact through the helper and stop when classification is possible. The selected result includes an `evidence_location` with the exact matching `doc_uuid`, `chunk_num`, and `content_chars`; if the bounded evidence ends at a material boundary, retrieve only that known chunk.

If the needed exhibit was absent, use one exact-ticker, exact-filing-date `search_filings` call with one tight query. Never run a ticker follow-up without a date bound.

For a user-requested company deep dive, search selected bundle documents with focused queries. Do not walk neighboring `chunk_num` values or fetch a whole document because a hit ends at a boundary. Retrieve a known chunk only when the final evidence requires it.

## 3. Enrich selected companies

### Text mode

Call `get_stock_context` once with all resolved `tickers` and `fields: ["price", "returns"]`. Skip ratios and descriptions. Create the same compact company-and-filing manifest used below, but include exactly one stock source from the response: `stock_context` for an inline batch or `stock_context_url` for an artifact. Feed it to:

```text
python3 <skill-dir>/scripts/build_dashboard.py --text --stock-cache <temporary-cache-path>
```

Present only the returned rows in the table described below. This path handles either MCP response mode while keeping artifact contents out of model context. Delete the cache after the final result.

### Dashboard mode

Read `methodology_financials`. Then:

1. For every resolved included company, call `get_financial_ratios` for the current year with `period: "FY"` and fields `returnOnEquity`, `returnOnInvestedCapital`, `netDebtToEBITDA`, and `ebitdaMargin`. On unavailable data, try the prior year and then one year earlier; stop at the first valid response.
2. Call `get_stock_context` once with all resolved `tickers` and fields `price`, `returns`, `profile`, `description`, `technicals`, and `earnings_history`. The MCP may return either a compact inline batch or one shared artifact, depending on response size.
3. Put the compact ratio responses and exactly one stock source in the dashboard manifest: `stock_context` for the complete inline batch or `stock_context_url` for the shared capability URL. Do not inspect an artifact payload.

The builder extracts only top-level company name, ticker, description, structured price/returns/technicals, date-keyed earnings history, and allowlisted profile fields. It discards database, user-note, executive, estimate, and other unused sections.

The builder selects each company from the shared artifact by ticker, verifies fresh and cached stock identity, and verifies the ticker in every compact ratio response. A missing or failed ticker result keeps the filing card but omits enrichment. A stock ticker or secondary CIK mismatch reports `identity_mismatch`; a ratio ticker mismatch reports `ratio_identity_mismatch`. An unresolved issuer reports `unresolved` and is never fetched. Duplicate company records merge by qualified ticker, while unresolved issuers merge only by CIK or bundle identity; every filing requires a bundle ID, duplicate accession IDs merge, and conflicting or malformed bundles are omitted with `manifest_conflict`.

The builder applies these rules:

- Keep returns in five fixed positions: Daily, WTD, MTD, YTD, and 1Y. Use `null` for missing values; missing is never zero.
- Sort earnings-history ISO date keys, select the latest four, and display them oldest-first. Actual above estimate is a beat; below is a miss; equal or missing is neutral.
- Multiply ROE, ROIC, and EBITDA margin decimal fractions by 100 exactly once. Leave ND/EBITDA as a multiple.
- Label ratios `FY<year>` plus the reported fiscal-year-end label when available. Do not infer an unavailable end date.
- Preserve the complete description in the collapsible About panel without copying it into the narrative response.

## 4. Build and render

Create a compact manifest and feed it to `build_dashboard.py` on stdin. Do not interpolate it into Python or shell source. Use this shape:

```json
{
  "title": "Management Changes",
  "ftype": "8-K / 6-K",
  "range": "Aug 5–6, 2026",
  "filters": [["appointments", "Appointments"]],
  "stock_context_url": "<single-use batch capability>",
  "companies": [{
    "ticker": "MSFT.US",
    "name": "Microsoft Corporation",
    "cik": "0000789019",
    "exchange": "NASDAQ",
    "ratios": {"ticker":"MSFT.US","year":2025,"period":"FY","ratios":{}},
    "filings": [{
      "id": "sec:0000789019:<accession>",
      "ft": "8-K",
      "fd": "Aug 6",
      "fl": "https://www.sec.gov/Archives/...",
      "tags": ["confirmed", "appointments"],
      "flag": false,
      "flagnote": "",
      "ev": [["pill-in", "APPOINTMENT", "Person", "Role and effective date"]],
      "docs": 2
    }]
  }]
}
```

For an inline MCP response, replace `stock_context_url` with `"stock_context": {<complete ticker-keyed batch>}`. Never provide both keys.

Run:

```text
python3 <skill-dir>/scripts/build_dashboard.py --template <skill-dir>/dashboard.html --output <cwd>/filing-monitor-<topic>-<date>.html --stock-cache <temporary-cache-path>
```

The builder prints only the saved path, counts, and per-ticker status. If the shared artifact reports `refresh_required`, request one fresh batch for tickers not already in the temporary cache and rerun with the same cache. Delete the cache after the final build.

Rendering contract:

- If the host exposes `show_widget`, render the completed HTML as the primary result. Do not duplicate company details in prose. If the tool requires full HTML, materialize the page only once for that final call.
- Otherwise use another verified HTML renderer when available.
- Without a renderer, link the saved HTML and use the helper's `--text` mode for the text table.
- On render failure, retain the saved HTML and fall back through the helper's `--text` mode.
- Skip saving only when the user explicitly requests render-only output.

The dashboard validates SEC HTTPS links, allowlists visual classes/colors, uses event listeners instead of inline handlers, filters nested bundles independently, and hides a company only when none of its bundles match.

## 5. Present results

Read `output_guidelines` before presenting substantive results.

- **Dashboard:** state only the company and filing-bundle counts plus the single most significant event, render the widget, and link the saved file when applicable.
- **Text:** show one row per filing bundle with `Ticker | Company | Event | Price (Δ) | 1Y | Filing`. Mark doubtful bundles `⚑ flagged`. Do not include descriptions, ratios, or EPS history.
- **No matches:** say no relevant results were found and suggest a broader query or wider date range.

Never reproduce filing chunks, complete descriptions, artifact URLs, or dashboard details already shown elsewhere.
