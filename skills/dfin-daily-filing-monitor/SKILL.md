---
name: dfin-daily-filing-monitor
description: Monitor recent SEC filings for any topic or corporate event. Use this skill whenever the user wants to screen, scan, or monitor SEC filings for a specific theme — management changes, executive appointments, debt restructuring, M&A activity, earnings guidance, regulatory events, or any other topic. Triggers on phrases like "any [topic] filings recently?", "monitor for [topic]", "scan recent 8-Ks for [topic]", "what companies announced [topic] this week?", "daily filing briefing", "morning scan", or any request to track corporate events across multiple companies via SEC disclosures. Also use when the user says something casual like "what happened in filings today" or "any interesting 8-Ks this week?".
---

# Daily Filing Monitor

Screen recent SEC filings for any topic, then enrich each result with live stock context and financial ratios — delivered as an interactive dashboard by default, or a concise text table if the user prefers. The workflow has three phases: (1) find the relevant filings, (2) pull market and fundamental data for each company, (3) render everything in a single dashboard card per company (or skip to a text table — see Presenting results).

**Scope: US-listed companies filing with the SEC.** This covers domestic issuers (8-K, 10-Q, 10-K) and foreign private issuers that file with the SEC, including ADRs (which file 20-F annual reports and 6-K interim reports). Every company here is treated as US-listed, so tickers always use the `.US` suffix — there is no non-US exchange handling in this skill.

## Requirements

- dfin.pro MCP must be connected (`search_filings`, `get_stock_context`, `get_financial_ratios`)
- Bash + an available Python interpreter (`python3`, `python`, or `py -3`) for parsing large result sets and writing the saved dashboard file
- `show_widget` for the dashboard

The MCP parameters below were verified against the tool schemas. If any call rejects a parameter (API drift), call `agent_help(topic="agent_guide")` to re-check the contract rather than guessing.

---

## Phase 1: Find Relevant Filings

### 1a. Parse the request

Extract:
- **Topic**: What kind of corporate event? (e.g. "management changes", "debt restructuring", "M&A")
- **Date range**: Default = last 2 calendar days from today. Accept natural language ("this week" → 7 days, "today" → 1 day). Format as `YYYY-MM-DD`.
- **Filing type**: Default `8-K` (the domestic current-report form where most event-driven disclosures land). Use `10-Q`/`10-K` only if explicitly requested. For foreign private issuers / ADRs, the equivalents are `6-K` (interim/current events, analogous to 8-K) and `20-F` (annual report, analogous to 10-K) — include these when the scan should cover ADRs or when explicitly requested.
- **Sector filter**: Note it — apply as a post-filter since `search_filings` has no sector parameter.
- **Output mode**: Default = dashboard. Switch to **text mode** if the request says anything like "don't build a dashboard", "no dashboard", "just list them", or "just text" — then skip Phase 3 and present a concise table instead (see Presenting results).

Don't ask for clarification upfront — make a reasonable assumption and proceed.

### 1b. Generate 5 search queries

Cover the topic from five angles:

- **Query 1 — Plain language**: How a press release would describe it.
- **Query 2 — Legal/technical language**: The terminology that appears inside SEC filings.
- **Query 3 — SEC item number**: The specific 8-K item that triggers this disclosure type.
- **Query 4 — Process/transition terms**: Procedural language around timing, approvals, successors.
- **Query 5 — Financial/compensation terms**: The financial aspects that accompany the event.

Common 8-K items:
| Item | Event type |
|------|-----------|
| 5.02 | Executive departures, appointments, director changes |
| 1.01 | Material agreements (M&A, credit facilities) |
| 1.03 | Bankruptcy or receivership |
| 2.02 | Earnings releases, results of operations |
| 2.06 | Material impairments |
| 8.01 | Other material events |

**Example — management changes:**
1. `"new CEO CFO president appointed management change"`
2. `"appointment chief executive officer principal officer departure resignation"`
3. `"Item 5.02 departure appointment directors certain officers"`
4. `"effective date successor interim transition board approved"`
5. `"employment agreement base salary severance compensation executive"`

**Example — M&A:**
1. `"merger acquisition deal announced definitive agreement"`
2. `"purchase price consideration closing conditions representations warranties"`
3. `"Item 1.01 material definitive agreement merger acquisition"`
4. `"regulatory approval antitrust HSR filing closing conditions"`
5. `"cash per share premium enterprise value EBITDA multiple consideration"`

**Example — debt restructuring:**
1. `"debt restructuring refinancing credit agreement"`
2. `"term loan revolving facility amendment restated bankruptcy"`
3. `"Chapter 11 reorganization plan Item 1.03 credit agreement amendment"`
4. `"lenders noteholders consent solicitation exchange offer waiver"`
5. `"covenant leverage ratio interest coverage liquidity maturity extension"`

