# dfin.pro MCP for Fundamental Research

> Ask. Analyze. Alpha.

Source-grounded company **SEC filings**, **financial statements**, **ratios**, **stock context**, **fund/ETF analytics**, **earnings transcripts**, **dfin.pro research reports**, and a **fundamentals stock screener** - brought into Claude Code, Cowork, OpenAI Codex, Hermes, and other AI agents through the **dfin.pro Model Context Protocol (MCP)** server.

[dfin.pro](https://www.dfin.pro) turns company filings and earnings transcripts into verifiable, source-grounded research for serious investors. This plugin connects that data to your agentic workflow and ships four skills that guide agents through research, screening, note capture, and filing monitoring.

## What you get

- **dfin.pro MCP tools** over the public dfin.pro MCP server: filing search, transcript search, report search, securities lookup, a fundamentals stock screener, annual financial statements, financial ratios, stock context, and fund/ETF analytics.
- **The `dfin-research` skill** - handles source-grounded public-company, security, peer, earnings, statement, ratio, filing, transcript, report, price, and fund research.
- **The `dfin-screener` skill** - builds and runs contract-backed stock screens across financial, valuation, growth, technical, and other supported criteria.
- **The `dfin-note` skill** - saves completed financial research or material news as structured private notes with research or news categories and source relationships.
- **The `dfin-daily-filing-monitor` skill** - scans recent SEC filings for a requested theme or corporate event and presents an enriched briefing or dashboard.
- **Codex and Claude packaging** - both plugin formats bundle the OAuth-enabled MCP connection, alongside agent-facing docs links.

## Setup

### 1. Create your account

Create an account at **[dfin.pro](https://www.dfin.pro)**. During early access, OAuth connections are available to approved trial accounts and accounts that already have a usable API key. The bundled MCP connection uses the canonical `https://www.dfin.pro/mcp` endpoint and discovers dfin.pro's OAuth configuration automatically. Eligible accounts do not need to paste an API key or configure an environment variable for the plugin flow.

For the installation and connection steps, follow the example for your tool or AI:

- [OpenAI Codex](https://www.dfin.pro/docs/examples/codex-dfin-mcp/)
- [Claude Code](https://www.dfin.pro/docs/examples/claude-code-dfin-mcp/)
- [Claude.ai or Cowork](https://www.dfin.pro/docs/examples/claude-dfin-mcp/)
- [Grok](https://www.dfin.pro/docs/examples/grok-dfin-mcp/)

## Documentation

Use the public website for setup and REST reference material. After connecting, load agent guidance through `agent_help`:

- [Documentation map](https://www.dfin.pro/docs.md) - the complete documentation index
- [MCP setup](https://www.dfin.pro/docs/mcp/) - connection and authentication for supported clients
- `agent_help(topic="agent_guide")` - the required first read for tool selection and methodology routing
- `agent_help(topic="methodology_search")` - search, provenance, and document handling
- `agent_help(topic="methodology_financials")` - structured statements, ratios, sourcing, and verification
- `agent_help(topic="methodology_screening")` - contract discovery and safe screener construction
- `agent_help(topic="methodology_notes")` - private-note selection, privacy, linking, and ownership
- [REST API reference](https://www.dfin.pro/docs/api/v1.md) - detailed lower-level request and response contracts

## Links

- Website: [https://www.dfin.pro](https://www.dfin.pro)
- Contact: [info@dfin.pro](mailto:info@dfin.pro)

## License

MIT
