---
name: dfin-daily-filing-monitor
description: Monitor the last one to three days of SEC filings for a named topic or corporate event. Use this skill when the user wants to screen, scan, or monitor very recent filings for a specific theme such as management changes, executive appointments, debt restructuring, M&A activity, earnings guidance, or regulatory events. Triggers include "management changes announced today", "morning scan for debt restructuring", "daily M&A filing monitor", "any [topic] filings recently?", and "scan recent 8-Ks for [topic]". Do not use it for theme-less filing-news briefings or longer historical windows.
---

# Daily Filing Monitor

Before the first DFin call, read `agent_help(topic="agent_guide")` once. Read `methodology_search` before discovery, `methodology_financials` before ratio enrichment, and `output_guidelines` before presenting substantive results. Read `methodology_delegation` before delegating any bounded work.

DFin skill version: 0.1.7, updated 2026-08-08.

Monitor US-listed SEC filers, including foreign private issuers and ADRs. Keep exchange-qualified tickers exactly as returned. Deliver one company card with one nested section per filing bundle, or a concise table when the user requests text.

## Non-negotiable context boundary

- Keep filing and document searches on API delivery and pass their artifact URLs directly to local helpers. A valid empty `list_latest_filings` API response may be saved unchanged as the census. Handle a valid empty `search_filings` response immediately with the helper's scope-bound `--empty` attestation; do not turn it into a reusable result artifact. If a harness security policy blocks another artifact URL, follow the `methodology_search` allowlist, retry, warning, and inline sequence exactly; inline is not a fallback for any other failure.
- Call `list_latest_filings` exactly once per scan. Its saved accession population is the immutable working census for current and historical dates alike; never refresh, replace, or expand it while that scan is running.
- Request stock context in stable batches of at most 10 resolved tickers with the delivery mode selected below. Pass the artifact URLs or complete inline batches directly to the dashboard helper.
- Treat every capability URL as sensitive. Never quote, log, persist, or share it.
- Download artifacts only into local helpers. Except for a methodology-approved inline fallback, never print, read, or return a complete artifact or chunk to model context.
- When inline fallback is required, write the direct response unchanged to temporary JSON without quoting or analyzing it. Use only the helper's bounded summaries and selected evidence for classification.
- Never read a generated dashboard back merely to inspect it. Materialize it once only when a host renderer requires complete HTML.

Use the bundled scripts without reading their source during a normal run:

- `scripts/filing_artifact.py`: fetch, group, summarize, and select filing evidence; maintain and audit the filer-coverage ledger.
- `scripts/build_dashboard.py`: consume inline or artifact stock context, assemble safe DATA, and write the dashboard or compact text rows.

## 1. Route the request

Extract the topic, date window, requested forms, sector filter, and output mode. Require one named event, theme, or evidence target. If this skill is explicitly invoked without one, ask for one monitoring theme and make no DFin calls. Otherwise default to the last two calendar days and use one day for “today.” Accept only inclusive windows of one to three calendar days. For a longer request, explain that complete cross-company monitoring is limited to three days, ask the user to narrow it, and make no DFin calls.

Choose forms:

- Honor explicit forms exactly.
- Before discovery, identify the plausible SEC disclosure paths for the topic and select a defensible form universe. Current reports such as `8-K` and `6-K` are a starting point, not a universal answer; prospectus, registration, annual, quarterly, and foreign-issuer forms may also carry the event.
- Treat examples as guidance, not an exhaustive or mandatory mapping. For example, a capital-raising scan should consider whether offering, prospectus, or registration filings are needed in addition to current reports.
- Pass the complete selected form list to `list_latest_filings`. Call `search_filings` separately per form because its `filing_type` is scalar.
- Finalize the form universe before enumeration. If later evidence suggests a broadly missing form, finish the frozen scan with a scope note; start a new scan only when expanded universe-wide coverage is requested. A companion form for a company already in the census may still surface through its ticker-scoped reconciliation search and is handled below.

Use dashboard mode by default. Use text mode when the user says “no dashboard,” “just list them,” “just text,” or equivalent.

## 2. Enumerate, search, and reconcile

Create new temporary census and coverage-state paths outside the repository. Enumerate the complete point-in-time accession population once before thematic search:

```yaml
filing_types: <agent-selected form-prefix array>
days: <1-3>
limit: -1
result_level: accession
data_in_db_only: false
delivery: api
```

