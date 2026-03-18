# OpenSearch Launchpad — Architecture & Design

## 1. Overview

OpenSearch Launchpad is an MCP-powered assistant that guides developers from initial
requirements to a running OpenSearch search setup. It collects a sample document,
gathers preferences (budget, performance, query pattern), plans a search architecture,
executes the plan (indices, ML models, ingest pipelines, search UI), and optionally
deploys to Amazon OpenSearch Service or Serverless.

The system is designed to work across multiple agentic IDEs — Kiro, Cursor, Claude Code,
VS Code (Copilot), and others — by leveraging the IDE's own agent rather than bundling
a custom LLM. Domain knowledge and procedures live in **steering files** (delivered as
**Agent Skills** per the open standard at agentskills.io). **MCP tools** provide
execution capabilities and workflow predictability. As agents mature, the orchestration
layer thins and steering files + external MCP servers become sufficient on their own.

---

## 2. Prerequisites

### All Phases (Local Development)

| Requirement | Version / Notes |
|-------------|----------------|
| **Python** | 3.11+ |
| **uv** | Package runner ([install](https://docs.astral.sh/uv/getting-started/installation/)) |
| **Docker** | Installed and running ([download](https://docs.docker.com/get-docker/)) |
| **opensearch-launchpad MCP server** | `uvx opensearch-launchpad@latest` (from PyPI) |

### Phase 5 Only (AWS Deployment)

| Requirement | Notes |
|-------------|-------|
| **AWS CLI** | With credentials configured (`aws configure` or env vars) |
| **IAM permissions** | OpenSearch Service, IAM, Bedrock (for semantic/agentic search) |
| **awslabs.aws-api-mcp-server** | `uvx awslabs.aws-api-mcp-server@latest` |
| **aws-knowledge MCP server** | `uvx fastmcp run https://knowledge-mcp.global.api.aws` |
| **opensearch-mcp-server** | `uvx opensearch-mcp-server-py@latest` |

All Phase 5 MCP servers must be added to the IDE's MCP configuration before starting
AWS deployment. See S5.5 for per-IDE MCP config locations.

---

## 3. Tenets

These tenets guide all architectural decisions. When in conflict, earlier tenets
take priority.

### T1. Leverage the IDE agent — never bundle your own LLM

The IDE's agent (Kiro, Claude Code, Cursor, etc.) is the orchestrator. We provide
knowledge and tools; the IDE provides reasoning. This eliminates model dependencies,
reduces cost, and lets each IDE use its best model.

### T2. Keep steering files under 500 lines

Any file loaded into an agent's context window — SKILL.md, steering files, rules
files — must stay under 500 lines. Longer files dilute attention and reduce
adherence across all platforms (Claude Code recommends < 200 lines, Cursor recommends
< 500 lines). When a file grows beyond this limit, split it using progressive
disclosure: metadata in the skill, details in reference files or MCP tool responses.

### T3. Progressive disclosure over monolithic context

Agents should load only what they need, when they need it. At startup, only skill
names and descriptions are in context (~100 tokens each). Full instructions load on
activation (< 5000 tokens recommended). Detailed references, knowledge bases, and
step-by-step procedures load on demand via MCP tool calls or reference file reads.

### T4. One domain per file

Each skill, steering file, or rule file covers exactly one concern. A file that
covers "AWS serverless provisioning" should not also cover "search UI design tokens."
This keeps files focused, testable, and within the 500-line limit.

### T5. Steering files override where external knowledge falls short

External MCP servers (AWS Knowledge, AWS API, OpenSearch MCP) are the primary knowledge
source — they provide up-to-date, authoritative documentation and APIs. The model's
training data serves as a secondary source, filling gaps with general understanding.
Steering files sit on top as an override layer for project-specific context that
neither external servers nor the model can know: our specific workflow, tool
sequencing, conventions, and edge cases. As external MCP servers cover more ground,
steering files should shrink to only what genuinely needs overriding.

### T6. Orchestration tools add predictability — design them to thin over time

Orchestration MCP tools (`prepare_aws_deployment`, `set_preferences`, etc.) exist to
keep the agent on the right track: which steering file to read, which phase we're in,
what to ask next. They compensate for current agent limitations — agents sometimes
skip steps, lose their place, or drift in long multi-phase workflows. The
orchestration layer should be as thin as possible and is expected to shrink as agents
improve. The end state is: steering files + execution tools + external MCP servers —
with orchestration becoming optional or removed entirely. Design decisions should
favor putting knowledge in steering files (durable) over encoding it in orchestration
tools (transitional).

### T7. Write once, run on any IDE

All domain knowledge lives in steering files delivered as Agent Skills (the open
standard). IDE-specific integration is a thin adapter layer. Adding support for a new
IDE should require only a configuration file and possibly a skill-to-native mapping —
never forking the core knowledge or procedures.

---

## 4. Current Architecture (Kiro Power — Released)

The Kiro Power is the released, production path. It remains fully supported while
the Agent Skills architecture (S5) is validated across IDEs.

### 4.1 How It Works

```
User <-> Kiro Agent <-> MCP Protocol <-> mcp_server.py <-> OrchestratorEngine
              |                                |
         reads POWER.md                   exposes tools
         reads steering/*.md              manages state
```

- **POWER.md** (17.5K chars, ~350 lines): Kiro reads this at session start. Contains
  the full workflow description, all tool documentation, rules, and phase instructions.
- **Steering files** (800-18K chars each): Loaded by Kiro based on `inclusion: auto`
  descriptions. Contain step-by-step AWS deployment procedures, UI design tokens, etc.
- **MCP tools**: Stateful phase tools (`load_sample`, `set_preferences`,
  `start_planning`, `execute_plan`, etc.) plus low-level OpenSearch operations.
- **OrchestratorEngine**: Transport-agnostic state machine with phases:
  `COLLECT_SAMPLE -> GATHER_INFO -> EXEC_FAILED -> DONE`.
- **Knowledge files**: Markdown guides (semantic search, dense/sparse vector models,
  agentic search) read via `read_knowledge_base` tool calls.

### 4.2 Workflow Phases

| Phase | Tools | Description |
|-------|-------|-------------|
| 1. Collect Sample | `load_sample` | Load sample doc (IMDB, file, URL, index, paste) |
| 2. Preferences | `set_preferences` | Budget, performance, query pattern, deployment |
| 3. Plan | `start_planning`, `refine_plan`, `finalize_plan` | Architecture proposal |
| 4. Execute | `execute_plan`, `retry_execution` | Create index, models, pipelines, UI |
| 4.5. Evaluate | `start_evaluation` | Optional search quality evaluation |
| 5. Deploy | `prepare_aws_deployment` | Optional AWS deployment |

---

## 5. Target Architecture (Multi-IDE via Agent Skills)

### 5.1 Why Agent Skills?

Agent Skills (agentskills.io) is an open standard originally developed by Anthropic
and now supported by 25+ tools:

- **Kiro**, **Cursor**, **Claude Code**, **VS Code (Copilot)**
- **JetBrains Junie**, **Gemini CLI**, **OpenAI Codex**, **Roo Code**
- **Goose**, **Amp**, **OpenHands**, **Databricks**, and more

Kiro supports Agent Skills natively (`.kiro/skills/`) alongside its existing Powers
and steering file systems. Skills in Kiro use the same progressive disclosure model
and can coexist with Powers for MCP integrations.

A skill is a directory with a `SKILL.md` file containing YAML frontmatter (name,
description) and markdown instructions. Skills support progressive disclosure:

1. **Discovery** (~100 tokens): name + description loaded at startup
2. **Activation** (< 5000 tokens): full SKILL.md loaded when task matches
3. **Execution** (on demand): reference files, scripts, assets loaded as needed

This maps perfectly to our needs: the workflow overview loads on activation, and
phase-specific details load on demand via reference files or MCP tool calls.

### 5.2 High-Level Architecture

```
User <-> IDE Agent <-> Agent Skills (SKILL.md + references)
              |                |
              |          references/ loaded on demand
              |
              +------> scripts/ (local execution)
              |            start_opensearch.sh, opensearch_ops.py
              |
              +------> external MCP servers (AWS deployment only)
                           opensearch-mcp-server, aws-knowledge-mcp-server
```

**Layer 1 — Agent Skills (knowledge — the durable layer)**
- Skills discovered at startup via name + description (~100 tokens each)
- Full SKILL.md loads on activation (< 500 lines)
- Reference files (procedures, domain guides) load on demand
- This is where all procedural knowledge lives: how to provision, how to deploy,
  how to configure search architectures
- The IDE agent is the orchestrator — no custom MCP server needed

**Layer 2 — Scripts (local execution)**
- `start_opensearch.sh` — start a local OpenSearch cluster via Docker
- `opensearch_ops.py` — CLI for all OpenSearch operations (create index, deploy
  model, create pipeline, index docs, launch UI, etc.)
- The IDE agent runs scripts directly based on SKILL.md instructions
- Scripts replace the custom MCP server's execution tools for the Agent Skills path

**Layer 3 — External MCP Servers (AWS deployment only)**
- `opensearch-mcp-server` — OpenSearch operations on remote clusters
- `aws-knowledge-mcp-server` — AWS documentation lookup
- `awslabs.aws-api-mcp-server` — AWS API calls for provisioning
- Only needed for Phase 5 (AWS deployment); local workflow is script-only

The Agent Skills path has no custom MCP server and no orchestration layer. The IDE
agent follows SKILL.md instructions, runs scripts for execution, and reads reference
files on demand. This is a cleaner architecture that trusts the IDE agent to maintain
workflow state — if the agent drifts, the SKILL.md rules and phase structure correct it.

### 5.3 Skill Structure

One skill, one workflow. The POWER.md workflow is also expressed as a single
Agent Skill with reference files for progressive disclosure. The Kiro Power
remains the production path until Agent Skills is validated across IDEs:

```
skills/opensearch-launchpad/
    SKILL.md                             # < 300 lines: rules, tool overview, workflow
    references/
        phase1-collect-sample.md         # Phase 1 procedures (< 500 lines each)
        phase2-preferences.md            # Phase 2 procedures
        phase3-planning.md               # Phase 3 procedures
        phase4-execution.md              # Phase 4 procedures
        phase5-aws-deployment.md         # Phase 5 overview + routing
        serverless-provision.md          # AWS serverless provisioning steps
        serverless-deploy.md             # AWS serverless search deployment
        domain-provision.md              # AWS domain provisioning steps
        domain-deploy.md                 # AWS domain search deployment
        domain-agentic.md               # AWS agentic search setup
        aws-reference.md                 # Cost, security, HA reference
```

Users install one skill. The agent activates it when the task matches, and loads
reference files on demand as the workflow progresses through phases. AWS deployment
(Phase 5) is just another phase — not a separate skill.

**Key properties:**
- Single skill, single install — no user confusion about which to choose
- `SKILL.md` stays under 500 lines (tenet T2); covers all 5 phases at overview level
- Reference files loaded on demand per phase (tenet T3)
- Each reference file covers one domain (tenet T4)
- Same skill works across Kiro, Claude Code, Cursor, VS Code, JetBrains, etc. (tenet T7)

### 5.4 SKILL.md Frontmatter

Following the agentskills.io specification:

```yaml
---
name: opensearch-launchpad
description: >
  Build OpenSearch search applications with guided architecture planning.
  Collects sample documents, gathers preferences, plans search architecture,
  and executes setup with indices, ML models, pipelines, and search UI.
  Use when the user wants to build a search app, set up OpenSearch, or
  design search architecture.
metadata:
  author: opensearch-project
  version: "1.0"
---
```

| Field | Constraint | Our usage |
|-------|-----------|-----------|
| `name` | Max 64 chars, lowercase + hyphens | `opensearch-launchpad` |
| `description` | Max 1024 chars | Workflow summary + trigger keywords |
| `compatibility` | Max 500 chars (optional) | `Requires Python 3.11+, uv, Docker` |

### 5.5 MCP Server Configuration Across IDEs

The Agent Skills spec does not include a mechanism for bundling MCP server
configuration. Each IDE handles MCP config differently:

| IDE | MCP Config Location |
|-----|-------------------|
| **Kiro** | Power `mcp.json` or `.kiro/settings/mcp.json` |
| **Claude Code** | `claude_desktop_config.json` or `--mcp` flag |
| **Cursor** | `.cursor/mcp.json` |
| **VS Code** | `.vscode/mcp.json` |

For Kiro, the full Power (`kiro/opensearch-launchpad/`) is retained with `POWER.md`,
`mcp.json`, and steering files. This is the released, production path. The Agent
Skills structure runs in parallel for other IDEs and will eventually serve Kiro as
well once validated. Kiro's docs note that "for MCP integrations, powers are usually
a better fit" — so the Power remains the primary Kiro integration.

For other IDEs, the SKILL.md body includes setup instructions telling the user how
to configure the MCP server for their IDE.

### 5.6 IDE Integration Matrix

| IDE | Skills Location | Skill Discovery | MCP Config |
|-----|----------------|-----------------|------------|
| **Kiro** | `.kiro/skills/` (future) | Power `POWER.md` + steering (current) | Power `mcp.json` |
| **Claude Code** | `.claude/skills/` | Auto or `/opensearch-launchpad` | `claude_desktop_config.json` |
| **Cursor** | `.claude/skills/` | Auto on keyword match | `.cursor/mcp.json` |
| **VS Code Copilot** | Agent Skills standard | Auto | `.vscode/mcp.json` |
| **JetBrains Junie** | Agent Skills standard | Auto | IDE MCP settings |
| **Gemini CLI** | Agent Skills standard | Auto | CLI config |

All IDEs share the same MCP server (`opensearch-launchpad` on PyPI) and the same
Agent Skills content. The only difference is the directory convention for skill
discovery (`.kiro/skills/` vs `.claude/skills/`), which can be resolved with
symlinks or by placing skills in a shared location.

### 5.7 Where Things Live (Agent Skills Path)

| Concern | Where it lives | Why |
|---------|---------------|-----|
| Procedures (how to provision, deploy, configure) | SKILL.md + references | Durable knowledge the IDE agent follows |
| Domain expertise (search architecture, model selection) | References + knowledge files | Loaded on demand per phase |
| Behavioral rules (one question per message, etc.) | SKILL.md | Shapes agent reasoning across all phases |
| Workflow routing (which phase, which file next) | SKILL.md phase structure | IDE agent tracks state; no orchestration layer |
| Local operations (create index, deploy model, start UI) | Scripts (`scripts/`) | IDE agent runs directly via bash/python |
| AWS infrastructure (provision, configure) | External MCP servers | AWS API, OpenSearch MCP, AWS Knowledge |

**Key difference from Kiro Power path:** No custom MCP server, no orchestration
engine. The IDE agent is the orchestrator, guided by SKILL.md.

---

## 6. Directory Structure

```
opensearch-launchpad/
    skills/                                 # Source of truth for Agent Skills
        opensearch-launchpad/
            SKILL.md                        # Workflow instructions (< 500 lines)
            scripts/                        # Execution scripts (IDE agent runs directly)
                start_opensearch.sh         # Start local OpenSearch via Docker
                opensearch_ops.py           # CLI for all OpenSearch operations
            references/                     # Loaded on demand per phase
                aws-serverless-01-provision.md
                aws-serverless-02-deploy-search.md
                aws-domain-01-provision.md
                aws-domain-02-deploy-search.md
                aws-domain-03-agentic-setup.md
                aws-reference.md
                knowledge/                  # Domain knowledge
                    opensearch_semantic_search_guide.md
                    dense_vector_models.md
                    sparse_vector_models.md
                    agentic_search_guide.md
    .claude/
        skills/ -> ../skills                # Symlink (Claude Code + Cursor)
    .cursor/
        skills/ -> ../skills                # Symlink (Cursor explicit)
    .kiro/
        skills/ -> ../skills                # Symlink (Kiro)
    kiro/
        opensearch-launchpad/               # Full Kiro Power (released, production)
            POWER.md                        # Workflow instructions for Kiro agent
            mcp.json                        # MCP server config (opensearch-launchpad)
            steering/                       # Step-by-step procedures for Kiro
                opensearch-workflow.md
                aws-opensearch-serverless.md
                aws-opensearch-domain.md
                oui-design-system.md
                oui-requirements.md
                aws/                        # AWS deployment sub-procedures
    opensearch_orchestrator/                # Custom MCP server (Kiro Power path only)
        mcp_server.py                       # MCP server entry point
        orchestrator_engine.py              # State machine + orchestration routing
        planning_session.py
        solution_planning_assistant.py
        worker.py
        tools.py
        opensearch_ops_tools.py
        shared.py
        handler.py
        knowledge/                          # Domain knowledge read via MCP tools
            opensearch_semantic_search_guide.md
            dense_vector_models.md
            sparse_vector_models.md
            agentic_search_guide.md
        sample_data/
        ui/
    tests/
    pyproject.toml
```

The `skills/` directory at the repo root is the single source of truth for Agent
Skills. IDE-specific directories (`.claude/skills/`, `.cursor/skills/`,
`.kiro/skills/`) symlink to it, so all IDEs read the same skill content with zero
duplication. The `opensearch_orchestrator/` module is used only by the Kiro Power
path — the Agent Skills path uses scripts instead.

---

## 7. Technical Stack

| Concern | Agent Skills Path | Kiro Power Path |
|---------|-------------------|-----------------|
| Agent orchestration | IDE-native agent | IDE-native agent |
| Knowledge delivery | Agent Skills (`SKILL.md` + references) | Kiro Power (`POWER.md` + steering) |
| Local execution | Scripts (`start_opensearch.sh`, `opensearch_ops.py`) | Custom MCP server (`opensearch-launchpad`) |
| Orchestration | None (IDE agent follows SKILL.md) | `OrchestratorEngine` state machine |
| AWS deployment | External MCP servers + AWS CLI | External MCP servers + AWS CLI |
| OpenSearch client | `opensearch-py` (via scripts) | `opensearch-py` (via MCP server) |
| Package manager | `uv` | `uv` / `uvx` |
| Distribution | Git clone (skills + scripts) | PyPI (`opensearch-launchpad`) |
| IDE integration | Kiro Power (released); Agent Skills (validating for other IDEs) |

---

## 8. FAQ

### Why Agent Skills over custom per-IDE adapters?

Agent Skills is supported by 25+ tools including all our targets: Kiro, Cursor,
Claude Code, VS Code, JetBrains, Gemini CLI, and more. Writing one SKILL.md gives us
all of these without maintaining separate `.cursorrules` and `CLAUDE.md` files with
duplicated content. The Kiro Power remains the released production path; Agent Skills
runs in parallel and will eventually unify the knowledge layer across all IDEs.

### Why keep procedures in steering files instead of MCP tool responses?

Steering files are the durable knowledge layer. Procedures (how to provision AWS,
how to configure search pipelines) are domain knowledge — they should live where
knowledge lives, not be encoded into tool implementations. MCP orchestration tools
route the agent to the right steering file at the right time, but they don't own the
content. This separation matters because:

1. Steering files are human-readable, auditable, and editable without code changes.
2. Steering files work across IDEs without tool-specific coupling.
3. As agents improve at following multi-file instructions, the orchestration tools
   can thin out without losing knowledge — it's all still in the steering files.
4. External MCP servers (AWS API, OpenSearch MCP, AWS Knowledge) already provide the
   execution surface. Steering files tell the agent how to use them.

### Why have orchestration tools at all?

Agents today lose track of where they are in multi-phase workflows. They skip steps,
batch questions that should be asked one at a time, or read the wrong steering file.
Orchestration tools (`prepare_aws_deployment`, `set_preferences`, etc.) add
predictability: they track state and route the agent to the right file at the right
time. This is a compensator for current limitations, not a permanent architectural
layer. As agents improve, these tools should be thinned or removed.

### Why not keep using a custom planner/worker LLM?

The original architecture used Strands agents with Bedrock Claude for planning and
execution. This added a model dependency, increased cost, and couldn't leverage
improvements in the IDE's own model. By delegating to the IDE agent and providing
knowledge via skills + MCP, we get better results with less complexity. Strands-based
agents remain available as fallbacks for standalone CLI mode.

### Why keep the full Kiro Power?

The Kiro Power (`POWER.md` + `mcp.json` + steering files) is the released,
production-tested path. It remains fully supported while the Agent Skills
architecture is validated across other IDEs (Claude Code, Cursor, VS Code, etc.).
The orchestrator, custom MCP server, and Kiro steering files are proven — removing
them prematurely would risk the released experience. Once Agent Skills is validated,
Kiro can transition to using Agent Skills for knowledge delivery while retaining
the Power for MCP config (which Agent Skills has no mechanism for).

### Why not use sub-agents?

Sub-agents (spawning a child agent with its own context and system prompt) are useful
when a task requires deep, isolated reasoning that would pollute the main agent's
context — e.g., "analyze these inputs and produce a structured result." The original
Strands-based planner and evaluator were effectively sub-agents.

We don't use sub-agents in the current design because:

1. **The IDE agent is capable enough.** With the right steering files and reference
   material loaded on demand, the IDE agent can handle planning, evaluation, and
   execution without needing a separate reasoning context.
2. **Sub-agents add complexity.** Each sub-agent needs its own system prompt, tool
   access, and result serialization. This is more code to maintain and debug.
3. **Sub-agents conflict with T1.** Spawning a sub-agent means either bundling a model
   (violates T1) or using client sampling, which not all IDEs support reliably.
4. **Steering files scale better.** Rather than isolating reasoning in a sub-agent, we
   load focused reference files on demand (T3). The agent gets the knowledge it needs
   for the current phase without carrying the full workflow in context.

If a future phase proves too complex for the IDE agent with steering files alone (e.g.,
a planning step that needs to reason over very large inputs), sub-agents can be
reconsidered — but the burden of proof is on the sub-agent approach to justify the
added complexity.

### Why 500 lines as the limit?

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/memory#claudemd-files) recommends < 200 lines for CLAUDE.md files
- [Cursor](https://docs.cursor.com/context/rules) recommends < 500 lines for rules files
- [Agent Skills spec](https://agentskills.io/specification) recommends < 500 lines for SKILL.md
- Kiro has no published limit, but the same principles apply

500 lines is the common upper bound. In practice, the primary instruction file
(SKILL.md) should target 200-300 lines, with 500 as the absolute ceiling.
