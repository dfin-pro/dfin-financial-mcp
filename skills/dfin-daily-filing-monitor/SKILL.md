---
name: dfin-daily-filing-monitor
description: Monitor the last one to three days of SEC filings for a named topic or corporate event. Use this skill when the user wants to screen, scan, or monitor very recent filings for a specific theme such as management changes, executive appointments, debt restructuring, M&A activity, earnings guidance, or regulatory events. Triggers include "management changes announced today", "morning scan for debt restructuring", "daily M&A filing monitor", "any [topic] filings recently?", and "scan recent 8-Ks for [topic]". Do not use it for theme-less filing-news briefings or longer historical windows.
---

# Daily Filing Monitor

DFin skill version: 0.1.9, updated 2026-08-27.

Before the first DFin call, read `agent_help(topic="agent_guide")` once. Read `methodology_search` before discovery, `methodology_financials` before ratio enrichment. Read `methodology_delegation` before delegating any eligible downstream work.

## Non-negotiable context boundary

- Call `list_latest_filings` exactly once per scan. Its accession population is the immutable working census.
- Treat `result_set_id`, `continuation_token`, and every capability URL as sensitive. Pass them only to the owning tool or local helper; never quote, log, persist in prose, or share them. The server-generated `scan_id` is the safe operator correlation reference and may be reported when diagnostics need to be traced.
- Keep census and filing-search delivery on `api`. Download artifacts only into local helpers and never read a complete artifact into model context.
- A non-empty census is searched only with `search_filing_census`. Do not run broad `search_filings` calls or ticker-by-ticker reconciliation.
- Call `search_filing_census` sequentially. Do not delegate it or issue concurrent continuations.
- Set `scan_mode` to `fast` by default. Set it to `thorough` when the user explicitly requests exhaustive per-filer review or needs a comprehensive/no-match conclusion. An audited scan is `complete` only when its census and delivered results are complete and every frozen filer is checked with no incomplete or failed outcome; it is `comprehensive` only when this is true for a thorough scan. A clean fast scan can be complete but is never comprehensive.
- Request stock context in stable bounded batches and pass complete responses or capability URLs directly to the dashboard helper.
- Use `scripts/filing_artifact.py` for census initialization, server-receipt import, summaries, selection, and audit. Use `scripts/build_dashboard.py` for enrichment assembly and output.

## 1. Route the request

Extract the topic, date window, requested forms, sector filter, output mode, and `scan_mode`. Require one named event, theme, or evidence target. If the skill is explicitly invoked without one, ask for one monitoring theme and make no DFin calls.

- Default to the last two SEC filing-calendar days and use one day for “today.”
- Accept inclusive windows of one to three calendar days. For longer windows, ask the user to narrow the request and make no DFin calls.
- Honor explicit forms exactly. Otherwise select a defensible topic-specific SEC form universe before enumeration. Current reports are a starting point, not a universal answer.
- Use dashboard mode by default. Use text mode for “no dashboard,” “just list them,” “just text,” or equivalent.
- Select `scan_mode: thorough` for an explicit exhaustive review or a requested definitive no-match conclusion; otherwise use `scan_mode: fast`.

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
mode: <scan_mode>
```

The initial call starts background processing. If the response is `in_progress`, read the compact stage and work-unit progress, wait for `next.after_seconds`, preserve `next.preserve_mode`, then repeat the same census ID, queries, result limit, mode, and exactly the returned `continuation_token`. Treat `preliminary_candidates` as unconfirmed. The continuation token is stable and the repeated call only reads status; processing continues without agent calls. A client-side timeout does not authorize a new scan: retry the same initial request or continuation unchanged so server idempotency returns the existing scan. Retain `scan_id` as the operator correlation reference.

Continue sequentially until `status: complete`. If the scan returns terminal `status: failed`, stop, report the safe failure and suggested retry, and do not claim coverage or empty results. Do not reinterpret a missing response, timeout, rate limit, expired continuation, or queued/running/retry-wait state as an empty result.

5. Pass the completed scan’s `results_url` on stdin to import its server-bound receipt and save the single-use artifact:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-import-scan --state <coverage-state-path> --fetch --save <scan-json-path> --query "<query 1>" [--query "<query 2>" ...] --results-per-query 5 --mode <scan_mode>
```

Use the same selected mode in the request and import command. The helper validates the census fingerprint, exact query binding, mode-appropriate DFin and SEC source routes, exact-recovery accounting, bounded SEC full-text search diagnostics, result identities, `total_filers = checked + not_checked + failed + incomplete`, and result-delivery arithmetic. It records checked, not-checked, and incomplete outcomes separately and emits bounded eligible summaries. Page those summaries locally with `summarize --state <coverage-state-path> --artifact <scan-json-path> --offset <next offset>`; the `.summary-index.json` sidecar prevents reopening the full artifact.

Use the bounded completion diagnostics for the ordinary report. Only when the user asks which filings were affected, page the sanitized issue records locally:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-issues --state <coverage-state-path> [--code <failure-code>] [--retryability retryable|deterministic] [--format <extension-or-content-type>] [--offset <next offset>]
```

6. Run the audit before enrichment:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-audit --state <coverage-state-path>
```

