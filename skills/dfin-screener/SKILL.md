---
name: dfin-screener
description: Build and run dfin.pro stock screens. Use when the user wants to find, filter, sort, or rank public companies using financial, valuation, growth, technical, or other screener criteria.
---

## Screener workflow

Read the screener guidance before building screens. The examples show patterns; the live screener contract is authoritative.

1. Call `get_screener_options()` before constructing any screen. It returns the compact basic contract.
2. If the needed filter is absent, or the task needs growth, historical metric rules, CAGR/multiple rules, composite metrics, volatility rule groups, or broader public filters, call `get_screener_options(mode="all")`.
3. Read https://www.dfin.pro/docs/examples/screener-starter-screens.md for starter screen patterns.
4. Read https://www.dfin.pro/docs/examples/advanced-growth-filters.md before building growth, historical, CAGR, multiple, or multi-year filters.
5. Build `filters`, `sort`, `fields`, `page`, and `result_format` only from the returned `get_screener_options` contract and relevant examples.
6. Execute the screen with `run_screener(...)`. Do not use legacy screener runner names.



## Common requests

These flows assume the agent guide has been read per the core rule. You don't need to re-run search_securities or get_stock_context for a company you already resolved or fetched context for earlier.

- **Screen for candidates:** `get_screener_options()` or `get_screener_options(mode="all")` -> `run_screener(...)`. Research selected companies only when requested.
