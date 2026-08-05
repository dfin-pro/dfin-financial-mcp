# News Notes and Article Sources

Use all applicable guidance in this reference for a news note. For a research note with one or more material article sources, apply the article-source workflow, then follow `research.md` for content selection and body shape.

## Article-Source Workflow

### Acquire the Source

1. Read article text supplied by the user or open the supplied URL with an available web tool. For a news event without an article, retrieve the underlying announcement or primary source when available.
2. If a paywall, login, or access restriction prevents reading the full article, do not infer it from headlines or snippets and do not bypass access controls. Ask the user either to provide the full article or to allow an available computer or browser to access it when that is feasible and permitted.
3. Do not claim to summarize an inaccessible article. If the user accepts substituting accessible coverage, clearly identify the source actually used.

### Extract Meaningful Insights

- Identify what is genuinely new, what changed, why it matters, who is affected, and what expectations or investment views may change.
- Separate article reporting, attributed source or company claims, established facts, and fresh inference.
- Preserve material timing, magnitude, causality, uncertainty, and affected securities. Omit incidental details and copied prose.

### Corroborate Material Claims

- Validate only claims material to the interpretation or investment conclusion; do not verify every data point.
- Prioritize magnitude, timing, guidance, transaction terms, regulatory details, causality, and consequential quotations.
- Use filings and transcripts when they can confirm, qualify, or contradict those claims. Use primary web sources when appropriate.
- Label material claims that cannot be corroborated as unverified or secondary-source reporting rather than treating them as established.

### Add External Context When Useful

Use web search when an article lacks necessary context, another material development may affect the interpretation, or primary or independent reporting could clarify the event. Prefer primary sources and meaningful corroboration. Do not add generic background merely to lengthen the note.

## News-Note Workflow

Use `category="news"`. Extract meaningful insights and investment relevance rather than producing a section-by-section source summary.

### Compare Existing Research

- In addition to the shared user-note search, call `search_reports` when the news may affect an existing thesis, forecast, risk, catalyst, or company view. Retrieve only the evidence needed under the search methodology.
- Classify meaningful relationships as supporting existing research, contradicting it, adding context without changing it, or making it potentially stale.
- Carry material classifications into the shared comparison step and link only substantively relevant notes and reports.

### Shape the Body

Write the body in Markdown (using correct markdown syntax) and use the smallest structure that communicates what is new and why it matters. Identify the article and event or publication date when available. Include only elements supported by material content. Combine, rename, reorder, or omit sections as appropriate; never add an empty or boilerplate section merely to follow this list.

Possible Markdown elements include:

- Source lines such as `**Event date:** 2026-08-05` and `**Source:** [Article title](https://example.com)`.
- `## What happened` for a concise factual description of the development.
- `## Meaningful insights` for what is genuinely new, why it matters, and who is affected.
- `## Corroboration and context` for material support, qualification, contradiction, or clearly labeled unverified claims.
- `## Relation to existing research` when the news materially supports, contradicts, updates, or makes existing notes or DFin reports stale.
- `## Investment implications` when the event changes expectations, thesis, risks, catalysts, or follow-up work.
- `## References` for the article and other material sources, using valid Markdown links when stable URLs are available.
- `## Follow-ups` only for genuine open questions or evidence still needed.

A short news note may combine what happened, the meaningful insight, and the investment implication into one concise Markdown section or a few paragraphs. Omit research comparison, corroboration, implications, or follow-up headings when there is nothing material to say.
