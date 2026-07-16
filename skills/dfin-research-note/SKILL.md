---
name: dfin-research-note
description: >-
  Create durable private dfin.pro research notes that capture the analysis and insight from work already performed in a thread or chat. Use when the user asks to save, capture, add, log, or create a note from an investment thesis, detailed analytical work, peer/company comparisons, source-grounded diligence, what a news item or corporate event means for a company, the reasoning behind a transaction, or expensive data compilation across filings, transcripts, statements, reports, and prior notes. Especially useful after multi-step analysis where insights, supporting data, source references, and impacted tickers should be preserved in the user's private notes database.
---

# dfin.pro Research Note

Use this skill to turn research work from a thread into one high-signal private note with clean metadata. The goal is to preserve the analysis and the insight, not to dump the chat. That insight takes different forms — a thesis, a piece of diligence, what a news item actually means for a company, why a position was bought or sold — but the bar does not move: a note earns its place by carrying the thinking, not the artifact.

## Core Workflow

0. Read the agent_help(topic="methodology_notes") first, if not already done.
1. Review the thread's analysis and identify what is worth preserving:
   - Key conclusions, thesis changes, variant views, causal explanations, risks, assumptions, open questions, and decision-relevant judgments.
   - Expensive-to-recreate data compilations such as pulled statement tables, peer comparisons, filing/transcript excerpts, or manually reconciled metrics.
   - Source identifiers, SEC links, report public IDs, note public IDs, and exchange-qualified tickers surfaced during the work.
2. Create a concise, distinctive subject describing the analysis theme. Do not use company names or tickers here, as tickers have a dedicated field; prefer subjects like "Margin durability after mix shift" or "Capex risk in AI demand cycle."
3. Set `category` to match what the thread actually produced — this skill covers every note that comes out of research, not just one type:
   - `investment_thesis` — the work developed, changed, or argued a view on a security: what it is worth, or what happens next and why.
   - `transaction` — why a position was bought or sold, and the thinking that drove it.
   - `news` — the insight concerns a news item or corporate event: what it means for the company, not merely that it happened.
   - `research` — analysis, diligence, peer comparison, or data compilation that isn't one of the above. This is the default and the common case.
   - `other` — only when none of the above fit.

   The category says what the insight is *about*; it does not lower the bar for what the note must carry. A news item with nothing but the headline, or a trade with no reasoning attached, is not worth a note — see What To Preserve. When a thread produces several of these, categorize by what the note is *for*: a note whose point is the thesis is `investment_thesis` even if most of its body is supporting analysis. Category is structured metadata that `search_notes` and `list_notes` filter on, so the wrong one makes the note hard to find later.
4. Build a body that synthesizes the intelligence first, then preserves data and external references.
5. Call `create_note` with `subject`, `body`, the `category` chosen in step 3, `tickers`, and — when the relationships exist — `linked_note_ids` for same-user notes and `linked_report_ids` for DFin stock analysis reports. These are two separate fields; do not put report IDs in `linked_note_ids`.
6. Report the created note's `public_id`, subject, linked tickers, and any important omitted/uncertain references.

## What To Preserve

Prioritize the true analytical work:

- What the analysis concluded and why.
- Which facts changed the conclusion.
- Which assumptions drive the answer.
- Where evidence is strong, weak, contradictory, or still missing.
- What would matter next for the investment case.
- Supporting data and analytics that materially explain or substantiate the insight, especially when the thread compiled, transformed, reconciled, or compared the data.

Include summarized or processed analytics by default when they support the note's conclusions. Include raw or semi-raw data only when it would be costly to reconstruct or is central to the reasoning. Prefer compact tables with units, periods, and source identifiers; avoid long copied passages, unrelated tool logs, prompt chatter, or mechanical steps.

## References

Use the note body for external source references and the note tool fields for structured ticker, same-user note, and DFin stock analysis report relationships.

- **Filings and transcripts:** include DFin `doc_uuid` values in the body when available. Include SEC links when they were used or surfaced. Do not put filing or transcript IDs into `linked_note_ids`.
- **DFin research reports:** Put stock analysis report `public_id` values in `linked_report_ids` — not `linked_note_ids`, which is only for the user's own notes. Do not recurse through any references that were used to build the DFin research report.
- **User notes:** Put relevant other notes' public IDs in `linked_note_ids` and also mention their role in the body.
- **Web or external sources:** include stable URLs in the body only when they materially support the note.
- **Uncertain references:** if a claim is useful but the source identifier is missing, label it as thread-derived and avoid inventing a `doc_uuid`, public ID, or URL.

## Tickers

Pass all impacted or covered securities in `tickers` using exchange-qualified symbols such as `MSFT.US` or `BRK-B.US`.

- Include every company materially analyzed, compared, or affected by the note.
- Resolve ambiguous bare symbols with `search_securities` before creating the note.
- **Newly added ticker links must be active.** A delisted or acquired name — routine in M&A and peer work — will be rejected. If a ticker is inactive, drop it from `tickers` and name the company in the body instead, so the coverage is preserved even though the structured link isn't. Existing links on an older note may point at tickers that have since gone inactive; that is fine and does not need fixing.
- Do not add tangential tickers mentioned only in passing.

## Body Structure

Use proper Markdown syntax and formatting. Adapt the headings to the thread, but keep this order unless there is a clear reason not to:

```markdown
**Date:** <current date>
**Scope:** <one sentence on what thread/work this note captures>

## Key insights
- <decision-relevant insight>
- <variant view / causal explanation / conclusion>

## Analysis
<Short synthesis of the reasoning, including assumptions, risks, and what evidence mattered.>

## Data compiled
<Tables or bullets for expensive-to-recreate figures, peer comps, KPIs, statement pulls, or reconciliations. Include units and periods.>

## References
- Filing/transcript: <company>, <form/event/period>, doc_uuid=<...>, SEC=<...>
- Web sources: <Site>, <Headline>, <url>

## Follow-ups
- <open question, missing source, next diligence step>
```

## Quality Bar

- Make the note self-standing enough that a future agent can understand the analysis without reopening the original chat.
- Be faithful to the thread. Do not add new conclusions unless you clearly mark them as a fresh inference and source them.
- Keep citations and source identifiers close enough to the claims they support.
- Avoid saving secrets, API keys, credentials, or unrelated private conversation.
- If the thread was a simple one-shot data lookup, create a direct note only when the user explicitly asked for it; do not over-engineer it.
- When in doubt, confirm with the user as needed.
