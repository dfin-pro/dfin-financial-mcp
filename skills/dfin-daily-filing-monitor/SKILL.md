---
name: dfin-daily-filing-monitor
description: Monitor the last one to three days of SEC filings for a named topic or corporate event. Use this skill when the user wants to screen, scan, or monitor very recent filings for a specific theme such as management changes, executive appointments, debt restructuring, M&A activity, earnings guidance, or regulatory events. Triggers include "management changes announced today", "morning scan for debt restructuring", "daily M&A filing monitor", "any [topic] filings recently?", and "scan recent 8-Ks for [topic]". Do not use it for theme-less filing-news briefings or longer historical windows.
---

# Daily Filing Monitor

Before the first DFin call, read `agent_help(topic="agent_guide")` once. Read `methodology_search` before discovery, `methodology_financials` before ratio enrichment, and `output_guidelines` before presenting substantive results. Read `methodology_delegation` before delegating any eligible downstream work.

DFin skill version: 0.1.7, updated 2026-08-08.

Monitor US-listed SEC filers, including foreign private issuers and ADRs. Keep exchange-qualified tickers exactly as returned. Deliver one company card with one nested section per filing bundle, or a concise table when the user requests text.

## Non-negotiable context boundary

- Call `list_latest_filings` exactly once per scan. Its accession population is the immutable working census.
- Treat `result_set_id`, `continuation_token`, `scan_id`, and every capability URL as sensitive. Pass them only to the owning tool or local helper; never quote, log, persist in prose, or share them.
- Keep census and filing-search delivery on `api`. Download artifacts only into local helpers and never read a complete artifact into model context.
- A non-empty census is searched only with `search_filing_census`. Do not run broad `search_filings` calls or ticker-by-ticker reconciliation.
- Call `search_filing_census` sequentially. Do not delegate it or issue concurrent continuations.
- Request stock context in stable bounded batches and pass complete responses or capability URLs directly to the dashboard helper.
- Use `scripts/filing_artifact.py` for census initialization, server-receipt import, summaries, selection, and audit. Use `scripts/build_dashboard.py` for enrichment assembly and output.

## 1. Route the request

Extract the topic, date window, requested forms, sector filter, and output mode. Require one named event, theme, or evidence target. If the skill is explicitly invoked without one, ask for one monitoring theme and make no DFin calls.

- Default to the last two SEC filing-calendar days and use one day for “today.”
- Accept inclusive windows of one to three calendar days. For longer windows, ask the user to narrow the request and make no DFin calls.
- Honor explicit forms exactly. Otherwise select a defensible topic-specific SEC form universe before enumeration. Current reports are a starting point, not a universal answer.
- Use dashboard mode by default. Use text mode for “no dashboard,” “just list them,” “just text,” or equivalent.

## 2. Enumerate and search the frozen census

1. Create new temporary census, coverage-state, scan-result, and enrichment paths outside the repository.

2. Finalize 3–5 short source-native queries covering plain language, legal terminology, the applicable SEC item, and only the most relevant process or financial terms. Preserve their exact spelling and order for the entire scan. Examples:

   - Management: `new CEO CFO appointed resigned`, `Item 5.02 appointment departure`, `interim successor effective date`.
   - M&A: `merger acquisition definitive agreement`, `purchase price closing conditions`, `Item 1.01 merger`.
   - Debt: `credit agreement refinancing restructuring`, `covenant waiver maturity extension`, `Chapter 11 reorganization`.

3. Enumerate once:

```yaml
filing_types: <agent-selected form-prefix array>
days: <1-3>
limit: -1
result_level: accession
data_in_db_only: false
delivery: api
```

For a non-empty response, retain the returned `result_set_id` only for `search_filing_census`. Pass `results_url` on stdin to initialize the local census without exposing it:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-init --state <coverage-state-path> --expected-form <form> [--expected-form <form> ...] --save <census-json-path> --fetch
```

For a valid empty inline response, write the complete response unchanged to `<census-json-path>` and use `--artifact <census-json-path>`. Audit the empty ledger; do not call `search_filing_census`. If enumeration or artifact saving fails, stop the comprehensive workflow, report that no frozen census was available, and do not claim no matches.

Use the helper-returned `date_from`, `date_to`, census fingerprint, accession count, filer count, `coverage.as_of`, and issues. Never infer dates from `days`, rerun enumeration, replace the census, or expand the form universe during the scan.

4. Start the server-bound thematic scan:

```yaml
census_result_set_id: <result_set_id from the one enumeration call>
queries: <exact finalized query array>
results_per_query: 5
continuation_token: ""
```

If the response is `in_progress`, repeat the same census ID, queries, and result limit with exactly the returned `continuation_token`. Honor `retry_after_seconds` before continuing. A client-side timeout does not authorize a new scan: retry the same initial request or continuation unchanged so server idempotency can recover the completed step.

Continue sequentially until `status: complete`. Do not reinterpret a missing response, timeout, rate limit, or expired continuation as an empty result.

5. Pass the completed scan’s `results_url` on stdin to import its server-bound receipt and save the single-use artifact:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-import-scan --state <coverage-state-path> --fetch --save <scan-json-path> --query "<query 1>" [--query "<query 2>" ...] --results-per-query 5
```

