from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opensearch_launchpad.opensearch_ops_tools as tools


class FakeClient:
    def __init__(self):
        self.calls = []

    def search(self, index, body):
        self.calls.append({"index": index, "body": body})
        return {
            "hits": {
                "hits": [],
                "total": {"value": 0},
            },
            "took": 3,
        }


class FakeAutocompleteClient:
    def __init__(self, hits):
        self.calls = []
        self._hits = hits

    def search(self, index, body):
        self.calls.append({"index": index, "body": body})
        return {
            "hits": {
                "hits": self._hits,
                "total": {"value": len(self._hits)},
            },
            "took": 2,
        }



class FakeSuggestionClient:
    def __init__(self):
        self.calls = []

    def search(self, index, body):
        self.calls.append({"index": index, "body": body})
        return {
            "hits": {
                "hits": [
                    {"_source": {"title": "Completely unrelated fallback suggestion"}},
                ],
                "total": {"value": 1},
            },
            "took": 1,
        }



def _base_field_specs():
    return {
        "primaryTitle": {"type": "text", "normalizer": ""},
        "primaryTitle.keyword": {"type": "keyword", "normalizer": ""},
        "embedding_vector": {"type": "knn_vector", "normalizer": ""},
        "genres": {"type": "keyword", "normalizer": ""},
        "startYear": {"type": "integer", "normalizer": ""},
        "VendorID": {"type": "integer", "normalizer": ""},
        "tpep_pickup_datetime": {"type": "date", "normalizer": ""},
    }



def test_suggestion_api_returns_meta_tuple(monkeypatch):
    index_name = "imdb_movies"
    tools._search_ui.suggestion_meta_by_index[index_name] = [
        {
            "text": "romantic comedies from the 90s",
            "capability": "semantic",
            "query_mode": "hybrid",
            "field": "primaryTitle",
            "value": "",
            "case_insensitive": False,
        }
    ]

    class _NoClient:
        pass

    monkeypatch.setattr(tools, "_create_client", lambda: _NoClient())

    suggestions, suggestion_meta = tools._search_ui_suggestions(index_name=index_name, max_count=6)

    assert suggestions
    assert suggestions[0] == "romantic comedies from the 90s"
    assert suggestion_meta
    assert suggestion_meta[0]["capability"] == "semantic"



def test_suggestion_api_does_not_fallback_when_explicit_meta_is_empty(monkeypatch):
    index_name = "wikipedia"
    tools._search_ui.suggestion_meta_by_index[index_name] = []
    client = FakeSuggestionClient()

    monkeypatch.setattr(tools, "_create_client", lambda: client)

    suggestions, suggestion_meta = tools._search_ui_suggestions(index_name=index_name, max_count=6)

    assert suggestions == []
    assert suggestion_meta == []
    assert client.calls == []



def test_suggestion_api_does_not_mix_index_fallback_when_explicit_meta_exists(monkeypatch):
    index_name = "wikipedia"
    tools._search_ui.suggestion_meta_by_index[index_name] = [
        {
            "text": "ada lovelace",
            "capability": "semantic",
            "query_mode": "hybrid",
            "field": "title",
            "value": "",
            "case_insensitive": False,
        }
    ]
    client = FakeSuggestionClient()

    monkeypatch.setattr(tools, "_create_client", lambda: client)

    suggestions, suggestion_meta = tools._search_ui_suggestions(index_name=index_name, max_count=6)

    assert suggestions == ["ada lovelace"]
    assert len(suggestion_meta) == 1
    assert suggestion_meta[0]["capability"] == "semantic"
    assert client.calls == []



def test_semantic_chip_routes_to_hybrid(monkeypatch):
    client = FakeClient()
    index_name = "imdb_movies"
    tools._search_ui.suggestion_meta_by_index[index_name] = [
        {
            "text": "romantic paris films",
            "capability": "semantic",
            "query_mode": "hybrid",
            "field": "primaryTitle",
            "value": "",
            "case_insensitive": False,
        }
    ]

    monkeypatch.setattr(tools, "_create_client", lambda: client)
    monkeypatch.setattr(tools, "_extract_index_field_specs", lambda *_: _base_field_specs())
    monkeypatch.setattr(
        tools,
        "_resolve_semantic_runtime_hints",
        lambda *_: {
            "vector_field": "embedding_vector",
            "model_id": "model-123",
            "default_pipeline": "imdb_hybrid_pipeline",
            "source_field": "combined_text",
        },
    )

    result = tools._search_ui_search(
        index_name=index_name,
        query_text="romantic paris films",
        size=10,
        debug=True,
    )

    assert result["error"] == ""
    assert result["query_mode"] == "semantic_hybrid"
    assert result["used_semantic"] is True
    assert result["capability"] == "semantic"

    assert client.calls
    query = client.calls[-1]["body"]["query"]
    assert "hybrid" in query
    queries = query["hybrid"]["queries"]
    assert any("neural" in item for item in queries)



