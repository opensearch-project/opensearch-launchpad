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
| `start_evaluation` | 4.5 | Execute verification queries, compute metrics, and run LLM evaluation |
| `set_relevance_judgments` | 4.5 | Store manual LLM relevance judgments; call when `manual_judgment_required=true` |
| `set_evaluation_from_evaluation_complete` | 4.5 | Parse/store `<evaluation_complete>` evaluator response |
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

### Data-driven evaluation (Phase 4.5)

After execution, `start_evaluation` runs a data-driven pipeline using phased helpers on an `EvaluationState` object before the LLM scores anything:

1. `_fetch_evaluation_inputs` — resolves `index_name` and loads `suggestion_meta` from verification capture
2. `_execute_searches` — calls `run_data_driven_evaluation_pipeline()` which executes each verification query against the live index and pre-builds the LLM judgment prompt in a single call; both `query_results` and `judgment_prompt` are stored on state
3. `_judge_relevance` — reuses the judgment prompt from step 2; on success, calls `process_relevance_judgments()` which parses the LLM response, computes metrics (P@5, P@10, MRR, per-capability breakdown, failure rate), and formats the evidence text — all in one call; results are cached on `EvaluationState.evidence_text`
4. `_evaluate_quality` — builds the evaluation prompt using cached `evidence_text` from state (no re-computation), then the LLM evaluator produces dimension scores grounded in actual per-query data, plus categorized improvement suggestions tagged with `[INDEX_MAPPING]`, `[EMBEDDING_FIELDS]`, `[MODEL_SELECTION]`, `[SEARCH_PIPELINE]`, or `[QUERY_TUNING]`
5. `_render_evaluation_response` — calls `build_evaluation_attachments()` to guarantee `evaluation_result_table` is always present (falls back to an explanatory message when data-driven results are unavailable)

The MCP server imports three facade functions from `opensearch_ops_tools.py` for the evaluation pipeline: `run_data_driven_evaluation_pipeline`, `process_relevance_judgments`, and `build_evaluation_attachments`. Lower-level functions (`execute_evaluation_queries`, `build_relevance_judgment_prompt`, `parse_relevance_judgment_response`, `compute_evaluation_metrics`, `format_evaluation_evidence`) remain internal to `opensearch_ops_tools.py`.

When client sampling is unavailable, `start_evaluation` returns `manual_judgment_required=true` with the judgment prompt. The Kiro agent judges relevance and calls `set_relevance_judgments()`, which also uses `process_relevance_judgments()` to parse, compute, and cache results on state. Then `start_evaluation` is called again to complete the evaluation with pre-stored judgments.

If the client doesn't support `sampling/createMessage` for the evaluator step, `start_evaluation` returns `manual_evaluation_required=true` with the evaluation prompt. Run it with your LLM and call `set_evaluation_from_evaluation_complete(evaluator_response)`.

---

## Testing

All tests live in the `tests/` directory and run with [pytest](https://docs.pytest.org/) via `uv`:

```bash
uv run pytest -q
```

### Test categories

| Category | File pattern | What it covers |
|----------|-------------|----------------|
| MCP server / orchestrator | `test_mcp_*.py`, `test_orchestrator_*.py` | MCP tool dispatch, planner/worker flows, evaluation pipeline |
| Agent Skills (standalone scripts) | `test_agent_skills_*.py` | `skills/opensearch-launchpad/scripts/lib/` — client, operations, samples, search |
| Shared logic | `test_mapping_*.py`, `test_search_ui_*.py`, `test_worker_*.py`, etc. | Mapping guardrails, query routing, hybrid weights, UI query routing |

### Running a subset

```bash
# Only Agent Skills tests
uv run pytest tests/test_agent_skills_*.py -v

# Only MCP tests
uv run pytest tests/test_mcp_*.py -v

# Single file
uv run pytest tests/test_agent_skills_search.py -v
```

### Writing new tests

- Tests must not require a running OpenSearch cluster. Use fake/mock clients (see existing `_FakeClient` patterns).
- Agent Skills tests import from `skills/opensearch-launchpad/scripts/lib/` by inserting the scripts directory onto `sys.path` (see `test_agent_skills_client.py` for the pattern).
- MCP/orchestrator tests import from `opensearch_orchestrator/` using the standard `sys.path.insert(0, ...)` pointing to the repo root.

### CI

GitHub Actions runs the full test suite (`uv run pytest -q`) on every push and PR across Linux, macOS, and Windows. See `.github/workflows/ci.yml`.

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
