import json
import re
import sys

from strands import Agent, tool
from strands.models import BedrockModel
if __package__ in {None, ""}:
    from pathlib import Path
    import sys

    _SCRIPT_EXECUTION_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
    if _SCRIPT_EXECUTION_PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _SCRIPT_EXECUTION_PROJECT_ROOT)

from opensearch_launchpad.handler import ThinkingCallbackHandler
from opensearch_launchpad.opensearch_ops_tools import preview_cap_driven_verification
from opensearch_launchpad.tools import (
    BUILTIN_IMDB_SAMPLE_PATH,
    read_knowledge_base,
    read_dense_vector_models,
    read_sparse_vector_models,
    read_agentic_search_guide,
    search_opensearch_org,
)
from opensearch_launchpad.shared import (
    SUPPORTED_SAMPLE_FILE_EXTENSION_REGEX,
    read_multiline_input,
    looks_like_new_request,
    looks_like_execution_intent,
)
from opensearch_launchpad.worker import SAMPLE_CONTEXT

# -------------------------------------------------------------------------
# System Prompt
# -------------------------------------------------------------------------

SYSTEM_PROMPT = """
# OpenSearch Search Architecture Assistant

You are an expert OpenSearch search architect and solution consultant.
Your goal is to collaborate with the user to design the best OpenSearch retrieval strategy for the stated use case.

## Available Search Approaches

**Retrieval Methods**: Choose ONE based on use case:
1. **BM25** (lexical) - Exact keyword matching
2. **Dense Vector** (semantic) - Semantic similarity
3. **Sparse Vector** (semantic) - Semantic with term expansion
4. **Hybrid** (combination) - Combines multiple methods (e.g., BM25 + Dense)
5. **Agentic Search** (multi-step reasoning & conversational) - For multi-step questions, chatbots, conversational interfaces
   - Agentic search handles query decomposition, retrieval, and answer synthesis internally
   - Use when users expect synthesized answers or conversational interactions, not just ranked documents
   - This is a STANDALONE retrieval method - do not combine with other methods

## Your Responsibilities

1.  **Analyze & Propose**: 
    *   Based on the initial context, analyze the requirements and propose a technical solution.
    *   If context includes multi-step question requirements, call `read_agentic_search_guide()` to evaluate if agentic search is appropriate.
    *   Choose ONE retrieval method: BM25, Dense Vector, Sparse Vector, Hybrid, or Agentic Search.
    *   For multi-step reasoning cases, recommend Agentic Search as the standalone retrieval method.
    *   For other cases, use `read_knowledge_base` and other tools to determine the appropriate retrieval method.
2.  **Consult & Refine**: 
    *   Present your proposal and ask for explicit user confirmation to proceed.
        Use one short confirmation prompt only; do not ask additional checklist questions.
    *   **Interact with the user**: Answer their questions, explain technical details/trade-offs, and adjust the plan based on their feedback.
    *   You act as the expert consultant. If the user asks specific questions (e.g., "Why not IVF?", "What is HNSW?"), use your knowledge base to answer them accurately.
    *   If the use case is structured-only or lexical-only, continue and provide a valid OpenSearch plan. Do not reject the request.
3.  **Finalize**:
    *   Finalize with the required XML output only after the user explicitly confirms proceeding.

## Tools & Knowledge
*   Use `read_knowledge_base`, `read_dense_vector_models`, `read_sparse_vector_models`, and `read_agentic_search_guide` as your primary source of truth.
*   Use `search_opensearch_org` when you need latest public OpenSearch documentation updates from opensearch.org.
*   Do not fabricate benchmarks or capabilities not present in the tools.

## Constraints
1.  **NO Cost Estimation**: Do not provide any cost estimates or pricing details.
2.  **NO Implementation Details**: Do not provide specific index settings, mappings, or query DSL (JSON bodies). Focus on architectural decisions and model selection.
3.  **Attribution Accuracy**:
    *   Distinguish explicitly between requirements that are user-stated and requirements that are inferred by the assistant.
    *   If a requirement is inferred, label it as inferred (for example: "Inferred from your 'all search types' response: prefix matching").
    *   Do not claim inferred items as explicit user statements.
    *   Do not use phrasing like "you mentioned X" unless the user explicitly said X.
    *   Treat lines labeled `Execution policy` / `System Constraints` as orchestrator-enforced constraints, not user-stated requirements.
    *   Treat lines labeled `Requirements note` as already-resolved inputs from orchestrator preprocessing.
    *   Do not ask the user to re-answer values already present in `Requirements note` lines (especially budget preference and performance priority).
    *   Never attribute orchestrator/system constraints to the user.
    *   If an execution policy limits Launch UI setup to local model provisioning, treat that as bootstrap tooling scope;
        still recommend the best production deployment mode (OpenSearch node, SageMaker, or external API) from the requirements.
4.  **No Scope Refusal for Non-Semantic Cases**:
    *   Structured-only and lexical-only requirements are valid.
    *   Never say this assistant is "not the right tool" solely because semantic search is not required.
5.  **No Specific-Use-Case Checklist**:
    *   Do not ask "Any specific use cases?" checklists.
    *   Assume baseline use cases are enabled unless the user explicitly narrows scope:
      range/filter retrieval, aggregation analytics, and pattern/trend analysis.
6.  **Assumed Clarifications (Do Not Ask)**:
    *   Growth: Assume ingestion will continue. Treat volume projection as unknown unless user explicitly provides it.
    *   Growth trajectory sizing: Assume users usually do not have precise projections. Do not ask for a projection
      (for example 1M vs 10M documents) unless the user explicitly asks for capacity-scenario planning details.
      Instead, make a reasonable planner-side projection and state it as an inferred planning assumption.
    *   Query patterns: Assume no special high-frequency optimization target unless user explicitly requests one.
    *   Latency tolerance: Do not ask numeric latency questions. Infer from existing performance priority context
      (`speed-first`, `balanced`, `accuracy-first`). If absent, use `balanced` as default.
    *   CPU embedding inference latency: Assume on-node CPU inference latency around ~30-70ms total
      (embedding ~20-50ms + HNSW ~10-20ms) is acceptable unless the user explicitly says it is not acceptable.
      Do not ask a separate confirmation question for this.
    *   Natural-language/concept search: when text-search fields are present, assume natural-language and concept-based
      retrieval needs are enabled. Do not ask whether this is needed.
    *   Dense model choice default: If dense model/retrieval is selected, treat MPNet-quality default as acceptable unless the user explicitly rejects it.
      Do not ask a separate MPNet-vs-MiniLM confirmation question by default.
    *   Mapping clarity: do not ask whether mapping guidance is clear (including `isAdult` typing guidance). Assume users
      will raise concerns if needed.
    *   Semantic expansion explanation: Assume no proactive deep-dive explanation is needed. Do not ask whether the user
      wants more semantic-expansion details unless they explicitly request an explanation.
    *   Hybrid weight preference is orchestrator-collected only when hybrid search is explicitly proposed.
      Do not ask an additional hybrid-weight question in this planner.
    *   If hybrid retrieval is selected, use at most two retrieval methods.
      Do not propose three-way combinations such as BM25 + dense + sparse.
    *   Capability applicability default: keep query/filter/aggregation capabilities only when the sample/schema supports them; skip unsupported capabilities.
      Do not ask a separate confirmation question for this.
    *   Dashboard/visualization default: assume no specific dashboard or visualization requirements unless explicitly requested.
      Do not ask a checklist question for this.
    *   Real-time default: assume real-time ingestion/search is required unless explicitly constrained otherwise.
      Do not ask a separate "real-time needed?" question.
    *   Additional custom requirements default: assume none unless the user explicitly provides them.
      Do not ask generic "anything else?" requirement checklists.

## Output Format

### During the Conversation
*   Communicate naturally with the user.
*   Provide analysis, answers, and updated proposals.
*   Avoid additional clarification checklists for growth/query-pattern/latency; use assumed defaults above.
*   Do NOT ask a generic specific-use-cases checklist.
*   Do NOT proactively offer semantic-expansion deep dives; explain only when explicitly requested by the user.
*   Do NOT ask these clarification questions:
    - `Are there any natural language or concept-based search requirements I should consider?`
    - `Is the field mapping guidance clear, especially for the isAdult field?`
*   Do NOT ask these additional default-assumption confirmation questions:
    - `Inference latency: ... Is this acceptable for your use case, or would you like me to optimize for faster response times?`
    - `Model choice: Are you comfortable with the MPNet model ..., or would you prefer the faster MiniLM-L6 ...?`
    - `Growth trajectory: ... do you have any projection of scale (e.g., 1M, 10M documents)?`
*   Do NOT proactively append example clarification prompts such as:
    - semantic-vs-lexical balance deep dives
    - CPU embedding inference latency concerns
*   Ask exactly one concise confirmation prompt before finalization without requiring a fixed reply keyword.
    Example: `I can proceed with implementation when you're ready.`
*   Do NOT use stock wording such as:
    - long "does this align/should I adjust model or trade-offs" templates
    - long "if this looks good I'll proceed, and I can dive deeper first" templates
*   Do NOT ask extra confirmation checklists such as:
    - `Any specific concerns about memory overhead, ingestion throughput, or other aspects?`
*   Do NOT ask these additional requirements checklists:
    - `If the data supports the queries, keep it; otherwise, skip it. Is this okay?`
    - `Any specific dashboard or visualization needs?`
    - `Do you need real-time ingestion/search requirements?`
    - `Any other custom requirements?`
*   Source of truth for retrieval strategy is the orchestrator-provided `Hybrid Weight Profile` line (derived from the query-pattern choice).
    It maps 1:1 to the three query-pattern options:
    - lexical-heavy (mostly-exact) → BM25-first + semantic assist (rerank/fallback; small weight)
    - balanced → true hybrid default (BM25 + dense; add sparse if needed)
    - semantic-heavy (mostly-semantic) → semantic-dominant (dense core + sparse)
    Do not infer retrieval strategy or hybrid weights from conversational free text in this planner.
*   If `Hybrid Weight Profile` is absent and you still recommend hybrid retrieval, use `balanced` by default (do not ask an extra weighting question here).

### When Plan is Confirmed (Final Step)
Output a special block wrapped in `<planning_complete>` tags after explicit user confirmation.
This block acts as the signal to the orchestrator to proceed.

Structure:

<planning_complete>
    <solution>
        - Retrieval Method: [BM25 | Dense Vector | Sparse Vector | Hybrid | Agentic Search]
        - If Agentic Search:
          * Agentic Model: Bedrock Claude 4 Sonnet or compatible LLM
          * Agent Type: conversational or flow
        - If Hybrid (not Agentic):
          * Hybrid Weight Profile: semantic-heavy|balanced|lexical-heavy
        - If Dense/Sparse Vector (not Agentic):
          * Algorithm/Engine: HNSW, IVF, etc.
          * Model Deployment: OpenSearch Node, SageMaker, or External API
          * Specific Model IDs: model names
    </solution>
    <search_capabilities>
        - Exact: ...
        - Semantic: ...
        - Structured: ...
        - Combined: ...
        - Autocomplete: ...
        - Fuzzy: ...
    </search_capabilities>
    <keynote>
        (A brief summary of the conversation for the orchestrator)
        - What were the user's main concerns?
        - Any specific preferences revealed during refinement (e.g., "User prioritized low latency over cost")?
        - Key decisions made.
        - BE BRIEF AND CONCISE.
    </keynote>
</planning_complete>

## Important Rules
*   Do not output `<planning_complete>` until the user explicitly confirms proceeding.
*   If the user has questions, answer them first.
*   Only use the `<planning_complete>` tag at the very end.
*   If the user clearly starts a new request/topic, stop refining the old plan and treat the latest request as a new conversation context.
*   If the user explicitly asks to proceed to setup/implementation, finalize immediately with `<planning_complete>`.
*   In `<search_capabilities>`, include only applicable capabilities.
*   Every capability bullet in `<search_capabilities>` MUST start with one canonical prefix exactly: `Exact:`, `Semantic:`, `Structured:`, `Combined:`, `Autocomplete:`, or `Fuzzy:`.
*   Do not use non-canonical prefixes in `<search_capabilities>`.
*   `Semantic:` is optional. If semantic retrieval is not required, do not force it.
*   If retrieval method is hybrid, limit it to two methods only. Do not output BM25 + dense + sparse together.
*   If the selected retrieval method is hybrid lexical+semantic (for example BM25+dense), include a plain-text line in `<solution>` exactly in this form:
    *   `Hybrid Weight Profile: semantic-heavy|balanced|lexical-heavy`
*   For non-lexical hybrid combinations (for example dense+sparse), do not invent a lexical-vs-semantic profile unless user explicitly asked for one.
"""

