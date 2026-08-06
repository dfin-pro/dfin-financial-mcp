---
name: dfin-note
description: >-
  Create durable private dfin.pro notes from completed financial research or material news and article content. Use when the user asks to save, capture, add, or create a dfin.pro note from analytical work, thesis development, peer or company comparisons, filings, transcripts, reports, prior notes, news articles, announcements, or current events. Route the note to the research or news category, preserve meaningful insights and sources, and compare relevant existing user notes and DFin reports.
---

# dfin.pro Note

Before the first DFin tool call in a task, read `agent_help(topic="agent_guide")` and `agent_help(topic="methodology_notes")` once if not already read.

DFin skill version: 0.1.5, updated 2026-08-05.

Turn completed analysis or material news into one high-signal private note. Preserve durable insight rather than dumping a chat or summarizing an article mechanically.

## Choose the Note Mode

- Honor an explicit user choice for the note category.
- Use `news` when the note primarily captures a recent article, announcement, or event and explains what changed and why it matters. Read [references/news.md](references/news.md) completely before proceeding.
- Use `research` when the durable value is original synthesis, thesis development, comparison, modeling, or analysis, even if news initiated the work. Read [references/research.md](references/research.md) completely before proceeding.
- If the category remains ambiguous, choose the mode that reflects the note's primary durable value.

Read [references/news.md](references/news.md) for every news note and whenever one or more articles are material sources. An article-sourced research note reads both references: apply the article-source workflow in `news.md`, but retain the `research` category and follow `research.md` for content selection and body shape.

## Core Workflow

1. Follow the selected mode reference and any applicable article-source guidance to acquire evidence and select material content.
2. Collect source identifiers and all materially affected exchange-qualified tickers. Do not add tangential securities.
3. Discover related prior research.
    - Call `search_notes` to find relevant existing user notes, reading `agent_help(topic="methodology_search")` first if needed.
    - Use `find_linked_notes` when a known note, ticker, or report may expose relevant connections. Omit the query for structural proximity; reuse or refine the research query when relevance ordering is more useful.
    - Keep graph exploration bounded: start from the strongest seed, then re-seed at most twice when a result opens a distinct branch relevant to the saved conclusion. Prefer `max_hops=1` for follow-ups and stop sooner if no materially new candidates appear. Do not recursively expand results or exhaust pagination unless the user requests broader research.
    - Deduplicate overlapping discoveries by note public ID.
    - Use `get_note` when complete content is needed to compare a candidate or decide whether to link it.
4. Draft a concise, distinctive subject and self-standing Markdown body using only the mode elements that materially improve the note. Do not put company names or tickers in the subject.
5. Compare the draft with relevant existing user notes and DFin reports. Point out material support, contradiction, or potentially stale prior research to the user. If a contradiction would change the saved conclusion or intended relationships, ask the user to resolve it before creation. Otherwise, include the material comparison in the note and proceed.
6. Call `create_note` with the selected category, drafted subject and body, all material tickers, and only note or report relationships materially relevant to the saved conclusion.
7. Report the created note's `public_id`, category, subject, linked tickers, material research comparisons, and any omitted or uncertain references. Present `url` as the direct link for opening the formatted note.

## Reference Placement

Use the note body for external source references and the note tool fields for structured ticker, same-user note, and DFin stock analysis report relationships.

- Put filing and transcript `doc_uuid` values and used SEC links in the body. Do not put filing or transcript IDs in `linked_note_ids`.
- For selected DFin stock analysis report relationships, follow the report-identifier flow in the notes methodology and put each resolved report `public_id` in `linked_report_ids`. Do not recurse through sources used to build a DFin report.
- Put relevant same-user note public IDs in `linked_note_ids` and explain their role in the body.
- Put stable material web URLs in the body.
- Label useful claims with missing source identifiers as thread-derived; never invent identifiers or URLs.

## Quality Bar

- Make the note understandable without reopening the original chat or article.
- Write the body as valid Markdown. Use headings, paragraphs, lists, tables, emphasis, and links only when they improve readability; never leave placeholder text or empty headings.
- Stay faithful to the supplied material and completed analysis. Distinguish reported facts, company or source claims, calculations, and fresh inference; clearly label new conclusions as fresh inference and cite their supporting evidence.
- Keep citations and source identifiers close to the claims they support.
- Keep the scope proportionate. Omit long copied passages, routine background, unrelated tool logs, prompt chatter, and mechanical steps. Never save secrets, API keys, credentials, or unrelated private conversation.
- For complex work in either mode, read `agent_help(topic="output_guidelines")` once before drafting if not already read. Complex work includes multi-source synthesis, material calculations or reconciliations, peer comparisons, thesis or valuation judgments, or substantial tables or charts. Do not load it for routine capture.
