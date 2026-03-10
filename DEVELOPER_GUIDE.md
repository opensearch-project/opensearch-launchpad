# Developer Guide

This guide covers local development, MCP server internals, and the release process for contributors to OpenSearch Launchpad.

---

## Standalone CLI (Local Development)

Start the interactive orchestrator in a terminal:

```bash
python opensearch_orchestrator/orchestrator.py
```

The orchestrator guides you through sample collection, requirements gathering, solution planning, and execution — all in one interactive session.

---

## MCP Server

The MCP server exposes the orchestrator workflow as a set of phase tools. Any MCP-compatible client (Claude Desktop, MCP Inspector, etc.) can drive the conversation.

### Prerequisites

Install [uv](https://docs.astral.sh/uv/) (one-time, no sudo needed):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Running from PyPI

```bash
uvx opensearch-launchpad@latest
```

If installed via `pip`:

```bash
opensearch-launchpad
```

> This starts a stdio MCP server (JSON-RPC), not an interactive CLI. Launch it from an MCP client. For an interactive terminal session, use `python opensearch_orchestrator/orchestrator.py` instead.

### Running locally (dev)

```bash
uv run opensearch_orchestrator/mcp_server.py
```

`uv` reads inline script metadata and auto-installs dependencies into a cached virtual environment.

### Claude Desktop integration

1. Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "opensearch-launchpad": {
      "command": "uvx",
      "args": ["opensearch-launchpad@latest"]
    }
  }
}
```

2. Restart Claude Desktop. The `opensearch_workflow` prompt is available in the prompt picker and describes the full tool sequence.

### Generic MCP clients

Any MCP-compatible client can connect via stdio and discover tools with `tools/list`. The `opensearch_workflow` prompt (available via `prompts/list`) describes the workflow. Tool docstrings also include prerequisite hints.

### Without uv

Install dependencies manually and point to the server script:

```bash
pip install mcp opensearch-py
```

```json
{
  "mcpServers": {
    "opensearch-launchpad": {
      "command": "python3",
      "args": ["opensearch_orchestrator/mcp_server.py"],
      "cwd": "/path/to/agent"
    }
  }
}
```

---

## MCP Workflow Tools

The server exposes high-level phase tools:

| Tool | Phase | Description |
|------|-------|-------------|
| `load_sample` | 1 | Load a sample document (built-in IMDB, local file, URL, index, or paste) |
| `set_preferences` | 2 | Set budget, performance, query pattern, deployment preferences |
| `start_planning` | 3 | Start the planning agent; returns initial architecture proposal |
| `refine_plan` | 3 | Send user feedback to refine the proposal |
| `finalize_plan` | 3 | Finalize the plan when the user confirms |
| `set_plan_from_planning_complete` | 3 | Parse/store a `<planning_complete>` planner response |
| `execute_plan` | 4 | Return worker bootstrap payload for execution |
| `set_execution_from_execution_report` | 4 | Parse/store `<execution_report>` and update retry state |
| `retry_execution` | 4 | Return resume bootstrap payload from last failed step |
| `prepare_aws_deployment` | 5 | Return deployment target and steering files for AWS |
| `connect_search_ui_to_endpoint` | 5 | Switch Search UI to query an AWS OpenSearch endpoint after deployment |
| `cleanup` | Post | Remove test documents on user request |

The following execution/knowledge tools are also exposed:
`create_index`, `create_and_attach_pipeline`, `create_bedrock_embedding_model`,
`create_local_pretrained_model`, `apply_capability_driven_verification`,
`launch_search_ui`, `set_search_ui_suggestions`, `read_knowledge_base`,
`read_dense_vector_models`, `read_sparse_vector_models`, `search_opensearch_org`.

Advanced tools are hidden by default; set `OPENSEARCH_MCP_ENABLE_ADVANCED_TOOLS=true` to expose them.

### Localhost index auth (`source_type="localhost_index"`)

| Mode | Behavior |
|------|----------|
| `"default"` | Username `admin`, password `myStrongPassword123!` |
| `"none"` | No authentication |
| `"custom"` | Requires `localhost_auth_username` + `localhost_auth_password` |

Local Docker auto-bootstrap uses `admin` and reads the password from `OPENSEARCH_PASSWORD` (falls back to `myStrongPassword123!`).

### Planner backend in MCP mode

- Planning uses client sampling (client LLM only — no server-side Bedrock in MCP mode).
- If the client does not support `sampling/createMessage`, `start_planning` returns `manual_planning_required=true` with `manual_planner_system_prompt` and `manual_planner_initial_input`. Run planner turns with your LLM and call `set_plan_from_planning_complete(planner_response)`.

---

## Release Process

Releases are handled automatically by GitHub CI when a git tag is pushed. To cut a new release:

1. **Bump the version** in both files to the same value (e.g. `0.10.1`):
   - `pyproject.toml` — `[project].version`
   - `opensearch_orchestrator/__init__.py` — `__version__`

2. **Verify versions match** (optional sanity check):
   ```bash
   python -c "import tomllib; p=tomllib.load(open('pyproject.toml','rb')); import opensearch_orchestrator as pkg; print('pyproject=', p['project']['version'], 'package=', pkg.__version__)"
   ```

3. **Run tests**:
   ```bash
   uv run pytest -q
   ```

4. **Commit, tag, and push**:
   ```bash
   git add pyproject.toml opensearch_orchestrator/__init__.py
   git commit -m "Bump version to 0.10.1"
   git tag v0.10.1
   git push origin main --tags
   ```

   CI will automatically build and publish the package to PyPI.
