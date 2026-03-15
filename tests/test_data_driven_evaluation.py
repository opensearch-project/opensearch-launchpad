"""Tests for data-driven evaluation: execute_evaluation_queries, LLM relevance judgment, compute_evaluation_metrics."""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opensearch_orchestrator.opensearch_ops_tools import (
    execute_evaluation_queries,
    build_relevance_judgment_prompt,
    parse_relevance_judgment_response,
    apply_relevance_judgments,
    compute_evaluation_metrics,
    format_evaluation_evidence,
)


# ---------------------------------------------------------------------------
# build_relevance_judgment_prompt tests
# ---------------------------------------------------------------------------


def test_build_judgment_prompt_includes_queries_and_docs():
    query_results = [{
        "query_text": "Carmencita 1894",
        "capability": "exact",
        "field": "primaryTitle",
        "hits": [
            {"id": "doc-1", "score": 10.0, "preview": "Carmencita (1894)",
             "source": {"primaryTitle": "Carmencita", "startYear": 1894}},
        ],
    }]
    prompt = build_relevance_judgment_prompt(query_results)
    assert "Carmencita 1894" in prompt
    assert "doc-1" in prompt
    assert "exact" in prompt
    assert "primaryTitle" in prompt


def test_build_judgment_prompt_handles_no_hits():
    query_results = [{
        "query_text": "missing",
        "capability": "semantic",
        "field": "",
        "hits": [],
    }]
    prompt = build_relevance_judgment_prompt(query_results)
    assert "no results returned" in prompt


def test_build_judgment_prompt_multiple_queries():
    query_results = [
        {"query_text": "query1", "capability": "exact", "field": "f1",
         "hits": [{"id": "d1", "score": 1.0, "preview": "p1", "source": {"f1": "v1"}}]},
        {"query_text": "query2", "capability": "fuzzy", "field": "f2",
         "hits": [{"id": "d2", "score": 0.5, "preview": "p2", "source": {"f2": "v2"}}]},
    ]
    prompt = build_relevance_judgment_prompt(query_results)
    assert "Query 1" in prompt
    assert "Query 2" in prompt
    assert "query1" in prompt
    assert "query2" in prompt


# ---------------------------------------------------------------------------
# parse_relevance_judgment_response tests
# ---------------------------------------------------------------------------


def test_parse_judgment_response_basic():
    response = "doc-1: 1 | relevant match\ndoc-2: 0 | not relevant"
    query_results = [{
        "query_text": "test",
        "capability": "exact",
        "field": "title",
        "hits": [
            {"id": "doc-1", "score": 10.0, "preview": "p1", "source": {}},
            {"id": "doc-2", "score": 5.0, "preview": "p2", "source": {}},
        ],
    }]
    judged = parse_relevance_judgment_response(response, query_results)
    assert len(judged) == 1
    assert judged[0]["judgments"][0]["relevance"] == 1
    assert judged[0]["judgments"][0]["reason"] == "relevant match"
    assert judged[0]["judgments"][1]["relevance"] == 0


def test_parse_judgment_response_with_dash_separator():
    response = "doc-1: 1 - good match\ndoc-2: 0 - irrelevant"
    query_results = [{
        "query_text": "test",
        "capability": "exact",
        "field": "",
        "hits": [
            {"id": "doc-1", "score": 1.0, "preview": "", "source": {}},
            {"id": "doc-2", "score": 0.5, "preview": "", "source": {}},
        ],
    }]
    judged = parse_relevance_judgment_response(response, query_results)
    assert judged[0]["judgments"][0]["relevance"] == 1
    assert judged[0]["judgments"][1]["relevance"] == 0