### 1c. Run search_filings

```
filing_type: "8-K"
date_from: <computed>
date_to: <today>
queries: [query1, query2, query3, query4, query5]
results_per_query: 20
```

### 1d. Parse and filter results

Results often exceed 100KB and get saved to a file. Parse with bash + Python, using whichever interpreter is available on this machine (`python3`, `python`, or `py -3` — on Windows `python3` is often absent):

```bash
cat "<result-file-path>" | python -c "
import json, sys
data = json.load(sys.stdin)
results = data.get('result') or data.get('results') or []

best = {}
for r in results:
    if not isinstance(r, dict):
        continue
    ticker = r.get('ticker', '')
    score = r.get('reranking_score', 0)
    if ticker not in best or score > best[ticker]['score']:
        best[ticker] = {
            'ticker': ticker,
            'name': r.get('name', ''),
            'score': score,
            'date': r.get('filing_date', ''),
            'filing_type': r.get('filing_type', ''),
            'uri': r.get('meta_data', {}).get('source_uri', ''),
            'content': r.get('content', '')[:220]
        }

ranked = [v for v in sorted(best.values(), key=lambda x: -x['score']) if v['score'] > 0.01]
print(f'{len(ranked)} tickers above threshold (showing top 15)')
for v in ranked[:15]:
    print('---')
    print(f'Score: {v[\"score\"]:.4f} | {v[\"ticker\"]} | {v[\"name\"]}')
    print(f'Filed: {v[\"date\"]} | {v[\"filing_type\"][:60]}')
    print(f'URI: {v[\"uri\"][:120]}')
    print(f'Content: {v[\"content\"]}')
    print()
"
```

Keep the preview short (≤220 chars) — it is only used to band each name below, not to reproduce the filing.

Band each ticker from the first-pass snippet alone — **do not run extra per-ticker searches to "verify"** (that pulls full filing chunks into context and is the single biggest token cost). Judge relevance, don't over-judge: when in doubt, include and flag rather than exclude, and let the user decide.

Three bands:

- **Confirmed** — the snippet clearly shows the event: for management changes, a named person plus appoint / resign / depart / promote language, or an explicit "Item 5.02 … appointment/departure" naming a person. Include; tag `confirmed`; `flag: false`.
- **Flagged** — positive score but the snippet is inconclusive: cover-page only, or generic boilerplate (bylaws officer sections, credit-agreement "Administrative Agent may resign", agency/dealer agreements). **Include it anyway**, tag `flagged`, set `flag: true`, and give a short `flagnote` saying why (e.g. "cover page only — may be a bylaws amendment"). This surfaces high-scoring names the user may want without you silently dropping them.
- **Excluded** — only when the snippet is clearly an unrelated topic, or `reranking_score` ≤ ~0.02.

The dashboard renders flagged cards with an amber "⚑" badge and a `Flagged` filter, so confirmed and doubtful names are visually separated but both present.

**Optional deep dive (only if the user asks about a specific company)** — re-run `search_filings` scoped to that name: `ticker="<TICKER>.US"` (use the exchange-qualified form — the bare symbol returns no results), same `queries`, higher `results_per_query`; or `get_document_content` (via `doc_uuid` + `chunk_num`) to read the actual disclosure. Both are token-heavy, so reserve them for on-demand drill-downs, not the default scan.

---

## Phase 2: Enrich with Market & Fundamental Data

For each company that passes the filter, make two parallel calls:

