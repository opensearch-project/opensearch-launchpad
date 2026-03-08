from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opensearch_launchpad.worker as worker
from opensearch_launchpad.shared import clear_last_worker_run_state, get_last_worker_run_state


def test_extract_hybrid_weight_profile_parses_supported_values():
    context = """
    - Retrieval Method: Hybrid Search (Dense Vector + BM25)
    - Hybrid Weight Profile: semantic-heavy
    """

    profile = worker._extract_hybrid_weight_profile(context)

    assert profile == "semantic-heavy"


def test_resolve_hybrid_weights_semantic_heavy_lexical_semantic_scope():
    context = """
    - Retrieval Method: Hybrid Search (Dense Vector + BM25)
    - Hybrid Weight Profile: semantic-heavy
    """

    enabled, weights, profile = worker._resolve_hybrid_search_pipeline_weights(context)

    assert enabled is True
    assert weights == [0.2, 0.8]
    assert profile == "semantic-heavy"


def test_resolve_hybrid_weights_lexical_heavy_lexical_semantic_scope():
    context = """
    - Retrieval Method: Hybrid Search (Dense Vector + BM25)
    - Hybrid Weight Profile: lexical-heavy
    """

    enabled, weights, profile = worker._resolve_hybrid_search_pipeline_weights(context)

    assert enabled is True
    assert weights == [0.8, 0.2]
    assert profile == "lexical-heavy"


def test_resolve_hybrid_weights_defaults_to_balanced_when_profile_missing():
    context = """
    - Retrieval Method: Hybrid Search (Dense Vector + BM25)
    - Score Normalization: Min-Max or L2
    """

    enabled, weights, profile = worker._resolve_hybrid_search_pipeline_weights(context)

    assert enabled is True
    assert weights == [0.5, 0.5]
    assert profile == "balanced"


def test_resolve_hybrid_weights_not_enabled_for_dense_sparse_only_hybrid():
    context = """
    - Retrieval Method: Hybrid Search (Dense Vector + Sparse Vector)
    - No BM25 component
    """

    enabled, weights, profile = worker._resolve_hybrid_search_pipeline_weights(context)

    assert enabled is False
    assert weights == [0.5, 0.5]
    assert profile == ""


def test_resolve_hybrid_weights_not_enabled_for_non_hybrid():
    context = """
    - Retrieval Method: Dense Vector
    - Model: amazon.titan-embed-text-v2
    """

    enabled, weights, profile = worker._resolve_hybrid_search_pipeline_weights(context)

    assert enabled is False
    assert weights == [0.5, 0.5]
    assert profile == ""


def test_resolve_localhost_source_protection_from_source_line_with_quotes():
    context = """
    - Retrieval Method: Structured filtering and aggregations only
    - Source: localhost OpenSearch index 'yellow-tripdata'
    """

    enabled, source_index = worker._resolve_localhost_source_protection(context)

    assert enabled is True
    assert source_index == "yellow-tripdata"


def test_resolve_localhost_source_protection_from_source_line_without_quotes():
    context = """
    Source: localhost OpenSearch index yellow_tripdata_v2
    """

    enabled, source_index = worker._resolve_localhost_source_protection(context)

    assert enabled is True
    assert source_index == "yellow_tripdata_v2"


def test_resolve_localhost_source_protection_from_numbered_markdown_source_line():
    context = """
    4. **Source**: localhost OpenSearch index 'yellow-tripdata'
    """

    enabled, source_index = worker._resolve_localhost_source_protection(context)

    assert enabled is True
    assert source_index == "yellow-tripdata"


def test_resolve_source_local_file_from_json_context():
    context = '{"source_local_file": "opensearch_launchpad/sample_data/imdb.title.basics.tsv"}'

    resolved = worker._resolve_source_local_file(context)

    assert resolved == "opensearch_launchpad/sample_data/imdb.title.basics.tsv"


def test_resolve_source_local_file_from_status_text():
    context = "Sample document loaded from 'opensearch_launchpad/sample_data/imdb.title.basics.tsv'."

    resolved = worker._resolve_source_local_file(context)

    assert resolved == "opensearch_launchpad/sample_data/imdb.title.basics.tsv"


def test_resolve_source_local_file_from_dataset_source_line_with_absolute_path():
    context = """
    Dataset Profile:
    - Source: /Users/kaituo/Downloads/wikipedia.parquet
    - Record count: 156,289 records
    """

    resolved = worker._resolve_source_local_file(context)

    assert resolved == "/Users/kaituo/Downloads/wikipedia.parquet"


def test_resolve_source_local_file_from_source_line_with_descriptive_text():
    context = """
    Dataset Profile:
    - Source: Wikipedia articles parquet file (/Users/kaituo/Downloads/wikipedia.parquet)
    """

    resolved = worker._resolve_source_local_file(context)

    assert resolved == "/Users/kaituo/Downloads/wikipedia.parquet"