def test_manual_query_defaults_to_hybrid(monkeypatch):
    client = FakeClient()
    tools._search_ui.suggestion_meta_by_index.clear()

    monkeypatch.setattr(tools, "_create_client", lambda: client)
    monkeypatch.setattr(tools, "_extract_index_field_specs", lambda *_: _base_field_specs())
    monkeypatch.setattr(
        tools,
        "_resolve_semantic_runtime_hints",
        lambda *_: {
            "vector_field": "embedding_vector",
            "model_id": "model-456",
            "default_pipeline": "imdb_hybrid_pipeline",
            "source_field": "combined_text",
        },
    )

    result = tools._search_ui_search(
        index_name="imdb_movies",
        query_text="space exploration documentaries",
        size=10,
        debug=True,
    )

    assert result["query_mode"] == "hybrid_default"
    assert result["capability"] == "manual"
    assert result["used_semantic"] is True
    assert "hybrid" in result["query_body"]["query"]



def test_manual_structured_query_routes_to_structured_filter(monkeypatch):
    client = FakeClient()
    tools._search_ui.suggestion_meta_by_index.clear()

    monkeypatch.setattr(tools, "_create_client", lambda: client)
    monkeypatch.setattr(tools, "_extract_index_field_specs", lambda *_: _base_field_specs())
    monkeypatch.setattr(
        tools,
        "_resolve_semantic_runtime_hints",
        lambda *_: {
            "vector_field": "embedding_vector",
            "model_id": "model-456",
            "default_pipeline": "imdb_hybrid_pipeline",
            "source_field": "combined_text",
        },
    )

    result = tools._search_ui_search(
        index_name="imdb_movies",
        query_text="VendorID: 2 and tpep_pickup_datetime: 2024-12-01T00:12:27",
        size=10,
        debug=True,
    )

    assert result["query_mode"] == "structured_filter"
    assert result["capability"] == "structured"
    assert result["used_semantic"] is False
    assert result["query_body"]["query"]["bool"]["filter"] == [
        {"term": {"VendorID": {"value": 2}}},
        {"term": {"tpep_pickup_datetime": {"value": "2024-12-01T00:12:27"}}},
    ]


def test_exact_chip_keeps_exact_term_query(monkeypatch):
    client = FakeClient()
    index_name = "imdb_movies"
    tools._search_ui.suggestion_meta_by_index[index_name] = [
        {
            "text": "tt000013",
            "capability": "exact",
            "query_mode": "term",
            "field": "tconst.keyword",
            "value": "",
            "case_insensitive": False,
        }
    ]

    monkeypatch.setattr(tools, "_create_client", lambda: client)
    monkeypatch.setattr(tools, "_extract_index_field_specs", lambda *_: _base_field_specs())
    monkeypatch.setattr(
        tools,
        "_resolve_semantic_runtime_hints",
        lambda *_: {
            "vector_field": "embedding_vector",
            "model_id": "model-xyz",
            "default_pipeline": "imdb_hybrid_pipeline",
            "source_field": "combined_text",
        },
    )

    result = tools._search_ui_search(index_name=index_name, query_text="tt000013", size=10, debug=True)

    assert result["query_mode"] == "exact_term"
    assert result["used_semantic"] is False
    query = result["query_body"]["query"]
    assert "term" in query
    assert query["term"]["tconst.keyword"]["value"] == "tt000013"



