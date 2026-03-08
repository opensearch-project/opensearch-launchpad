from opensearch_launchpad.handler import ThinkingCallbackHandler


def test_callback_logs_do_not_write_stdout(capsys):
    handler = ThinkingCallbackHandler(show_reasoning=True)

    handler(
        reasoningText="reasoning",
        data="response",
        complete=True,
        current_tool_use={"name": "read_knowledge_base"},
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "reasoning" in captured.err
    assert "response" in captured.err
    assert "Tool #1: read_knowledge_base." in captured.err
