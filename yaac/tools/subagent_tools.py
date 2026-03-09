"""Subagent spawning tool for YAAC."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.usage import UsageLimits

from ..tool_events import emit_call, emit_return
from ..utils import retry_async

_UNLIMITED = UsageLimits(request_limit=None)


@dataclass
class ProfileConfig:
    """Parsed agent profile with optional tool and skill restrictions."""

    system_prompt: str = ""
    tools: list[str] | None = None
    skills: list[str] | None = None
    profile_dir: Path | None = None


async def spawn_subagent(
    task: str,
    profile: str | None = None,
    context: str | None = None,
) -> str:
    """Spawn an independent subagent with a fresh context to handle a focused subtask.

    Each subagent can have its own set of tools and skills, configured via the
    agent profile's AGENT.md frontmatter:
      - ``tools``: comma-separated list of tool names the subagent may use.
        When omitted the subagent inherits all tools.
      - ``skills``: comma-separated list of skill names the subagent may use.
        When omitted the subagent inherits all discovered skills.

    Profiles may also bundle exclusive skills under a ``skills/`` subdirectory
    inside the profile folder (e.g. ``.yaac/agents/my-agent/skills/``).

    Args:
        task: The subtask description.
        profile: Optional profile name from .yaac/agents/ for a specialized persona.
        context: Optional extra context prepended to the task.

    Returns:
        The subagent's final response.
    """
    from ..agent import create_agent
    from ..skills import build_scoped_registry

    full_task = f"Context:\n{context}\n\nTask:\n{task}" if context else task
    emit_call("spawn_subagent", {"profile": profile or "default", "task": task})

    config = _load_profile(profile) if profile else ProfileConfig()

    extra_dirs: list[Path] = []
    if config.profile_dir:
        skills_dir = config.profile_dir / "skills"
        if skills_dir.is_dir():
            extra_dirs.append(skills_dir)

    skill_registry = None
    if config.skills is not None or extra_dirs:
        skill_registry = build_scoped_registry(
            allowed_names=config.skills,
            extra_dirs=extra_dirs or None,
        )

    subagent = create_agent(
        system_prompt_addition=config.system_prompt,
        allowed_tools=config.tools,
        skill_registry=skill_registry,
    )
    result = await retry_async(subagent.run, full_task, usage_limits=_UNLIMITED, max_attempts=3)
    response = result.output

    emit_return("spawn_subagent", response)
    return response


def _parse_csv_field(value: str) -> list[str]:
    """Parse a comma-separated frontmatter value into a trimmed list."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _load_profile(name: str) -> ProfileConfig:
    """Load an agent profile and extract tool/skill configuration."""
    from ..skills import _parse_frontmatter

    for base in (
        Path.cwd() / ".yaac" / "agents",
        Path.home() / ".yaac" / "agents",
    ):
        path = base / name / "AGENT.md"
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8")
                fields, body = _parse_frontmatter(text)

                tools = _parse_csv_field(fields["tools"]) if "tools" in fields else None
                skills = _parse_csv_field(fields["skills"]) if "skills" in fields else None

                return ProfileConfig(
                    system_prompt=f"\n\n{body}" if body else "",
                    tools=tools,
                    skills=skills,
                    profile_dir=path.parent,
                )
            except Exception:
                pass
    return ProfileConfig()
