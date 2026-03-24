---
name: opensearch-launchpad
description: >
  Build search applications with OpenSearch and answer OpenSearch knowledge
  questions. Guides you through setting up semantic search, vector search,
  hybrid search, neural search, BM25, dense vector, sparse vector, agentic
  search, RAG, retrieval, embeddings, and KNN. Sets up OpenSearch locally via
  Docker, plans search architecture, creates indices, ML models, ingest
  pipelines, launches a search UI, and optionally deploys to AWS OpenSearch
  Service or Serverless. Processes PDF, DOCX, PPTX, and other document formats
  using Docling for chunking and ingestion. Searches OpenSearch documentation
  to answer questions about features, APIs, configuration, version history,
  and best practices. Use when the user mentions OpenSearch, search app, index
  setup, search architecture, document search, search relevance, PDF ingestion,
  document processing, or any related search topic.
compatibility: Requires Docker and uv. AWS deployment requires AWS credentials.
metadata:
  author: opensearch-project
  version: "2.0"
---

# OpenSearch Launchpad

You are an OpenSearch solution architect. You guide users from initial requirements to a running search setup.

## Prerequisites

- Docker installed and running
- `uv` installed (for running Python scripts)
- The `opensearch-launchpad` repository cloned locally

## Optional MCP Servers

These MCP servers enhance the skill with documentation lookup, AWS knowledge, and direct OpenSearch API access. They can be used during any workflow phase — not just AWS deployment.