def test_autocomplete_selection_routes_to_exact_term_on_keyword_field(monkeypatch):
    client = FakeClient()
    tools._search_ui.suggestion_meta_by_index.clear()

    monkeypatch.setattr(tools, "_create_client", lambda: client)
    monkeypatch.setattr(
        tools,
        "_extract_index_field_specs",
        lambda *_: {
            "url": {"type": "keyword", "normalizer": ""},
            "text_embedding": {"type": "knn_vector", "normalizer": ""},
        },
    )
    monkeypatch.setattr(
        tools,
        "_resolve_semantic_runtime_hints",
        lambda *_: {
            "vector_field": "text_embedding",
            "model_id": "model-123",
            "default_pipeline": "wiki_hybrid_search_pipeline",
            "source_field": "text",
        },
    )

    selected_value = "https://en.wikipedia.org/wiki/Ada"
    result = tools._search_ui_search(
        index_name="wiki_docs",
        query_text=selected_value,
        size=10,
        debug=True,
        search_intent="autocomplete_selection",
        field_hint="url",
    )

    assert result["error"] == ""
    assert result["capability"] == "exact"
    assert result["query_mode"] == "exact_term"
    assert result["query_body"]["query"]["term"]["url"]["value"] == selected_value


def test_autocomplete_selection_prefers_keyword_subfield_for_text_field(monkeypatch):
    client = FakeClient()
    tools._search_ui.suggestion_meta_by_index.clear()

    monkeypatch.setattr(tools, "_create_client", lambda: client)
    monkeypatch.setattr(
        tools,
        "_extract_index_field_specs",
        lambda *_: {
            "title": {"type": "text", "normalizer": ""},
            "title.keyword": {"type": "keyword", "normalizer": ""},
            "text_embedding": {"type": "knn_vector", "normalizer": ""},
        },
    )
    monkeypatch.setattr(
        tools,
        "_resolve_semantic_runtime_hints",
        lambda *_: {
            "vector_field": "text_embedding",
            "model_id": "model-123",
            "default_pipeline": "wiki_hybrid_search_pipeline",
            "source_field": "text",
        },
    )

    selected_value = "Ada Lovelace"
    result = tools._search_ui_search(
        index_name="wiki_docs",
        query_text=selected_value,
        size=10,
        debug=True,
        search_intent="autocomplete_selection",
        field_hint="title",
    )

    assert result["error"] == ""
    assert result["capability"] == "exact"
    assert result["query_mode"] == "exact_term"
    assert result["query_body"]["query"]["term"]["title.keyword"]["value"] == selected_value


def test_semantic_falls_back_to_bm25_when_runtime_missing(monkeypatch):
    client = FakeClient()
    index_name = "imdb_movies"
    tools._search_ui.suggestion_meta_by_index[index_name] = [
        {
            "text": "romantic paris films",
            "capability": "semantic",
            "query_mode": "hybrid",
            "field": "primaryTitle",
            "value": "",
            "case_insensitive": False,
        }
    ]

    monkeypatch.setattr(tools, "_create_client", lambda: client)
    monkeypatch.setattr(tools, "_extract_index_field_specs", lambda *_: _base_field_specs())
    monkeypatch.setattr(
        tools,
        "_resolve_semantic_runtime_hints",
        lambda *_: {
            "vector_field": "embedding_vector",
            "model_id": "",
            "default_pipeline": "imdb_hybrid_pipeline",
            "source_field": "combined_text",
        },
    )

    result = tools._search_ui_search(
        index_name=index_name,
        query_text="romantic paris films",
        size=10,
        debug=True,
    )

    assert result["query_mode"] == "semantic_bm25_fallback"
    assert result["used_semantic"] is False
    assert "semantic runtime unresolved" in result["fallback_reason"]
    assert "multi_match" in result["query_body"]["query"]


def test_combined_uses_structured_filter_when_semantic_runtime_missing(monkeypatch):
    client = FakeClient()
    index_name = "imdb_movies"
    tools._search_ui.suggestion_meta_by_index[index_name] = [
        {
            "text": "startYear: 1969 and genres: Documentary",
            "capability": "combined",
            "query_mode": "hybrid_structured",
            "field": "startYear",
            "value": "1969",
            "case_insensitive": False,
        }
    ]

    monkeypatch.setattr(tools, "_create_client", lambda: client)
    monkeypatch.setattr(tools, "_extract_index_field_specs", lambda *_: _base_field_specs())
    monkeypatch.setattr(
        tools,
        "_resolve_semantic_runtime_hints",
        lambda *_: {
            "vector_field": "embedding_vector",
            "model_id": "",
            "default_pipeline": "imdb_hybrid_pipeline",
            "source_field": "combined_text",
        },
    )

    result = tools._search_ui_search(
        index_name=index_name,
        query_text="startYear: 1969 and genres: Documentary",
        size=10,
        debug=True,
    )

    assert result["query_mode"] == "combined_lexical_filter"
    assert result["capability"] == "combined"
    assert result["used_semantic"] is False
    assert "semantic runtime unresolved" in result["fallback_reason"]
    assert "bool" in result["query_body"]["query"]
    assert "must" not in result["query_body"]["query"]["bool"]
    assert result["query_body"]["query"]["bool"]["filter"] == [
        {"term": {"startYear": {"value": 1969}}},
        {"term": {"genres": {"value": "Documentary"}}},
    ]


