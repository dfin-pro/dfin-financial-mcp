# dfin.pro MCP for Fundamental Research

> Ask. Analyze. Alpha.

Source-grounded company **SEC filings**, **financial statements**, **ratios**, **stock context**, **fund/ETF analytics**, and a **fundamentals stock screener** — brought into Claude Code, Cowork, Codex, and other AI agents through the **dfin.pro Model Context Protocol (MCP)** server.

[dfin.pro](https://www.dfin.pro) turns company filings and earnings transcripts into verifiable, source-grounded research for serious investors. This plugin connects that data to your agentic workflow and ships a `dfin-research` skill that guides agents to use it accurately.

## What you get

- **dfin.pro MCP tools** over the public dfin.pro API: filing search, securities lookup, a fundamentals stock screener (basic and advanced), annual financial statements, financial ratios, stock context, and fund/ETF analytics.
- **The `dfin-research` skill** — auto-activates on financial-research questions and applies dfin.pro's analysis methodology: resolve the ticker first, ground every figure in retrieved data, verify the numbers, and cite every source.

## Get an API key

Create an account at **[dfin.pro](https://www.dfin.pro)** and generate an API key in your account settings. The MCP uses the same `Authorization: Bearer <api_key>` credential as the REST API.

## Install (Claude Code)

```bash
/plugin marketplace add dfin-pro/dfin-financial-mcp
/plugin install dfin-financial-mcp@dfin
```

Then set your API key so the bundled MCP connection can authenticate:

```bash
export DFIN_API_KEY="your-api-key"   # add to your shell profile to persist it
```

Claude Code connects to `https://www.dfin.pro/mcp` with your bearer token automatically.

## Connect other clients (Cowork and header-less clients)

Clients that cannot send custom headers — for example Claude Cowork connectors — can use the URL-token endpoint, where your API key is embedded in the path:

```
https://www.dfin.pro/mcp/<your-api-key>
```

Add that as a custom connector or remote MCP server. The bearer-header method above is recommended where it is supported; treat a tokenized URL as a secret, since it can appear in logs and browser history.

## Documentation

Once connected, the server exposes its own guidance as MCP resources:

- `dfin://docs/methodology` — how to research with the tools (ticker resolution, evidence, verification, citations)
- `dfin://docs/api/v1/agent-hints` — concise endpoint signposts
- `dfin://docs/api/v1` — full request and response contracts

## Links

- Website: [https://www.dfin.pro](https://www.dfin.pro)
- Contact: [info@dfin.pro](mailto:info@dfin.pro)

## License

MIT