def test_parse_judgment_response_missing_doc_defaults_to_zero():
    response = "doc-1: 1 | match"
    query_results = [{
        "query_text": "test",
        "capability": "exact",
        "field": "",
        "hits": [
            {"id": "doc-1", "score": 1.0, "preview": "", "source": {}},
            {"id": "doc-2", "score": 0.5, "preview": "", "source": {}},
        ],
    }]
    judged = parse_relevance_judgment_response(response, query_results)
    assert judged[0]["judgments"][0]["relevance"] == 1
    assert judged[0]["judgments"][1]["relevance"] == 0
    assert "no judgment provided" in judged[0]["judgments"][1]["reason"]


def test_parse_judgment_response_computes_metrics():
    response = "doc-1: 1 | match\ndoc-2: 0 | no match"
    query_results = [{
        "query_text": "test",
        "capability": "exact",
        "field": "",
        "hits": [
            {"id": "doc-1", "score": 1.0, "preview": "", "source": {}},
            {"id": "doc-2", "score": 0.5, "preview": "", "source": {}},
        ],
    }]
    judged = parse_relevance_judgment_response(response, query_results)
    assert judged[0]["has_relevant"] is True
    assert judged[0]["reciprocal_rank"] == 1.0
    assert judged[0]["precision_at_5"] > 0


# ---------------------------------------------------------------------------
# apply_relevance_judgments tests
# ---------------------------------------------------------------------------


def test_apply_judgments_basic():
    query_results = [{
        "query_text": "test",
        "capability": "exact",
        "hits": [
            {"id": "doc-1", "score": 1.0, "preview": "", "source": {}},
            {"id": "doc-2", "score": 0.5, "preview": "", "source": {}},
        ],
    }]
    judgment_map = {"doc-1": (1, "match"), "doc-2": (0, "no match")}
    judged = apply_relevance_judgments(query_results, judgment_map)
    assert judged[0]["judgments"][0]["relevance"] == 1
    assert judged[0]["judgments"][1]["relevance"] == 0
    assert judged[0]["has_relevant"] is True


def test_apply_judgments_no_hits():
    query_results = [{"query_text": "test", "capability": "exact", "hits": []}]
    judged = apply_relevance_judgments(query_results, {})
    assert judged[0]["has_relevant"] is False
    assert judged[0]["precision_at_5"] == 0
    assert judged[0]["reciprocal_rank"] == 0


# ---------------------------------------------------------------------------
# execute_evaluation_queries tests
# ---------------------------------------------------------------------------


def test_execute_evaluation_queries_empty_inputs():
    assert execute_evaluation_queries("", []) == []
    assert execute_evaluation_queries("my-index", []) == []
    assert execute_evaluation_queries("", [{"text": "hello"}]) == []


def test_execute_evaluation_queries_skips_empty_text():
    result = execute_evaluation_queries("my-index", [{"text": "", "capability": "exact"}])
    assert result == []


def test_execute_evaluation_queries_calls_search(monkeypatch):
    import opensearch_orchestrator.opensearch_ops_tools as ops

    calls = []

    def mock_search(index_name, query_text, size=10, debug=False):
        calls.append({"index": index_name, "query": query_text, "size": size})
        return {
            "hits": [
                {"id": "doc-1", "score": 10.0, "preview": "Test doc", "source": {"title": "Test"}},
            ],
            "total": 1,
            "took_ms": 5,
            "query_mode": "exact_term",
            "capability": "exact",
            "used_semantic": False,
            "fallback_reason": "",
        }

    monkeypatch.setattr(ops, "_search_ui_search", mock_search)

    suggestion_meta = [
        {"text": "Carmencita 1894", "capability": "exact", "field": "primaryTitle", "query_mode": "term"},
    ]
    results = execute_evaluation_queries("my-index", suggestion_meta, size=10)

    assert len(results) == 1
    assert results[0]["query_text"] == "Carmencita 1894"
    assert results[0]["capability"] == "exact"
    assert results[0]["total_hits"] == 1
    assert len(results[0]["hits"]) == 1
    assert calls[0]["index"] == "my-index"


