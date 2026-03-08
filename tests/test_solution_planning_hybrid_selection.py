from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opensearch_launchpad.solution_planning_assistant as planner


def test_extract_hybrid_weight_profile_from_context_line():
    profile = planner._extract_hybrid_weight_profile(
        "Requirements note...\nHybrid Weight Profile: lexical-heavy\nMore context"
    )
    assert profile == "lexical-heavy"


def test_extract_hybrid_weight_profile_returns_empty_when_missing():
    profile = planner._extract_hybrid_weight_profile("No profile in this text.")
    assert profile == ""


def test_planner_confirmation_detects_simple_positive_reply():
    assert planner._looks_like_planner_confirmation("Looks good")


def test_planner_confirmation_rejects_change_request():
    assert not planner._looks_like_planner_confirmation("Looks good, but change the model to MiniLM")


def test_extract_sample_doc_json_from_system_context_line():
    context = (
        "[SYSTEM PRE-PROCESSING RESULT]\n"
        'Sample document: {"title":"Carmencita","isAdult":"0"}\n'
    )
    sample_doc_json = planner._extract_sample_doc_json(context)

    assert sample_doc_json
    assert '"sample_doc"' in sample_doc_json
    assert "Carmencita" in sample_doc_json


def test_extract_sample_doc_json_from_bulleted_context_line():
    context = (
        "Data Profile:\n"
        '- Sample document: {"content":"The quick brown fox"}\n'
    )
    sample_doc_json = planner._extract_sample_doc_json(context)

    assert sample_doc_json
    assert '"sample_doc"' in sample_doc_json
    assert "quick brown fox" in sample_doc_json


def test_extract_sample_doc_json_from_sample_document_structure_line():
    context = (
        "User Requirements:\n"
        '- Sample document structure: {"content":"The quick brown fox"}\n'
    )
    sample_doc_json = planner._extract_sample_doc_json(context)

    assert sample_doc_json
    assert '"sample_doc"' in sample_doc_json
    assert "quick brown fox" in sample_doc_json


def test_filter_search_capabilities_block_keeps_only_applicable_ids():
    capability_block = (
        "- Exact: exact title lookup\n"
        "- Semantic: concept search\n"
        "- Structured: filters\n"
    )
    filtered = planner._filter_search_capabilities_block(
        capability_block,
        ["structured", "exact"],
    )

    assert "- Exact: exact title lookup" in filtered
    assert "- Structured: filters" in filtered
    assert "Semantic" not in filtered


def test_append_capability_precheck_notes_to_keynote():
    keynote = "- User prefers balanced relevance and latency."
    updated = planner._append_capability_precheck_notes(
        keynote,
        [
            {
                "id": "autocomplete",
                "reason": "No compatible fields/values were found in sampled documents.",
            }
        ],
    )

    assert "System-verified capability applicability" in updated
    assert "autocomplete" in updated


def test_system_prompt_blocks_additional_requirement_checklists():
    prompt = planner.SYSTEM_PROMPT

    assert "Do NOT ask these additional requirements checklists" in prompt
    assert "Any specific dashboard or visualization needs?" in prompt
    assert "Do you need real-time ingestion/search requirements?" in prompt
    assert "Any other custom requirements?" in prompt