**Text mode shortcut:** if the user asked for text output (no dashboard), you only need latest price, daily change, and the 1Y return — so call `get_stock_context` and **skip `get_financial_ratios`** (ratios, EPS dots, and description aren't shown in the text table). This saves one call per company.

### 2a. get_stock_context

```
ticker: "<TICKER>.US"
```

All companies in scope are US-listed (including ADRs), so always use the `.US` suffix. If the ticker doesn't resolve, run `search_securities` to confirm the correct `.US` symbol before retrying.

Extract the fields below. **`get_stock_context` may return with some fields missing or null** (common for recent listings, thin-coverage names, or ADRs) — this is expected, not an error. For any field that's absent, set the corresponding DATA key to `"—"` (or omit optional keys like `rb`/`rc`) and carry on; never fabricate a value and never abort the company over a missing field.

- **Price & daily change** (`price`, `change`, `change_p`)
- **Returns** (the 5 entries in `r`, in order): **Daily** = `change_p`; **WTD**, **MTD**, **YTD** from `todate_returns`; **1Y** = `1y` cumulative from `trailing_returns`
- **Market cap** (`mkt_cap`)
- **52-week high/low** (`high_52w`, `low_52w`) + current price for range position
- **Volume today vs 52-week avg** (`volume`, `vol_avg52w`) → compute ratio
- **Beta** (`Technicals.Beta`)
- **Forward P/E** (`fwd_pe`)
- **Company description** (`General_Information.Description`) — full text, used in collapsible panel
- **EPS beat/miss streak**: last 4 quarters from `Earnings_History` — for each, check if `epsActual >= epsEstimate` (beat = ✓, miss = ✗). Note this benchmark is the **consensus analyst estimate**, not management guidance; the dashboard labels it "vs Est" accordingly.

### 2b. get_financial_ratios

```
ticker: "<TICKER>.US"
year: <current_year - 1>   # most recent completed fiscal year
period: "FY"
fields: ["returnOnEquity", "returnOnInvestedCapital", "netDebtToEBITDA", "ebitdaMargin"]
```

If the call returns null or empty for `year - 1`, retry with `year - 2`. If a ratio is still unavailable, set its DATA key to `"—"` rather than leaving it blank. Likewise, if fewer than 4 quarters of EPS history exist, include only the quarters available (the dashboard pads/omits gracefully).

Extract:
- **ROE** (`returnOnEquity`) — format as %
- **ROIC** (`returnOnInvestedCapital`) — format as %
- **ND/EBITDA** (`netDebtToEBITDA`) — format as "x" multiple
- **EBITDA margin** (`ebitdaMargin`) — format as %

---

## Phase 3: Render the Dashboard

The dashboard UI lives in `dashboard.html` in the same directory as this SKILL.md (shown in the `<location>` tag above this skill's content — use that absolute path). **Read it once**, then in your `show_widget` call paste that template with `/* INJECT_DATA */` replaced by your DATA object. Do **not** read a saved/rendered `.html` file back into context afterward — you already have the template and DATA, so re-reading just doubles the template's token cost.

### Step 1 — Build the DATA object

```json
{
  "title": "<topic, e.g. Management Changes>",
  "ftype": "<filing type label for the header, e.g. \"8-K\", \"10-K\", or \"8-K / 10-Q\">",
  "range": "<date range, e.g. Jun 28–30, 2026>",
  "stats": [["N", "Label"], ...],
  "filters": [["all", "All (N)"], ["confirmed", "Confirmed (X)"], ["flagged", "Flagged (Y)"], ...],
  "cos": [ <company objects — see schema below> ]
}
```

Per-company schema (use these exact short keys):

| Key | Value |
|-----|-------|
| `t` | Ticker symbol |
| `bg` / `fg` | Badge background / foreground hex. Pick distinct colors per ticker, drawn from the dfin.pro brand palette so cards stay on-brand: deep navy (`#101923`, `#142231`, `#1d2935`) or brand-green (`#12ce5d`, `#0f9d49`, `#167247`) backgrounds with white (`#ffffff`) or pale-green (`#cae8d7`) foreground; the gold `#d2b90a` works as an occasional accent badge. |
| `tags` | Space-separated filter tag IDs matching the `filters` array. Include `confirmed` or `flagged` (per the banding in 1d) plus any event-type tags. |
| `flag` | `true` for a Flagged (doubtful) name — renders an amber "⚑" badge. Omit or `false` for Confirmed. |
| `flagnote` | Short reason shown in the badge when `flag` is true, e.g. `"cover page only — may be a bylaws amendment"`. |
| `n` | Full company name |
| `s` | `"EXCHANGE · Sector"` |
| `mc` | Market cap string e.g. `"$30.3B"` |
| `b` | Beta string e.g. `"1.00"` |
| `ev` | Events: `[["pill-class", "LABEL", "Subject", "detail text"], ...]`. For personnel events the subject is the person's name; for non-personnel events (M&A, debt, etc.) use the subject of the event (counterparty, facility, plan) — it renders as `**Subject** — detail`. |
| `p` | Price string e.g. `"$28.79"` |
| `pc` | Change string e.g. `"+$0.60 (+2.13%)"` |
| `pp` | `true` if change is positive |
| `r` | Returns: `[[value, is_positive], ...]` — 5 entries: Daily, WTD, MTD, YTD, 1Y |
| `lo` / `hi` / `cur` | 52w low, 52w high, current price (numbers) |
| `rb` | Range badge text e.g. `"↓ Near 52W Low"` or `"★ 52W High"` — omit if neither |
| `rc` | Range badge class: `"badge-low"` or `"badge-high"` |
| `v` | Volume string e.g. `"15.1M"` |
| `vr` | Volume ratio string e.g. `"1.75×"` |
| `vh` | `true` if ratio > 1.5 (highlights the volume in dfin gold) |
| `roe` / `roic` / `nd` / `em` / `pe` | Fundamental strings e.g. `"18.5%"`, `"-1.27×"`, `"19.5×"` |
| `eps` | `[[beat, "pct"], ...]` — up to 4 entries oldest-first (fewer is fine); beat: `1`=beat `0`=miss `-1`=neutral/no data |
| `fd` | Filing date string e.g. `"Jun 29"` |
| `fl` | SEC filing URL |
| `d` | Company description (1–3 sentences) |

Event pill classes:
- Personnel: `pill-in` (green, appointment), `pill-out` (red, departure), `pill-promo` (blue, promotion), `pill-board` (purple, board/director), `pill-interim` (gray, interim)
- Corporate events: `pill-deal` (indigo, M&A / agreements), `pill-debt` (orange, debt / credit / restructuring), `pill-spin` (amber, spin-off / separation), `pill-event` (slate, other material events)

### Step 2 — Save, then render

Do both in one pass, saving first so a saved copy exists even if the widget fails.

**1. Save to disk (default).** Write the finished page to the **current working directory** as `filing-monitor-<topic-slug>-<YYYY-MM-DD>.html`, by injecting DATA into the template *on disk* — never echo the injected HTML to stdout or Read the saved file back (either reloads the whole page into context). Skip this step only if the user asked to render in-app without saving (e.g. "just show it, don't save"). Text mode has no HTML, so nothing to save.

```bash
python - <<'PY'
import datetime, re, pathlib
tmpl = pathlib.Path(r"<ABSOLUTE_PATH_TO>/dashboard.html").read_text(encoding="utf-8")   # from the <location> tag
data = r'''
<YOUR DATA OBJECT AS VALID JSON>
'''
topic = "<topic, e.g. management changes>"
slug = re.sub(r'[^a-z0-9]+', '-', topic.lower()).strip('-')
out = pathlib.Path(f"filing-monitor-{slug}-{datetime.date.today()}.html")
out.write_text(tmpl.replace("/* INJECT_DATA */", data), encoding="utf-8")
print("Saved", out.resolve())
PY
```

This costs only the small DATA payload (the template is read from disk, not context). Exporting later would re-materialize the whole page in context, so always save here rather than after the fact.

**2. Render.** Call `show_widget` with the template (already read once) and `/* INJECT_DATA */` replaced by the same DATA object. Then note the saved path in one line of your summary.

**If rendering fails** — `show_widget` errors, the template can't be read, injection breaks, or the user reports the widget didn't render — don't fail the task. Fall back to **text mode** (see Presenting results) and print the same findings as a concise table. The saved `.html` from step 1, if written, is still valid — point the user to it.

---

## Token efficiency

The costly moves are large tool results landing in context. Keep the scan lean:

- **Never read the raw `search_filings` result into context.** It routinely exceeds 100KB and is auto-saved to a file — always distill it with the Phase 1d Python script and read only the distilled output.
- **Band from first-pass snippets; skip per-ticker "verification" searches by default** (see 1d). Those return full filing chunks and were historically the biggest single cost. Reserve them and `get_document_content` for user-requested deep dives.
- **Render in one pass.** Read `dashboard.html` once and inject inline in the `show_widget` call. Saving to disk (Phase 3 Step 2) is fine — it injects into the template on disk — but never Read the saved file back or echo its contents to stdout, which would put the whole page through context twice.
- **Keep the distiller preview short** (≤220 chars/ticker, top ~15) and use the compact short DATA keys as defined — don't add verbose fields.
- `get_stock_context` and `get_financial_ratios` are one call each per included company; limiting the number of included companies (via sensible banding) is the main lever on their cost.

## Presenting results

Keep on-screen output concise. This constrains what you **print**, not how much you reason internally — do the full scan, banding, and checks as needed; just don't narrate every step or repeat data that's already shown elsewhere.

**Do not duplicate details across the screen and the dashboard.** The per-company details live in exactly one place:

- **Dashboard mode (default):** print only a 1–2 line headline — the count and the single most significant event (e.g. "5 companies found; most notable: AEO CFO departure"). Then render the dashboard. Do **not** also describe each company in prose — that doubles token cost for no benefit.
- **Text mode (user opted out, or dashboard fallback):** skip `show_widget` and print a compact markdown table, one row per company, then stop. Columns:

  | Ticker | Company | Event | Price (Δ) | 1Y | Filing |
  |--------|---------|-------|-----------|-----|--------|

  where **Event** = who + what changed (e.g. "Michael Mathias — EVP & CFO → advisory role, eff. Aug 3"), **Price (Δ)** = latest price with daily change (e.g. "$17.29 (+0.52%)"), **1Y** = trailing 1-year return, **Filing** = SEC link. Flag doubtful names inline with a "⚑ flagged" note in the Event cell. Omit descriptions, ratios, and EPS history — text mode is deliberately lean.

If no genuinely relevant results are found, say so in one line and suggest broader queries or a wider date range.
