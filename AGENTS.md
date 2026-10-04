# AGENTS Instructions

## Python Bytecode Cache

For Linux Python commands that write bytecode in `/tmp`, set `PYTHONPYCACHEPREFIX=/tmp/dhyana_pycache` so all runs reuse one shared cache directory. Never create a unique cache-prefix directory for a single run, because repeated 100 MB caches can exhaust `/tmp`.

## Skill Version Coordination

- Do not propose, request, or perform skill version or updated-date changes unless the user explicitly instructs you to change them. Ordinary skill content work must proceed with the existing version metadata unchanged; do not pause or broaden the task to discuss a version bump.
- When the user explicitly requests a skill version change, synchronize the version number and updated date with the corresponding skill metadata or guidance in the main Dhyana repository as part of the same change. Verify that both repositories report the same version before completing the work.

## MCP Live Verification Coordination

Keep the main repository's MCP live verification suite in sync with the current public MCP surface. When a tool or resource is added, retired, renamed, or changes its arguments, defaults, response shape, or supported modes, update the live case manifest and its focused contract tests in the same effort. Keep at least one schema-valid live case for every public tool, and use separate cases for materially different modes or data sources. Check the manifest against the current registered schemas and run the focused non-live verifier tests before handing off. Static and schema checks do not establish live provider success; preserve the corresponding live case for release verification.
