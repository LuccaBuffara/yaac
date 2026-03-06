"""Meta tools for creating skills and agent profiles."""

import re
from pathlib import Path

from ..tool_events import emit_call, emit_return

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


async def create_skill(name: str, description: str, instructions: str) -> str:
    """Create a new persistent skill that Helena can load on-demand.

    Skills are Markdown instruction sets stored in ~/.helena/skills/ and
    persist globally across all projects and sessions. Once created the skill
    appears in the catalog and can be activated with activate_skill.

    Args:
        name: Unique skill name — lowercase alphanumeric with hyphens
              (e.g. 'deploy-aws', 'write-tests').
        description: One-line description shown in the skill catalog.
        instructions: Full skill instructions in Markdown format.

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
    """Create a named agent profile for use with spawn_subagent.

    Agent profiles are stored globally in ~/.helena/agents/ as AGENT.md files.
    When spawn_subagent is called with profile=<name>, the profile's
    system_prompt is appended to the subagent's base prompt, giving it
    a specialized focus or persona.

    Args:
        name: Unique profile name — lowercase alphanumeric with hyphens
              (e.g. 'test-writer', 'security-reviewer').
        description: What this agent specializes in.
        system_prompt: System prompt extension / instructions for this agent.

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
