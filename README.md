# OpenSearch Launchpad

An AI-powered assistant that guides you from initial requirements to a running OpenSearch search setup. It collects a sample document, gathers preferences, plans a search architecture, and executes the plan — creating indices, ML models, ingest pipelines, and a local search UI — with optional deployment to Amazon OpenSearch Service or Serverless.

Works with **Claude Code**, **Cursor**, **Kiro**, and any agent that supports the [Agent Skills specification](https://agentskills.io/specification).

---

## Install the Agent Skill

Install into any project using [`npx skills`](https://agentskills.io):

```bash
npx skills add opensearch-project/opensearch-launchpad
```

This discovers `skills/opensearch-launchpad/SKILL.md` and symlinks it into your agent's skill directory (`.claude/skills/`, `.cursor/skills/`, etc.). Works with Claude Code, Cursor, OpenCode, Codex, and [many more](https://agentskills.io).

### Install options

```bash
# Install to a specific agent
npx skills add opensearch-project/opensearch-launchpad -a claude-code

# Install globally (available across all projects)
npx skills add opensearch-project/opensearch-launchpad -g

# Install to all detected agents
npx skills add opensearch-project/opensearch-launchpad --all

# List available skills before installing
npx skills add opensearch-project/opensearch-launchpad --list
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

## How it works

| Path | IDEs | How it connects |
|------|------|-----------------|
| **Agent Skill** | Claude Code, Cursor, Kiro, OpenCode, Codex | Agent reads `SKILL.md` and runs Python scripts directly via the terminal |
| **Kiro Power** | Kiro | Kiro runs the MCP server (`opensearch-launchpad`) which exposes phase tools |

The **Agent Skill** path uses standalone scripts in `skills/opensearch-launchpad/scripts/` with zero dependency on the MCP server or `opensearch_orchestrator` package. The **Kiro Power** path is maintained for backward compatibility with existing Kiro Power installations.

---

## Prerequisites

- **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed
- **Docker** installed and running ([Download Docker](https://docs.docker.com/get-docker/))
- **For AWS deployment (optional):** AWS credentials configured — see [AWS Setup](#aws-setup-optional)

---

## What It Does

OpenSearch Launchpad walks you through five phases to build a production-ready search solution:

| Phase | What happens |
|-------|-------------|
| **1. Sample Document** | Provide a sample document (built-in IMDB dataset, local file, URL, existing index, or paste JSON) |
| **2. Preferences** | Set your budget, performance priority, query pattern, and deployment preferences |
| **3. Plan** | An AI planner designs your search architecture (BM25, semantic, hybrid, or agentic) |
| **4. Execute** | Automatically creates OpenSearch indices, ML models, ingest pipelines, and a search UI locally |
| **4.5 Evaluate** | *(Optional)* Evaluate search quality and iterate on the architecture |
| **5. Deploy** | *(Optional)* Deploy to Amazon OpenSearch Service or Amazon OpenSearch Serverless |

### Quick Start

After installing, just describe what you want to build:

> *"Help me build a hybrid search app for my product catalog"*

The agent guides you through each phase interactively.

---

## AWS Setup (Optional)

Phase 5 deploys your local search solution to AWS. This is optional — Phases 1–4 work entirely locally.

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

## Contributing

See the [Developer Guide](DEVELOPER_GUIDE.md) for local development setup, MCP server internals, tool reference, and the release process.

## License

This project is licensed under the Apache License, Version 2.0. See [LICENSE.txt](LICENSE.txt) for details.