For a non-empty response, pass `results_url` on stdin without exposing it, save the immutable census outside the repository, and initialize the new ledger with every selected form repeated as `--expected-form`:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-init --state <coverage-state-path> --expected-form <form> [--expected-form <form> ...] --save <census-json-path> --fetch
```

For a valid empty inline response, write the complete response unchanged to `<census-json-path>` and use `--artifact <census-json-path>` instead of `--save ... --fetch`. The coverage-state file must not already exist: the helper refuses to overwrite it. The helper verifies accession-level delivery, the one-to-three-day window, `limit: -1`, the selected form universe, counts, and coverage metadata, and records a stable census fingerprint without printing the population. A joint accession may list several issuers; preserve every listed issuer CIK in the frozen census while retaining one unique accession count. Use the returned `date_from` and `date_to` for every search rather than inferring them from `days`. Preserve every reported issue. A structurally valid census with `coverage.complete=false` still produces a ledger for an explicitly incomplete best-effort scan. If enumeration, download, JSON decoding, or census saving fails before a ledger exists, run only the form-specific broad searches and classification steps; skip reconciliation and `coverage-audit`, state that no census was available, and never present a no-match or comprehensive conclusion. Do not call `list_latest_filings` again, invent pagination, or widen the window.

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
delivery: api
include_content_head: true
include_content_tail: true
content_preview_chars: 150
```

Finalize the thematic query set before recording the first search receipt. Expand only a deficient query and never above 10 results without stating why. If a query changes after any receipt was recorded, reset only the local search-derived ledger, then rerun every broad and ticker search with the revised set:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-reset-searches --state <coverage-state-path>
```

This preserves the census population, scope, `coverage.as_of`, upstream issues, and fingerprint. Never re-run `coverage-init` or `list_latest_filings` within the scan. On an external SEC timeout, wait 30 seconds and retry once unchanged. If the retry fails, preserve the original date, form, ticker, and query scope, record `timeout`, and report temporary unavailability; narrowing the coverage scope cannot satisfy reconciliation.

Pass each returned `results_url` on stdin to the filing helper; never place it in prose. Fetch, save, validate, record coverage, filter out new companies, and emit bounded eligible summaries in one operation. The helper leaves the downloaded response byte-for-byte unchanged and writes a compact `<temporary-json-path>.summary-index.json` sidecar containing only census-bound, model-safe bundle metadata. Use a distinct temporary path for every broad or ticker-scoped search so later classification cannot overwrite an earlier candidate artifact:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-add-search --state <coverage-state-path> --expected-form <form> --fetch --save <temporary-json-path> --query "<query 1>" [--query "<query 2>" ...]
```

If the form-specific search still fails after its prescribed retry, record the form-level failure without fabricating a successful receipt:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-add-search --state <coverage-state-path> --expected-form <form> --failed --reason <timeout|rate_limited|malformed_response|artifact_unavailable> --query "<query 1>" [--query "<query 2>" ...]
```

For a successful empty broad search, use the same command with `--empty` instead of `--fetch --save <temporary-json-path>`; do not create a fake result artifact. This is an explicit agent attestation that the just-completed scoped tool call returned `{"count": 0}`. For non-empty results, use one immutable saved path per call. The helper rejects byte-identical response payloads and reuse of a canonical artifact path.

The helper prints no more than 15 eligible accession-level bundle summaries with previews of at most 220 characters, one validated SEC source link per bundle, and explicit remaining-count metadata. New-company results never enter these summaries. Keep the temporary artifact and its summary-index sidecar outside the repository and delete both after the scan. If `truncated` is true, page with the same command below until every eligible returned bundle has been reviewed. The helper automatically reads the compact sidecar, so later pages do not reopen, refilter, or regroup the complete search response; if the sidecar is absent or invalid, it safely falls back to the raw artifact:

```text
python3 <skill-dir>/scripts/filing_artifact.py summarize --state <coverage-state-path> --artifact <temporary-json-path> --offset <offset + shown_count>
```

If the methodology-approved security-policy fallback required `delivery: inline`, write the entire direct response unchanged to `<temporary-json-path>`, then use `coverage-add-search --artifact <temporary-json-path>` with the same state, form, and query arguments. Do not run an unfiltered summary first.

Do not invent or rewrite an artifact URL. Both delivery branches preserve one temporary file per search for later bundle selection; resume with the identity rules.

### Reconcile missing filers

After every form-specific broad search is recorded, request one bounded page of missing filers:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-missing --state <coverage-state-path>
```

After processing and marking that page, request `coverage-missing` again from offset zero because the pending set has changed. Repeat until `missing_filer_count` is zero. Failed filers leave the pending queue but remain audit failures. Use `--offset` only to page through one unchanged snapshot before any marks are applied.

