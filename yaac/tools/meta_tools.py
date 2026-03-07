"""Meta tools for creating skills, agent profiles, and planning agents."""

import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic_ai.usage import UsageLimits

from ..tool_events import emit_call, emit_return

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
_UNLIMITED = UsageLimits(request_limit=None)
_PLAN_MODE_PROFILE = "plan-mode"
_PLAN_MODE_DESCRIPTION = "Read-only planning agent that explores the codebase and designs implementation plans."
_PLAN_MODE_SYSTEM_PROMPT = """Your role is to explore the codebase and design implementation plans.

=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
This is a READ-ONLY planning task. You are STRICTLY PROHIBITED from:

- Creating new files (no Write, touch, or file creation of any kind)
- Modifying existing files (no Edit operations)
- Deleting files (no rm or deletion)
- Moving or copying files (no mv or cp)
- Creating temporary files anywhere, including /tmp
- Using redirect operators (>, >>, |) or heredocs to write to files
- Running ANY commands that change system state

Your role is EXCLUSIVELY to explore the codebase and design implementation plans. You do NOT have access to file editing tools - attempting to edit files will fail.

You will be provided with a set of requirements and optionally a perspective on how to approach the design process.

## Your Process

1. Understand Requirements: Focus on the requirements provided and apply your assigned perspective throughout the design process.
2. Explore Thoroughly:
   - Read any files provided to you in the initial prompt.
   - Find existing patterns and conventions using `glob_search`, `grep_search`, and `read_file`.
   - Understand the current architecture.
   - Identify similar features as reference.
   - Trace through relevant code paths.
   - Use `run_bash` ONLY for read-only operations such as `ls`, `git status`, `git log`, `git diff`, `find`, `grep`, `cat`, `head`, and `tail`.
   - NEVER use `run_bash` for `mkdir`, `touch`, `rm`, `cp`, `mv`, `git add`, `git commit`, `npm install`, `pip install`, or any file creation/modification.
3. Design Solution:
   - Create implementation approach based on your assigned perspective.
   - Consider trade-offs and architectural decisions.
   - Follow existing patterns where appropriate.
4. Detail the Plan:
   - Provide step-by-step implementation strategy.
   - Identify dependencies and sequencing.
   - Anticipate potential challenges.

## Required Output

End your response with:

Critical Files for Implementation

List 3-5 files most critical for implementing this plan:

path/to/file1.ts - [Brief reason: e.g., "Core logic to modify"]
path/to/file2.ts - [Brief reason: e.g., "Interfaces to implement"]
path/to/file3.ts - [Brief reason: e.g., "Pattern to follow"]

REMEMBER: You can ONLY explore and plan. You CANNOT and MUST NOT write, edit, or modify any files. You do NOT have access to file editing tools."""


async def create_skill(name: str, description: str, instructions: str) -> str:
    """Persist a new skill to ~/.yaac/skills/ so it's available in all future sessions and auto-discovered locations.

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

    skill_dir = Path.home() / ".yaac" / "skills" / name
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
    """Persist a new agent profile to ~/.yaac/agents/ for use with spawn_subagent.

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

    profile_dir = Path.home() / ".yaac" / "agents" / name
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


async def plan_mode(task: str, steps: list[str], directory: str = ".") -> str:
    """Run a dedicated read-only planning subagent for complex tasks.

    Args:
        task: Short description of the complex task being planned.
        steps: Optional planning prompts or desired phases to consider.
        directory: Directory to treat as the planning workspace context. Defaults to cwd.

    Returns:
        The planning subagent's final response and the path to the written TODO.md plan.
    """
    emit_call("plan_mode", {"task": task, "steps": steps, "directory": directory})

    if not task.strip():
        result = "Error: task must not be empty."
        emit_return("plan_mode", result)
        return result

    normalized_steps = [step.strip() for step in steps if step.strip()]
    if not normalized_steps:
        result = "Error: steps must include at least one non-empty item."
        emit_return("plan_mode", result)
        return result

    workspace_dir = Path(directory).expanduser().resolve()

    try:
        from ..agent import create_agent

        planning_agent = create_agent(system_prompt_addition=f"\n\n{_PLAN_MODE_SYSTEM_PROMPT}")
        planning_prompt = "\n\n".join(
            [
                f"Working directory for planning: {workspace_dir}",
                f"Requirements:\n{task.strip()}",
                "Planning considerations:\n" + "\n".join(f"- {step}" for step in normalized_steps),
            ]
        )
        response = await planning_agent.run(planning_prompt, usage_limits=_UNLIMITED)
        plan_text = response.output

        workspace_dir.mkdir(parents=True, exist_ok=True)
        todo_file = workspace_dir / "TODO.md"
        header = [
            f"# Plan: {task.strip()}",
            "",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            f"Workspace: {workspace_dir}",
            "",
            "## Requested Steps",
            *(f"- {step}" for step in normalized_steps),
            "",
            "## Planning Output",
            "",
        ]
        todo_file.write_text("\n".join(header) + plan_text.strip() + "\n", encoding="utf-8")
        result = f"Plan written to {todo_file}\n\n{plan_text}"
    except Exception as e:
        result = f"Error running planning agent: {e}"

    emit_return("plan_mode", result)
    return result


def ensure_plan_mode_profile() -> str:
    """Ensure the built-in read-only planning agent profile exists."""
    profile_dir = Path.home() / ".yaac" / "agents" / _PLAN_MODE_PROFILE
    profile_file = profile_dir / "AGENT.md"

    content = (
        f"---\nname: {_PLAN_MODE_PROFILE}\ndescription: {_PLAN_MODE_DESCRIPTION}\n---\n\n{_PLAN_MODE_SYSTEM_PROMPT}\n"
    )

    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_file.write_text(content, encoding="utf-8")
    return str(profile_file)
