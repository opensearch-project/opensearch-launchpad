from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opensearch_launchpad.planning_session as planning_session


class _StubAgent:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.calls = 0

    def __call__(self, _prompt: str) -> str:
        self.calls += 1
        return self._response_text


def _planning_complete_response() -> str:
    return (
        "<planning_complete>"
        "<solution>- Retrieval Method: lexical BM25</solution>"
        "<search_capabilities>- Exact: keyword match</search_capabilities>"
        "<keynote>- done</keynote>"
        "</planning_complete>"
    )


def test_start_planning_stops_after_internal_retry_limit(monkeypatch) -> None:
    stub_agent = _StubAgent(_planning_complete_response())
    monkeypatch.setattr(planning_session, "_create_planner_agent", lambda: stub_agent)
    session = planning_session.PlanningSession()
    session._internal_retry_limit = 3

    result = session.start("sample context")

    assert result["is_complete"] is False
    assert result["result"] is None
    assert "retry limit" in result["response"].lower()
    assert stub_agent.calls == 3


def test_start_planning_returns_non_final_response_without_retry(monkeypatch) -> None:
    stub_agent = _StubAgent("Initial proposal. Please review.")
    monkeypatch.setattr(planning_session, "_create_planner_agent", lambda: stub_agent)
    session = planning_session.PlanningSession()

    result = session.start("sample context")

    assert result == {
        "response": "Initial proposal. Please review.",
        "is_complete": False,
        "result": None,
    }
    assert stub_agent.calls == 1