The helper validates the census fingerprint, exact query binding, issuer routes, result identities, and `total_filers = checked + failed`. It records `checked_empty` as successful coverage and emits bounded eligible summaries. Page those summaries locally with `summarize --state <coverage-state-path> --artifact <scan-json-path> --offset <next offset>`; the `.summary-index.json` sidecar prevents reopening the full artifact.

6. Run the audit before enrichment:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-audit --state <coverage-state-path>
```

An incomplete census, `coverage_unknown`, missing internal document, internal search failure, exhausted SEC timeout/rate limit, malformed receipt, or any unpolled filer blocks comprehensive coverage. Never turn those failures into no-match conclusions. Delete all census, state, scan, sidecar, and evidence files after the final result.

### Identity and source rules

- CIK is the authoritative coverage identity; preserve every ticker alias returned by the census.
- Covered CIKs are searched only in DFin. Explicitly uncovered CIKs are searched only through SEC. Unknown coverage fails closed.
- Use CIK plus SEC accession as the filing bundle identity; fall back to `doc_uuid` only when no accession exists.
- Preserve every issuer association on joint accessions. Coverage bookkeeping does not automatically attribute an event to every co-filer.
- Same-CIK companion accessions may be included and labeled. Results for CIKs outside the frozen census are excluded.
- Keep unresolved issuers under their CIK and skip ticker-based enrichment.

## 3. Classify bundles

Classify from bounded previews:

- **Confirmed** — the preview clearly states the requested event.
- **Flagged** — plausible but inconclusive after one permitted second look.
- **Excluded** — clearly unrelated; do not enrich or render it.

For only the top 3–5 plausible cover-page-only bundles, select the bundle locally and search its returned UUIDs:

```text
python3 <skill-dir>/scripts/filing_artifact.py select --artifact <scan-json-path> --bundle <bundle-id>
```

Call `search_in_documents` with one tight query, at most 20 UUIDs, `results_per_query: 3`, and `delivery: api`; pass the result to `summarize --fetch --save`. Stop as soon as classification is possible. Retrieve a known chunk only when bounded evidence ends at a material boundary. Never walk neighboring chunks or fetch an entire document speculatively.

## 4. Enrich selected companies

### Text mode

Batch resolved tickers in stable groups of at most four. Call `get_stock_context` with `fields: ["price", "returns"]` and `delivery: inline`. Retry only tickers whose result has a typed availability or timeout error. Feed complete response objects unchanged to `build_dashboard.py --text`.

### Dashboard mode

1. Read `methodology_financials`. Fetch the four required annual ratios for the current year, then the prior two years until one valid vintage is found.
2. Batch resolved tickers in stable groups of at most four. Call `get_stock_context` with:

```yaml
fields: ["price", "returns", "profile", "description", "technicals", "earnings_history"]
delivery: api
```

3. Retry only typed error tickers, first as a smaller batch and then singly. Preserve successful batches in the temporary cache.
4. Put exact stock-context capability URLs in `stock_context_urls` and compact ratio responses in each company’s `ratios` field. Never inspect or hand-summarize stock-context artifacts.

The dashboard builder validates ticker and CIK identity, merges batches, retains sparse data safely, and aborts on conflicting identities. Missing values remain missing rather than becoming zero.

## 5. Build, render, and present

Create the established compact dashboard manifest and run:

```text
python3 <skill-dir>/scripts/build_dashboard.py --template <skill-dir>/dashboard.html --output <cwd>/filing-monitor-<topic>-<date>.html --stock-cache <temporary-cache-path>
```

Render the completed HTML when a verified renderer is available. Otherwise link the saved HTML and use the helper’s `--text` output. On render failure, retain the file and fall back to text.

Read `output_guidelines` before presenting substantive results.

- Report selected forms, frozen accession/filer counts, internally checked covered filers, SEC-checked uncovered filers, failures, companion count, `coverage.as_of`, coverage issues, and the most significant event.
- In text mode, use `Ticker | Company | Event | Price (Δ) | 1Y | Filing`; mark doubtful bundles `⚑ flagged`.
- Say no relevant results were found only when `coverage-audit` is complete. Otherwise say no matches were found in an incomplete scan and name the unresolved issue.
- Phrase completeness narrowly: every issuer in the one frozen census has a server-bound checked or failed outcome. This does not prove perfect thematic recall for image-only content or unavailable exhibits.
- Never reproduce filing chunks, complete descriptions, capability identifiers, or dashboard details already rendered elsewhere.