For every returned search ticker, call `search_filings` with this request. **Omit `filing_type`** so relevant companion disclosures in other forms can surface:

```yaml
ticker: <exchange-qualified ticker from coverage-missing>
date_from: <original inclusive filing date>
date_to: <original inclusive filing date>
queries: <the exact same thematic queries>
results_per_query: 5
delivery: api
include_content_head: true
include_content_tail: true
content_preview_chars: 150
```

For a usable non-empty result, fetch, save, validate, mark the census filer checked, record companion accessions, exclude new companies, and emit only eligible summaries in one operation. Repeat the exact query set:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-mark --state <coverage-state-path> --ticker <ticker> --status checked --fetch --save <ticker-search-json-path> --query "<query 1>" [--query "<query 2>" ...]
```

For the methodology-approved inline fallback, write the response unchanged and replace `--fetch --save <ticker-search-json-path>` with `--artifact <ticker-search-json-path>`. The helper rejects wrong-ticker, conflicting-identity, or out-of-window results before recording the check.

For a successful zero-result response, use the same command with `--empty` instead of `--fetch --save <ticker-search-json-path>`. This explicitly attests the just-completed ticker/date/query call; never substitute an old or copied response.

For a timeout, `429`, malformed response, failed artifact retrieval, or unresolved result, follow the applicable retry guidance and record the unresolved attempt rather than treating it as no match:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-mark --state <coverage-state-path> --ticker <ticker> --status failed --reason <stable-issue-code>
```

Use `timeout`, `rate_limited`, `malformed_response`, `artifact_unavailable`, or `unresolved_ticker` as the stable issue code. Do not put error messages or URLs in `--reason`.

If `coverage-missing` returns no usable ticker, resolve it with `search_securities` only when one issuer match is unambiguous, then bind the exchange-qualified result to the census CIK and rerun `coverage-missing`:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-bind-ticker --state <coverage-state-path> --cik <cik> --ticker <resolved-ticker>
```

If no unambiguous ticker can be resolved, record the terminal unresolved mapping by CIK:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-mark --state <coverage-state-path> --cik <cik> --status failed --reason unresolved_ticker
```

Do not create one worker per ticker or prescribe fixed concurrency. When the `methodology_delegation` eligibility gate passes, delegate bounded retrieval, reconciliation, enrichment, and mechanical compilation with minimal task packets and compact structured output. Require the methodology's task-appropriate result-to-source mapping and worker self-check so the coordinating agent can validate the batch without reconstructing references or repeating retrieval. Serialize shared ledger updates. Keep warnings, ambiguous classification, materiality, verification, and final synthesis with the coordinating agent.

Run the audit after all follow-ups and before enrichment:

```text
python3 <skill-dir>/scripts/filing_artifact.py coverage-audit --state <coverage-state-path>
```

An audit with `complete: false` exits nonzero and means the frozen-census scan is not comprehensive. A failed broad-form search, conflicting or unverified identity, or unresolved census filer blocks completion. A tickerless filer already matched by SEC-source CIK in a broad result is checked and may remain under its CIK, but a tickerless pending filer must be resolved or failed. A validated new accession for an existing census CIK is an included companion and may be classified and rendered without changing the census. A validated accession for a CIK outside the census is excluded, never reconciled or enriched, and does not block completion; report only its aggregate count using the audit's `post_start_exclusion_note`. Never turn a failed, unsearchable, conflicting, or unpolled census filer into a no-match conclusion. Delete the coverage state, saved census, and all temporary filing artifacts after the final result.

### Identity rules

- Use CIK as the authoritative coverage-ledger identity and preserve every returned ticker alias. Use the ledger's selected exchange-qualified ticker for a missing-filer search.
- Use a returned exchange-qualified ticker as the primary presentation identity without modification.
- Resolve a bare or missing ticker with `search_securities` only when one issuer match is unambiguous.
- If unresolved, keep the filing under its CIK or bundle identity and skip stock/ratio enrichment.
- When an ambiguous ticker alias is independently reconciled by authoritative SEC-source CIKs, keep the affected issuers under their CIK identities and skip ticker-based enrichment for them.
- Outside the coverage ledger, use CIK only as a secondary collision key. Never replace a valid presentation ticker with CIK.
- Use CIK plus SEC accession as the bundle identity; fall back to `doc_uuid` when no accession is available.
- Normalize `8-K 10.2` into bundle form `8-K` and document designation `10.2`.
- Keep the original accession map immutable. Deduplicate included companions and excluded new-company filings by authoritative SEC accession; neither class may enter `coverage-missing`. When a search result matches a frozen joint accession, use its frozen issuer CIK associations to mark every associated issuer surfaced or checked; this is coverage bookkeeping only and does not automatically attribute an event to every issuer.

