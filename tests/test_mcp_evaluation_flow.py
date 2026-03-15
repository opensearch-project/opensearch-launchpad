"""Tests for MCP evaluation tools: start_evaluation, set_evaluation_from_evaluation_complete."""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opensearch_orchestrator.mcp_server as mcp_server
import pytest


@pytest.fixture(autouse=True)
def _reset_eval_state():
    """Reset _eval_state to a fresh instance before each test."""
    mcp_server._eval_state = mcp_server.EvaluationState()
    yield
    mcp_server._eval_state = mcp_server.EvaluationState()


class _DummyContext:
    def __init__(self, session) -> None:
        self.session = session


class _EvaluationSession:
    """Session that returns a well-formed <evaluation_complete> block."""

    def __init__(self, response_text: str) -> None:
        self._response_text = response_text

    async def create_message(self, *, messages, max_tokens, system_prompt):
        _ = messages, max_tokens, system_prompt
        from mcp import types as mcp_types
        return type(
            "SamplingResult",
            (),
            {"content": mcp_types.TextContent(type="text", text=self._response_text)},
        )()


_VALID_EVALUATION_RESPONSE = """\
<evaluation_complete>
<search_quality_summary>Hybrid search performs well for exact and semantic queries.</search_quality_summary>
<issues>
- Semantic recall drops on very long queries
</issues>
<suggested_preferences>{"query_pattern": "mostly-semantic"}</suggested_preferences>
</evaluation_complete>
"""


class _RecordingEngine:
    def __init__(self) -> None:
        self.plan_result = {"solution": "Hybrid Search", "search_capabilities": "", "keynote": ""}
        self.captured: dict = {}

    def set_evaluation(self, *, search_quality_summary, issues="", suggested_preferences=None, metrics=None, improvement_suggestions=""):
        self.captured["summary"] = search_quality_summary
        self.captured["issues"] = issues
        self.captured["prefs"] = suggested_preferences
        self.captured["metrics"] = metrics
        self.captured["improvement_suggestions"] = improvement_suggestions
        return {"status": "Evaluation stored.", "result": {"search_quality_summary": search_quality_summary}}


def test_start_evaluation_returns_manual_fallback_without_ctx(monkeypatch) -> None:
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)
    mcp_server._eval_state.judged_results = []
    mcp_server._eval_state.metrics = {}
    monkeypatch.setattr(mcp_server, "_last_verification_suggestion_meta", [])

    result = asyncio.run(mcp_server.start_evaluation(ctx=None))

    assert result["error"] == "Evaluation failed in client mode."
    assert result["manual_evaluation_required"] is True
    assert "evaluation_prompt" in result


def test_start_evaluation_requires_plan(monkeypatch) -> None:
    class _NoPlanEngine:
        plan_result = None

    monkeypatch.setattr(mcp_server, "_engine", _NoPlanEngine())

    result = asyncio.run(mcp_server.start_evaluation(ctx=None))
    assert "error" in result
    assert "plan" in result["error"].lower()


def test_start_evaluation_with_client_sampling_stores_result(monkeypatch) -> None:
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)
    monkeypatch.setattr(mcp_server, "_persist_engine_state", lambda *a, **kw: None)
    mcp_server._eval_state.judged_results = []
    mcp_server._eval_state.metrics = {}
    monkeypatch.setattr(mcp_server, "_last_verification_suggestion_meta", [])

    ctx = _DummyContext(_EvaluationSession(_VALID_EVALUATION_RESPONSE))
    result = asyncio.run(mcp_server.start_evaluation(ctx=ctx))

    assert "error" not in result
    assert result["evaluation_backend"] == "client_sampling"
    assert engine.captured["summary"] == "Hybrid search performs well for exact and semantic queries."
    assert engine.captured["prefs"] == {"query_pattern": "mostly-semantic"}


def test_start_evaluation_returns_manual_fallback_on_method_not_found(monkeypatch) -> None:
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)
    mcp_server._eval_state.judged_results = []
    mcp_server._eval_state.metrics = {}
    monkeypatch.setattr(mcp_server, "_last_verification_suggestion_meta", [])

    class _FailSession:
        async def create_message(self, **kwargs):
            raise Exception("Method not found")

    result = asyncio.run(mcp_server.start_evaluation(ctx=_DummyContext(_FailSession())))

    assert result["error"] == "Evaluation failed in client mode."
    assert result["manual_evaluation_required"] is True
    assert "evaluation_prompt" in result


def test_set_evaluation_from_evaluation_complete_parses_and_stores(monkeypatch) -> None:
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)
    monkeypatch.setattr(mcp_server, "_persist_engine_state", lambda *a, **kw: None)

    result = mcp_server.set_evaluation_from_evaluation_complete(_VALID_EVALUATION_RESPONSE)

    assert "error" not in result
    assert engine.captured["summary"] == "Hybrid search performs well for exact and semantic queries."