def test_combined_structured_only_query_uses_filter_when_semantic_ready(monkeypatch):
    client = FakeClient()
    index_name = "imdb_movies"
    tools._search_ui.suggestion_meta_by_index[index_name] = [
        {
            "text": "VendorID: 2 and passenger_count: 1",
            "capability": "combined",
            "query_mode": "hybrid_structured",
            "field": "VendorID",
            "value": "2",
            "case_insensitive": False,
        }
    ]

    monkeypatch.setattr(tools, "_create_client", lambda: client)
    monkeypatch.setattr(
        tools,
        "_extract_index_field_specs",
        lambda *_: {
            "VendorID": {"type": "integer", "normalizer": ""},
            "passenger_count": {"type": "integer", "normalizer": ""},
            "embedding_vector": {"type": "knn_vector", "normalizer": ""},
        },
    )
    monkeypatch.setattr(
        tools,
        "_resolve_semantic_runtime_hints",
        lambda *_: {
            "vector_field": "embedding_vector",
            "model_id": "model-abc",
            "default_pipeline": "imdb_hybrid_pipeline",
            "source_field": "combined_text",
        },
    )

    result = tools._search_ui_search(
        index_name=index_name,
        query_text="VendorID: 2 and passenger_count: 1",
        size=10,
        debug=True,
    )

    assert result["query_mode"] == "combined_structured_filter"
    assert result["capability"] == "combined"
    assert result["used_semantic"] is False
    assert "bool" in result["query_body"]["query"]
    assert "must" not in result["query_body"]["query"]["bool"]
    assert result["query_body"]["query"]["bool"]["filter"] == [
        {"term": {"VendorID": {"value": 2}}},
        {"term": {"passenger_count": {"value": 1}}},
    ]


def test_autocomplete_returns_prefix_options_for_keyword_field(monkeypatch):
    client = FakeAutocompleteClient(
        [
            {"_source": {"tconst": "tt0000001", "primaryTitle": "Carmencita"}},
            {"_source": {"tconst": "tt0012345", "primaryTitle": "Le clown et ses chiens"}},
            {"_source": {"tconst": "nm9999999", "primaryTitle": "Not matching prefix"}},
        ]
    )

    monkeypatch.setattr(tools, "_create_client", lambda: client)
    monkeypatch.setattr(
        tools,
        "_extract_index_field_specs",
        lambda *_: {
            "tconst": {"type": "keyword", "normalizer": ""},
            "primaryTitle": {"type": "text", "normalizer": ""},
        },
    )

    result = tools._search_ui_autocomplete(
        index_name="imdb_movies",
        prefix_text="tt",
        size=5,
        preferred_field="tconst",
    )

    assert result["error"] == ""
    assert result["field"] == "tconst"
    assert result["options"] == ["tt0000001", "tt0012345"]
    assert client.calls
    should = client.calls[-1]["body"]["query"]["bool"]["should"]
    assert any("prefix" in clause and "tconst" in clause["prefix"] for clause in should)


def test_autocomplete_reads_source_value_for_keyword_subfield(monkeypatch):
    client = FakeAutocompleteClient(
        [
            {"_source": {"tconst": "tt0000100"}},
            {"_source": {"tconst": "tt0000200"}},
        ]
    )

    monkeypatch.setattr(tools, "_create_client", lambda: client)
    monkeypatch.setattr(
        tools,
        "_extract_index_field_specs",
        lambda *_: {
            "tconst.keyword": {"type": "keyword", "normalizer": ""},
        },
    )

    result = tools._search_ui_autocomplete(
        index_name="imdb_movies",
        prefix_text="tt0",
        size=5,
        preferred_field="tconst.keyword",
    )

    assert result["error"] == ""
    assert result["options"] == ["tt0000100", "tt0000200"]
