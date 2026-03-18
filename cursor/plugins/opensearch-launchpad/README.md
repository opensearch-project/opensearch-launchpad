# OpenSearch Launchpad — Cursor Plugin

This directory is a **Cursor plugin** (manifest + skill) for [OpenSearch Launchpad](https://github.com/opensearch-project/opensearch-launchpad). The **Agent Skill** guides the Cursor agent through the full workflow using **scripts** and direct OpenSearch API calls — **no MCP server required** for this plugin.

It follows Cursor’s plugin structure from [Plugins reference](https://cursor.com/docs/reference/plugins).

---

## Prerequisites

- **Docker** (for local OpenSearch and search UI)
- **uv** (for running Python scripts; install from [astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/))
- **For AWS deployment (Phase 5):** AWS credentials; optional MCP servers (see main repo README)

---

## What this plugin provides

- **Skill:** `opensearch-launchpad` — workflow (sample → preferences → plan → execute → optional AWS). The agent runs scripts in `skills/opensearch-launchpad/scripts/` (e.g. `start_opensearch.sh`, `opensearch_ops.py`).
- **No MCP server** — The skill instructs the agent to run scripts directly. The `opensearch-launchpad` MCP server exists for **Kiro Power** and **Claude Desktop**; for Cursor with this Agent Skill, scripts do the job.

---

## Installation

### As a Cursor plugin

This plugin bundles:

- `.cursor-plugin/plugin.json` (required manifest)
- `skills/` → `../../../skills` (symlink to repo Agent Skills)

Cursor discovers the skill from `skills/opensearch-launchpad/SKILL.md`. Clone the repo (or add this plugin source); the symlink is checked in.

### Manual project config

From the **repo root**, `.cursor/skills` is a symlink to `../skills`. Open the project in Cursor; the skill is discovered from `.cursor/skills/opensearch-launchpad/SKILL.md`. No MCP config needed for the core workflow.

For **AWS Phase 5** only, you may add optional MCP servers to `.cursor/mcp.json` (e.g. `opensearch-mcp-server`, `aws-knowledge-mcp-server`) — see the main [README](../../../README.md).

---

## Marketplace / distribution

To submit this plugin to the Cursor marketplace, ensure this folder contains:

- `.cursor-plugin/plugin.json` (required)
- `skills/` → `../../../skills` (symlink; skill at `skills/opensearch-launchpad/SKILL.md`)

This plugin is registered in `cursor/.cursor-plugin/marketplace.json`. The MCP server (PyPI `opensearch-launchpad`) is a separate integration for Kiro and Claude Desktop; this Cursor plugin is skill-only.
