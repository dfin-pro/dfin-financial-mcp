# dfin-financial-mcp

Plugin packaging for the dfin.pro MCP server: four agent skills plus Claude and Codex plugin metadata. The MCP server itself, and the docs it serves via `agent_help` (`agent_guide`, `methodology`, the focused `methodology_*` pages, `api_reference`), live in a **different repo** — they cannot be edited from here.

## Keep documentation in sync

This repo describes itself in several places at once, and they drift apart quietly. Any change to what the plugin *is* or *ships* must be carried through every surface below in the same commit:

- `README.md` — the skill list, what each skill does, and the setup steps.
- `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` — version and description.
- `.claude-plugin/marketplace.json` — its plugin description names the skills individually.
- `.agents/plugins/marketplace.json` — display and policy metadata.
- `skills/*/SKILL.md` — the frontmatter `description` is the routing surface that decides when a skill triggers.
- `skills/*/agents/openai.yaml` — Codex-facing display metadata, where present.

Concrete checks before committing:

- **Adding, removing, or renaming a skill?** Update the README skill list, both marketplace descriptions, and add or remove `agents/openai.yaml` to match the other skills.
- **Changing what a skill covers?** Update its frontmatter `description` too — the body and the description must not promise different things. A capability named in a description but taught nowhere will trigger the skill and then strand the agent.
- **Bumping the version?** Bump `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` **together**. They have drifted before, with Codex left behind at `0.1.0` for two releases.

## Version convention

Patch numbers are zero-padded: `0.1.0` → `0.1.01` → `0.1.02`. This is deliberate, not a typo — do not "correct" it to semver (`0.1.2`) without asking. Both plugin manifests carry the same value.

## Writing skills

`SKILL.md` files are guidance for the agent on **how and when** to use a tool. They are not documentation of **what** the tool is — the MCP tool schema already carries the name, parameters, enums, and defaults into the agent's context for free, before any skill loads.

The test: if a line would still be worth reading with the tool list closed, it is guidance. If it only restates the schema, delete it — the agent already had it. Good examples in `skills/dfin-research/SKILL.md`: prefer `frequency="w"` for ranges over 5 years, `as_reported` for one company versus `standardized` for comparisons, use at least 2 filters on `search_filings`. None of those are in a schema.

Related: guidance the MCP server delivers at runtime does not belong here either. A 202 (pending) response already tells the agent to wait and retry, so no skill repeats that.

## Data coverage

Worth knowing before writing scope claims, since the boundaries are not uniform:

- **Filings, financial statements:** US companies only. Statements error out on a non-US ticker, so the boundary enforces itself.
- **Ratios:** US, plus international figures sourced from a third-party API whose accuracy dfin does not vouch for. These return **silently** — no error, no provenance marker. This is why the skills scope financial data to US companies rather than relying on failure to stop the agent.
- **Transcripts, prices:** US and many international names.
- **Screener:** global (third-party data).

`get_stock_context` reports per-name coverage, which beats encoding any of this as a rule an agent has to reason through.