def test_execute_evaluation_queries_handles_search_error(monkeypatch):
    import opensearch_orchestrator.opensearch_ops_tools as ops

    def mock_search(**kwargs):
        raise ConnectionError("OpenSearch unavailable")

    monkeypatch.setattr(ops, "_search_ui_search", mock_search)

    results = execute_evaluation_queries("my-index", [{"text": "test", "capability": "exact"}])
    assert len(results) == 1
    assert "error" in results[0]
    assert results[0]["total_hits"] == 0


# ---------------------------------------------------------------------------
# compute_evaluation_metrics tests
# ---------------------------------------------------------------------------


def test_compute_metrics_empty():
    metrics = compute_evaluation_metrics([])
    assert metrics["query_count"] == 0
    assert metrics["mean_precision_at_5"] == 0.0
    assert metrics["mrr"] == 0.0


def test_compute_metrics_perfect_results():
    judged = [{
        "query_text": "test",
        "capability": "exact",
        "query_mode": "exact_term",
        "took_ms": 5,
        "precision_at_5": 1.0,
        "precision_at_10": 1.0,
        "reciprocal_rank": 1.0,
        "has_relevant": True,
        "fallback_reason": "",
    }]
    metrics = compute_evaluation_metrics(judged)
    assert metrics["query_count"] == 1
    assert metrics["mean_precision_at_5"] == 1.0
    assert metrics["mrr"] == 1.0
    assert metrics["query_failure_rate"] == 0.0
    assert "exact" in metrics["per_capability"]


def test_compute_metrics_mixed_results():
    judged = [
        {
            "query_text": "exact query",
            "capability": "exact",
            "query_mode": "exact_term",
            "took_ms": 5,
            "precision_at_5": 1.0,
            "precision_at_10": 0.8,
            "reciprocal_rank": 1.0,
            "has_relevant": True,
            "fallback_reason": "",
        },
        {
            "query_text": "semantic query",
            "capability": "semantic",
            "query_mode": "semantic_hybrid",
            "took_ms": 50,
            "precision_at_5": 0.0,
            "precision_at_10": 0.0,
            "reciprocal_rank": 0.0,
            "has_relevant": False,
            "fallback_reason": "",
        },
    ]
    metrics = compute_evaluation_metrics(judged)
    assert metrics["query_count"] == 2
    assert metrics["mean_precision_at_5"] == 0.5
    assert metrics["query_failure_rate"] == 0.5
    assert len(metrics["failing_queries"]) == 1
    assert metrics["failing_queries"][0]["capability"] == "semantic"


def test_compute_metrics_slow_queries():
    judged = [{
        "query_text": "slow query",
        "capability": "semantic",
        "query_mode": "semantic_hybrid",
        "took_ms": 800,
        "precision_at_5": 0.5,
        "precision_at_10": 0.5,
        "reciprocal_rank": 0.5,
        "has_relevant": True,
        "fallback_reason": "",
    }]
    metrics = compute_evaluation_metrics(judged)
    assert len(metrics["slow_queries"]) == 1
    assert metrics["slow_queries"][0]["took_ms"] == 800


# ---------------------------------------------------------------------------
# format_evaluation_evidence tests
# ---------------------------------------------------------------------------


