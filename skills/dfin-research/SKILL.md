---
name: dfin-research
description: >-
  Research public companies, stocks, ETFs, and funds with dfin.pro's source-grounded financial data. Use for company or peer analysis, earnings research, statements and ratios, filing, transcript, or report evidence, prices, stock screening, fund analytics, or other evidence-backed public-equity work.
---

# dfin.pro Research

DFin skill version: 0.1.9, updated 2026-08-27.

Before the first DFin tool call in a task, read `agent_help(topic="agent_guide")` once if it has not already been read.

## Plan the work

- Use `search_reports` and `search_notes` early to surface relevant prior insights before gathering new evidence.
- Before each call to `search_filing`, name every filter and its reason: ticker · filing_type · fiscal_year · fiscal_period · date bounds · searchtype. Leaving one empty is a decision. State it.
- For substantial repetitive data gathering or processing that can be divided into independent, mechanically verifiable batches, consider task delegation to subagents. Read `agent_help(topic="methodology_delegation")` before proceeding. Delegate only if every mandatory requirement passes; otherwise keep the work in the primary agent.

## Token efficiency

- Use API delivery for search results. If a returned artifact URL is blocked, follow the `methodology_search` fallback exactly; do not substitute inline delivery for other failures or convenience.
- For `search_filings`, inspect `status`, `results_complete`, and `limitations` before drawing a coverage conclusion. A partial response contains usable surviving evidence but is not exhaustive; report the limitation and do not turn absent results into a no-match claim. With API delivery, these fields accompany the existing artifact reference and are repeated inside the downloaded artifact.
- A date-scoped `search_filings` request may combine indexed DFin evidence with SEC filing evidence when its interval crosses reliable indexed coverage. Treat the response as one deduplicated search rather than reconciling the sources yourself. If `fiscal_scope_adjusted` is reported, explain that the SEC portion was searched by filing date without the supplied fiscal filter.
- Load tool schemas with select:, never a broad keyword query — a keyword query with max_results ≥ tool count returns the entire server. Statements task → select:mcp__dfin__agent_help,mcp__dfin__get_financial_statements, mcp__dfin__get_financial_statement_options
    Add only if the question needs segments, KPIs, quarters, or quotes: select:mcp__dfin__search_filings,mcp__dfin__search_in_documents

## Workflow patterns

- **Company analysis:** Use `get_stock_context` when the requested overview is broad or multi-part → retrieve the structured data and source evidence needed for the question → synthesize. Compact returns are the default. Request the optional return-distribution analysis only when it is material to the question, include returns, and use API delivery because the result is structured data.
- **Peer comparison:** Establish the comparison set → retrieve comparable structured data in parallel → gather issuer-specific source evidence → compare and rank only on supported dimensions. Remember to incorporate any differences in periods, accounting basis, scope, currency, and units in the analysis work.
- **Filing, transcript, or report question:** Use the relevant discovery or evidence-search workflow → deepen the search within selected documents when necessary. Stock context is optional.
- **Multi-year document evidence:** Use one fiscal-year list when the goal is the strongest evidence across the selected years. Use separate year-scoped searches when the answer must represent every year, because multi-year search ranks all selected years together under one result allowance.
- **Table inspection:** follow `agent_help(topic="methodology_search")` and execute the bundled `scripts/extract_table_context.py`, resolving it relative to this `SKILL.md`.

## Analysis and presentation

- Perform calculations and data analysis programmatically and reproducibly, using Python with pandas and NumPy. For large datasets, use Polars and Parquet where available. Do not create or rely on spreadsheet files for analysis unless the user explicitly requests one.

### Simple Analytical Work

- Lead with the direct answer or conclusion, then support it with retrieved evidence, calculations, analysis, and citations.
- Write for a professional investor in clear, natural, concise language. Match depth to the question without reducing the answer to clipped fragments.
- Accuracy and faithful representation of the evidence come first. Include material caveats and uncertainty, but omit repetition, routine background, and process narration.
- Distinguish reported facts, management claims, calculations, and inference. Use consistent inputs, show material formulas, and label calculated results.
- Use comparable benchmarks and explain the financial mechanism, material counterevidence, and what would change the conclusion when relevant.
- Use tables, charts, images, or diagrams when they communicate comparative, chronological, quantitative, or structural information more efficiently than prose. Label periods, units, currency, scope, and basis as applicable.

### Complex Analytical Work

For presenting substantive or complex research analysis, read `agent_help(topic="output_guidelines")` once if it has not already been read. Complex work includes multi-source synthesis, material calculations or reconciliations, peer comparisons, thesis or valuation judgments, or output needing substantial tables or charts. The additional guidance is approximately 1,600 tokens and is intentionally unnecessary for simpler work.
