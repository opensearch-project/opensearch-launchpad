# OpenSearch Solution Architect — Design Document

## 1. Overview

This system is an MCP-powered assistant that guides users from initial requirements to a running OpenSearch search setup. It collects a sample document, gathers preferences (budget, performance, query pattern), plans a search architecture using an AI planner agent, and executes the plan to create indices, ML models, ingest pipelines, and a local search UI — with optional deployment to Amazon OpenSearch Service or Serverless.

The system is delivered as a **Kiro Power** (`POWER.md` + `mcp.json`) backed by a published Python MCP server package (`opensearch-launchpad` on PyPI).

---

## 2. Architecture

### 2.1 Entry Points

| Mode | How it runs |
|------|-------------|
| **Kiro Power (published)** | `mcp.json` runs `uvx opensearch-launchpad@latest` |
| **Local dev** | `.kiro/settings/mcp.json` runs `uv run opensearch_launchpad/mcp_server.py` |

The Kiro AI reads `POWER.md` for workflow instructions and calls MCP tools exposed by `mcp_server.py` over stdio.

### 2.2 Core Modules

#### `mcp_server.py` — MCP Server
- Entry point. Exposes all workflow tools to the Kiro agent via the MCP protocol.
- Manages stateful workflow progression through `OrchestratorEngine`.
- Persists state to disk for cross-session resumption.

#### `orchestrator_engine.py` — Transport-Agnostic State Machine
- Phase-based state machine: `COLLECT_SAMPLE → PREFERENCES → PLANNING → EXECUTION`.
- Contains no transport-specific code — used by both the MCP server and the local CLI.

#### `orchestrator.py` — Local CLI Agent
- Strands-based interactive terminal agent wrapping `OrchestratorEngine`.
- For local development and testing only (not used in the published MCP server path).

#### `planning_session.py` — Planning Session
- Manages the plan → refine → finalize cycle.
- Drives the `solution_planning_assistant` sub-agent and processes its structured output.

#### `solution_planning_assistant.py` — Architecture Planner Sub-Agent
- Strands sub-agent acting as a senior search architect.
- Reads knowledge base guides (`read_knowledge_base`, `read_dense_vector_models`, etc.).
- Produces a structured `<conclusion>` with retrieval strategy, index variant, and model deployment options.

#### `worker.py` — Execution Sub-Agent
- Strands sub-agent acting as an automation engineer.
- Receives the finalized plan and executes index creation, model registration, pipeline setup, and UI launch.
- Reports a structured execution summary consumed by `mcp_server.py`.

#### `tools.py` — Sample & Knowledge Tools
- Sample document loading: `load_sample` (built-in IMDB, local file, URL, localhost index, paste).
- Knowledge base reading: `read_knowledge_base`, `read_dense_vector_models`, `read_sparse_vector_models`, `read_agentic_search_guide`.
- Web search: `search_opensearch_org` (DuckDuckGo site-restricted to opensearch.org).

#### `opensearch_ops_tools.py` — Low-Level OpenSearch Operations
- Index management: `create_index`, `index_doc`, `index_verification_docs`, `cleanup_docs`.
- ML models: `create_bedrock_embedding_model`, `create_local_pretrained_model`.
- Pipelines: `create_and_attach_pipeline`.
- Agentic search: `create_bedrock_agentic_model`, `create_agentic_search_agent`, `create_agentic_search_pipeline`.
- Search UI: `launch_search_ui`, `set_search_ui_suggestions`, `cleanup_ui_server` — serves static React frontend at `http://127.0.0.1:8765`.
- Capability verification: `apply_capability_driven_verification`, `preview_cap_driven_verification`.
- Docker: auto-starts a local OpenSearch container if no cluster is reachable.

#### `shared.py` — Shared Utilities
- `Phase` enum, conversation state helpers, input parsing utilities.

#### `handler.py` — Thinking Callback Handler
- Handles streaming and thinking-block output from Strands agents.

---

## 3. Workflow Phases

The workflow is driven by the Kiro AI reading `POWER.md`. Each phase calls specific MCP tools:

### Phase 1 — Collect Sample Document
- Mandatory first step before any planning or execution.
- Tool: `load_sample(source_type, source_value, ...)`
- Sources: `builtin_imdb` | `local_file` | `url` | `localhost_index` | `paste`
- Returns inferred text fields and `text_search_required` flag.

### Phase 2 — Gather Preferences
- Tools: `set_preferences(budget, performance, query_pattern, deployment_preference)`
- Questions asked one at a time: query pattern, performance priority, budget, deployment preference.
- Skips irrelevant questions based on sample analysis (e.g., skips semantic questions if `text_search_required=false`).

### Phase 3 — Plan
- Tools: `start_planning()`, `refine_plan(user_feedback)`, `finalize_plan()`
- `start_planning` may return `manual_planning_required=true`, in which case the AI drives planning via `set_plan_from_planning_complete`.
- The planner sub-agent (`solution_planning_assistant`) reads knowledge base guides and produces a structured architecture proposal.

### Phase 4 — Execute
- Tools: `execute_plan()`, `retry_execution()`
- The worker sub-agent creates OpenSearch resources: index, ML model, ingest pipeline, verification docs, search UI.
- On failure, the user can fix the issue and call `retry_execution()`.

### Phase 5 — Deploy to AWS (optional)
- Tool: `prepare_aws_deployment()` — returns deployment target, steering files, and state template.
- Requires AWS MCP servers (`awslabs.aws-api-mcp-server`, `opensearch-mcp-server`, `aws-docs`).
- Follows steering files in `steering/` for serverless or domain deployment tracks.

---

## 4. Supporting Assets

| Path | Purpose |
|------|---------|
| `opensearch_launchpad/knowledge/` | Markdown guides read by the planner (semantic search, dense/sparse vector models, agentic search) |
| `opensearch_launchpad/sample_data/` | Built-in IMDB dataset (`imdb.title.basics.tsv`) |
| `opensearch_launchpad/ui/search_builder/` | Static React frontend served by the local UI server |
| `steering/` | AWS deployment step-by-step instructions (serverless and domain tracks) |
| `local/` | Local-only Strands agents for development and testing |

---

## 5. Technical Stack

| Concern | Technology |
|---------|-----------|
| Agent framework | `strands-agents` |
| MCP server | `fastmcp` (via `mcp` package) |
| Model service | AWS Bedrock |
| Planning/execution model | Claude Sonnet (extended thinking enabled) |
| OpenSearch client | `opensearch-py` |
| Package manager | `uv` / `uvx` |
| Distribution | PyPI (`opensearch-launchpad`) |
| IDE integration | Kiro Power (`POWER.md` + `mcp.json`) |
