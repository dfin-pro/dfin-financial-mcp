---
name: dfin-note
description: >-
  Create durable private dfin.pro notes from completed financial research or material news and article content. Use when the user asks to save, capture, add, or create a note from analytical work, thesis development, peer or company comparisons, filings, transcripts, reports, prior notes, news articles, announcements, or current events.
---

# dfin.pro Note

DFin skill version: 0.1.9, updated 2026-08-27.

Before the first DFin tool call in a task, read `agent_help(topic="agent_guide")` and `agent_help(topic="methodology_notes")` once if not already read.

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
    - Use `get_note` when complete content is needed to compare a candidate or decide whether to link it.
4. Read `agent_help(topic="output_guidelines")` once before drafting, if not already read.
5. Draft a concise and distinctive subject and self-standing Markdown body. Include only the content elements that materially improve the note.  Default to fewer than 500 words for the substantive note body (word count does not include links, references, compact tables, and follow-ups or monitoring items).
6. Preserve the user's insights, conclusions, and pattern recognition as the substance of the note. Do not silently rewrite, dilute, or substitute the user's conclusions with the agent's own view. The notebook is a record of the user's thinking; the agent supports it rather than authoring it.
7. Compare the draft with relevant existing user notes and DFin reports. Tell the user about material support, discrepancies, contradictions, or potentially stale research. Supporting facts and source links may be incorporated as context when they do not change the user's conclusion. Do not add an agent-generated conclusion, caveat, or interpretive comparison to the note unless it is clearly identified and the user approves its inclusion. If a contradiction would change the saved conclusion or intended relationships, ask the user to resolve it before creation.
8. Before saving, present the proposed note to the user. Summarize its key points; separately identify any agent-added analysis, inference, caveat, or conclusion; and call out material assumptions, uncertainties, and unsupported or contested claims. Ask the user to confirm that the draft, including every agent-added element, is correct or to provide revisions. Do not call `create_note` until the user gives clear approval.
9. Call `create_note` with the user-confirmed category, subject and body, all material tickers, and only note, report, transcript, or raw-document relationships materially relevant to the saved conclusion.
10. After creating the note, consider whether it materially changes any related existing note. Update an older note only when the new information resolves a material open item, materially confirms, changes, or invalidates a saved conclusion, or adds context needed to understand its current status. Do not update notes merely because they are related. Maintain bidirectional links for every material update: the new note must link to the relevant prior note, and the update in the prior note must link to the new note.
11. Preserve the historical record in any updated note. Normally append a concise dated update that states what changed, what it resolves or leaves open, and links to the newer note. Do not silently rewrite or delete the original conclusion. Correct prior text only when it is factually wrong, and make the correction and its basis clear.
12. Before updating an existing note, show the user each proposed update and obtain clear approval. Keep agent-provided interpretation distinct from the user's view. Then update only the approved notes.
13. Report the created note and any maintenance work: its `note_id`, category, subject, linked tickers, updated notes, notes intentionally left unchanged, and any omitted or uncertain references. Present the result as a Markdown link in the form `[subject](url)`, using the returned `url` to open the formatted note.

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


## User-Facing Communication About Existing Notes

- When discussing an existing note with the user, assume they do not remember its ID, title, contents, or the prior discussion.
- On the first mention, identify it with a descriptive linked subject, not just the raw note ID: `[note_id: Subject](canonical note URL)`. On subsequent references use the `[note_id](url)`.
- Give reasonable context needed to understand the points referenced from the note: what the note is about, its relevant conclusion or claim, and why it matters now. Use plain language.
- Do not dump or mechanically summarize the full prior note. Usually several sentences context is enough. Add details (like tables, links to articles, additional references, etc.) when needed.
- For each additional note, introduce it independently before relying on it. Do not assume that “the other note,” “that thesis,” or a raw identifier is meaningful context.
- Be specific about a proposed action. Do not say that a line or topic needs correction without explaining what the note currently says, what changed or conflicts, and the proposed correction.


### Examples

**Good:**

> In [ab39q43a: Acme Margin Recovery Thesis](url), you argued that gross margins would recover as input costs normalized, helping earnings recover without needing a material increase in sales. The note treated lower freight and component costs as the main mechanism and left the pace of demand recovery as an open question.
>
> In the latest results, input costs did normalize, but gross margin remained flat because pricing weakened and factory utilization declined. That means the specific margin-recovery mechanism in the prior note is no longer supported, though the broader demand-recovery thesis has not yet been disproven.
>
> I propose appending a dated update to the note: record that cost normalization did not produce the expected margin benefit, explain the pricing and utilization offset, and revise the open question to whether volume recovery can restore utilization. I would link the update to the new results note so the reasoning trail is easy to follow.

**Avoid:**

> In note `ab39q43a`, the line about margin normalization deserves a correction based on the latest results. This may affect the demand thesis and should probably be updated with the new information.