def test_format_evidence_includes_key_sections():
    judged = [{
        "query_text": "Carmencita 1894",
        "capability": "exact",
        "query_mode": "exact_term",
        "field": "primaryTitle",
        "took_ms": 5,
        "used_semantic": False,
        "fallback_reason": "",
        "total_hits": 1,
        "hits": [
            {"id": "doc-1", "score": 10.0, "preview": "Carmencita (1894)", "source": {}},
        ],
        "judgments": [{"doc_id": "doc-1", "relevance": 1, "reason": "LLM judged relevant"}],
        "precision_at_5": 1.0,
        "precision_at_10": 1.0,
        "reciprocal_rank": 1.0,
        "has_relevant": True,
    }]
    metrics = {
        "query_count": 1,
        "mean_precision_at_5": 1.0,
        "mean_precision_at_10": 1.0,
        "mrr": 1.0,
        "query_failure_rate": 0.0,
        "per_capability": {"exact": {"count": 1, "mean_p5": 1.0, "mean_p10": 1.0, "mrr": 1.0}},
        "failing_queries": [],
        "slow_queries": [],
    }
    evidence = format_evaluation_evidence(judged, metrics)
    assert "Aggregate Metrics" in evidence
    assert "Per-Capability Breakdown" in evidence
    assert "Per-Query Evidence" in evidence
    assert "Carmencita 1894" in evidence
    assert "exact_term" in evidence
    assert "P@5: 1.00" in evidence


def test_format_evidence_shows_failing_queries():
    judged = [{
        "query_text": "missing query",
        "capability": "semantic",
        "query_mode": "semantic_hybrid",
        "field": "",
        "took_ms": 50,
        "used_semantic": True,
        "fallback_reason": "",
        "total_hits": 0,
        "hits": [],
        "judgments": [],
        "precision_at_5": 0.0,
        "precision_at_10": 0.0,
        "reciprocal_rank": 0.0,
        "has_relevant": False,
    }]
    metrics = {
        "query_count": 1,
        "mean_precision_at_5": 0.0,
        "mean_precision_at_10": 0.0,
        "mrr": 0.0,
        "query_failure_rate": 1.0,
        "per_capability": {"semantic": {"count": 1, "mean_p5": 0.0, "mean_p10": 0.0, "mrr": 0.0}},
        "failing_queries": [{"query_text": "missing query", "capability": "semantic", "query_mode": "semantic_hybrid", "fallback_reason": ""}],
        "slow_queries": [],
    }
    evidence = format_evaluation_evidence(judged, metrics)
    assert "Failing Queries" in evidence
    assert "missing query" in evidence


# ---------------------------------------------------------------------------
# Backward compatibility: _parse_evaluation_complete_response
# ---------------------------------------------------------------------------


def test_parse_evaluation_complete_with_improvement_suggestions():
    import opensearch_orchestrator.mcp_server as mcp_server

    response = """\
<evaluation_complete>
<relevance>
Relevance: [4/5] - Good relevance for exact queries
</relevance>
<query_coverage>
Query Coverage: [3/5] - Semantic queries weak
</query_coverage>
<ranking_quality>
Ranking Quality: [4/5] - Good ranking
</ranking_quality>
<capability_gap>
Capability Gap: [3/5] - Missing fuzzy support
</capability_gap>
<issues>
- [SEARCH_PIPELINE] [Relevance] Hybrid weights too lexical-heavy
</issues>
<improvement_suggestions>
- [INDEX_MAPPING] Add .keyword sub-field to genres for structured filtering
- [SEARCH_PIPELINE] Shift hybrid weights from 0.8/0.2 to 0.5/0.5
- [MODEL_SELECTION] Consider dense vector model for better semantic coverage
</improvement_suggestions>
<suggested_preferences>{"query_pattern": "balanced"}</suggested_preferences>
</evaluation_complete>
"""
    parsed = mcp_server._parse_evaluation_complete_response(response)
    assert "error" not in parsed
    assert "improvement_suggestions" in parsed
    assert "INDEX_MAPPING" in parsed["improvement_suggestions"]
    assert "SEARCH_PIPELINE" in parsed["improvement_suggestions"]
    assert parsed["suggested_preferences"] == {"query_pattern": "balanced"}


def test_parse_evaluation_complete_without_improvement_suggestions():
    """Backward compatibility: old format without <improvement_suggestions> still works."""
    import opensearch_orchestrator.mcp_server as mcp_server

    response = """\
<evaluation_complete>
<relevance>
Relevance: [4/5] - Good
</relevance>
<issues>
- Some issue
</issues>
<suggested_preferences>{}</suggested_preferences>
</evaluation_complete>
"""
    parsed = mcp_server._parse_evaluation_complete_response(response)
    assert "error" not in parsed
    assert "improvement_suggestions" not in parsed


