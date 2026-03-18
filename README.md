# OpenSearch Agent Skills

A curated collection of **Agent Skills** for OpenSearch. Each skill is a self-contained package of instructions, context, and tooling that teaches AI coding agents how to work with OpenSearch — from building search applications to managing clusters, optimizing queries, and more.

Works with **Claude Code**, **Cursor**, **Kiro**, and any agent that supports the [Agent Skills specification](https://agentskills.io/specification).

---

## Available Skills

| Skill | Category | Description |
|-------|----------|-------------|
| **[opensearch-launchpad](skills/opensearch-launchpad/)** | General | Get started with OpenSearch. Guides you through semantic, hybrid, neural, and agentic search setup with local execution and optional AWS deployment. |

> More skills coming soon — contributions welcome! See [Contributing a New Skill](#contributing-a-new-skill).

---

## Install a Skill

Install any skill into your project using [`npx skills`](https://agentskills.io):

```bash
npx skills add opensearch-project/opensearch-agent-skills
```

This discovers skills under `skills/` and symlinks them into your agent's skill directory (`.claude/skills/`, `.cursor/skills/`, etc.). Works with Claude Code, Cursor, OpenCode, Codex, and [many more](https://agentskills.io).

### Install options

```bash
# Install to a specific agent
npx skills add opensearch-project/opensearch-agent-skills -a claude-code

# Install globally (available across all projects)
npx skills add opensearch-project/opensearch-agent-skills -g

# Install to all detected agents
npx skills add opensearch-project/opensearch-agent-skills --all

# List available skills before installing
npx skills add opensearch-project/opensearch-agent-skills --list
```

After installing, try:

> *"I want to build a semantic search app with 10M docs"*

Your agent reads the skill instructions and runs the scripts directly — **no MCP server required**.

---

## Install in Kiro (Kiro Power)

> **[OpenSearch Launchpad Power](https://github.com/opensearch-project/opensearch-launchpad/tree/main/kiro/opensearch-launchpad)** — Add this power source URL in Kiro to get started.

1. Open **Kiro**
2. Go to **Powers** panel
3. Click **Add Power** and paste:
   ```
   https://github.com/opensearch-project/opensearch-launchpad/tree/main/kiro/opensearch-launchpad
   ```
4. Kiro reads `POWER.md` and connects the MCP server automatically — no local clone required.

---

## How It Works

| Path | IDEs | How it connects |
|------|------|-----------------|
| **Agent Skill** | Claude Code, Cursor, Kiro, OpenCode, Codex | Agent reads `SKILL.md` and runs scripts directly via the terminal |
| **Kiro Power** | Kiro | Kiro runs the MCP server (`opensearch-launchpad`) which exposes phase tools |

The **Agent Skill** path uses standalone scripts with zero dependency on the MCP server or `opensearch_orchestrator` package. The **Kiro Power** path is maintained for backward compatibility with existing Kiro Power installations.

---

## Prerequisites

- **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed
- **Docker** installed and running ([Download Docker](https://docs.docker.com/get-docker/))
- **For AWS deployment (optional):** AWS credentials configured — see [AWS Setup](#aws-setup-optional)

---

## Repo Structure

```
skills/                        # All agent skills
    opensearch-launchpad/      # Get started with OpenSearch
            SKILL.md           # Skill instructions (< 500 lines)
            scripts/           # Execution scripts
            references/        # Loaded on demand per phase
    search-relevance/          # Future: query tuning, ranking, evaluation
    log-analytics/             # Future: log ingestion, parsing, dashboards
    observability/             # Future: traces, metrics, monitoring
kiro/                          # Kiro Power integrations
opensearch_orchestrator/       # MCP server (Kiro Power path only)
tests/                         # All tests
```

---

## Contributing a New Skill

We welcome contributions of new skills! Each skill should teach an AI agent how to accomplish a specific OpenSearch task.

### Skill template

Create a new directory under the appropriate domain category:

```
skills/<category>/<skill-name>/
    SKILL.md              # Required: instructions with YAML frontmatter
    scripts/              # Optional: execution scripts the agent runs
    references/           # Optional: detailed docs loaded on demand
```

### SKILL.md format

```yaml
---
name: opensearch-your-skill-name
description: >
  One paragraph describing what the skill does and when agents should
  activate it. Include trigger keywords that users might say.
compatibility: List any prerequisites (e.g., Docker, uv, AWS credentials).
metadata:
  author: your-github-handle
  version: "1.0"
---

# Your Skill Name

Instructions for the agent go here. Keep under 500 lines.
Use references/ for detailed procedures loaded on demand.
```

### Conventions

- **One skill, one concern** — a skill should do one thing well
- **SKILL.md under 500 lines** — use `references/` for detailed procedures
- **No LLM dependencies** — skills leverage the IDE's agent, not a bundled model
- **Scripts over MCP servers** — prefer standalone scripts the agent runs directly
- **Tests required** — add tests under `tests/` following existing patterns

See the [Developer Guide](DEVELOPER_GUIDE.md) for testing, CI, and release details. See [DESIGN.md](DESIGN.md) for architectural tenets.

---

## AWS Setup (Optional)

Phase 5 of opensearch-launchpad deploys your local search solution to AWS. This is optional — Phases 1–4 work entirely locally.

### 1. Add AWS MCP Servers

Add these servers to the power's `mcp.json` configuration in Kiro:

```json
{
  "mcpServers": {
    "awslabs.aws-api-mcp-server": {
      "command": "uvx",
      "args": ["awslabs.aws-api-mcp-server@latest"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" }
    },
    "aws-knowledge-mcp-server": {
      "command": "uvx",
      "args": ["fastmcp", "run", "https://knowledge-mcp.global.api.aws"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" }
    },
    "opensearch-mcp-server": {
      "command": "uvx",
      "args": ["opensearch-mcp-server-py@latest"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" }
    }
  }
}
```

### 2. Configure AWS Credentials

```bash
aws configure
```

Or set environment variables:

```bash
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"
```

### 3. Required IAM Permissions

Your AWS user/role needs permissions for:
- **OpenSearch Service** — create/manage domains and serverless collections
- **IAM** — create and manage roles for OpenSearch
- **Bedrock** — invoke models (for semantic and agentic search)

---

## Troubleshooting

### `spawn uvx ENOENT` or Docker not found

Some MCP clients cannot find `uvx` or `docker` from the JSON config environment.

**Fix:** Locate the full paths and add them to `env.PATH` in your MCP config:

```bash
which uvx      # e.g. /Users/you/.local/bin/uvx
which docker   # e.g. /usr/local/bin/docker
```

Then in Kiro: **Cmd+Shift+P** → `Kiro: Open user MCP config (JSON)` and update:

```jsonc
{
  "mcpServers": {
    "opensearch-launchpad": {
      "command": "uvx",
      "args": ["opensearch-launchpad@latest"],
      "env": {
        "FASTMCP_LOG_LEVEL": "ERROR",
        "PATH": "/usr/local/bin:/usr/bin:/bin:/Users/you/.local/bin"
      }
    }
  }
}
```

---

## License

This project is licensed under the Apache License, Version 2.0. See [LICENSE.txt](LICENSE.txt) for details.
