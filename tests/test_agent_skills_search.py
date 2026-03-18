"""Tests for skills/opensearch-launchpad/scripts/lib/search.py"""

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-launchpad" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.search import (
    _value_shape,
    _text_richness_score,
    extract_index_field_specs,
    _resolve_text_query_fields,
    _resolve_field_spec_for_doc_key,
    _build_default_lexical_query,
    _build_default_lexical_body,
    _build_neural_clause,
    _strip_wrapping_quotes,
    _parse_structured_pairs,
    _parse_structured_clauses,
    _coerce_structured_value,
    _split_structured_clauses,
    _suggestion_candidates_from_doc,
    preview_text,
    generate_suggestions,
    _resolve_autocomplete_fields,
    _source_field_variants,
    _extract_values_from_source_by_path,
    autocomplete,
    search_ui_search,
)


# ---------------------------------------------------------------------------
# Shared field specs
# ---------------------------------------------------------------------------
def _base_field_specs():
    return {
        "primaryTitle": {"type": "text", "normalizer": ""},
        "primaryTitle.keyword": {"type": "keyword", "normalizer": ""},
        "embedding_vector": {"type": "knn_vector", "normalizer": ""},
        "genres": {"type": "keyword", "normalizer": ""},
        "startYear": {"type": "integer", "normalizer": ""},
        "isAdult": {"type": "boolean", "normalizer": ""},
    }


class _FakeClient:
    def __init__(self, search_response=None):
        self.calls = []
        self._search_response = search_response or {
            "hits": {"hits": [], "total": {"value": 0}},
            "took": 1,
        }

    def search(self, index, body, size=10):
        self.calls.append({"index": index, "body": body})
        return self._search_response


# ---------------------------------------------------------------------------
# _value_shape
# ---------------------------------------------------------------------------
def test_value_shape_basic():
    shape = _value_shape("Hello World 123")

    assert shape["token_count"] == 3
    assert shape["looks_numeric"] is False
    assert shape["looks_date"] is False


def test_value_shape_numeric():
    shape = _value_shape("42.5")

    assert shape["looks_numeric"] is True


def test_value_shape_date():
    shape = _value_shape("2024-01-15")

    assert shape["looks_date"] is True


def test_value_shape_empty():
    shape = _value_shape("")

    assert shape["length"] == 0
    assert shape["alpha_ratio"] == 0.0


# ---------------------------------------------------------------------------
# _text_richness_score
# ---------------------------------------------------------------------------
def test_text_richness_score_rich_text():
    score = _text_richness_score("The quick brown fox jumps over the lazy dog")

    assert score > 50


def test_text_richness_score_short_text():
    score = _text_richness_score("X")

    assert score == 0.0


def test_text_richness_score_numeric_text():
    score = _text_richness_score("12345")

    # Numeric text has low alpha ratio so lower score
    assert score < 30


# ---------------------------------------------------------------------------
# extract_index_field_specs
# ---------------------------------------------------------------------------
def test_extract_index_field_specs_walks_properties():
    class _FakeIndices:
        def get_mapping(self, index):
            return {
                "my-index": {
                    "mappings": {
                        "properties": {
                            "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                            "year": {"type": "integer"},
                            "nested": {"properties": {"inner": {"type": "text"}}},
                        }
                    }
                }
            }

    class _Client:
        indices = _FakeIndices()

    specs = extract_index_field_specs(_Client(), "my-index")

    assert specs["title"]["type"] == "text"
    assert specs["title.keyword"]["type"] == "keyword"
    assert specs["year"]["type"] == "integer"
    assert specs["nested.inner"]["type"] == "text"


def test_extract_index_field_specs_handles_exception():
    class _FakeIndices:
        def get_mapping(self, index):
            raise Exception("connection failed")

    class _Client:
        indices = _FakeIndices()

    specs = extract_index_field_specs(_Client(), "missing-index")

    assert specs == {}


# ---------------------------------------------------------------------------
# _resolve_text_query_fields
# ---------------------------------------------------------------------------
def test_resolve_text_query_fields_prefers_text_type():
    specs = _base_field_specs()

    fields = _resolve_text_query_fields(specs)

    assert "primaryTitle" in fields
    assert "primaryTitle.keyword" not in fields