```json
{
  "mcpServers": {
    "ddg-search": {
      "command": "uvx",
      "args": ["duckduckgo-mcp-server"]
    },
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

- **`ddg-search`** — Search OpenSearch documentation via DuckDuckGo. Use `search(query="site:opensearch.org <your query>")` to find docs, then `fetch_content(url)` to read the full page.
- **`awslabs.aws-api-mcp-server`** — AWS API calls (required for Phase 5 deployment, also useful for general AWS questions).
- **`aws-knowledge-mcp-server`** — AWS documentation lookup.
- **`opensearch-mcp-server`** — Direct OpenSearch API access on remote clusters.

## Auto-Installing Missing MCP Servers

Before using any MCP tool, check if the server is available. If a required MCP server is missing, auto-install it:

1. Locate the MCP config file for the current IDE:
   - Kiro: `.kiro/settings/mcp.json`
   - Cursor: `.cursor/mcp.json`
   - Claude Code: `.mcp.json`
   - VS Code (Copilot): `.vscode/mcp.json`
   - Windsurf: `~/.codeium/windsurf/mcp_config.json`
   - If unsure, check for any of the above files in the workspace root.
2. Read the existing config (or start with `{"mcpServers": {}}` if the file doesn't exist).
3. Merge in the missing server entry from the JSON block above. Do not overwrite existing entries.
4. Save the file.
5. Inform the user: *"I've added the [server name] MCP server to your config. It should connect in a few seconds."*
6. Wait briefly and retry the tool call.

## Answering OpenSearch Knowledge Questions

When the user asks about OpenSearch features, APIs, configuration, version history, or any general OpenSearch topic:

1. Run `opensearch_ops.py search-docs --query "<your query>"` to search opensearch.org (default).
   - Covers `docs.opensearch.org` (APIs, configuration, query DSL, plugins), `opensearch.org/blog` (release announcements, feature deep-dives), and `opensearch.org/platform`.
2. For AWS-specific questions (e.g. Amazon OpenSearch Service, Serverless, IAM policies, pricing), use `--site docs.aws.amazon.com`:
   ```bash
   uv run python scripts/opensearch_ops.py search-docs --query "OpenSearch Serverless pricing" --site docs.aws.amazon.com
   ```
3. Review the returned titles, URLs, and snippets.
4. If more detail is needed, fetch the full page content from the top result URL.
5. Summarize the answer based on the documentation.

Examples:
```bash
uv run python scripts/opensearch_ops.py search-docs --query "OpenSearch 3.5 features"
uv run python scripts/opensearch_ops.py search-docs --query "neural sparse search" --count 3
uv run python scripts/opensearch_ops.py search-docs --query "OpenSearch Service domain access policy" --site docs.aws.amazon.com
```

This applies at any point — not just during the workflow phases.

## Scripts

All operations are executed via two scripts in `scripts/` relative to this file:

- **`start_opensearch.sh`** — Start a local OpenSearch cluster via Docker
- **`opensearch_ops.py`** — CLI for all OpenSearch operations. See [CLI Reference](references/cli-reference.md) for exact invocations and examples

```bash
bash scripts/start_opensearch.sh
uv run python scripts/opensearch_ops.py <command> [options]
```

## Key Rules

- Ask **one** preference question per message.
- **Never skip Phase 1** (sample document collection).
- Show architecture proposals to the user before execution.
- Follow the phases **in order** — do not jump ahead.
- When a step fails, present the error and wait for guidance.

## Workflow Phases

### Phase 1 — Start OpenSearch & Collect Sample

Start OpenSearch, then ask the user for their data source. Use `load-sample` to load data. The output includes inferred text fields — use these to inform the plan.

If the user provides PDF, DOCX, PPTX, XLSX, or other document files (not structured data like CSV/JSON/TSV), use Docling to process them before indexing. Read `references/knowledge/document_processing_guide.md` for the full workflow. In summary:

1. Install Docling: `uv pip install docling`
2. Convert the document using Docling's `DocumentConverter` to extract structured text.
3. Chunk the output using `HybridChunker(max_tokens=512, overlap_tokens=50)`.
4. Export chunks as JSONL and use `opensearch_ops.py index-bulk` to load them.

Ask the user whether they want to process the entire document or specific page ranges.

### Phase 2 — Gather Preferences

Ask the user **one at a time**: query pattern (keyword, semantic, hybrid, agentic) and deployment preference. Skip questions that don't apply.

### Phase 3 — Plan

Design a search architecture based on sample data and preferences. Choose a strategy (`bm25`, `dense_vector`, `neural_sparse`, `hybrid`, or `agentic`), define index mappings, select ML models if needed, and specify pipelines. Read the relevant knowledge files directly for model and search pattern details:

- `references/knowledge/dense_vector_models.md`
- `references/knowledge/sparse_vector_models.md`
- `references/knowledge/opensearch_semantic_search_guide.md`
- `references/knowledge/agentic_search_guide.md`
- `references/knowledge/document_processing_guide.md` (when working with PDF/DOCX/PPTX sources)

Present the plan and wait for user approval.

### Phase 4 — Execute

Execute the approved plan step by step using `opensearch_ops.py` commands: create index, deploy model, create pipeline, index documents, launch UI. Run `opensearch_ops.py --help` for the full command reference.

### Phase 4.5 — Evaluate (Optional)

After successful execution, offer to evaluate search quality. Read `references/knowledge/evaluation_guide.md` for the evaluation methodology. Use `opensearch_ops.py search` to run test queries. If evaluation suggests improvements, offer to restart from Phase 3 with updated preferences.

### Phase 5 — Deploy to AWS (Optional)

Only if the user wants AWS deployment. Read the appropriate reference guide:

| Strategy | Target | Guide |
|---|---|---|
| `neural_sparse` | serverless | [Provision](references/aws-serverless-01-provision.md) then [Deploy](references/aws-serverless-02-deploy-search.md) |
| `dense_vector` / `hybrid` | serverless | [Provision](references/aws-serverless-01-provision.md) then [Deploy](references/aws-serverless-02-deploy-search.md) |
| `bm25` | serverless | [Provision](references/aws-serverless-01-provision.md) then [Deploy](references/aws-serverless-02-deploy-search.md) |
| `agentic` | domain | [Provision](references/aws-domain-01-provision.md) then [Deploy](references/aws-domain-02-deploy-search.md) then [Agentic](references/aws-domain-03-agentic-setup.md) |

**Required MCP servers for Phase 5:** `awslabs.aws-api-mcp-server`, `aws-knowledge-mcp-server`, `opensearch-mcp-server` (see Optional MCP Servers section above).

See [AWS Reference](references/aws-reference.md) for cost, security, and constraints.