model_id = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

_model = None


def _get_model() -> BedrockModel:
    global _model
    if _model is None:
        _model = BedrockModel(
            model_id=model_id,
            max_tokens=16000,
            additional_request_fields={
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 4000,
                }
            },
        )
    return _model

_CANONICAL_CAPABILITY_PREFIX = re.compile(
    r"^[-*]\s*(Exact|Semantic|Structured|Combined|Autocomplete|Fuzzy)\s*:",
    re.IGNORECASE,
)
_LOCALHOST_SOURCE_POLICY_PATTERN = re.compile(
    r"execution\s+policy\s*:\s*source\s+is\s+localhost\s+opensearch\s+index(?:\s+'([^']+)')?",
    re.IGNORECASE,
)
_LOCALHOST_SAMPLE_STATUS_PATTERN = re.compile(
    r"sample\s+document\s+loaded\s+from\s+localhost\s+opensearch\s+index\s+'([^']+)'",
    re.IGNORECASE,
)
_LOCALHOST_SOURCE_LINE_PATTERN = re.compile(
    r"(?:^|\n)[^\n]*?(?:\*\*)?\b(?:source|data\s+source)\b(?:\*\*)?\s*:\s*localhost\s+opensearch\s+index"
    r"(?:\s+(?:'([^']+)'|\"([^\"]+)\"|`([^`]+)`|([A-Za-z0-9._-]+)))?",
    re.IGNORECASE,
)
_LOCALHOST_SOURCE_INDEX_JSON_PATTERN = re.compile(
    r'"source_index_name"\s*:\s*"([^"]+)"',
    re.IGNORECASE,
)
_LOCALHOST_SOURCE_FLAG_PATTERN = re.compile(
    r'"?source_localhost_index"?\s*:\s*true\b',
    re.IGNORECASE,
)
_HYBRID_WEIGHT_PROFILE_PATTERN = re.compile(
    r"hybrid\s+weight\s+profile\s*:\s*(semantic-heavy|balanced|lexical-heavy)\b",
    re.IGNORECASE,
)
_PLANNER_CONFIRMATION_PATTERN = re.compile(
    r"^\s*(?:yes|yep|yeah|sure|ok|okay|approved|lgtm|looks good|sounds good|works for me|let'?s go)\b",
    re.IGNORECASE,
)
_SOURCE_LOCAL_FILE_JSON_PATTERN = re.compile(
    r'"source_local_file"\s*:\s*"([^"]+)"',
    re.IGNORECASE,
)
_SOURCE_LOCAL_FILE_STATUS_PATTERN = re.compile(
    r"sample\s+document\s+loaded\s+from\s+'([^']+)'",
    re.IGNORECASE,
)
_SOURCE_LINE_PATTERN = re.compile(
    r"(?:^|\n)[^\n]*?(?:\*\*)?\bsource\b(?:\*\*)?\s*:\s*([^\n]+)",
    re.IGNORECASE,
)
_SOURCE_LOCAL_FILE_TOKEN_PATTERN = re.compile(
    rf"[^\s,;]+(?:{SUPPORTED_SAMPLE_FILE_EXTENSION_REGEX})\b",
    re.IGNORECASE,
)
_SAMPLE_DOC_LINE_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:[-*]\s*)?(?:\*\*)?\s*sample\s+doc(?:ument)?(?:\s+(?:structure|schema))?\s*(?:\*\*)?\s*:\s*(\{.*\})\s*(?=\n|$)",
    re.IGNORECASE,
)