def test_resolve_text_query_fields_falls_back_to_keyword():
    specs = {"genre": {"type": "keyword", "normalizer": ""}}

    fields = _resolve_text_query_fields(specs)

    assert "genre" in fields


def test_resolve_text_query_fields_empty_specs():
    fields = _resolve_text_query_fields({})

    assert fields == ["*"]


# ---------------------------------------------------------------------------
# _resolve_field_spec_for_doc_key
# ---------------------------------------------------------------------------
def test_resolve_field_spec_exact_match():
    specs = _base_field_specs()
    name, spec = _resolve_field_spec_for_doc_key("genres", specs)

    assert name == "genres"
    assert spec["type"] == "keyword"


def test_resolve_field_spec_case_insensitive():
    specs = _base_field_specs()
    name, spec = _resolve_field_spec_for_doc_key("GENRES", specs)

    assert name == "genres"


def test_resolve_field_spec_leaf_match():
    specs = {"nested.field.name": {"type": "text", "normalizer": ""}}
    name, spec = _resolve_field_spec_for_doc_key("name", specs)

    assert name == "nested.field.name"


def test_resolve_field_spec_no_match():
    specs = _base_field_specs()
    name, spec = _resolve_field_spec_for_doc_key("nonexistent", specs)

    assert name == ""
    assert spec == {}


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------
def test_build_default_lexical_query():
    q = _build_default_lexical_query("hello world", ["title", "body"])

    assert q["multi_match"]["query"] == "hello world"
    assert q["multi_match"]["fields"] == ["title", "body"]
    assert q["multi_match"]["fuzziness"] == "AUTO"


def test_build_default_lexical_query_wildcard_no_fuzziness():
    q = _build_default_lexical_query("test", ["*"])

    assert "fuzziness" not in q["multi_match"]


def test_build_default_lexical_body():
    body = _build_default_lexical_body("test", 20, ["title"])

    assert body["size"] == 20
    assert "multi_match" in body["query"]


def test_build_neural_clause():
    clause = _build_neural_clause("search text", "vec_field", "model-1", 5)

    assert "neural" in clause
    neural = clause["neural"]["vec_field"]
    assert neural["query_text"] == "search text"
    assert neural["model_id"] == "model-1"
    assert neural["k"] == 10  # max(5, 10)


def test_build_neural_clause_large_size():
    clause = _build_neural_clause("text", "vec", "m", 50)

    assert clause["neural"]["vec"]["k"] == 50


# ---------------------------------------------------------------------------
# Structured query parsing
# ---------------------------------------------------------------------------
def test_strip_wrapping_quotes_double():
    assert _strip_wrapping_quotes('"hello world"') == "hello world"


def test_strip_wrapping_quotes_single():
    assert _strip_wrapping_quotes("'hello'") == "hello"


def test_strip_wrapping_quotes_none():
    assert _strip_wrapping_quotes("hello") == "hello"


def test_parse_structured_pairs_single():
    pairs = _parse_structured_pairs("genre: Comedy")

    assert pairs == [("genre", "Comedy")]


def test_parse_structured_pairs_multiple():
    pairs = _parse_structured_pairs("genre: Comedy and year: 1999")

    assert len(pairs) == 2
    assert pairs[0] == ("genre", "Comedy")
    assert pairs[1] == ("year", "1999")


def test_parse_structured_pairs_quoted_value():
    pairs = _parse_structured_pairs('title: "The Matrix"')

    assert pairs == [("title", "The Matrix")]


def test_parse_structured_pairs_no_colon():
    pairs = _parse_structured_pairs("free text search")

    assert pairs == []


def test_parse_structured_pairs_invalid_gap():
    pairs = _parse_structured_pairs("garbage genre: Comedy")

    assert pairs == []


def test_coerce_structured_value_integer():
    assert _coerce_structured_value("42", "integer") == 42


def test_coerce_structured_value_float():
    assert _coerce_structured_value("3.14", "float") == 3.14