def test_set_evaluation_from_evaluation_complete_rejects_missing_block(monkeypatch) -> None:
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)

    result = mcp_server.set_evaluation_from_evaluation_complete("No block here.")
    assert "error" in result
    assert "<evaluation_complete>" in result["error"] or "evaluation_complete" in result["error"]


def test_parse_evaluation_complete_extracts_all_fields() -> None:
    parsed = mcp_server._parse_evaluation_complete_response(_VALID_EVALUATION_RESPONSE)
    assert "error" not in parsed
    assert "Hybrid search" in parsed["search_quality_summary"]
    assert "Semantic recall" in parsed["issues"]
    assert parsed["suggested_preferences"] == {"query_pattern": "mostly-semantic"}


def test_parse_evaluation_complete_returns_error_on_missing_summary() -> None:
    bad_response = "<evaluation_complete><issues>- some issue</issues></evaluation_complete>"
    parsed = mcp_server._parse_evaluation_complete_response(bad_response)
    assert "error" in parsed


def test_build_evaluation_prompt_covers_key_dimensions(monkeypatch) -> None:
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)
    mcp_server._eval_state.index_name = ""
    mcp_server._eval_state.suggestion_meta = []
    mcp_server._eval_state.judged_results = []
    mcp_server._eval_state.metrics = {}

    prompt = mcp_server._build_evaluation_prompt_from_state(mcp_server._eval_state)

    assert "relevance" in prompt.lower()
    assert "query coverage" in prompt.lower()
    assert "ranking quality" in prompt.lower()
    assert "capability gap" in prompt.lower()
    # latency and recall are not the focus
    assert "1" in prompt and "5" in prompt
    assert "<evaluation_complete>" in prompt
    assert "<relevance>" in prompt
    assert "<query_coverage>" in prompt
    assert "<ranking_quality>" in prompt
    assert "<capability_gap>" in prompt
    assert "<issues>" in prompt
    assert "<suggested_preferences>" in prompt


def test_build_evaluation_prompt_includes_suggestion_meta_when_available(monkeypatch) -> None:
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)
    mcp_server._eval_state.index_name = ""
    mcp_server._eval_state.suggestion_meta = [
        {"capability": "semantic", "text": "films about loss"},
        {"capability": "exact", "text": "Carmencita 1894"},
    ]
    mcp_server._eval_state.judged_results = []
    mcp_server._eval_state.metrics = {}

    prompt = mcp_server._build_evaluation_prompt_from_state(mcp_server._eval_state)

    assert "films about loss" in prompt
    assert "Carmencita 1894" in prompt
    assert "Verification Queries" in prompt
    assert "observed" in prompt.lower() or "verification" in prompt.lower()


def test_build_evaluation_prompt_notes_missing_evidence(monkeypatch) -> None:
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)
    mcp_server._eval_state.index_name = ""
    mcp_server._eval_state.suggestion_meta = []
    mcp_server._eval_state.judged_results = []
    mcp_server._eval_state.metrics = {}

    prompt = mcp_server._build_evaluation_prompt_from_state(mcp_server._eval_state)

    assert "architectural estimates" in prompt.lower() or "no verification" in prompt.lower()


def test_apply_capability_driven_verification_stores_suggestion_meta(monkeypatch) -> None:
    import asyncio
    monkeypatch.setattr(mcp_server, "_last_verification_suggestion_meta", [])
    monkeypatch.setattr(mcp_server, "_last_verification_index_name", "")

    def _fake_impl(**kwargs):
        return {
            "applied": True,
            "index_name": "my-index",
            "suggestion_meta": [
                {"capability": "exact", "text": "Carmencita 1894"},
                {"capability": "semantic", "text": "early silent films"},
            ],
        }

    monkeypatch.setattr(mcp_server, "apply_capability_driven_verification_impl", _fake_impl)
    monkeypatch.setattr(mcp_server, "_persist_engine_state", lambda *a, **kw: None)
    async def _noop_rewrite(*, result, ctx):
        return result

    monkeypatch.setattr(mcp_server, "_rewrite_semantic_suggestion_entries_with_client_llm", _noop_rewrite)

    asyncio.run(mcp_server.apply_capability_driven_verification(
        worker_output="some plan", index_name="my-index", ctx=None
    ))

    assert len(mcp_server._last_verification_suggestion_meta) == 2
    assert mcp_server._last_verification_suggestion_meta[0]["capability"] == "exact"
    assert mcp_server._last_verification_index_name == "my-index"