def test_resolve_source_local_file_from_builtin_sample_hint():
    context = (
        "Dataset: IMDb title basics "
        "(built-in sample: opensearch_launchpad/sample_data/imdb.title.basics.tsv)"
    )

    resolved = worker._resolve_source_local_file(context)

    assert resolved == "opensearch_launchpad/sample_data/imdb.title.basics.tsv"


def test_contains_model_memory_failure_detects_expected_signals():
    response_text = (
        "Model deployment failed: native memory circuit_breaking_exception. "
        "The model deployment has failed due to memory constraints on the OpenSearch cluster."
    )

    assert worker._contains_model_memory_failure(response_text) is True


def test_enforce_model_setup_failure_policy_blocks_lexical_fallback():
    response_text = (
        "The model deployment has failed due to memory constraints on the OpenSearch cluster. "
        "Proceeding with a lexical-only fallback."
    )
    report = {
        "status": "success",
        "steps": {
            "model_setup": "success",
            "index_setup": "success",
            "pipeline_setup": "success",
            "capability_precheck": "success",
            "ui_launch": "success",
        },
        "failed_step": "",
        "notes": [],
    }

    normalized_text, normalized_report = worker._enforce_model_setup_failure_policy(response_text, report)

    assert "reconnect docker" in normalized_text.lower()
    assert normalized_report["status"] == "failed"
    assert normalized_report["failed_step"] == "model_setup"


def test_extract_sample_doc_json_from_context_sample_document_line():
    context = (
        "[SYSTEM PRE-PROCESSING RESULT]\n"
        'Sample document: {"title":"Example","year":"2024"}\n'
    )

    sample_doc_json = worker._extract_sample_doc_json(context)

    assert sample_doc_json
    assert '"sample_doc"' in sample_doc_json
    assert "Example" in sample_doc_json


def test_extract_sample_doc_json_from_bulleted_sample_document_line():
    context = (
        "Data Profile:\n"
        '- Sample document: {"title":"Example Bullet","year":"2024"}\n'
    )

    sample_doc_json = worker._extract_sample_doc_json(context)

    assert sample_doc_json
    assert '"sample_doc"' in sample_doc_json
    assert "Example Bullet" in sample_doc_json


def test_extract_sample_doc_json_from_sample_document_structure_line():
    context = (
        "User Requirements:\n"
        '- Sample document structure: {"title":"Structured Example","year":"2024"}\n'
    )

    sample_doc_json = worker._extract_sample_doc_json(context)

    assert sample_doc_json
    assert '"sample_doc"' in sample_doc_json
    assert "Structured Example" in sample_doc_json


def test_extract_sample_doc_json_from_embedded_sample_doc_payload():
    context = (
        '{"status":"Sample document stored.",'
        '"sample_doc":{"title":"Payload Sample","description":"alpha"}}'
    )

    sample_doc_json = worker._extract_sample_doc_json(context)

    assert sample_doc_json
    assert "Payload Sample" in sample_doc_json


def test_resolve_resume_source_defaults_from_checkpoint_state():
    previous_state = {
        "source_local_file": "opensearch_launchpad/sample_data/imdb.title.basics.tsv",
        "source_index_name": "imdb_titles",
        "sample_doc_json": '{"sample_doc":{"primaryTitle":"Carmencita"}}',
    }

    source_local_file, source_index_name, sample_doc_json = worker._resolve_resume_source_defaults(
        previous_state
    )

    assert source_local_file == "opensearch_launchpad/sample_data/imdb.title.basics.tsv"
    assert source_index_name == "imdb_titles"
    assert "Carmencita" in sample_doc_json


def test_store_worker_run_state_persists_source_metadata():
    clear_last_worker_run_state()
    context = (
        "Source: opensearch_launchpad/sample_data/imdb.title.basics.tsv\n"
        'Sample document: {"primaryTitle":"Carmencita"}\n'
        "Search Capabilities:\n"
        "- Exact: title lookup"
    )
    report = {
        "status": "failed",
        "steps": {
            "model_setup": "success",
            "index_setup": "failed",
            "pipeline_setup": "skipped",
            "capability_precheck": "skipped",
            "ui_launch": "skipped",
        },
        "failed_step": "index_setup",
        "notes": [],
    }

    worker._store_worker_run_state(context, report, "<execution_report>{}</execution_report>")
    stored = get_last_worker_run_state()

    assert stored.get("source_local_file") == "opensearch_launchpad/sample_data/imdb.title.basics.tsv"
    assert stored.get("source_index_name", "") == ""
    assert "sample_doc" in str(stored.get("sample_doc_json", ""))