def test_coerce_structured_value_boolean_true():
    assert _coerce_structured_value("true", "boolean") is True


def test_coerce_structured_value_boolean_false():
    assert _coerce_structured_value("0", "boolean") is False


def test_coerce_structured_value_string():
    assert _coerce_structured_value("hello", "keyword") == "hello"


def test_parse_structured_clauses_text_field():
    specs = {"title": {"type": "text", "normalizer": ""}}
    clauses, err = _parse_structured_clauses("title: Matrix", specs)

    assert err == ""
    assert clauses == [{"match_phrase": {"title": "Matrix"}}]


def test_parse_structured_clauses_keyword_field():
    specs = {"genre": {"type": "keyword", "normalizer": ""}}
    clauses, err = _parse_structured_clauses("genre: Comedy", specs)

    assert err == ""
    assert clauses == [{"term": {"genre": {"value": "Comedy"}}}]


def test_parse_structured_clauses_unrecognized_returns_none():
    specs = {"genre": {"type": "keyword", "normalizer": ""}}
    clauses, err = _parse_structured_clauses("free text", specs)

    assert clauses is None


def test_split_structured_clauses():
    clauses = [
        {"match_phrase": {"title": "test"}},
        {"term": {"year": {"value": 2020}}},
        {"term": {"genre": {"value": "Action"}}},
    ]
    text, filters = _split_structured_clauses(clauses)

    assert len(text) == 1
    assert len(filters) == 2


# ---------------------------------------------------------------------------
# Preview & suggestions
# ---------------------------------------------------------------------------
def test_suggestion_candidates_from_doc():
    doc = {
        "id": 1,
        "title": "The Matrix is a great movie",
        "year": 1999,
        "embedding": [0.1, 0.2],
    }
    candidates = _suggestion_candidates_from_doc(doc)

    assert any("Matrix" in c for c in candidates)


def test_suggestion_candidates_skips_numeric_and_short():
    doc = {"id": "1", "x": "42.5", "date": "2024-01-01"}
    candidates = _suggestion_candidates_from_doc(doc)

    assert candidates == []


def test_preview_text_returns_best_candidate():
    source = {"title": "A great movie about adventure", "id": 1}

    text = preview_text(source)

    assert "great movie" in text


def test_preview_text_empty_source():
    assert preview_text({}) == "(No preview text)"


def test_preview_text_non_dict_values():
    source = {"data": None, "nested": {"a": 1}, "list": [1, 2]}

    assert preview_text(source) == "(No preview text)"


def test_generate_suggestions_returns_deduped(monkeypatch):
    client = _FakeClient(search_response={
        "hits": {
            "hits": [
                {"_source": {"title": "The Matrix movie classic"}},
                {"_source": {"title": "the matrix movie classic"}},  # duplicate
                {"_source": {"title": "Inception is mind bending"}},
            ],
            "total": {"value": 3},
        },
        "took": 1,
    })

    suggestions = generate_suggestions(client, "movies", max_count=6)

    lowered = [s.lower() for s in suggestions]
    assert len(lowered) == len(set(lowered))


def test_generate_suggestions_empty_index():
    client = _FakeClient()

    suggestions = generate_suggestions(client, "", max_count=6)

    assert suggestions == []


# ---------------------------------------------------------------------------
# Autocomplete helpers
# ---------------------------------------------------------------------------
def test_resolve_autocomplete_fields_prefers_keyword():
    specs = {
        "title": {"type": "text", "normalizer": ""},
        "genre": {"type": "keyword", "normalizer": ""},
    }
    fields = _resolve_autocomplete_fields(specs)

    assert fields[0] == "genre"


def test_resolve_autocomplete_fields_with_preferred():
    specs = {
        "title": {"type": "text", "normalizer": ""},
        "genre": {"type": "keyword", "normalizer": ""},
    }
    fields = _resolve_autocomplete_fields(specs, preferred_field="title")

    assert fields[0] == "title"


def test_source_field_variants_keyword_suffix():
    variants = _source_field_variants("title.keyword")

    assert variants == ["title", "title.keyword"]


def test_source_field_variants_plain():
    variants = _source_field_variants("title")

    assert variants == ["title"]


