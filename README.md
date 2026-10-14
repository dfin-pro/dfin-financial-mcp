# dfin.pro MCP for Fundamental Research

> Ask. Analyze. Alpha.

Source-grounded company **SEC filings**, **financial statements**, **ratios**, **stock context**, **fund/ETF analytics**, **earnings transcripts**, **dfin.pro research reports**, and a **fundamentals stock screener** - brought into Claude, Claude Code, OpenAI Codex, ChatGPT, Hermes, and other AI agents through the **dfin.pro Model Context Protocol (MCP)** server.

[dfin.pro](https://www.dfin.pro) turns company filings and earnings transcripts into verifiable, source-grounded research for serious investors. This plugin connects that data to your agentic workflow and ships five skills that guide agents through research, screening, semantic screening, note capture, and filing monitoring.

## What you get

- **dfin.pro MCP tools** over the public dfin.pro MCP server: filing search, transcript search, report search, securities lookup, a fundamentals stock screener, annual financial statements, financial ratios, stock context, and fund/ETF analytics.
- **The `dfin-research` skill** - handles source-grounded public-company, security, peer, earnings, statement, ratio, filing, transcript, report, price, and fund research.
- **The `dfin-screener` skill** - builds and runs contract-backed stock screens across financial, valuation, growth, technical, and other supported criteria.
- **The `dfin-semantic-screener` skill** - runs a quantitative screen and then searches filing or transcript evidence across up to 100 selected stocks.
- **The `dfin-note` skill** - saves completed financial research or material news as structured private notes with research or news categories and source relationships.
- **The `dfin-daily-filing-monitor` skill** - scans recent SEC filings for a requested theme or corporate event and presents an enriched briefing or dashboard.
- **Codex and Claude packaging** - both plugin formats bundle the OAuth-enabled MCP connection, alongside agent-facing docs links.

## Setup

### 1. Create your account

Create and verify an account at **[dfin.pro](https://www.dfin.pro)**. The bundled MCP connection uses the canonical `https://www.dfin.pro/mcp` endpoint and discovers dfin.pro's OAuth configuration automatically, so an eligible account does not need to paste an API key or configure an environment variable for the plugin flow. Existing API-key integrations remain supported.

Every account receives 250 free core REST and MCP data requests per UTC calendar month before its existing paid or operator access rules apply. Help, discovery guidance, securities lookup, and balance requests do not consume that allowance. The allowance and rate limits are shared across REST requests, API keys, and OAuth clients. Call `get_credit_balance` after connecting to inspect the account's billing mode, available DFin credits, monthly allowance usage and reset time, Notebook access, and shared rate limits. When PAYG is enabled, Notebook tools require an active Base or higher research subscription. When PAYG is disabled, existing Notebook access and quota behavior continue. Notebook tools never consume credits. After the free allowance, accepted PAYG data results use the documented standard call price. Operator-managed trial access waives REST and MCP charges after allowance exhaustion. Research-subscription trials remain separate and do not waive ordinary core PAYG charges. Polls and failed attempts create no additional charge. A pending response may follow an uncertain committed charge, and a failed response may follow previously charged partial output; inspect the balance and reconcile before retrying. Identical successful requests replay without another allowance request or charge during the configured replay window, which defaults to 90 seconds from completion and does not extend on retry. Polling the same processing task returns fresh progress and counts as one request over that task generation. Accepted partial evidence can be charged once; later recovery or full results from the same task do not create another charge. Agentic credit purchasing is future work and will use a separate method.

For the installation and connection steps, follow the example for your tool or AI:

- [OpenAI Codex](https://www.dfin.pro/docs/examples/codex-dfin-mcp/)
- [Claude Code](https://www.dfin.pro/docs/examples/claude-code-dfin-mcp/)
- [Claude](https://www.dfin.pro/docs/examples/claude-dfin-mcp/)
- [ChatGPT](https://www.dfin.pro/agents/chatgpt.md)
- [Hermes](https://www.dfin.pro/agents/hermes.md)
- [Grok](https://www.dfin.pro/docs/examples/grok-dfin-mcp/)

For Claude, Claude Code, and Codex, copy the setup prompt near the beginning of the relevant guide; each opens its matching client workflow directly. ChatGPT and Hermes have setup prompts in their linked workflows. The public [setup dispatcher](https://www.dfin.pro/agents.md) selects the intended client before fetching its instructions. Each client workflow inspects the existing installation, installs only missing components where supported, guides browser authorization, and verifies the selected research skills and a live MCP result. Continuation confirms the existing host and profile without reinstalling; verification-only requests check the existing setup without changing configuration. ChatGPT uses the same repository plugin on supported desktop installations or permitted direct OAuth on the web; Hermes uses direct OAuth with the five DFin skills installed separately. The guides include independent manual steps, and the workflow and guides include fresh-session continuation prompts.

## Documentation

Use the public website for setup and REST reference material.

- [Documentation map](https://www.dfin.pro/docs/) - the complete documentation index

## Links

- Website: [https://www.dfin.pro](https://www.dfin.pro)
- Contact: [info@dfin.pro](mailto:info@dfin.pro)

## License

MIT
