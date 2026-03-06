"""Subagent spawning tool for Helena Code."""

from pathlib import Path

from ..tool_events import emit_call, emit_return


async def spawn_subagent(
    task: str,
    profile: str | None = None,
    context: str | None = None,
) -> str:
    """Spawn an independent subagent to handle a focused subtask.

    The subagent has access to all the same tools and runs the full agentic
    loop to completion before returning its result. Use this to delegate
    parallelizable work, isolate a complex subtask, or use a specialized
    agent profile.

    Args:
        task: The task description for the subagent.
        profile: Optional agent profile name from .helena/agents/ to specialize
                 the subagent's behavior.
        context: Optional extra context to prepend to the task.

    Returns:
        The subagent's final response.
    """
    from ..agent import create_agent

    full_task = f"Context:\n{context}\n\nTask:\n{task}" if context else task
    emit_call("spawn_subagent", {"profile": profile or "default", "task": task})

    system_prompt_addition = _load_profile(profile) if profile else ""
    subagent = create_agent(system_prompt_addition=system_prompt_addition)
    result = await subagent.run(full_task)
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
