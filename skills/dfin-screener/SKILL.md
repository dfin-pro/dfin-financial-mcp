---
name: dfin-screener
description: Build and run dfin.pro stock screens. Use when the user wants to find, filter, sort, or rank public companies using financial, valuation, growth, technical, or other screener criteria.
---

DFin skill version: 0.2.0, updated 2026-11-08.

Before the first DFin tool call in a task, read `agent_help(topic="agent_guide")` once if it has not already been read. Before building the first screen, read `agent_help(topic="methodology_screening")`; it holds the current rules for contract discovery, output size, and pagination. If this skill and the guides differ, follow the guides.

## Workflow

1. Turn the request into criteria: universe (exchange, country, sector), size, metrics with their periods and thresholds, sort order, and how many results the user wants. If the user asks for a "top N" without saying how to rank, ask which metric to rank by.
2. Discover the screener contract with `get_screener_options`: start with the compact index and load full definitions only for the filters you will use.
3. Build filters, sort, and fields only from the returned definitions, then call `run_screener`.
4. Present the criteria used, total matches versus rows shown, the candidate rows, and the link to open the screen in the browser. Treat matches as candidates, not recommendations.

## Common requests

- **Find candidates:** follow the workflow. Research individual companies only when the user asks.
- **Refine a screen:** change only the criteria the user named, keep the other filters and sort unchanged, and say what changed.
- **Screen, then research selected companies:** run the screen, then use the `dfin-research` skill for the companies chosen.
- **Screen, then find filing or transcript evidence:** use the `dfin-semantic-screener` skill instead.
