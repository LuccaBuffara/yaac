"""Conversation history persistence for YAAC.

Saves and loads the full message history to .yaac/history.json in the
working directory, so conversations persist across sessions.
"""

from dataclasses import replace
from pathlib import Path
from pydantic_ai.messages import ModelMessagesTypeAdapter

HELENA_DIR = ".yaac"
HISTORY_FILE = "history.json"

# Tool results larger than this are truncated in stored history.
_MAX_TOOL_RESULT_CHARS = 1_500
# Oldest messages are dropped when this limit is exceeded.
_MAX_HISTORY_MESSAGES = 25   # ~12 turns
# Messages beyond the last N have their tool outputs stripped to "[omitted]".
_PRUNE_OLD_AFTER = 10
# Compact history when input token usage exceeds this fraction of context window.
_COMPACT_THRESHOLD = 0.65


def _history_path() -> Path:
    return Path.cwd() / HELENA_DIR / HISTORY_FILE


def trim_tool_results(messages: list) -> list:
    """Return a copy of messages with oversized tool results truncated.

    Only ToolReturnPart content is touched; everything else is left intact.
    This is applied when saving and when reloading history so that old large
    results don't keep burning input tokens every turn.
    """
    from pydantic_ai.messages import ModelRequest, ToolReturnPart

    out = []
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            out.append(msg)
            continue
        new_parts = list(msg.parts)
        changed = False
        for part in msg.parts:
            if (
                isinstance(part, ToolReturnPart)
                and isinstance(part.content, str)
                and len(part.content) > _MAX_TOOL_RESULT_CHARS
            ):
                truncated = (
                    part.content[:_MAX_TOOL_RESULT_CHARS]
                    + f"\n… [truncated {len(part.content) - _MAX_TOOL_RESULT_CHARS} chars]"
                )
                new_parts.append(replace(part, content=truncated))
                changed = True
            else:
                pass
        out.append(replace(msg, parts=new_parts) if changed else msg)
    return out


def prune_old_tool_results(messages: list, keep_recent: int = _PRUNE_OLD_AFTER) -> list:
    """Strip tool result content from messages older than the last N.

    Old tool outputs are rarely needed verbatim — the agent has already
    reasoned from them.  Stripping them to a placeholder dramatically reduces
    input tokens for long sessions without losing important context.
    """
    from pydantic_ai.messages import ModelRequest, ToolReturnPart

    if len(messages) <= keep_recent:
        return messages

    old_messages = messages[:-keep_recent]
    recent_messages = messages[-keep_recent:]

    pruned_old = []
    for msg in old_messages:
        if not isinstance(msg, ModelRequest):
            pruned_old.append(msg)
            continue
        new_parts = list(msg.parts)
        changed = False
        for part in msg.parts:
            if (
                isinstance(part, ToolReturnPart)
                and isinstance(part.content, str)
                and len(part.content) > 50
            ):
                new_parts.append(replace(part, content="[output omitted]"))
                changed = True
            else:
                pass
        pruned_old.append(replace(msg, parts=new_parts) if changed else msg)

    return pruned_old + recent_messages


def trim_history(messages: list) -> list:
    """Drop the oldest messages when history exceeds _MAX_HISTORY_MESSAGES.

    Keeps the most recent messages so the agent always has fresh context.
    Combined with trim_tool_results and prune_old_tool_results this keeps
    per-turn costs bounded.
    """
    if len(messages) > _MAX_HISTORY_MESSAGES:
        trimmed = messages[-_MAX_HISTORY_MESSAGES:]
        return _drop_leading_orphan_tool_results(trimmed)
    return messages


