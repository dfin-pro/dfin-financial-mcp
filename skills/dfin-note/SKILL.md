---
name: dfin-note
description: >-
  Create durable private dfin.pro notes from completed financial research or material news and article content. Use when the user asks to save, capture, add, or create a dfin.pro note from analytical work, thesis development, peer or company comparisons, filings, transcripts, reports, prior notes, news articles, announcements, or current events. Route the note to the research or news category, preserve meaningful insights and sources, and compare relevant existing user notes and DFin reports.
---

# dfin.pro Note

Before the first DFin tool call in a task, read `agent_help(topic="agent_guide")` and `agent_help(topic="methodology_notes")` once if not already read.

DFin skill version: 0.1.7, updated 2026-08-08.

Turn completed analysis or material news into one high-signal private note. Preserve durable insight rather than dumping a chat or summarizing an article mechanically.

## Choose the Note Mode

- Honor an explicit user choice for the note category.
- Use `news` when the note primarily captures a recent article, announcement, or event and explains what changed and why it matters. Read [references/news.md](references/news.md) completely before proceeding.
- Use `research` when the durable value is original synthesis, thesis development, comparison, modeling, or analysis, even if news initiated the work. Read [references/research.md](references/research.md) completely before proceeding.
- If the category remains ambiguous, choose the mode that reflects the note's primary durable value.

Read [references/news.md](references/news.md) for every news note and whenever one or more articles are material sources. An article-sourced research note reads both references: apply the article-source workflow in `news.md`, but retain the `research` category and follow `research.md` for content selection and body shape.

## Core Workflow

1. Follow the selected mode reference and any applicable article-source guidance to acquire evidence and select material content.
2. Collect source identifiers, exact document chunks used as evidence, and all materially affected exchange-qualified tickers. Do not add tangential securities.
3. Discover related prior research.
    - Read `agent_help(topic="methodology_search")` once before the first `search_notes` call, if it has not already been read, then call `search_notes` to find relevant existing user notes.
    - Keep the default API delivery for `search_notes` and follow the notes methodology for artifact handling and its policy-only inline fallback. Use inline delivery **only if access to www.dfin.pro api is blocked**.
    - Use `find_linked_notes` when a known note, ticker, report, transcript, or permanent document UUID may expose relevant connections. Omit the query for structural proximity; reuse or refine the research query when relevance ordering is more useful.
    - Keep graph exploration bounded: start from the strongest seed, then re-seed at most twice when a result opens a distinct branch relevant to the saved conclusion. Prefer `max_hops=1` for follow-ups and stop sooner if no materially new candidates appear. Do not recursively expand results or exhaust pagination unless the user requests broader research.
    - Deduplicate overlapping discoveries by `note_id`.
    - Use `get_note` when complete content is needed to compare a candidate or decide whether to link it.
4. Draft a concise, distinctive subject and self-standing Markdown body using only the mode elements that materially improve the note. Do not put company names or tickers in the subject.
5. Compare the draft with relevant existing user notes and DFin reports. Point out material support, contradiction, or potentially stale prior research to the user. If a contradiction would change the saved conclusion or intended relationships, ask the user to resolve it before creation. Otherwise, include the material comparison in the note and proceed.
6. Before saving, present the proposed note to the user. Summarize its key points, separately identify every new inference or conclusion, and call out material assumptions, uncertainties, and unsupported or contested claims. Ask the user to confirm that the draft, including its conclusions, is correct or to provide revisions. Do not call `create_note` until the user gives clear approval.
7. Call `create_note` with the user-confirmed category, subject and body, all material tickers, and only note, report, transcript, or raw-document relationships materially relevant to the saved conclusion.
8. Report the created note's `note_id`, category, subject, linked tickers, and any omitted or uncertain references. Present `url` as the direct link for opening the formatted note.

## Reference Placement

### User-Facing Body Links

- Write every available URL as a natural Markdown link whose descriptive text names the source or explains its relevance. Do not print a bare URL or expose a `note_id`, `report_id`, `transcript_id`, or `doc_uuid` in the body.
- Link SEC filings to the returned SEC `source_uri`, transcripts to their dfin.pro `source_uri`, related notes to their canonical Notebook URLs from `get_note`, and DFin reports to their canonical URLs from `get_report_details`.
- Link stable external sources with descriptive text. If a canonical or stable URL is unavailable, identify the source without inventing a URL. Label useful claims without a retrievable source as thread-derived.

### Structured Agent References

- Put materially relevant note IDs in `linked_note_ids`, DFin report IDs in `linked_report_ids`, and transcript IDs in `linked_transcript_ids`.
- Put other permanent indexed filing or source evidence in `linked_document_references` as objects containing `doc_uuid` and optional `chunk_num`, retaining the exact supporting chunk when one was used.
- Do not invent or generate any ids yourself.
- Prefer typed report and transcript relationships and do not duplicate them as raw document references. Never save a temporary `temp_` document UUID or derive an identifier from a URL. Follow the notes methodology for chunk provenance and later revalidation.
- Put materially affected exchange-qualified tickers in `tickers`.
- Explain each relationship's relevance through its natural body link. Do not recurse through sources used to build a DFin report.

## Quality Bar

- Read `agent_help(topic="output_guidelines")` once before drafting, if not already read