### Classify bundles

Classify from bounded previews before fetching more evidence:

- **Confirmed** — the preview clearly states the requested event. Include `confirmed` in bundle tags.
- **Flagged** — plausible but inconclusive after the permitted second look. Include `flagged`, set `flag: true`, and provide a short reason.
- **Excluded** — clearly unrelated. Do not enrich or render it.

For only the top 3–5 plausible cover-page-only bundles, take one scoped second look. First select the bundle locally:

```text
python3 <skill-dir>/scripts/filing_artifact.py select --artifact <temporary-json-path> --bundle <bundle-id>
```

Use the returned UUID batches in `search_in_documents` with one tight query, `results_per_query: 3`, and `delivery: api`. Never send more than 20 UUIDs. For API delivery, pass the returned URL to `summarize --fetch --save <second-look-json-path>`. If the methodology-approved security-policy fallback requires inline delivery, write its complete direct response unchanged to `<second-look-json-path>` and run `summarize --artifact <second-look-json-path>`. Use `select --artifact <second-look-json-path> --bundle <bundle-id>` only when the summary remains inconclusive, then stop when classification is possible. The selected result includes an `evidence_location` with the exact matching `doc_uuid`, `chunk_num`, and `content_chars`; if the bounded evidence ends at a material boundary, retrieve only that known chunk. Delete the second-look file after classification.

If the needed exhibit was absent, use one exact-ticker, exact-filing-date `search_filings` call with one tight query. Never run a ticker follow-up without a date bound.

For a user-requested company deep dive, search selected bundle documents with focused queries. Do not walk neighboring `chunk_num` values or fetch a whole document because a hit ends at a boundary. Retrieve a known chunk only when the final evidence requires it.

## 3. Enrich selected companies

### Text mode

Partition resolved tickers in stable order into batches of at most 10. Call `get_stock_context` once per batch with `fields: ["price", "returns"]` and `delivery: inline`; batches may run in parallel. Skip ratios and descriptions. Put every complete response object in the manifest's `stock_context_batches` array, unedited and including `format`, `count`, `success_count`, `error_count`, and `results`, then feed it to:

```text
python3 <skill-dir>/scripts/build_dashboard.py --text --stock-cache <temporary-cache-path>
```

Present only the returned rows in the table described below. Delete the cache after the final result.

### Dashboard mode

Read `methodology_financials`. Then:

1. For every resolved included company, call `get_financial_ratios` for the current year with `period: "FY"` and fields `returnOnEquity`, `returnOnInvestedCapital`, `netDebtToEBITDA`, and `ebitdaMargin`. On unavailable data, try the prior year and then one year earlier; stop at the first valid response.
2. Partition resolved tickers in stable order into batches of at most 10. Call `get_stock_context` once per batch with `delivery: api`; batches may run in parallel. Omit `fields` because API delivery returns complete artifacts and rejects a supplied field selector.
3. Put each compact ratio response in its company's `ratios` field and put every stock-context capability URL in the manifest's `stock_context_urls` array. Do not inspect artifact payloads outside the helper. Never retype, truncate, paraphrase, or hand-summarize a `data` field inside `results`; the builder fetches and merges the exact response shapes locally.

The builder extracts only top-level company name, ticker, description, structured price/returns/technicals, date-keyed earnings history, and allowlisted profile fields. It discards database, user-note, executive, estimate, and other unused sections.

The builder merges the batches locally and selects each company by ticker. It rejects a batch above 10 results, repeated or unrequested ticker results, and successful batches that omit an uncached ticker. It verifies fresh and cached stock identity and the ticker in every compact ratio response before duplicate company records are merged. For duplicate ratio responses, it uses the valid response with the newest integer fiscal year, preserving input order as the tie-breaker. Every uncached resolved ticker must have either a data result or an explicit error result. A malformed batch or ticker payload, conflicting manifest identity, two resolved tickers sharing one non-empty CIK, stock ticker or supplied secondary CIK mismatch, or ratio ticker mismatch aborts the build instead of creating a silently incomplete dashboard. A truly omitted stock CIK remains valid sparse data, but a supplied malformed CIK aborts. An invalid cache entry is discarded and refetched when a fresh source is available; without a fresh source it aborts. Legitimate sparse inline results, unresolved issuers, explicit availability errors, and refresh-required responses remain graceful: unavailable values stay `—`, unresolved issuers are never fetched, and filing cards remain present. Duplicate company records merge by qualified ticker, while unresolved issuers merge only by CIK or bundle identity; every filing requires a bundle ID, duplicate accession IDs merge, and conflicting or malformed filing bundles are omitted with `manifest_conflict`.