def _drop_leading_orphan_tool_results(messages: list) -> list:
    """Remove leading ModelRequest messages that contain only ToolReturnParts.

    When trim_history slices the history mid-turn, the first message(s) may
    be tool-result messages whose corresponding tool-use blocks were dropped.
    Sending those to the API causes a 400 error:
      "unexpected tool_use_id found in tool_result blocks"

    We advance past any such leading messages until the list starts with
    either a UserPromptPart message or a ModelResponse.
    """
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    idx = 0
    while idx < len(messages):
        msg = messages[idx]
        if not isinstance(msg, ModelRequest):
            # ModelResponse at the start is also invalid, keep scanning
            idx += 1
            continue
        has_user_prompt = any(isinstance(p, UserPromptPart) for p in msg.parts)
        if has_user_prompt:
            break  # this is a proper user turn, safe to start here
        # Only tool results (no user prompt) — orphaned, skip it
        idx += 1
    return messages[idx:]


def _messages_to_text(messages: list) -> str:
    """Serialize messages to plain text for compaction summarization."""
    from pydantic_ai.messages import (
        ModelRequest, ModelResponse, TextPart,
        UserPromptPart, ToolReturnPart, ToolCallPart,
    )

    lines = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            request_parts = list(msg.parts)
            for part in request_parts:
                if isinstance(part, UserPromptPart):
                    content = part.content if isinstance(part.content, str) else str(part.content)
                    lines.append(f"User: {content[:600]}")
                elif isinstance(part, ToolReturnPart):
                    lines.append(f"  [tool_result:{part.tool_name}]: {str(part.content)[:200]}")
        elif isinstance(msg, ModelResponse):
            response_parts = list(msg.parts)
            for response_part in response_parts:
                if isinstance(response_part, TextPart):
                    lines.append(f"Assistant: {response_part.content[:600]}")
                elif isinstance(response_part, ToolCallPart):
                    lines.append(f"  [tool_call:{response_part.tool_name}({str(response_part.args)[:150]})]")
    return "\n".join(lines)


async def compact_history(messages: list, model_name: str) -> list:
    """Summarize old messages and replace them with a compact summary message.

    Keeps the last _PRUNE_OLD_AFTER messages verbatim so recent context is
    preserved.  The summary is injected as a synthetic user message that the
    agent can read to reconstruct the conversation context.

    Returns the new (shorter) message list, or the original list if compaction
    fails.
    """
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from .config import resolve_model

    keep_recent = _PRUNE_OLD_AFTER
    if len(messages) <= keep_recent:
        return messages

    to_summarize = messages[:-keep_recent]
    to_keep = _drop_leading_orphan_tool_results(messages[-keep_recent:])

    conversation_text = _messages_to_text(to_summarize)
    if not conversation_text.strip():
        return messages

    compaction_prompt = (
        "Summarize the following conversation for an AI coding assistant. "
        "Be detailed but concise. Include:\n"
        "- The user's goal(s) and key instructions\n"
        "- Important discoveries and decisions\n"
        "- Files read, created, or modified\n"
        "- Work completed and what is still pending\n\n"
        f"Conversation:\n{conversation_text}"
    )

    try:
        summarizer = Agent(
            resolve_model(model_name),
            system_prompt="You summarize AI coding assistant conversations for context compaction.",
        )
        result = await summarizer.run(compaction_prompt)
        summary = result.output.strip()
        if not summary:
            return messages
    except Exception:
        return messages

    summary_msg = ModelRequest(parts=[
        UserPromptPart(
            content=f"[Conversation compacted — earlier context summary]\n\n{summary}",
        ),
    ])
    return [summary_msg] + to_keep


def load_history() -> list:
    """Load conversation history from .yaac/history.json.

    Returns an empty list if no history file exists yet.
    """
    path = _history_path()
    if not path.exists():
        return []
    try:
        messages = ModelMessagesTypeAdapter.validate_json(path.read_bytes())
        return trim_history(trim_tool_results(messages))
    except Exception:
        return []


def save_history(messages: list) -> None:
    """Persist conversation history to .yaac/history.json."""
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ModelMessagesTypeAdapter.dump_json(trim_history(trim_tool_results(messages))))


def clear_history() -> None:
    """Delete the history file."""
    path = _history_path()
    if path.exists():
        path.unlink()
