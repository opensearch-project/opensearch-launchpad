from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opensearch_launchpad.orchestrator as orchestrator


def test_system_prompt_includes_additional_requirements_defaults_section():
    prompt = orchestrator.SYSTEM_PROMPT

    assert "Additional Requirements Defaults" in prompt
    assert "Assume no specific dashboard or visualization requirement" in prompt
    assert "Assume real-time ingestion/search is required" in prompt
    assert "Assume no additional custom requirements unless the user explicitly provides them." in prompt


def test_additional_default_notes_have_stable_requirement_prefixes():
    assert orchestrator._DEFAULT_QUERY_SUPPORT_SCOPE_NOTE.startswith(
        orchestrator._DEFAULT_QUERY_SUPPORT_SCOPE_NOTE_PREFIX
    )
    assert orchestrator._DEFAULT_DASHBOARD_REQUIREMENT_NOTE.startswith(
        orchestrator._DEFAULT_DASHBOARD_REQUIREMENT_NOTE_PREFIX
    )
    assert orchestrator._DEFAULT_REALTIME_REQUIREMENT_NOTE.startswith(
        orchestrator._DEFAULT_REALTIME_REQUIREMENT_NOTE_PREFIX
    )
    assert orchestrator._DEFAULT_CUSTOM_REQUIREMENTS_NOTE.startswith(
        orchestrator._DEFAULT_CUSTOM_REQUIREMENTS_NOTE_PREFIX
    )