# ---------------------------------------------------------------------------
# set_evaluation with new optional parameters
# ---------------------------------------------------------------------------


def test_set_evaluation_with_metrics_and_suggestions():
    import opensearch_orchestrator.orchestrator as orchestrator

    engine = orchestrator.create_transport_agnostic_engine(orchestrator.SessionState())
    engine.load_sample("builtin_imdb")
    engine.set_plan(
        solution="Hybrid Search",
        search_capabilities="- Exact: title match",
        keynote="Test.",
    )
    result = engine.set_evaluation(
        search_quality_summary="Data-driven evaluation.",
        issues="- Semantic recall low",
        metrics={"query_count": 3, "mean_precision_at_5": 0.6, "mrr": 0.7},
        improvement_suggestions="- [SEARCH_PIPELINE] Adjust hybrid weights",
    )
    assert result["status"] == "Evaluation stored."
    assert result["result"]["metrics"]["query_count"] == 3
    assert result["result"]["improvement_suggestions"] == "- [SEARCH_PIPELINE] Adjust hybrid weights"


def test_set_evaluation_without_new_params_backward_compatible():
    import opensearch_orchestrator.orchestrator as orchestrator

    engine = orchestrator.create_transport_agnostic_engine(orchestrator.SessionState())
    engine.load_sample("builtin_imdb")
    engine.set_plan(
        solution="BM25",
        search_capabilities="- Exact: keyword",
        keynote="Test.",
    )
    result = engine.set_evaluation(
        search_quality_summary="Looks good.",
    )
    assert result["status"] == "Evaluation stored."
    assert "metrics" not in result["result"]
    assert "improvement_suggestions" not in result["result"]


# ---------------------------------------------------------------------------
# Enhanced _build_evaluation_prompt_from_state integration
# ---------------------------------------------------------------------------


def test_build_evaluation_prompt_includes_data_driven_evidence(monkeypatch):
    import opensearch_orchestrator.mcp_server as mcp_server

    class _FakeEngine:
        plan_result = {"solution": "Hybrid Search", "search_capabilities": "- Exact: title", "keynote": ""}

    monkeypatch.setattr(mcp_server, "_engine", _FakeEngine())

    # Pre-store judged results so _build_evaluation_prompt_from_state uses them directly
    _mock_judged = [{
        "query_text": "Carmencita 1894",
        "capability": "exact",
        "query_mode": "exact_term",
        "field": "primaryTitle",
        "took_ms": 5,
        "used_semantic": False,
        "fallback_reason": "",
        "total_hits": 1,
        "hits": [{"id": "doc-1", "score": 10.0, "preview": "Carmencita (1894)", "source": {"primaryTitle": "Carmencita"}}],
        "judgments": [{"doc_id": "doc-1", "relevance": 1, "reason": "match"}],
        "precision_at_5": 1.0,
        "precision_at_10": 1.0,
        "reciprocal_rank": 1.0,
        "has_relevant": True,
    }]
    _mock_metrics = {
        "query_count": 1, "mean_precision_at_5": 1.0, "mean_precision_at_10": 1.0,
        "mrr": 1.0, "query_failure_rate": 0.0, "per_capability": {}, "failing_queries": [], "slow_queries": [],
    }
    mcp_server._eval_state.index_name = "test-index"
    mcp_server._eval_state.suggestion_meta = [
        {"text": "Carmencita 1894", "capability": "exact", "field": "primaryTitle", "query_mode": "term"},
    ]
    mcp_server._eval_state.judged_results = _mock_judged
    mcp_server._eval_state.metrics = _mock_metrics

    prompt = mcp_server._build_evaluation_prompt_from_state(mcp_server._eval_state)

    assert "Search Quality Evidence (Data-Driven)" in prompt


