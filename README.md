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

Create an account at **[dfin.pro](https://www.dfin.pro)**. The bundled MCP connection uses the canonical `https://www.dfin.pro/mcp` endpoint and discovers dfin.pro's OAuth configuration automatically. No API key or environment variable is required for the plugin flow.

### 2. Install the plugin

**Claude Code:**

```bash
/plugin marketplace add dfin-pro/dfin-financial-mcp
/plugin install dfin-financial-mcp@dfin
```

This installs the four bundled skills and the dfin.pro MCP connection. Complete the OAuth prompt in step 3.

**Codex:**

```bash
codex plugin marketplace add dfin-pro/dfin-financial-mcp
```

Then install `dfin-financial-mcp` from the **dfin.pro** marketplace - in the Codex app under **Plugins**, or with `/plugins` in the Codex CLI. The marketplace requests authentication on install, and the bundled MCP connection starts the dfin.pro OAuth flow. Start a new thread after installation.

### 3. Complete OAuth sign-in

- **Claude Code** - after installation, run `/reload-plugins` if Claude asks you to activate the plugin. Then open `/mcp`, select `dfin`, and choose **Authenticate**. Claude opens the dfin.pro OAuth page in your browser; sign in, approve access, and return to Claude Code. If the browser does not open, copy the authentication URL shown by Claude into your browser. After updating an existing install, run `/reload-plugins` or restart Claude Code before authenticating.
- **Codex** - follow the authentication prompt shown during installation. If it is still waiting for authentication, open the MCP server list and select **Authenticate**, or run `codex mcp login dfin` when the server is configured as a standalone MCP connection.
- **Claude Cowork and other connector-based clients** - add `https://www.dfin.pro/mcp` as a custom connector and complete the OAuth sign-in flow.

If you previously installed version `0.1.6` or earlier, update or reinstall the plugin before retrying authentication. Those releases could leave an API-key-based MCP configuration in the client's plugin cache.

Existing non-plugin integrations can continue sending `Authorization: Bearer <DFIN_API_KEY>` if they are not ready to migrate to OAuth. Use an environment variable rather than hard-coding the key.

The legacy `https://www.dfin.pro/mcp/<your-api-key>` compatibility URL remains available for older clients that support neither OAuth nor custom headers, but it is not recommended because credential-bearing URLs can be retained by client, proxy, or browser logs.

For current OAuth setup details and client-specific troubleshooting, see the **[dfin.pro MCP setup docs](https://www.dfin.pro/docs/mcp/)**.

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
