"""Subagent spawning tool for Helena Code."""

from pathlib import Path

from pydantic_ai.usage import UsageLimits

from ..tool_events import emit_call, emit_return
from ..utils import retry_async

_UNLIMITED = UsageLimits(request_limit=None)


async def spawn_subagent(
    task: str,
    profile: str | None = None,
    context: str | None = None,
) -> str:
    """Spawn an independent subagent with a fresh context to handle a focused subtask.

    Args:
        task: The subtask description.
        profile: Optional profile name from .helena/agents/ for a specialized persona.
        context: Optional extra context prepended to the task.

    Returns:
        The subagent's final response.
    """
    from ..agent import create_agent

    full_task = f"Context:\n{context}\n\nTask:\n{task}" if context else task
    emit_call("spawn_subagent", {"profile": profile or "default", "task": task})

    system_prompt_addition = _load_profile(profile) if profile else ""
    subagent = create_agent(system_prompt_addition=system_prompt_addition)
    result = await retry_async(subagent.run, full_task, usage_limits=_UNLIMITED, max_attempts=3)
    response = result.output

    emit_return("spawn_subagent", response)
    return response


def _load_profile(name: str) -> str:
    """Load an agent profile's body as a system prompt extension."""
    from ..skills import _parse_frontmatter

    for base in (
        Path.cwd() / ".helena" / "agents",
        Path.home() / ".helena" / "agents",
    ):
        path = base / name / "AGENT.md"
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8")
                _, body = _parse_frontmatter(text)
                return f"\n\n{body}"
            except Exception:
                pass
    return ""