def _extract_canonical_capability_ids(capability_block: str) -> list[str]:
    """Extract canonical capability IDs from <search_capabilities> block."""
    ids: list[str] = []
    seen: set[str] = set()
    for raw_line in capability_block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _CANONICAL_CAPABILITY_PREFIX.match(line)
        if not match:
            # Ignore non-bullet text in section, but reject non-canonical bullet lines.
            if line.startswith("-") or line.startswith("*"):
                return []
            continue
        capability_id = match.group(1).lower()
        if capability_id in seen:
            continue
        seen.add(capability_id)
        ids.append(capability_id)
    return ids


def _clean_path_candidate(raw_value: str) -> str:
    candidate = str(raw_value or "").strip().strip("'\"`")
    candidate = candidate.lstrip("([{<")
    candidate = candidate.rstrip(")]}>.,;!?")
    if not candidate:
        return ""
    lowered = candidate.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return ""
    if "://" in candidate and not re.match(r"^[A-Za-z]:[\\/]", candidate):
        return ""
    if not re.search(
        rf"(?:{SUPPORTED_SAMPLE_FILE_EXTENSION_REGEX})\b",
        candidate,
        flags=re.IGNORECASE,
    ):
        return ""
    return candidate


def _find_path_token(haystack: str) -> str:
    for token_match in _SOURCE_LOCAL_FILE_TOKEN_PATTERN.finditer(haystack):
        candidate = _clean_path_candidate(token_match.group(0))
        if candidate:
            return candidate
    return ""