def test_build_evaluation_prompt_falls_back_when_no_data(monkeypatch):
    """When no judged or query results exist, falls back to legacy verification queries."""
    import opensearch_orchestrator.mcp_server as mcp_server

    class _FakeEngine:
        plan_result = {"solution": "BM25", "search_capabilities": "", "keynote": ""}

    monkeypatch.setattr(mcp_server, "_engine", _FakeEngine())
    mcp_server._eval_state.index_name = "test-index"
    mcp_server._eval_state.suggestion_meta = [
        {"text": "test query", "capability": "exact"},
    ]
    mcp_server._eval_state.judged_results = []
    mcp_server._eval_state.metrics = {}
    mcp_server._eval_state.query_results = []

    prompt = mcp_server._build_evaluation_prompt_from_state(mcp_server._eval_state)

    # Should fall back to legacy verification queries evidence
    assert "test query" in prompt
    assert "[exact]" in prompt


# ---------------------------------------------------------------------------
# format_unjudged_result_table tests
# ---------------------------------------------------------------------------

from opensearch_orchestrator.opensearch_ops_tools import (
    format_unjudged_result_table,
    build_evaluation_attachments,
)


def test_format_unjudged_result_table_basic():
    query_results = [
        {
            "query_text": "Carmencita 1894",
            "capability": "exact",
            "hits": [
                {"id": "doc-1", "score": 10.0, "source": {"primaryTitle": "Carmencita"}},
                {"id": "doc-2", "score": 5.0, "source": {"primaryTitle": "Other"}},
            ],
        },
        {
            "query_text": "runtimeMinutes: 5",
            "capability": "structured",
            "hits": [
                {"id": "doc-3", "score": 0.0, "source": {"runtimeMinutes": "5"}},
            ],
        },
    ]
    table = format_unjudged_result_table(query_results)
    assert "awaiting relevance judgment" in table
    assert "doc-1" in table
    assert "doc-2" in table
    assert "doc-3" in table
    assert "Carmencita 1894" in table
    assert "runtimeMinutes: 5" in table
    assert "? |" in table  # unjudged relevance
    assert "Queries executed: 2" in table
    assert "Queries with hits: 2" in table


def test_format_unjudged_result_table_empty():
    table = format_unjudged_result_table([])
    assert "awaiting relevance judgment" in table
    assert "Queries executed: 0" in table


def test_format_unjudged_result_table_no_hits():
    query_results = [
        {"query_text": "missing", "capability": "semantic", "hits": []},
    ]
    table = format_unjudged_result_table(query_results)
    assert "Queries executed: 1" in table
    assert "Queries with hits: 0" in table


def test_build_evaluation_attachments_uses_unjudged_table_from_diagnostic():
    """When judged_results is empty but diagnostic has query_results, show unjudged table."""
    diagnostic = {
        "manual_judgment_required": True,
        "query_results": [
            {
                "query_text": "test query",
                "capability": "exact",
                "hits": [
                    {"id": "v-1", "score": 1.0, "source": {"title": "Test"}},
                ],
            },
        ],
    }
    attachments = build_evaluation_attachments([], {}, diagnostic, {})
    assert "evaluation_result_table" in attachments
    assert "awaiting relevance judgment" in attachments["evaluation_result_table"]
    assert "v-1" in attachments["evaluation_result_table"]
    assert "No per-query breakdown available" not in attachments["evaluation_result_table"]


def test_build_evaluation_attachments_falls_back_when_no_query_results():
    """When both judged_results and query_results are empty, show fallback message."""
    diagnostic = {"fallback_reason": "no data"}
    attachments = build_evaluation_attachments([], {}, diagnostic, {})
    assert "No per-query breakdown available" in attachments["evaluation_result_table"]
