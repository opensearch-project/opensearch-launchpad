from pathlib import Path
import sys
import builtins

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opensearch_launchpad.shared as shared


def _read_with_inputs(monkeypatch, values):
    iterator = iter(values)
    monkeypatch.setattr(builtins, "input", lambda _prompt="": next(iterator))
    return shared.read_single_choice_input(
        title="Budget Preference",
        prompt="Choose budget/cost preference for this solution.",
        options=[
            ("flexible", "No strict budget constraints (flexible)"),
            ("cost-sensitive", "Cost-sensitive (prioritize cost-effectiveness)"),
        ],
        default_value="flexible",
    )


def test_read_single_choice_accepts_numeric_input_with_trailing_dot(monkeypatch):
    selected = _read_with_inputs(monkeypatch, ["1."])
    assert selected == "flexible"


def test_read_single_choice_accepts_numeric_input_with_multiple_trailing_dots(monkeypatch):
    selected = _read_with_inputs(monkeypatch, ["1.."])
    assert selected == "flexible"


def test_read_single_choice_accepts_numeric_input_with_trailing_parenthesis(monkeypatch):
    selected = _read_with_inputs(monkeypatch, ["2)"])
    assert selected == "cost-sensitive"