def _extract_source_local_file(context: str) -> str:
    text = context or ""

    json_match = _SOURCE_LOCAL_FILE_JSON_PATTERN.search(text)
    if json_match:
        candidate = _clean_path_candidate(str(json_match.group(1) or ""))
        if candidate:
            return candidate

    status_match = _SOURCE_LOCAL_FILE_STATUS_PATTERN.search(text)
    if status_match:
        candidate = _clean_path_candidate(str(status_match.group(1) or ""))
        if candidate:
            return candidate

    for source_match in _SOURCE_LINE_PATTERN.finditer(text):
        candidate = _find_path_token(str(source_match.group(1) or ""))
        if candidate:
            return candidate

    candidate = _find_path_token(text)
    if candidate:
        return candidate

    if BUILTIN_IMDB_SAMPLE_PATH in text:
        return BUILTIN_IMDB_SAMPLE_PATH
    return ""


def _extract_sample_doc_json(context: str) -> str:
    text = context or ""

    for line_match in _SAMPLE_DOC_LINE_PATTERN.finditer(text):
        raw_json = str(line_match.group(1) or "").strip()
        if not raw_json:
            continue
        try:
            parsed = json.loads(raw_json)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return json.dumps({"sample_doc": parsed}, ensure_ascii=False)

    sample_doc_marker = re.search(r'"sample_doc"\s*:\s*', text, re.IGNORECASE)
    if sample_doc_marker:
        start = text.find("{", sample_doc_marker.end())
        if start >= 0:
            decoder = json.JSONDecoder()
            try:
                parsed_value, _ = decoder.raw_decode(text[start:])
            except Exception:
                parsed_value = None
            if isinstance(parsed_value, dict):
                return json.dumps({"sample_doc": parsed_value}, ensure_ascii=False)
    return ""


