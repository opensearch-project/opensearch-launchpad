from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opensearch_launchpad.orchestrator as orchestrator

_EXPECTED_MODEL_DEPLOYMENT_OPTIONS = [
    (
        orchestrator._MODEL_DEPLOYMENT_OPTION_OPENSEARCH_NODE,
        "OpenSearch node (co-located with search cluster, simplest ops)",
    ),
    (
        orchestrator._MODEL_DEPLOYMENT_OPTION_SAGEMAKER_ENDPOINT,
        "SageMaker endpoint (separate compute, more flexible scaling)",
    ),
    (
        orchestrator._MODEL_DEPLOYMENT_OPTION_EXTERNAL_EMBEDDING_API,
        "External embedding API (e.g., OpenAI, Cohere - managed service)",
    ),
]


def test_read_model_deployment_preference_choice_returns_selected_value(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "read_single_choice_input",
        lambda **kwargs: orchestrator._MODEL_DEPLOYMENT_OPTION_EXTERNAL_EMBEDDING_API,
    )
    selected = orchestrator._read_model_deployment_preference_choice()
    assert selected == orchestrator._MODEL_DEPLOYMENT_OPTION_EXTERNAL_EMBEDDING_API


def test_read_model_deployment_preference_choice_normalizes_unknown_to_default(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "read_single_choice_input",
        lambda **kwargs: "unknown",
    )
    selected = orchestrator._read_model_deployment_preference_choice()
    assert selected == orchestrator._MODEL_DEPLOYMENT_OPTION_OPENSEARCH_NODE


def test_read_model_deployment_preference_choice_builds_friendly_prompt_with_detected_fields(
    monkeypatch,
):
    captured: dict[str, object] = {}

    def _fake_read_single_choice_input(**kwargs):
        captured.update(kwargs)
        return orchestrator._MODEL_DEPLOYMENT_OPTION_OPENSEARCH_NODE

    monkeypatch.setattr(orchestrator, "read_single_choice_input", _fake_read_single_choice_input)

    selected = orchestrator._read_model_deployment_preference_choice(
        [" title ", "", "description", "TITLE"]
    )

    assert selected == orchestrator._MODEL_DEPLOYMENT_OPTION_OPENSEARCH_NODE
    assert captured["title"] == "Embedding Model Hosting"
    assert captured["default_value"] == orchestrator._MODEL_DEPLOYMENT_OPTION_OPENSEARCH_NODE
    assert captured["options"] == _EXPECTED_MODEL_DEPLOYMENT_OPTIONS
    prompt = str(captured["prompt"])
    assert prompt.startswith("To enable semantic search, we use an embedding model")
    assert (
        "embedding model (an AI model that turns text into meaning vectors)"
        in prompt
    )
    assert prompt.endswith("For production, where should this embedding model run?")


def test_read_model_deployment_preference_choice_uses_fallback_prompt_without_fields(
    monkeypatch,
):
    captured: dict[str, object] = {}

    def _fake_read_single_choice_input(**kwargs):
        captured.update(kwargs)
        return orchestrator._MODEL_DEPLOYMENT_OPTION_OPENSEARCH_NODE

    monkeypatch.setattr(orchestrator, "read_single_choice_input", _fake_read_single_choice_input)

    selected = orchestrator._read_model_deployment_preference_choice(None)

    assert selected == orchestrator._MODEL_DEPLOYMENT_OPTION_OPENSEARCH_NODE
    prompt = str(captured["prompt"])
    assert prompt.startswith(
        "Your sample data includes text content suitable for semantic search."
    )
    assert (
        "embedding model (an AI model that turns text into meaning vectors)"
        in prompt
    )


def test_build_model_deployment_preference_note_for_sagemaker():
    note = orchestrator._build_model_deployment_preference_note(
        orchestrator._MODEL_DEPLOYMENT_OPTION_SAGEMAKER_ENDPOINT
    )
    assert "SageMaker endpoint" in note
