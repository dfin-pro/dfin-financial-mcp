---
name: dfin-screener
description: Build and run dfin.pro stock screens. Use when the user wants to find, filter, sort, or rank public companies using financial, valuation, growth, technical, or other screener criteria.
---

# dfin.pro Screener

Find, filter, sort, and rank public companies with the dfin.pro fundamentals screener. Screens generate candidates, not conclusions.

## Screener workflow

Read the screener guidance before building screens. The examples show patterns; the live screener contract is authoritative.

1. Call `get_screener_options()` before constructing any screen. It returns the compact basic contract.
2. If the needed filter is absent, or the task needs growth, historical metric rules, CAGR/multiple rules, composite metrics, volatility rule groups, or broader public filters, call `get_screener_options(mode="all")`.
3. Read https://www.dfin.pro/docs/examples/screener-starter-screens.md for starter screen patterns when the screen is non-trivial or a filter's shape is unclear. A simple screen — a few range filters, a sector include, and a sort — can be built straight from the `get_screener_options` contract without it.
4. Read https://www.dfin.pro/docs/examples/advanced-growth-filters.md before building growth, historical, CAGR, multiple, or multi-year filters.
5. Build `filters`, `sort`, `fields`, `page`, and `result_format` only from the returned `get_screener_options` contract and relevant examples.
6. Execute the screen with `run_screener(...)`. Do not use legacy screener runner names.



## Common requests

Screens run off the `get_screener_options` contract alone — you don't need `agent_help(topic="agent_guide")` to build one. Reach for it only if you're routing between tool areas, for example screening and then researching the hits.

- **Screen for candidates:** `get_screener_options()` or `get_screener_options(mode="all")` -> `run_screener(...)`. Research selected companies only when requested.