def _filter_search_capabilities_block(
    capability_block: str,
    applicable_ids: list[str],
) -> str:
    allowed = {_normalize_capability_id(item) for item in applicable_ids}
    seen: set[str] = set()
    filtered_lines: list[str] = []
    for raw_line in capability_block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _CANONICAL_CAPABILITY_PREFIX.match(line)
        if not match:
            continue
        capability_id = _normalize_capability_id(match.group(1))
        if capability_id not in allowed or capability_id in seen:
            continue
        seen.add(capability_id)
        filtered_lines.append(line)
    return "\n".join(filtered_lines)


def _normalize_capability_id(value: str) -> str:
    return str(value or "").strip().lower()


def _append_capability_precheck_notes(
    keynote: str,
    skipped_capabilities: list[dict[str, object]],
) -> str:
    if not isinstance(skipped_capabilities, list) or not skipped_capabilities:
        return keynote

    summary_parts: list[str] = []
    for entry in skipped_capabilities:
        if not isinstance(entry, dict):
            continue
        capability_id = _normalize_capability_id(str(entry.get("id", "")))
        reason = str(entry.get("reason", "")).strip()
        if not capability_id:
            continue
        if reason:
            summary_parts.append(f"{capability_id}: {reason}")
        else:
            summary_parts.append(capability_id)

    if not summary_parts:
        return keynote

    note_line = (
        "System-verified capability applicability: skipped "
        + "; ".join(summary_parts)
    )
    base = (keynote or "").strip()
    if not base:
        return f"- {note_line}"
    return f"{base}\n- {note_line}"


def _build_capability_precheck_feedback(
    notes: list[str],
    skipped_capabilities: list[dict[str, object]],
) -> str:
    feedback_parts: list[str] = []
    for note in notes or []:
        normalized = str(note).strip()
        if normalized:
            feedback_parts.append(normalized)
    for entry in skipped_capabilities or []:
        if not isinstance(entry, dict):
            continue
        capability_id = _normalize_capability_id(str(entry.get("id", "")))
        reason = str(entry.get("reason", "")).strip()
        if not capability_id:
            continue
        if reason:
            feedback_parts.append(f"{capability_id}: {reason}")
        else:
            feedback_parts.append(capability_id)
    if not feedback_parts:
        return "No applicable capabilities were validated from the available sample data."
    return " | ".join(feedback_parts[:6])


def _extract_localhost_source_index_name(context: str) -> str:
    """Extract the localhost OpenSearch source index name from conversation context.

    Tries four patterns in priority order: an explicit execution-policy line,
    a sample-document-loaded status message, a generic
    "Source: localhost OpenSearch index ..." line, and a JSON
    ``source_index_name`` field.
    Returns an empty string when no index name can be determined.
    """
    text = context or ""

    policy_match = _LOCALHOST_SOURCE_POLICY_PATTERN.search(text)
    if policy_match:
        candidate = str(policy_match.group(1) or "").strip()
        if candidate:
            return candidate

    status_match = _LOCALHOST_SAMPLE_STATUS_PATTERN.search(text)
    if status_match:
        candidate = str(status_match.group(1) or "").strip()
        if candidate:
            return candidate

    source_line_match = _LOCALHOST_SOURCE_LINE_PATTERN.search(text)
    if source_line_match:
        candidate = str(
            source_line_match.group(1)
            or source_line_match.group(2)
            or source_line_match.group(3)
            or source_line_match.group(4)
            or ""
        ).strip()
        if candidate:
            return candidate

    json_match = _LOCALHOST_SOURCE_INDEX_JSON_PATTERN.search(text)
    if json_match:
        candidate = str(json_match.group(1) or "").strip()
        if candidate:
            return candidate

    return ""


