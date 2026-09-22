import pytest
from pydantic_ai.messages import (
    ModelRequest, ModelResponse, TextPart, ToolReturnPart, UserPromptPart,
)

from yaac import history


def _user(text: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _tool_result(content: str) -> ModelRequest:
    return ModelRequest(parts=[
        ToolReturnPart(tool_name="read_file", content=content, tool_call_id="1"),
    ])


def _assistant(text: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=text)])


def test_trim_tool_results_truncates_only_oversized_results():
    messages = [_user("hi"), _tool_result("x" * 5_000), _tool_result("short")]

    trimmed = history.trim_tool_results(messages)

    assert trimmed[0] is messages[0]
    assert len(trimmed[1].parts[0].content) < 5_000
    assert "truncated" in trimmed[1].parts[0].content
    assert trimmed[2].parts[0].content == "short"


def test_prune_old_tool_results_keeps_recent_messages_intact():
    old = [_tool_result("y" * 200) for _ in range(5)]
    recent = [_tool_result("z" * 200) for _ in range(3)]

    pruned = history.prune_old_tool_results(old + recent, keep_recent=3)

    assert all(m.parts[0].content == "[output omitted]" for m in pruned[:5])
    assert all(m.parts[0].content == "z" * 200 for m in pruned[5:])


def test_trim_history_drops_leading_orphan_tool_results():
    messages = [_user(f"turn {i}") for i in range(history._MAX_HISTORY_MESSAGES)]
    messages += [_tool_result("orphan"), _assistant("done"), _user("last")]

    trimmed = history.trim_history(messages)

    assert len(trimmed) <= history._MAX_HISTORY_MESSAGES
    assert isinstance(trimmed[0], ModelRequest)
    assert any(isinstance(p, UserPromptPart) for p in trimmed[0].parts)


def test_save_and_load_history_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    messages = [_user("hello"), _assistant("hi there")]

    history.save_history(messages)
    loaded = history.load_history()

    assert (tmp_path / ".yaac" / "history.json").exists()
    assert [m.parts[0].content for m in loaded] == ["hello", "hi there"]

    history.clear_history()
    assert history.load_history() == []


def test_load_history_ignores_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".yaac" / "history.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json")

    assert history.load_history() == []
