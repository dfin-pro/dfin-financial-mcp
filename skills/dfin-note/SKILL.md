---
name: dfin-note
description: >-
  Create durable private dfin.pro notes from completed financial research or material news and article content. Use when the user asks to save, capture, add, or create a note from analytical work, thesis development, peer or company comparisons, filings, transcripts, reports, prior notes, news articles, announcements, or current events.
---

# dfin.pro Note

DFin skill version: 0.2.0, updated 2026-11-08.

Before the first DFin tool call in a task, read `agent_help(topic="agent_guide")` once if it has not already been read. Before the first notes tool call, read `agent_help(topic="methodology_notes")`; it holds the current rules for finding, linking, citing, approving, and discussing notes. If this skill and the guides differ, follow the guides.

The notebook is a record of the user's thinking. Support it; don't author it.

## Choose the note mode

- Honor the user's explicit category choice.
- Use `news` when the note mainly captures a recent article, announcement, or event: what changed and why it matters. Read [references/news.md](references/news.md) completely before proceeding.
- Use `research` when the durable value is original synthesis, thesis development, comparison, modeling, or analysis, even if news started the work. Read [references/research.md](references/research.md) completely before proceeding.
- If the category is still ambiguous, choose the mode that reflects the note's main durable value.
- A research note with material article sources reads both references: use the article-source workflow in `news.md`, keep the `research` category, and follow `research.md` for content and body shape.

## Workflow

1. **Gather evidence.** Follow the mode reference. Keep source identifiers, the exact chunks used as evidence, and every materially affected exchange-qualified ticker. Leave out tangential securities.
2. **Find related research.** Search the user's notes with `search_notes`, explore links from the strongest match with `find_linked_notes`, and open a candidate with `get_note` when you need its full content.
3. **Draft.** Read `agent_help(topic="output_guidelines")` once before drafting. Write a concise, distinctive subject and a self-standing Markdown body containing only elements that materially improve the note. Default to under 500 words for the substantive body, not counting links, references, compact tables, and follow-ups. Cite sources as `methodology_notes` directs.
4. **Keep the user's view intact.** The user's insights, conclusions, and pattern recognition are the substance of the note. Don't rewrite, dilute, or replace them with your own view.
5. **Compare with existing research.** Check the draft against related notes and DFin reports, and tell the user about material support, discrepancies, contradictions, or stale research. Supporting facts and source links may go in when they don't change the user's conclusion. Add your own conclusion, caveat, or interpretation only when it is clearly labeled and the user approves it. If a contradiction would change the saved conclusion or its relationships, ask the user to resolve it first.
6. **Get approval.** Show the proposed note: its key points, any agent-added analysis kept separate, and material assumptions, uncertainties, and contested claims. Call `create_note` only after the user clearly approves the draft.
7. **Create the note** with the confirmed category, subject, and body, all material tickers, and only the relationships material to the saved conclusion.
8. **Maintain older notes.** Update an existing note only when the new note resolves a material open item; confirms, changes, or invalidates a saved conclusion; or adds context needed to understand its current status. Don't update notes just because they are related. For each update:
   - Show the user the proposed change and get approval first.
   - Append a concise dated update that says what changed and what it resolves or leaves open, and link it to the new note. The new note links back.
   - Don't rewrite or delete the original conclusion. Correct earlier text only when it is factually wrong, and state the correction and its basis.
9. **Report back:** the note as `[note_id: Subject](url)` using the returned `url`, its category and tickers, the notes updated or intentionally left unchanged, and any omitted or uncertain references.