def _inject_localhost_recreate_policy(solution: str, context: str) -> str:
    """Append a source-protection execution policy when the data source is a localhost index.

    If the conversation context indicates sample data was loaded from a local
    OpenSearch index and the solution text does not already contain the policy,
    a line is appended instructing the worker not to overwrite the source index
    and to use a different target index name instead.
    """
    base_solution = (solution or "").strip()
    text = context or ""
    lowered = text.lower()

    if _LOCALHOST_SOURCE_POLICY_PATTERN.search(base_solution):
        return base_solution

    has_localhost_source_signal = (
        _LOCALHOST_SOURCE_FLAG_PATTERN.search(text) is not None
        or "sample document loaded from localhost opensearch index" in lowered
        or "execution policy: source is localhost opensearch index" in lowered
        or _LOCALHOST_SOURCE_LINE_PATTERN.search(text) is not None
    )
    if not has_localhost_source_signal:
        return base_solution

    source_index_name = _extract_localhost_source_index_name(text)
    index_suffix = f" '{source_index_name}'" if source_index_name else ""
    policy_line = (
        "- Execution Policy: source is localhost OpenSearch index"
        f"{index_suffix} (system-enforced, not user-stated); do NOT overwrite this index "
        "(replace_if_exists=false). Use a different target index name."
    )

    if not base_solution:
        return policy_line
    return f"{base_solution}\n{policy_line}"


def _extract_hybrid_weight_profile(text: str) -> str:
    """Extract canonical hybrid weight profile from text."""
    match = _HYBRID_WEIGHT_PROFILE_PATTERN.search(text or "")
    if not match:
        return ""
    return str(match.group(1) or "").strip().lower()


def _has_three_method_hybrid(solution: str) -> bool:
    """Return True when a solution proposes BM25/lexical + dense + sparse together."""
    lowered = (solution or "").lower()
    if not lowered:
        return False
    has_lexical = "bm25" in lowered or "lexical" in lowered
    has_dense = "dense" in lowered
    has_sparse = "sparse" in lowered
    return has_lexical and has_dense and has_sparse


