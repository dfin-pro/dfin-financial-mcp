# dfin.pro MCP for Fundamental Research

> Ask. Analyze. Alpha.

Source-grounded company **SEC filings**, **financial statements**, **ratios**, **stock context**, **fund/ETF analytics**, **earnings transcripts**, **dfin.pro research reports**, and a **fundamentals stock screener** - brought into Claude Code, Cowork, OpenAI Codex, Hermes, and other AI agents through the **dfin.pro Model Context Protocol (MCP)** server.

[dfin.pro](https://www.dfin.pro) turns company filings and earnings transcripts into verifiable, source-grounded research for serious investors. This plugin connects that data to your agentic workflow and ships four skills that guide agents through research, screening, note capture, and filing monitoring.

## What you get

- **dfin.pro MCP tools** over the public dfin.pro MCP server: filing search, transcript search, report search, securities lookup, a fundamentals stock screener, annual financial statements, financial ratios, stock context, and fund/ETF analytics.
- **The `dfin-research` skill** - handles source-grounded public-company, security, peer, earnings, statement, ratio, filing, transcript, report, price, and fund research.
- **The `dfin-screener` skill** - builds and runs contract-backed stock screens across financial, valuation, growth, technical, and other supported criteria.
- **The `dfin-research-note` skill** - saves substantial completed analysis as structured private research notes with ticker, note, report, and source references.
- **The `dfin-daily-filing-monitor` skill** - scans recent SEC filings for a requested theme or corporate event and presents an enriched briefing or dashboard.
- **Codex and Claude packaging** - Claude plugin metadata, Codex plugin metadata (which bundles the MCP connection for Codex), and agent-facing docs links.

## Setup

### 1. Choose authentication

Create an account at **[dfin.pro](https://www.dfin.pro)**. Interactive clients should connect to the canonical `https://www.dfin.pro/mcp` endpoint and complete OAuth sign-in. Existing integrations can continue to use a dfin.pro API key in the `Authorization: Bearer <api_key>` header.

### 2. Install the plugin

**Claude Code:**

```bash
/plugin marketplace add dfin-pro/dfin-financial-mcp
/plugin install dfin-financial-mcp@dfin
```

This installs the four bundled skills. On Claude Code you connect the MCP server yourself (step 3).

**Codex:**

```bash
codex plugin marketplace add dfin-pro/dfin-financial-mcp
```

Then install `dfin-financial-mcp` from the **dfin.pro** marketplace - in the Codex app under **Plugins**, or with `/plugins` in the Codex CLI - and start a new thread. Codex ships the connection: set `DFIN_API_KEY` and Codex authenticates to `https://www.dfin.pro/mcp` with `Authorization: Bearer ${DFIN_API_KEY}` automatically.

### 3. Connect the MCP server (Claude)

On Claude the plugin installs the skills only, so you add the connection yourself:

- **Claude Code and Claude Cowork** - add `https://www.dfin.pro/mcp` as a custom connector or remote MCP server and complete the OAuth sign-in flow.
- **Existing header-based integrations** - continue sending `Authorization: Bearer <DFIN_API_KEY>` if you are not ready to migrate to OAuth. Use an environment variable rather than hard-coding the key.

The legacy `https://www.dfin.pro/mcp/<your-api-key>` compatibility URL remains available for older clients that support neither OAuth nor custom headers, but it is not recommended because credential-bearing URLs can be retained by client, proxy, or browser logs.

For step-by-step setup per client - environment variables, the Codex install flow, and the Cowork connector - see the **[dfin.pro MCP setup docs](https://www.dfin.pro/docs/mcp/)**.

## Documentation

Use the public website directly rather than relying on MCP resource discovery:

- [Documentation map](https://www.dfin.pro/docs.md) - the complete documentation index
- [MCP setup](https://www.dfin.pro/docs/mcp/) - connection and authentication for supported clients
- [MCP agent guide](https://www.dfin.pro/docs/mcp/agent-guide.md) - the required first read for tool selection and methodology routing
- [Search methodology](https://www.dfin.pro/docs/methodology/search.md) - search, provenance, and document handling
- [Financials methodology](https://www.dfin.pro/docs/methodology/financials.md) - structured statements, ratios, sourcing, and verification
- [Screening methodology](https://www.dfin.pro/docs/methodology/screening.md) - contract discovery and safe screener construction
- [Notes methodology](https://www.dfin.pro/docs/methodology/notes.md) - private-note selection, privacy, linking, and ownership
- [REST API reference](https://www.dfin.pro/docs/api/v1.md) - detailed lower-level request and response contracts

## Links

- Website: [https://www.dfin.pro](https://www.dfin.pro)
- Contact: [info@dfin.pro](mailto:info@dfin.pro)

## License

MIT
