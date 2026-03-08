from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opensearch_launchpad.orchestrator as orchestrator


_EXPECTED_PREFIX_WILDCARD_OPTIONS = [
    (
        orchestrator._PREFIX_WILDCARD_OPTION_ENABLED,
        "Yes - include prefix/wildcard matching (implies lexical BM25)",
    ),
    (
        orchestrator._PREFIX_WILDCARD_OPTION_DISABLED,
        "No - semantic/structured search only for this capability",
    ),
]


def test_read_prefix_wildcard_preference_choice_returns_enabled_when_selected(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "read_single_choice_input",
        lambda **kwargs: orchestrator._PREFIX_WILDCARD_OPTION_ENABLED,
    )
    selected = orchestrator._read_prefix_wildcard_preference_choice()
    assert selected is True


def test_read_prefix_wildcard_preference_choice_defaults_to_disabled_on_unknown(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "read_single_choice_input",
        lambda **kwargs: "unexpected-value",
    )
    selected = orchestrator._read_prefix_wildcard_preference_choice()
    assert selected is False


def test_read_prefix_wildcard_preference_choice_builds_prompt_with_text_fields(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_read_single_choice_input(**kwargs):
        captured.update(kwargs)
        return orchestrator._PREFIX_WILDCARD_OPTION_DISABLED

    monkeypatch.setattr(orchestrator, "read_single_choice_input", _fake_read_single_choice_input)

    selected = orchestrator._read_prefix_wildcard_preference_choice(
        [" title ", "", "description", "TITLE"]
    )

    assert selected is False
    assert captured["title"] == "Prefix/Wildcard Matching"
    assert captured["default_value"] == orchestrator._PREFIX_WILDCARD_OPTION_DISABLED
    assert captured["options"] == _EXPECTED_PREFIX_WILDCARD_OPTIONS
    prompt = str(captured["prompt"])
    assert prompt.startswith(
        "From your sample data, fields like title, description look text-heavy."
    )
    assert "implies lexical BM25 support" in prompt


def test_build_prefix_wildcard_requirement_note_enabled_mentions_bm25():
    note = orchestrator._build_prefix_wildcard_requirement_note(True)
    assert "prefix/wildcard matching preference = enabled" in note
    assert "Include lexical BM25 capability" in note


def test_build_prefix_wildcard_requirement_note_disabled_avoids_forcing_bm25():
    note = orchestrator._build_prefix_wildcard_requirement_note(False)
    assert "prefix/wildcard matching preference = disabled" in note
    assert "Do NOT force lexical BM25 solely for prefix/wildcard support." in note