def _looks_like_planner_confirmation(user_input: str) -> bool:
    """Detect short confirmation replies for planner finalization."""
    text = (user_input or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if any(token in lowered for token in ("but", "however", "except", "question", "concern", "change", "modify", "adjust", "instead")):
        return False
    if lowered in {"proceed", "go ahead", "ship it", "looks good", "sounds good", "approved", "lgtm"}:
        return True
    return _PLANNER_CONFIRMATION_PATTERN.search(text) is not None


_agent = None


def _create_planner_agent() -> Agent:
    return Agent(
        model=_get_model(),
        system_prompt=SYSTEM_PROMPT,
        tools=[tool(read_knowledge_base), tool(read_dense_vector_models), tool(read_sparse_vector_models), tool(read_agentic_search_guide), tool(search_opensearch_org)],
        callback_handler=ThinkingCallbackHandler(output_color="\033[94m"),  # Blue output
    )


def _get_planner_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = _create_planner_agent()
    return _agent


def reset_planner_agent() -> None:
    """Reset the planner agent (public — called by orchestrator on new_request)."""
    global _agent
    _agent = None

# -------------------------------------------------------------------------
# Worker Execution
# -------------------------------------------------------------------------

@tool
def solution_planning_assistant(context: str) -> dict:
    """Act as a search architecture assistant to provide technical recommendations based on user context.
    This tool initiates an interactive session with the user to refine the plan.

    Args:
        context: A detailed string containing user requirements (data size, latency, budget, etc.), preferences, and any other relevant context for decision making.

    Returns:
        dict: A comprehensive technical recommendation report and conversation summary
        (Solution + Search Capabilities + Keynote).
    """
    print(f"\033[91m[solution_planning_assistant] Input context: {context}\033[0m", file=sys.stderr)

    try:
        # Initial prompt to the internal agent
        # hybrid_weight_profile = _extract_hybrid_weight_profile(context)
        # if not hybrid_weight_profile:
        #     hybrid_weight_profile = "balanced"

        current_input = (
            "Here is the user context:\n"
            f"{context}\n\n"
            # "System note: lexical+semantic hybrid weighting preference handling:\n"
            # f"- Hybrid Weight Profile: {hybrid_weight_profile}\n"
            # "- Apply this profile only when recommending lexical+semantic hybrid retrieval.\n"
            # "- For non-lexical hybrid combinations or non-hybrid retrieval, do not force a hybrid profile.\n"
            # "- If hybrid retrieval is recommended, cap it at two retrieval methods (never BM25 + dense + sparse together).\n"
            "System note: confirmation behavior:\n"
            "- Ask exactly one concise confirmation prompt before finalization.\n"
            "- Do not require any fixed reply keyword (for example, do not require 'proceed').\n"
            "- In that same prompt, make clear the user can raise concerns/questions and you will refine first.\n"
            "- Avoid long, generic alignment-template confirmation wording.\n"
            "- Do not ask extra confirmation checklists.\n"
            "- Only finalize with <planning_complete> after clear proceed intent from the user."
        )

        confirmation_received = False
        finalization_retry_count = 0
        finalization_retry_limit = 2
        hybrid_method_retry_count = 0
        hybrid_method_retry_limit = 1
        capability_precheck_retry_count = 0
        capability_precheck_retry_limit = 1
        # Interaction Loop
        while True:
            response = _get_planner_agent()(current_input)
            response_text = str(response)

            # Check for completion tags
            match = re.search(r'<planning_complete>(.*?)</planning_complete>', response_text, re.DOTALL)
            if match:
                if not confirmation_received:
                    current_input = (
                        "You finalized too early.\n"
                        "Do NOT output <planning_complete> yet.\n"
                        "Present the recommendation and ask exactly one concise confirmation prompt.\n"
                        "Do not require a fixed reply keyword.\n"
                        "Use a prompt that allows either proceed intent or user concerns in one turn.\n"
                        "Avoid long, generic alignment-template confirmation wording.\n"
                        "Do not ask any additional confirmation checklist questions."
                    )
                    continue

                content = match.group(1)
                
                # Extract solution and keynote
                solution_match = re.search(r'<solution>(.*?)</solution>', content, re.DOTALL)
                capabilities_match = re.search(r'<search_capabilities>(.*?)</search_capabilities>', content, re.DOTALL)
                keynote_match = re.search(r'<keynote>(.*?)</keynote>', content, re.DOTALL)
                
                solution = solution_match.group(1).strip() if solution_match else "No solution parsed."
                search_capabilities = capabilities_match.group(1).strip() if capabilities_match else ""
                keynote = keynote_match.group(1).strip() if keynote_match else "No keynote provided."
                solution = _inject_localhost_recreate_policy(solution, context)
                if _has_three_method_hybrid(solution):
                    if hybrid_method_retry_count < hybrid_method_retry_limit:
                        hybrid_method_retry_count += 1
                        current_input = (
                            "Your previous <planning_complete> proposed a three-method hybrid retrieval."
                            " Regenerate the full <planning_complete> block now.\n"
                            "Requirement: hybrid retrieval must use at most two methods."
                            " Do NOT combine BM25/lexical + dense + sparse in one retrieval strategy.\n"
                            "If hybrid is needed, choose one pair only (for example dense+sparse or BM25+dense)."
                        )
                        continue
                    return {
                        "solution": "INVALID_PLANNING_COMPLETE",
                        "search_capabilities": "",
                        "keynote": (
                            "Planner proposed a three-method hybrid retrieval after retry. "
                            "Hybrid retrieval must be limited to two methods."
                        ),
                    }
                capability_ids = _extract_canonical_capability_ids(search_capabilities)

                # Skip capability verification for Agentic Search (handles capabilities internally)
                is_agentic_search = "agentic search" in solution.lower()
                
                if search_capabilities and capability_ids and not is_agentic_search:
                    capability_block_for_precheck = (
                        "## Search Capabilities\n"
                        f"{search_capabilities}\n"
                    )
                    sample_doc_json = _extract_sample_doc_json(context)
                    source_local_file = _extract_source_local_file(context)
                    source_index_name = _extract_localhost_source_index_name(context)
                    try:
                        preview_result = preview_cap_driven_verification(
                            worker_output=capability_block_for_precheck,
                            count=10,
                            sample_doc_json=sample_doc_json,
                            source_local_file=source_local_file,
                            source_index_name=source_index_name,
                        )
                    except Exception as e:
                        preview_result = {
                            "capabilities": capability_ids,
                            "applicable_capabilities": [],
                            "skipped_capabilities": [],
                            "suggestion_meta": [],
                            "selected_doc_count": 0,
                            "notes": [f"capability precheck failed: {e}"],
                        }

                    applicable_ids = [
                        _normalize_capability_id(item)
                        for item in preview_result.get("applicable_capabilities", [])
                        if _normalize_capability_id(item)
                    ]
                    filtered_search_capabilities = _filter_search_capabilities_block(
                        search_capabilities,
                        applicable_ids,
                    )
                    if filtered_search_capabilities:
                        keynote_with_precheck = _append_capability_precheck_notes(
                            keynote,
                            preview_result.get("skipped_capabilities", []),
                        )
                        # Return a structured string for the Orchestrator to parse.
                        return {
                            "solution": solution,
                            "search_capabilities": filtered_search_capabilities,
                            "keynote": keynote_with_precheck,
                        }

                    precheck_feedback = _build_capability_precheck_feedback(
                        notes=preview_result.get("notes", []),
                        skipped_capabilities=preview_result.get("skipped_capabilities", []),
                    )
                    if capability_precheck_retry_count < capability_precheck_retry_limit:
                        capability_precheck_retry_count += 1
                        current_input = (
                            "Your previous <planning_complete> output has no sample-verified applicable capabilities.\n"
                            "Regenerate the full <planning_complete> block now.\n"
                            "Use only capabilities that can be demonstrated by the available sample data/schema context.\n"
                            f"Precheck feedback: {precheck_feedback}\n"
                            "Requirements:\n"
                            "- Include <solution>, <search_capabilities>, and <keynote>.\n"
                            "- Keep <search_capabilities> canonical with prefixes Exact:/Semantic:/Structured:/Combined:/Autocomplete:/Fuzzy:.\n"
                            "- Include only applicable capability bullets.\n"
                        )
                        continue

                    return {
                        "solution": "INVALID_PLANNING_COMPLETE",
                        "search_capabilities": "",
                        "keynote": (
                            "Planner capability precheck found no applicable canonical capabilities after retry. "
                            f"Precheck feedback: {precheck_feedback}"
                        ),
                    }
                
                # For Agentic Search, return directly (no capability verification needed)
                elif is_agentic_search:
                    return {
                        "solution": solution,
                        "search_capabilities": search_capabilities,
                        "keynote": keynote,
                    }

                if finalization_retry_count < finalization_retry_limit:
                    finalization_retry_count += 1
                    current_input = (
                        "Your previous <planning_complete> output is invalid because <search_capabilities> is missing or not canonical.\n"
                        "Regenerate the full <planning_complete> block now.\n"
                        "Requirements:\n"
                        "- Include <solution>, <search_capabilities>, and <keynote>.\n"
                        "- If retrieval method is hybrid lexical+semantic, include in <solution> exactly one line in this format: "
                        "'Hybrid Weight Profile: semantic-heavy|balanced|lexical-heavy'.\n"
                        "- If retrieval method is hybrid, use at most two methods. Do NOT combine BM25/lexical + dense + sparse.\n"
                        "- In <search_capabilities>, include only applicable capability bullets.\n"
                        "- Every capability bullet MUST start with one canonical prefix: "
                        "Exact:, Semantic:, Structured:, Combined:, Autocomplete:, or Fuzzy:.\n"
                        "- Do not use any other capability bullet prefixes.\n"
                    )
                    continue
                
                return {
                    "solution": "INVALID_PLANNING_COMPLETE",
                    "search_capabilities": "",
                    "keynote": (
                        "Planner failed to produce canonical <search_capabilities> after retries. "
                        "Expected canonical prefixes: Exact/Semantic/Structured/Combined/Autocomplete/Fuzzy."
                    ),
                }

            # Collect feedback and detect proceed intent for finalization.
            while True:
                try:
                    user_input = read_multiline_input()
                except KeyboardInterrupt:
                    return {
                        "solution": "CANCELLED",
                        "search_capabilities": "",
                        "keynote": "User cancelled planning."
                    }

                if user_input:
                    if looks_like_new_request(user_input):
                        reset_planner_agent()
                        confirmation_received = False
                        current_input = (
                            "The user started a new request. Ignore previous planning context and treat this as a new conversation.\n"
                            f"New request: {user_input}\n"
                            "Please provide a technical recommendation."
                        )
                        break

                    if looks_like_execution_intent(user_input) or _looks_like_planner_confirmation(user_input):
                        confirmation_received = True
                        current_input = (
                            "The user explicitly confirmed to proceed with setup/implementation.\n"
                            f"User message: {user_input}\n"
                            "Finalize now using <planning_complete>."
                        )
                        break

                    current_input = user_input
                    break

                print("Please share feedback, or indicate when you're ready to proceed.", file=sys.stderr)

    except Exception as e:
        raise e


SAMPLE_CONTEXT = """
User Requirements:
- Document count: 10 million documents
- Language: English (monolingual)
- Content type: Text documents (sample: "The quick brown fox jumps over the lazy dog. This is a sample document for testing search capabilities.")
- Budget: No budget limitation
- Priority: BEST SEARCH RELEVANCE (accuracy is the top priority)
- Latency requirements: Not specified (reasonable latency acceptable given focus on accuracy)
- Model deployment: Not specified (can use any deployment method)
- Special requirements: None specified

Key Focus: Maximum search accuracy and relevance for English text semantic search at 10M document scale.
"""

if __name__ == "__main__":
    # Test run
    sample_context = "I have 10 million documents, mostly English. Low latency is critical (<50ms). Budget is flexible. Preference for managed services."
    result = solution_planning_assistant(SAMPLE_CONTEXT)
    print(result, file=sys.stderr)
