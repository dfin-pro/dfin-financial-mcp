---
name: dfin-screener
description: Build and run dfin.pro stock screens. Use when the user wants to find, filter, sort, or rank public companies using financial, valuation, growth, technical, or other screener criteria.
---

Before the first DFin tool call in a task, read `agent_help(topic="agent_guide")` once if it has not already been read.

DFin skill version: 0.1.7, updated 2026-08-08.

## Screener workflow

Read the screener methodology before building screens. Examples show patterns; the live screener contract is authoritative.

1. Read `agent_help(topic="methodology_screening")` after the agent guide and before constructing the first screen in a task.
2. Call `get_screener_options(mode="basic", detail="index")` to discover canonical filters without loading full definitions.
3. If the needed key is absent, or the task needs growth, historical metric rules, CAGR/multiple rules, composite metrics, volatility rule groups, or broader public filters, call `get_screener_options(mode="all", detail="index")`.
4. Call `get_screener_options(mode=..., detail="full", filter_keys=[...])` with only the exact filters needed. Request no more than 20 unique keys per call.
5. Read https://www.dfin.pro/docs/examples/screener-starter-screens.md only when a starter pattern is useful. Read https://www.dfin.pro/docs/examples/advanced-growth-filters.md before building growth, historical, CAGR, multiple, or multi-year filters. Treat both as shapes and validate every key and value against the focused live contract.
6. Build `filters`, `sort`, `fields`, `page`, and `result_format` only from the returned contract. Execute with `run_screener(..., delivery="api")`; do not use legacy screener runner names.
7. Use `result_format="tickers"` for a candidate list and `result_format="rows"` only when returned fields are needed. The API artifact contains the exact requested page and a compact preview; fetch later pages explicitly only when the task requires them.

Use `delivery="inline"` only for a deliberately bounded page when artifact access is unavailable. Never silently relax filters, convert missing values to zero, or imply that a preview or single page is the complete match set. Treat results as candidates and verify selected securities before making investment claims.

## Token efficiency

- Prefer index discovery followed by focused full definitions. Use the compatibility full response without `filter_keys` only for genuinely broad contract inspection.
- Reuse contract definitions already retrieved in the task.
- Request only needed row fields, or tickers when downstream research does not need screener values.
- Compare `total`, `count`, `limit`, and `offset` before describing completeness. Do not auto-paginate.

## Common requests

You don't need to re-run search_securities or get_stock_context for a company you already resolved or fetched context for earlier.

- **Screen for candidates:** basic index -> all index if needed -> focused full definitions -> `run_screener(..., delivery="api")`. Research selected companies only when requested.