Fast mode merges bounded candidate pools from DFin indexed filing text and SEC full-text search over the frozen date and form scope. SEC hits are retained only when their accession maps back to the frozen census and the matched attachment is HTML; distinct HTML exhibits may appear as separate candidates. This route does not download each filing during the scan, and a clean completion does not support a comprehensive no-match conclusion. An incomplete or not-checked filer, a limited SEC query, incomplete census, malformed receipt, or `results_complete: false` also blocks comprehensive conclusions. When a comprehensive conclusion is required after a fast scan, initialize a new coverage-state path from the saved census artifact with the same expected forms, retain the exact query array and `results_per_query`, and start and import a `thorough` scan against the same frozen census. Do not call `list_latest_filings` again or reuse the fast scan's coverage state, which is already bound to its completed server receipt. A receipt's `recommended_follow_up` is a mandatory signal to take this path for a comprehensive request, not the only reason to do so. Delete all census, state, scan, sidecar, and evidence files after the final result.

### Identity and source rules

- CIK is the authoritative coverage identity; preserve every ticker alias returned by the census.
- In fast mode, DFin searches mapped filing documents while SEC full-text search independently discovers candidates for the same frozen date, form, and accession population. A result source may be `internal`, `sec_fts`, or `mixed`; `not_checked` means the fast route could not inspect every frozen accession for that filer, even if a positive SEC candidate was found.
- In thorough mode, covered CIKs start in DFin. When the live census permits external access, a frozen accession that is missing or fails internally is recovered by exact CIK/accession identity from the SEC accession index and its `.htm` or `.html` Document Format files; a filer may therefore finish with `internal`, `sec`, or `mixed` source. Explicitly uncovered frozen accessions use the same path. This recovery does not run SEC full-text discovery and cannot add out-of-census accessions.
- Treat `checked_hit` and `checked_empty` as successful only after every frozen accession associated with that filer was searched. `internal_and_sec_unavailable` means at least one accession remained unavailable even if the artifact retains partial evidence from the filer.
- Exact recovery searches the primary filing and HTML exhibits selected from SEC Document Format Files. It never downloads Data Files such as XBRL ZIP/XML packages; use the bounded `recovery_scope` counts to explain which HTML and non-HTML rows were encountered without dumping filenames.
- Use CIK plus SEC accession as the filing bundle identity; fall back to `doc_uuid` only when no accession exists.
- Preserve every issuer association on joint accessions. Coverage bookkeeping does not automatically attribute an event to every co-filer.
- Same-CIK companion accessions may be included and labeled. Results for CIKs outside the frozen census are excluded.
- Keep unresolved issuers under their CIK and skip ticker-based enrichment.

## 3. Classify bundles

Classify from bounded previews:

- **Confirmed** — the preview clearly states the requested event.
- **Flagged** — plausible but inconclusive after one permitted second look.
- **Excluded** — clearly unrelated; do not enrich or render it.
- Treat a summary with `metadata_only: true` or `candidate_sources: ["sec_fts"]` as a plausible second-look candidate rather than excluding it for an empty preview. Use its bounded `attachment_hints` to prioritize likely primary documents and substantive exhibits.

For only the top 3–5 plausible cover-page-only bundles, select the bundle locally and search its returned UUIDs:

```text
python3 <skill-dir>/scripts/filing_artifact.py select --artifact <scan-json-path> --bundle <bundle-id>
```

Call `search_in_documents` with one tight query, at most 20 UUIDs, `results_per_query: 3`, `max_results_per_doc_uuid: 3`, and `delivery: api`; pass the result to `summarize --fetch --save`. Stop as soon as classification is possible. Retrieve a known chunk only when bounded evidence ends at a material boundary. Never walk neighboring chunks or fetch an entire document speculatively.

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

- For a complete uncapped fast scan, report: “The fast scan surfaced {candidate_result_count} candidate results across {candidate_company_count} companies. Across the selected dates and filing types, {eligible_filing_count} filings from {eligible_company_count} companies were eligible for review. The queries were applied collectively across that filing set, which is effective for identifying likely events but does not verify every filing individually. For a filing-by-filing, audited review, run the same window in thorough mode.” Use the direct response’s `scan_summary` fields for these values.
- When fast `candidate_discovery_status` is `limited`, state that candidate retrieval reached a limit, so additional potentially relevant results may not be included, and recommend thorough mode. When it is `partial`, state that candidate discovery was incomplete; do not present the result as a clean scan or a no-match conclusion. Never report checked, not-checked, source-route, or local-index counts in a fast-mode user summary.
- For thorough mode, report `scan_summary.audit_status`, selected forms, the eligible filing and company counts, and the most significant event. Read the saved artifact only when an audited limitation or filing-level investigation needs explanation.
- In text mode, use `Ticker | Company | Event | Price (Δ) | 1Y | Filing`; mark doubtful bundles `⚑ flagged`.
- Say no relevant results were found only when `coverage-audit` reports `comprehensive: true`. A complete fast scan may report its observed matches, but it cannot support a no-match conclusion. Otherwise say no matches were surfaced by the bounded scan and name the limitation or unresolved issue.
- Do not use “census” in investor-facing prose. Say “eligible filing set” or “eligible filings” instead. This does not prove perfect thematic recall for image-only content or unavailable exhibits.
- Never reproduce filing chunks, complete descriptions, capability identifiers, or dashboard details already rendered elsewhere.
