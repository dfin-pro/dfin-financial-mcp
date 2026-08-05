---
name: dfin-note
description: >-
  Create durable private dfin.pro notes from completed financial research or material news and article content. Use when the user asks to save, capture, add, or create a dfin.pro note from analytical work, thesis development, peer or company comparisons, filings, transcripts, reports, prior notes, news articles, announcements, or current events. Route the note to the research or news category, preserve meaningful insights and sources, and compare relevant existing user notes and DFin reports.
---

# dfin.pro Note

Before the first DFin tool call in a task, read `agent_help(topic="agent_guide")` and `agent_help(topic="methodology_notes")` once if not already read.

DFin skill version: 0.1.4, updated 2026-08-05.

Turn completed analysis or material news into one high-signal private note. Preserve durable insight rather than dumping a chat or summarizing an article mechanically.

## Choose the Note Mode

- Honor an explicit user choice between `research` and `news` for the note category.
- Use `news` when the note primarily captures a recent article, announcement, or event and explains what changed and why it matters. Read [references/news.md](references/news.md) completely before proceeding.
- Use `research` when the durable value is original synthesis, thesis development, comparison, modeling, or analysis, even if news initiated the work. Read [references/research.md](references/research.md) completely before proceeding.
- If the category remains ambiguous, choose the mode that reflects the note's primary durable value.

Read exactly one mode reference unless the task genuinely produces two separate notes.

## Core Workflow

1. Follow the selected mode reference to acquire evidence and select material content.
2. Collect source identifiers and all materially affected exchange-qualified tickers. Do not add tangential securities.
3. Call `search_notes` to find relevant existing user notes, reading `agent_help(topic="methodology_search")` first if needed. Use `find_linked_notes` (limit hops to 1 or 2) to identify any other potential relevant notes not found via search. Follow the loaded notes skill/methodology and link only substantively relevant notes.
4. Draft a concise, distinctive subject and self-standing Markdown body using only the mode elements that materially improve the note. Do not put company names or tickers in the subject.
5. Compare the draft with relevant existing user notes and DFin reports. Point out material support, contradiction, or potentially stale prior research to the user. If a contradiction would change the saved conclusion or intended relationships, ask the user to resolve it before creation. Otherwise, include the material comparison in the note and proceed.
6. Call `create_note` with the selected category, drafted subject and body, all material tickers, and any selected same-user note or DFin report relationships.
7. Report the created note's `public_id`, category, subject, linked tickers, material research comparisons, and any omitted or uncertain references.

## Reference Placement

Use the note body for external source references and the note tool fields for structured ticker, same-user note, and DFin stock analysis report relationships.

- Put filing and transcript `doc_uuid` values and used SEC links in the body. Do not put filing or transcript IDs in `linked_note_ids`.
- Put relevant DFin stock analysis report public IDs in `linked_report_ids`. Do not recurse through sources used to build a DFin report.
- Put relevant same-user note public IDs in `linked_note_ids` and explain their role in the body.
- Put stable material web URLs in the body.
- Label useful claims with missing source identifiers as thread-derived; never invent identifiers or URLs.

## Quality Bar

- Make the note understandable without reopening the original chat or article.
- Write the body as valid Markdown. Use headings, paragraphs, lists, tables, emphasis, and links only when they improve readability; never leave placeholder text or empty headings.
- Distinguish reported facts, company or source claims, calculations, and fresh inference.
- Keep the scope proportionate. Omit long copied passages, routine background, unrelated tool logs, prompt chatter, and mechanical steps.
- For complex work in either mode, read `agent_help(topic="output_guidelines")` once before drafting if not already read. Complex work includes multi-source synthesis, material calculations or reconciliations, peer comparisons, thesis or valuation judgments, or substantial tables or charts. Do not load it for routine capture.
