# dfin.pro MCP for Fundamental Research

> Ask. Analyze. Alpha.

Source-grounded company **SEC filings**, **financial statements**, **ratios**, **stock context**, **fund/ETF analytics**, **earnings transcripts**, **dfin.pro research reports**, and a **fundamentals stock screener** - brought into Claude Code, Cowork, OpenAI Codex, Hermes, and other AI agents through the **dfin.pro Model Context Protocol (MCP)** server.

[dfin.pro](https://www.dfin.pro) turns company filings and earnings transcripts into verifiable, source-grounded research for serious investors. This plugin connects that data to your agentic workflow and ships a `dfin-research` skill that guides agents to use it accurately.

## What you get

- **dfin.pro MCP tools** over the public dfin.pro MCP server: filing search, transcript search, report search, securities lookup, a fundamentals stock screener, annual financial statements, financial ratios, stock context, and fund/ETF analytics.
- **The `dfin-research` skill** - auto-activates on financial-research questions and applies dfin.pro's analysis methodology: resolve the ticker first, ground every figure in retrieved data, verify the numbers, and cite every source.
- **Codex and Claude packaging** - Claude plugin metadata, Codex plugin metadata (which bundles the MCP connection for Codex), and agent-facing docs links.

## Setup

### 1. Get an API key

Create an account at **[dfin.pro](https://www.dfin.pro)** and generate an API key in your account settings. The MCP uses the same `Authorization: Bearer <api_key>` credential as the REST API.

### 2. Install the plugin

**Claude Code:**

```bash
/plugin marketplace add dfin-pro/dfin-financial-mcp
/plugin install dfin-financial-mcp@dfin
```

This installs the `dfin-research` skill. On Claude Code you connect the MCP server yourself (step 3).

**Codex:**

```bash
codex plugin marketplace add dfin-pro/dfin-financial-mcp
```

Then install `dfin-financial-mcp` from the **dfin.pro** marketplace - in the Codex app under **Plugins**, or with `/plugins` in the Codex CLI - and start a new thread. Codex ships the connection: set `DFIN_API_KEY` and Codex authenticates to `https://www.dfin.pro/mcp` with `Authorization: Bearer ${DFIN_API_KEY}` automatically.

### 3. Connect the MCP server (Claude)

On Claude the plugin installs the skill only, so you add the connection yourself. The right method depends on the client:

- **Claude Code** - add `https://www.dfin.pro/mcp` as an MCP server with `Authorization: Bearer <DFIN_API_KEY>`. Use an environment variable rather than hard-coding the key.
- **Claude Cowork and other header-less clients** - use the URL-token endpoint, where your key is embedded in the path: `https://www.dfin.pro/mcp/<your-api-key>`. Add it as a custom connector or remote MCP server, and treat the tokenized URL as a secret, since it can appear in logs and browser history.

For step-by-step setup per client - environment variables, the Codex install flow, and the Cowork connector - see the **[dfin.pro MCP setup docs](https://www.dfin.pro/docs/mcp/)**.

## Documentation

For human-readable documentation, start here:

- [Docs map](https://www.dfin.pro/docs/) - navigation for humans and agents
- [MCP setup](https://www.dfin.pro/docs/mcp/) - MCP connection, authentication, resources, and response conventions
- [MCP agent guide](https://www.dfin.pro/docs/mcp/agent-guide/) - which MCP tool to call and when
- [REST API reference](https://www.dfin.pro/docs/api/v1/) - detailed REST contracts when you need lower-level API details

Once connected, the server exposes its own guidance as MCP resources:

- `dfin://docs` - documentation map
- `dfin://docs/mcp/agent-guide` - MCP-first tool-selection guidance
- `dfin://docs/mcp` - MCP setup, auth, resources, and response conventions
- `dfin://docs/methodology` - financial-analysis workflow, verification discipline, and citations
- `dfin://docs/api/v1` - REST developer reference for detailed request and response contracts

When discovering resources, use the `dfin://...` resource URIs directly when your MCP client supports that. If your client requires a server filter before listing resources, use the configured server id shown by that client, or list all resources and select the DFin entries. Do not infer the resource server id from a normalized tool namespace such as `mcp__dfin_pro`, because clients may use different labels for tool namespaces and resource server ids.

## Links

- Website: [https://www.dfin.pro](https://www.dfin.pro)
- Contact: [info@dfin.pro](mailto:info@dfin.pro)

## License

MIT
