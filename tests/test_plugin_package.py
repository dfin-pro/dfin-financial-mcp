"""Regression tests for the shared Claude and Codex plugin package."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MCP_URL = "https://www.dfin.pro/mcp"
PLUGIN_VERSION = "0.1.9"


def _load_json(relative_path: str):
    return json.loads((REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8"))


class PluginPackageTests(unittest.TestCase):
    """Keep both plugin hosts on the same OAuth-discoverable MCP endpoint."""

    def test_codex_manifest_references_the_shared_root_mcp_config(self):
        codex_manifest = _load_json(".codex-plugin/plugin.json")

        self.assertEqual(codex_manifest["mcpServers"], "./.mcp.json")

    def test_claude_uses_root_mcp_auto_discovery(self):
        claude_manifest = _load_json(".claude-plugin/plugin.json")

        self.assertNotIn("mcpServers", claude_manifest)
        self.assertTrue((REPOSITORY_ROOT / ".mcp.json").is_file())

    def test_mcp_config_uses_oauth_discovery_without_api_key_headers(self):
        mcp_config = _load_json(".mcp.json")
        server = mcp_config["mcpServers"]["dfin"]

        self.assertEqual(server, {"type": "http", "url": MCP_URL})
        self.assertNotIn("headers", server)
        self.assertNotIn("bearer_token_env_var", server)

    def test_codex_marketplace_authenticates_on_install(self):
        marketplace = _load_json(".agents/plugins/marketplace.json")
        plugin = next(
            item
            for item in marketplace["plugins"]
            if item["name"] == "dfin-financial-mcp"
        )

        self.assertEqual(plugin["policy"]["authentication"], "ON_INSTALL")
        self.assertEqual(plugin["policy"]["installation"], "AVAILABLE")
        self.assertEqual(
            plugin["source"],
            {
                "source": "url",
                "url": "https://github.com/dfin-pro/dfin-financial-mcp.git",
                "ref": "main",
            },
        )

    def test_host_manifests_keep_the_same_release_version(self):
        claude_manifest = _load_json(".claude-plugin/plugin.json")
        codex_manifest = _load_json(".codex-plugin/plugin.json")

        self.assertEqual(claude_manifest["version"], PLUGIN_VERSION)
        self.assertEqual(codex_manifest["version"], PLUGIN_VERSION)

    def test_screener_skill_has_codex_interface_metadata(self):
        metadata_path = REPOSITORY_ROOT / "skills/dfin-screener/agents/openai.yaml"

        self.assertTrue(metadata_path.is_file())
        metadata = metadata_path.read_text(encoding="utf-8")
        self.assertIn('display_name: "DFin Screener"', metadata)
        self.assertIn("$dfin-screener", metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)


if __name__ == "__main__":
    unittest.main()