def test_source_field_variants_empty():
    assert _source_field_variants("") == []


def test_extract_values_from_source_simple():
    source = {"title": "Hello", "year": 2024}

    values = _extract_values_from_source_by_path(source, "title")

    assert values == ["Hello"]


def test_extract_values_from_source_nested():
    source = {"meta": {"author": {"name": "Alice"}}}

    values = _extract_values_from_source_by_path(source, "meta.author.name")

    assert values == ["Alice"]


def test_extract_values_from_source_list():
    source = {"tags": ["python", "java"]}

    values = _extract_values_from_source_by_path(source, "tags")

    assert "python" in values
    assert "java" in values


def test_extract_values_from_source_missing_path():
    values = _extract_values_from_source_by_path({"a": 1}, "b.c")

    assert values == []


# ---------------------------------------------------------------------------
# autocomplete
# ---------------------------------------------------------------------------
def test_autocomplete_empty_prefix():
    client = _FakeClient()

    result = autocomplete(client, "my-index", "")

    assert result["options"] == []
    assert result["error"] == ""


def test_autocomplete_empty_index():
    client = _FakeClient()

    result = autocomplete(client, "", "test")

    assert result["options"] == []


def test_autocomplete_returns_matching_options():
    client = _FakeClient(search_response={
        "hits": {
            "hits": [
                {"_source": {"genre": "Comedy"}},
                {"_source": {"genre": "Crime"}},
                {"_source": {"genre": "Action"}},
            ],
            "total": {"value": 3},
        },
        "took": 1,
    })

    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {"genre": {"type": "keyword"}}}}}

    client.indices = _FakeIndices()

    result = autocomplete(client, "idx", "C", preferred_field="genre")

    assert "Comedy" in result["options"]
    assert "Crime" in result["options"]
    assert "Action" not in result["options"]  # doesn't start with "C"


# ---------------------------------------------------------------------------
# search_ui_search — integration
# ---------------------------------------------------------------------------
def test_search_ui_search_match_all_no_query(monkeypatch):
    client = _FakeClient()

    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {"title": {"type": "text"}}}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {}}}}

    client.indices = _FakeIndices()

    result = search_ui_search(client, "idx", "")

    assert result["error"] == ""
    assert result["query_mode"] == "match_all"


def test_search_ui_search_missing_index():
    client = _FakeClient()

    result = search_ui_search(client, "", "test query")

    assert result["error"] == "Missing index name."


def test_search_ui_search_bm25_default(monkeypatch):
    client = _FakeClient()

    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {"title": {"type": "text"}}}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {}}}}

    client.indices = _FakeIndices()

    result = search_ui_search(client, "idx", "hello world")

    assert result["error"] == ""
    assert result["query_mode"] == "bm25_default"
    assert result["used_semantic"] is False
    assert result["capability"] == "manual"


def test_search_ui_search_structured_filter(monkeypatch):
    client = _FakeClient()

    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {
                "startYear": {"type": "integer"},
                "genres": {"type": "keyword"},
            }}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {}}}}

    client.indices = _FakeIndices()

    result = search_ui_search(client, "idx", "startYear: 1999 and genres: Comedy")

    assert result["query_mode"] == "structured_filter"
    assert result["capability"] == "structured"
    assert result["used_semantic"] is False


def test_search_ui_search_hybrid_when_semantic_ready(monkeypatch):
    class _FakeIngest:
        def get_pipeline(self, id):
            return {id: {"processors": [
                {"text_embedding": {
                    "model_id": "model-1",
                    "field_map": {"title": "embedding"},
                }}
            ]}}

    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {
                "title": {"type": "text"},
                "embedding": {"type": "knn_vector"},
            }}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {
                "default_pipeline": "my-ingest",
            }}}}

    client = _FakeClient()
    client.indices = _FakeIndices()
    client.ingest = _FakeIngest()

    result = search_ui_search(client, "idx", "semantic search test")

    assert result["query_mode"] == "hybrid_default"
    assert result["used_semantic"] is True
    assert result["capability"] in ("semantic", "manual")