The builder applies these rules:

- Keep returns in five fixed positions: Daily, WTD, MTD, YTD, and 1Y. Use `null` for missing values; missing is never zero. Daily is shown only in the price change line; the return tiles display WTD, MTD, YTD, and 1Y.
- Sort earnings-history ISO date keys, select the latest four, and display them oldest-first. Actual above estimate is a beat; below is a miss; equal or missing is neutral.
- Multiply ROE, ROIC, and EBITDA margin decimal fractions by 100 exactly once. Leave ND/EBITDA as a multiple.
- Label ratios with the source vintage as `FY<year>`; do not add the fiscal-year-end month. Omit the volume block when current volume is unavailable or nonpositive instead of displaying a misleading zero and `0.00×` average volume.
- Preserve the complete description in the collapsible About panel without copying it into the narrative response.

## 4. Build and render

Create a compact manifest and feed it to `build_dashboard.py` on stdin. Do not interpolate it into Python or shell source. Use this shape:

```json
{
  "title": "Management Changes",
  "ftype": "8-K / 6-K",
  "range": "Aug 5–6, 2026",
  "filters": [["appointments", "Appointments"]],
  "stock_context_urls": ["<single-use batch capability>", "<next batch capability>"],
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

For inline MCP responses, replace `stock_context_urls` with `"stock_context_batches": [{<complete ticker-keyed batch>}, ...]`. Copy every response object unchanged; never extract only `results` or rewrite any nested `data` string. Never provide both keys. The builder retains backward compatibility with singular `stock_context_url` and `stock_context`, but the skill uses the batched keys consistently.

Run:

```text
python3 <skill-dir>/scripts/build_dashboard.py --template <skill-dir>/dashboard.html --output <cwd>/filing-monitor-<topic>-<date>.html --stock-cache <temporary-cache-path>
```

The builder prints only the saved path, counts, and per-ticker status. If any artifact reports `refresh_required`, it still caches successful batches; request fresh batches only for tickers not already in the temporary cache and rerun with the same cache. Delete the cache after the final build.

Rendering contract:

- If the host exposes `show_widget`, render the completed HTML as the primary result. Do not duplicate company details in prose. If the tool requires full HTML, materialize the page only once for that final call.
- Otherwise use another verified HTML renderer when available.
- Without a renderer, link the saved HTML and use the helper's `--text` mode for the text table.
- On render failure, retain the saved HTML and fall back through the helper's `--text` mode.
- Skip saving only when the user explicitly requests render-only output.

The dashboard validates SEC HTTPS links, allowlists visual classes/colors, uses event listeners instead of inline handlers, filters nested bundles independently, and hides a company only when none of its bundles match.

## 5. Present results

Read `output_guidelines` before presenting substantive results.

- **Dashboard:** state the selected form universe, frozen-census accession and filer counts, completed broad-form searches, broadly surfaced and individually checked census-filer counts, failures, included companion count, `coverage.as_of`, coverage issues or audit warnings, and the single most significant event; keep it to 1–2 compact lines, render the widget, and link the saved file when applicable. If the audit's excluded post-start count is nonzero, add its exact `post_start_exclusion_note` and no per-company detail for those exclusions.
- **Text:** give the same compact coverage statement, then show one row per filing bundle with `Ticker | Company | Event | Price (Δ) | 1Y | Filing`. Mark doubtful bundles `⚑ flagged`. Do not include descriptions, ratios, or EPS history.
- **No matches:** only when the audit is complete, say no relevant results were found within the selected form universe and suggest broader queries or a different topic-appropriate form universe. When the audit is incomplete, say no matches were found in an incomplete scan and name the unresolved coverage issue.

Phrase completeness narrowly: every filer in the one frozen census within the selected form universe has a recorded broad or ticker-scoped check against available searchable filings. `coverage.as_of` identifies when that census was assembled; later new-company filings are outside it and explicitly excluded. This does not prove perfect thematic recall: it covers available primary text and surfaced exhibits, not guaranteed image-only filings or exhibits that were not surfaced by the search. The audit reports `request_binding: agent_attested` because `search_filings` responses do not independently authenticate the query that produced them; the coordinating agent must preserve the exact tool-call-to-receipt association for both empty and non-empty responses.

Never reproduce filing chunks, complete descriptions, artifact URLs, or dashboard details already shown elsewhere.
