---
name: dfin-research
description: >-
  Research public companies, stocks, ETFs, and funds with dfin.pro's source-grounded financial data. Use for company or peer analysis, earnings research, statements and ratios, filing, transcript, or report evidence, prices, fund analytics, or other evidence-backed public-equity work.
---

# dfin.pro Research

DFin skill version: 0.2.0, updated 2026-11-08.

Before the first DFin tool call in a task, read `agent_help(topic="agent_guide")` once if it has not already been read. It holds the current rules for tools, retries, and efficiency, and lists the focused topics to load for each kind of work. If this skill and the guide differ, follow the guide.

## Plan the work

1. Check prior work. Use `search_notes` to find notes relevant to the question. If one is relevant, call `find_linked_notes` on the strongest match with the default `max_hops=2`, and re-seed at most twice from a result that opens a distinct, relevant branch. This read-only check doesn't need `methodology_notes`. Use `search_reports` for relevant prior insights. If nothing relevant returns or access is unavailable, continue.
2. Decide which evidence the question needs: structured data (statements, ratios, prices), source documents (filings, transcripts, reports), or both.
3. For large, repetitive work that splits into independent, mechanically checkable batches, read `agent_help(topic="methodology_delegation")` and delegate only if every requirement passes.

## Workflow patterns

- **Company analysis:** Use `get_stock_context` when the overview is broad or multi-part → retrieve the structured data and source evidence the question needs → synthesize.
- **Peer comparison:** Establish the comparison set → retrieve comparable structured data in parallel → gather issuer-specific source evidence → compare and rank only on supported dimensions, adjusting for differences in period, accounting basis, scope, currency, and units.
- **Filing, transcript, or report question:** Find relevant documents with the search tools or `list_latest_filings`, `list_latest_transcripts`, or `list_latest_reports` → use `search_in_documents` to search inside selected documents when needed. When the answer must cover every year or period, run a separate search for each; a single multi-year search ranks all years together and can leave some unrepresented. Stock context is optional.
- **Mentions by other companies:** Search filings, transcripts, or reports with no `ticker`, query the subject company's name, and put its ticker in `exclude_tickers`. Treat the results as ranked discovery, not a complete list. `methodology_search` explains the search settings.
- **Stock screens:** For a quantitative screen, use the `dfin-screener` skill. For a screen followed by filing or transcript evidence, use the `dfin-semantic-screener` skill. If neither skill is available, read `agent_help(topic="methodology_screening")` before screening.
- **Filing revisions:** Call `compare_filings` in `discover` mode to choose two filings, then in `compare` mode for that pair. Read the returned warnings before calling missing text a deletion, and share `comparison_url` when returned.
- **Missing prepared statements:** Keep any statements `get_financial_statements` returned, then follow `agent_help(topic="methodology_financials")` to decide whether filings can supply the missing periods. An unfinished check is not confirmed absence.
- **Table evidence:** Before reading any table's body, run the bundled `scripts/extract_table_context.py` (resolve it relative to this `SKILL.md`) to choose the table. `methodology_search` explains when and how.
- **Image-derived evidence:** Filing content can include data extracted from images, shown in Markdown image syntax. Verify it as `methodology_search` directs before relying on it.

## Analysis and presentation

- Perform calculations programmatically and reproducibly in Python with pandas and NumPy; use Polars and Parquet for large datasets where available. Do not use spreadsheet files for analysis unless the user asks for one.
- Before drafting an answer that uses DFin evidence, read `agent_help(topic="citations")` once and cite as it directs.

### Simple analytical work

- Lead with the direct answer, then support it with evidence, calculations, and citations.
- Write for a professional investor in clear, natural, concise language. Match depth to the question without reducing the answer to clipped fragments.
- Accuracy and faithful representation of the evidence come first. Include material caveats; omit repetition, routine background, and process narration.
- Distinguish reported facts, management claims, calculations, and inference. Show material formulas and label calculated results.
- Use tables or charts when they communicate comparative, chronological, or quantitative information better than prose. Label periods, units, currency, scope, and basis.

### Complex analytical work

For multi-source synthesis, material calculations or reconciliations, peer comparisons, thesis or valuation judgments, or output needing substantial tables or charts, read `agent_help(topic="output_guidelines")` once before drafting. It is about 1,600 tokens and unnecessary for simpler work.
