# dfin.pro MCP for Fundamental Research

> Ask. Analyze. Alpha.

Source-grounded company **SEC filings**, **financial statements**, **ratios**, **stock context**, **fund/ETF analytics**, **earnings transcripts**, **dfin.pro research reports**, and a **fundamentals stock screener** - brought into Claude Code, Cowork, OpenAI Codex, Hermes, and other AI agents through the **dfin.pro Model Context Protocol (MCP)** server.

[dfin.pro](https://www.dfin.pro) turns company filings and earnings transcripts into verifiable, source-grounded research for serious investors. This plugin connects that data to your agentic workflow and ships a `dfin-research` skill that guides agents to use it accurately.

## What you get

- **dfin.pro MCP tools** over the public dfin.pro MCP server: filing search, transcript search, report search, securities lookup, a fundamentals stock screener, annual financial statements, financial ratios, stock context, and fund/ETF analytics.
- **The `dfin-research` skill** - auto-activates on financial-research questions and applies dfin.pro's analysis methodology: resolve the ticker first, ground every figure in retrieved data, verify the numbers, and cite every source.
- **Codex and Claude packaging** - includes Claude plugin metadata, Codex plugin metadata, a shared MCP config, and agent-facing docs links.

## Get an API key

Create an account at **[dfin.pro](https://www.dfin.pro)** and generate an API key in your account settings. The MCP uses the same `Authorization: Bearer <api_key>` credential as the REST API.

## Set a permanent environment variable

Set `DFIN_API_KEY` once. Claude Code and Codex both use this same variable. Using an environment variable keeps the API key out of the plugin files and avoids hard-coding it in MCP config text.

For macOS with the default Zsh shell:

```bash
echo 'export DFIN_API_KEY="your-api-key"' >> ~/.zshrc
source ~/.zshrc
```

For Linux Bash terminals:

```bash
echo 'export DFIN_API_KEY="your-api-key"' >> ~/.bashrc
source ~/.bashrc
```

For macOS if you explicitly use Bash instead of Zsh:

```bash
echo 'export DFIN_API_KEY="your-api-key"' >> ~/.bash_profile
source ~/.bash_profile
```

For Windows PowerShell:

```powershell
[Environment]::SetEnvironmentVariable("DFIN_API_KEY", "your-api-key", "User")
```

For Windows Command Prompt (`cmd.exe`):

```cmd
setx DFIN_API_KEY "your-api-key"
```

You do not need to restart your computer. On macOS and Linux, the `source` command above loads the variable into the current terminal. On Windows, close and reopen PowerShell or Command Prompt after setting the variable. If Claude Code or Codex was already running before you set the key, restart that agent so it inherits the updated environment.

## Install (Claude Code)

```bash
/plugin marketplace add dfin-pro/dfin-financial-mcp
/plugin install dfin-financial-mcp@dfin
```

Claude Code connects to `https://www.dfin.pro/mcp` with `Authorization: Bearer ${DFIN_API_KEY}` through the bundled MCP config.

## Install (Codex)

Add the dfin.pro marketplace from GitHub:

```bash
codex plugin marketplace add dfin-pro/dfin-financial-mcp
```

Then install the plugin from the Codex plugin directory:

- In the Codex app, open **Plugins**, choose the **dfin.pro** marketplace, and install `dfin-financial-mcp`.
- In Codex CLI, run `codex`, then `/plugins`, choose the **dfin.pro** marketplace, and install `dfin-financial-mcp`.

Start a new Codex thread after installation so the plugin is available. Codex connects to `https://www.dfin.pro/mcp` with `Authorization: Bearer ${DFIN_API_KEY}` through the bundled `.mcp.json` config.

## Connect other clients (Claude Cowork, Claude.ai website, etc.)

Clients that cannot send custom headers - for example Claude Cowork connectors - can use the URL-token endpoint, where your API key is embedded in the path:

```text
https://www.dfin.pro/mcp/<your-api-key>
```

Add that as a custom connector or remote MCP server. The bearer-header method above is recommended where it is supported; treat a tokenized URL as a secret, since it can appear in logs and browser history.

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
