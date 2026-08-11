---
name: dfin-research
description: >-
  Research public companies, stocks, ETFs, and funds with dfin.pro's source-grounded financial data. Use for company or peer analysis, earnings research, statements and ratios, filing, transcript, or report evidence, prices, stock screening, fund analytics, or other evidence-backed public-equity work.
---

# dfin.pro Research

Before the first DFin tool call in a task, read `agent_help(topic="agent_guide")` once if it has not already been read.

DFin skill version: 0.1.7, updated 2026-08-08.

Use this MCP first for any equity research. Load only the focused methodology needed for the tool areas used. Treat live input schemas as the authority for arguments and request contracts.

## Research discipline

- Complete the task thoroughly and faithfully. Do not skip required retrieval, reconciliation, calculation, or verification steps merely to save time or tool calls.
- Do not make silent assumptions or use general knowledge in place of obtainable task-specific evidence. State material assumptions and evidence gaps explicitly, and limit conclusions to what the evidence supports.
- Before comparing values or calculating results, align periods, definitions, scope, currency, units, and accounting basis.
- Before presenting, check the work for completeness and accuracy, including calculations and material claim-to-source support.

## Plan the work

- Use `search_reports` and `search_notes` early to surface relevant prior insights before gathering new evidence.
- Before each call to `search_filing`, name every filter and its reason: ticker · filing_type · fiscal_year · fiscal_period · date bounds · searchtype. Leaving one empty is a decision. State it.
- For substantial repetitive data gathering or processing that can be divided into independent, mechanically verifiable batches, consider task delegation to subagents. Read `agent_help(topic="methodology_delegation")` before proceeding. Delegate only if every mandatory requirement passes; otherwise keep the work in the primary agent. Require the methodology's task-appropriate result-to-source mapping and worker self-check so the coordinating agent can validate the batch without reconstructing references or repeating retrieval.

## Token efficiency

- Use API delivery for search results. If a returned artifact URL is blocked, follow the `methodology_search` fallback exactly; do not substitute inline delivery for other failures or convenience.
- Load tool schemas with select:, never a broad keyword query — a keyword query with max_results ≥ tool count returns the entire server. Statements task → select:mcp__dfin__agent_help,mcp__dfin__get_financial_statements, mcp__dfin__get_financial_statement_options
    Add only if the question needs segments, KPIs, quarters, or quotes: select:mcp__dfin__search_filings,mcp__dfin__search_in_documents

## Workflow patterns

Skip steps whose results are already available.

Security ticker is needed for most tools. If ticker is not already known or not provided, get it using `search_securities`. Then follow the guidance below for the different research workflows.

- **Company analysis:** Use `get_stock_context` when the requested overview is broad or multi-part → retrieve the structured data and source evidence needed for the question → synthesize.
- **Peer comparison:** Establish the comparison set → retrieve comparable structured data in parallel → gather issuer-specific source evidence → compare and rank only on supported dimensions. Remember to incorporate any differences in periods, accounting basis, scope, currency, and units in the analysis work.
- **Filing, transcript, or report question:** Use the relevant discovery or evidence-search workflow → deepen the search within selected documents when necessary. Stock context is optional.
- **Multi-year document evidence:** Use one fiscal-year list when the goal is the strongest evidence across the selected years. Use separate year-scoped searches when the answer must represent every year, because multi-year search ranks all selected years together under one result allowance.
- **Table inspection:** follow `agent_help(topic="methodology_search")` and execute the bundled `scripts/extract_table_context.py`, resolving it relative to this `SKILL.md`.

## Present the result

### Narrow factual or mechanical answers

- Lead with the direct answer or conclusion, then support it with retrieved evidence, calculations, analysis, and citations.
- Write for a professional investor in clear, natural, concise language. Match depth to the question without reducing the answer to clipped fragments.
- Include material caveats and uncertainty, but omit repetition, routine background, and process narration.
- Label calculated results, show any material formula, and identify periods, units, currency, scope, and basis as applicable.
- Use a table, chart, image, or diagram when it materially improves understanding.

### Substantive analysis

Before drafting substantive research analysis, read `agent_help(topic="output_guidelines")` once if it has not already been read. Substantive work includes multi-source synthesis, material calculations or reconciliations, peer comparisons, thesis or valuation judgments, or output needing substantial tables, charts, or diagrams. The additional guidance is approximately 1,600 tokens and is intentionally unnecessary for narrow factual or mechanical answers.