def test_start_evaluation_uses_stored_suggestion_meta(monkeypatch) -> None:
    import asyncio
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)
    monkeypatch.setattr(mcp_server, "_last_verification_suggestion_meta", [
        {"capability": "semantic", "text": "action movies from the 90s"},
    ])
    monkeypatch.setattr(mcp_server, "_last_verification_index_name", "")
    monkeypatch.setattr(mcp_server, "get_last_worker_run_state", lambda: {})
    mcp_server._eval_state.judged_results = []
    mcp_server._eval_state.metrics = {}

    result = asyncio.run(mcp_server.start_evaluation(ctx=None))

    assert result["manual_evaluation_required"] is True
    assert "action movies from the 90s" in result["evaluation_prompt"]


def test_evaluation_result_table_always_present_in_manual_fallback(monkeypatch) -> None:
    """evaluation_result_table must always be present, even without data-driven results."""
    import asyncio
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)
    monkeypatch.setattr(mcp_server, "_last_verification_suggestion_meta", [])
    monkeypatch.setattr(mcp_server, "_last_verification_index_name", "")
    mcp_server._eval_state.judged_results = []
    mcp_server._eval_state.metrics = {}
    mcp_server._eval_state.diagnostic = {}

    result = asyncio.run(mcp_server.start_evaluation(ctx=None))

    assert "evaluation_result_table" in result
    assert "No per-query breakdown available" in result["evaluation_result_table"]


def test_evaluation_result_table_always_present_on_method_not_found(monkeypatch) -> None:
    """evaluation_result_table must always be present in Method not found fallback."""
    import asyncio
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)
    monkeypatch.setattr(mcp_server, "_last_verification_suggestion_meta", [])
    monkeypatch.setattr(mcp_server, "_last_verification_index_name", "")
    mcp_server._eval_state.judged_results = []
    mcp_server._eval_state.metrics = {}
    mcp_server._eval_state.diagnostic = {}

    class _FailSession:
        async def create_message(self, **kwargs):
            raise Exception("Method not found")

    result = asyncio.run(mcp_server.start_evaluation(ctx=_DummyContext(_FailSession())))

    assert "evaluation_result_table" in result
    assert "No per-query breakdown available" in result["evaluation_result_table"]


def test_evaluation_result_table_always_present_in_set_evaluation(monkeypatch) -> None:
    """evaluation_result_table must always be present in set_evaluation_from_evaluation_complete."""
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)
    monkeypatch.setattr(mcp_server, "_persist_engine_state", lambda *a, **kw: None)
    mcp_server._eval_state.judged_results = []
    mcp_server._eval_state.metrics = {}
    mcp_server._eval_state.diagnostic = {}

    result = mcp_server.set_evaluation_from_evaluation_complete(_VALID_EVALUATION_RESPONSE)

    assert "evaluation_result_table" in result
    assert "No per-query breakdown available" in result["evaluation_result_table"]


def test_evaluation_result_table_shows_unjudged_when_query_results_available(monkeypatch) -> None:
    """When manual judgment is required and query_results exist, show unjudged table instead of fallback."""
    import asyncio
    engine = _RecordingEngine()
    monkeypatch.setattr(mcp_server, "_engine", engine)
    # Set up suggestion_meta and index_name so the pipeline runs searches
    monkeypatch.setattr(mcp_server, "_last_verification_suggestion_meta", [
        {"text": "Carmencita 1894", "capability": "exact", "field": "primaryTitle", "query_mode": "term"},
    ])
    monkeypatch.setattr(mcp_server, "_last_verification_index_name", "test-index")
    mcp_server._eval_state.judged_results = []
    mcp_server._eval_state.metrics = {}
    mcp_server._eval_state.diagnostic = {}

    # Mock run_data_driven_evaluation_pipeline (called by _execute_searches in Phase 2)
    _mock_query_results = [
        {
            "query_text": "Carmencita 1894",
            "capability": "exact",
            "query_mode": "term",
            "field": "primaryTitle",
            "took_ms": 5,
            "used_semantic": False,
            "fallback_reason": "",
            "total_hits": 1,
            "hits": [
                {"id": "verification-1", "score": 10.0, "preview": "Carmencita", "source": {"primaryTitle": "Carmencita"}},
            ],
        },
    ]
    monkeypatch.setattr(
        mcp_server, "run_data_driven_evaluation_pipeline",
        lambda index_name, suggestion_meta, size=5: (_mock_query_results, "mock judgment prompt"),
    )
    monkeypatch.setattr(mcp_server, "get_last_worker_run_state", lambda: {})

    result = asyncio.run(mcp_server.start_evaluation(ctx=None))

    assert "evaluation_result_table" in result
    assert "awaiting relevance judgment" in result["evaluation_result_table"]
    assert "verification-1" in result["evaluation_result_table"]
    assert "No per-query breakdown available" not in result["evaluation_result_table"]
