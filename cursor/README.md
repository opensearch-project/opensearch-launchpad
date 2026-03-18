# Cursor plugins (OpenSearch Launchpad)

This folder follows the [Cursor plugin template](https://github.com/cursor/plugin-template) layout for building and publishing Cursor Marketplace plugins from this repo.

## Layout

- **`.cursor-plugin/marketplace.json`** — Marketplace manifest; lists plugins and `pluginRoot`.
- **`plugins/opensearch-launchpad/`** — The OpenSearch Launchpad plugin (MCP server + Agent Skill).
- **`.cursor/skills`** — Symlink to `../../skills` for local discovery (same pattern as repo root `.cursor` and `.claude`).
- **`docs/`** — Documentation for adding or customizing plugins.
- **`scripts/`** — Optional validation or tooling.

## Plugins

| Plugin | Path | Description |
|--------|------|-------------|
| **opensearch-launchpad** | `plugins/opensearch-launchpad/` | Agent Skill only (no MCP): workflow + scripts for OpenSearch (indices, ML models, pipelines, search UI, optional AWS). |

## Getting started

1. **`.cursor-plugin/marketplace.json`**: Set `name`, `owner`, and `metadata` if you publish to the marketplace.
2. **`plugins/opensearch-launchpad/.cursor-plugin/plugin.json`**: Set `name` (kebab-case), `displayName`, `author`, `description`, `keywords`, `license`, `version`.
3. Skill content lives in the repo root `skills/opensearch-launchpad/`; the plugin uses a symlink `skills` → `../../../skills`. No MCP server — the Agent Skill uses scripts only.

## Single plugin vs multi-plugin

This repo currently has one plugin under `plugins/`. To add more, create `plugins/<name>/` and register it in `.cursor-plugin/marketplace.json` (see `docs/add-a-plugin.md`).

For a **single-plugin** repo, you can move `plugins/opensearch-launchpad/*` to the repository root and keep one `.cursor-plugin/plugin.json`, removing `.cursor-plugin/marketplace.json`.

## Local testing

From the **main agent repo root** (parent of `cursor/`), use the repo-level `.cursor/mcp.json` and `.cursor/skills` → `../skills` so Cursor discovers the MCP server and skill. The `cursor/` folder is the template layout for submission; when developing, the agent root `.cursor` is used.

See [plugins/opensearch-launchpad/README.md](plugins/opensearch-launchpad/README.md) for installation and troubleshooting.
