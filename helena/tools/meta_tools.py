"""Meta tools for creating skills and agent profiles."""

import re
from pathlib import Path

from ..tool_events import emit_call, emit_return

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


async def create_skill(name: str, description: str, instructions: str) -> str:
    """Persist a new skill to ~/.helena/skills/ so it's available in all future sessions and auto-discovered locations.

    Args:
        name: Lowercase alphanumeric with hyphens (e.g. 'deploy-aws').
        description: One-line description shown in the catalog.
        instructions: Full instructions in Markdown format.

    Returns:
        Success or error message.
    """
    emit_call("create_skill", {"name": name})

    if not _NAME_RE.match(name):
        result = "Error: name must be lowercase alphanumeric with hyphens (e.g. 'deploy-aws')."
        emit_return("create_skill", result)
        return result

    skill_dir = Path.home() / ".helena" / "skills" / name
    skill_file = skill_dir / "SKILL.md"

    try:
        skill_dir.mkdir(parents=True, exist_ok=True)
        content = f"---\nname: {name}\ndescription: {description}\n---\n\n{instructions}\n"
        skill_file.write_text(content, encoding="utf-8")

        # Reload the registry so the skill is immediately available
        from ..skills import init_skills
        init_skills()

        result = f"Skill '{name}' created at {skill_file} and loaded into the catalog."
    except Exception as e:
        result = f"Error creating skill: {e}"

    emit_return("create_skill", result)
    return result


async def create_agent_profile(name: str, description: str, system_prompt: str) -> str:
    """Persist a new agent profile to ~/.helena/agents/ for use with spawn_subagent.

    Args:
        name: Lowercase alphanumeric with hyphens (e.g. 'test-writer').
        description: What this agent specializes in.
        system_prompt: System prompt extension for this agent.

    Returns:
        Success or error message.
    """
    emit_call("create_agent_profile", {"name": name})

    if not _NAME_RE.match(name):
        result = "Error: name must be lowercase alphanumeric with hyphens."
        emit_return("create_agent_profile", result)
        return result

    profile_dir = Path.home() / ".helena" / "agents" / name
    profile_file = profile_dir / "AGENT.md"

    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        content = f"---\nname: {name}\ndescription: {description}\n---\n\n{system_prompt}\n"
        profile_file.write_text(content, encoding="utf-8")
        result = (
            f"Agent profile '{name}' created at {profile_file}. "
            f"Use spawn_subagent with profile='{name}' to invoke it."
        )
    except Exception as e:
        result = f"Error creating agent profile: {e}"

    emit_return("create_agent_profile", result)
    return result
