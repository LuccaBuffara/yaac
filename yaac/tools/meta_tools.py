"""Meta tools for creating skills, agent profiles, and planning agents."""

import re
from pathlib import Path

from pydantic_ai.usage import UsageLimits

from ..tool_events import emit_call, emit_return

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
_CHECKLIST_RE = re.compile(r"^- \[( |x)\] (.+)$", re.MULTILINE)
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
2. Check Existing Progress: If existing session todos are provided, review them carefully. Tasks marked COMPLETED are ALREADY DONE — do NOT re-plan or duplicate them. Only plan remaining tasks and any new tasks.
3. Explore Thoroughly:
   - Read any files provided to you in the initial prompt.
   - Find existing patterns and conventions using `glob_search`, `grep_search`, and `read_file`.
   - Understand the current architecture.
   - Identify similar features as reference.
   - Trace through relevant code paths.
   - Use `run_bash` ONLY for read-only operations such as `ls`, `git status`, `git log`, `git diff`, `find`, `grep`, `cat`, `head`, and `tail`.
   - NEVER use `run_bash` for `mkdir`, `touch`, `rm`, `cp`, `mv`, `git add`, `git commit`, `npm install`, `pip install`, or any file creation/modification.
4. Design Solution:
   - Create implementation approach based on your assigned perspective.
   - Consider trade-offs and architectural decisions.
   - Follow existing patterns where appropriate.
5. Detail the Plan:
   - Provide step-by-step implementation strategy.
   - Identify dependencies and sequencing.
   - Anticipate potential challenges.

## Required Output Format

Your plan MUST use markdown checklist syntax for ALL actionable tasks:
- `- [ ]` for tasks that still need to be done
- `- [x]` for tasks that are already completed (preserve from existing session todos)

Group tasks under logical headings. Example:

### Phase 1: Setup
- [x] Create database schema (already done)
- [ ] Add migration script

### Phase 2: Implementation
- [ ] Implement API endpoint
- [ ] Add input validation

The caller will automatically parse these checklist items into session-scoped todos.

End your response with:

### Critical Files for Implementation

List 3-5 files most critical for implementing this plan:

path/to/file1.ts - [Brief reason: e.g., "Core logic to modify"]
path/to/file2.ts - [Brief reason: e.g., "Interfaces to implement"]
path/to/file3.ts - [Brief reason: e.g., "Pattern to follow"]

REMEMBER: You can ONLY explore and plan. You CANNOT and MUST NOT write, edit, or modify any files. You do NOT have access to file editing tools."""


def _parse_checklist(text: str) -> list[dict[str, str]]:
    """Extract checklist items from plan text into todo dicts."""
    todos: list[dict[str, str]] = []
    for i, match in enumerate(_CHECKLIST_RE.finditer(text), start=1):
        done = match.group(1) == "x"
        content = match.group(2).strip()
        todos.append({
            "id": str(i),
            "content": content,
            "status": "completed" if done else "pending",
        })
    return todos


async def create_skill(
    name: str,
    description: str,
    instructions: str,
    files: dict[str, str] | None = None,
) -> str:
    """Persist a new skill to ~/.yaac/skills/ so it's available in all future sessions and auto-discovered locations.

    A skill is a folder containing SKILL.md plus any bundled resources (scripts,
    templates, reference docs, examples) that help the agent execute the skill.
    Use the `files` parameter to create sub-files inside the skill directory so
    the agent can read and run them when the skill is activated.

    Args:
        name: Lowercase alphanumeric with hyphens (e.g. 'deploy-aws').
        description: One-line description shown in the catalog.
        instructions: Full instructions in Markdown format.
        files: Optional mapping of relative path → file content for bundled
            resources.  Paths must be relative (e.g. 'scripts/setup.sh',
            'templates/config.yaml', 'examples/demo.py').  Directories are
            created automatically.  SKILL.md is always written from the
            `instructions` argument and must NOT appear here.

    Returns:
        Success or error message.
    """
    emit_call("create_skill", {"name": name})

    if not _NAME_RE.match(name):
        result = "Error: name must be lowercase alphanumeric with hyphens (e.g. 'deploy-aws')."
        emit_return("create_skill", result)
        return result

    # Validate bundled file paths
    if files:
        for rel_path in files:
            p = Path(rel_path)
            if p.is_absolute():
                result = f"Error: bundled file path must be relative, got '{rel_path}'."
                emit_return("create_skill", result)
                return result
            if p.name == "SKILL.md" and str(p) == "SKILL.md":
                result = "Error: 'SKILL.md' must not appear in `files`; use the `instructions` argument instead."
                emit_return("create_skill", result)
                return result

    skill_dir = Path.home() / ".yaac" / "skills" / name
    skill_file = skill_dir / "SKILL.md"

    try:
        skill_dir.mkdir(parents=True, exist_ok=True)
        content = f"---\nname: {name}\ndescription: {description}\n---\n\n{instructions}\n"
        skill_file.write_text(content, encoding="utf-8")

        # Write bundled resources
        created_files: list[str] = []
        if files:
            for rel_path, file_content in files.items():
                target = skill_dir / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(file_content, encoding="utf-8")
                created_files.append(rel_path)

        # Reload the registry so the skill is immediately available
        from ..skills import init_skills
        init_skills()

        extra = ""
        if created_files:
            extra = f" Bundled {len(created_files)} file(s): {', '.join(created_files)}."
        result = f"Skill '{name}' created at {skill_file} and loaded into the catalog.{extra}"
    except Exception as e:
        result = f"Error creating skill: {e}"

    emit_return("create_skill", result)
    return result


async def create_agent_profile(
    name: str,
    description: str,
    system_prompt: str,
    tools: list[str] | None = None,
    skills: list[str] | None = None,
) -> str:
    """Persist a new agent profile to ~/.yaac/agents/ for use with spawn_subagent.

    Each profile can declare its own set of tools and skills, independent from
    the main agent. When the profile is used with ``spawn_subagent``, the
    subagent will only have access to the declared tools and skills.

    Available tool names: read_file, write_file, update_file, list_directory,
    run_bash, glob_search, grep_search, spawn_subagent, create_skill,
    create_agent_profile, plan_mode, todo_read, todo_write, lsp_diagnostics,
    lsp_query, memory_read, memory_write.

    You can also place profile-exclusive skills under a ``skills/``
    subdirectory inside the profile folder. These skills are only available to
    subagents spawned with this profile.

    Args:
        name: Lowercase alphanumeric with hyphens (e.g. 'test-writer').
        description: What this agent specializes in.
        system_prompt: System prompt extension for this agent.
        tools: Optional list of tool names this profile's subagent may use.
            When omitted the subagent inherits all tools.
        skills: Optional list of skill names this profile's subagent may use.
            When omitted the subagent inherits all discovered skills.

    Returns:
        Success or error message.
    """
    emit_call("create_agent_profile", {"name": name})

    if not _NAME_RE.match(name):
        result = "Error: name must be lowercase alphanumeric with hyphens."
        emit_return("create_agent_profile", result)
        return result

    from ..agent import TOOL_REGISTRY

    if tools is not None:
        unknown = [t for t in tools if t not in TOOL_REGISTRY]
        if unknown:
            result = f"Error: unknown tool names: {', '.join(unknown)}. Available: {', '.join(TOOL_REGISTRY.keys())}"
            emit_return("create_agent_profile", result)
            return result

    profile_dir = Path.home() / ".yaac" / "agents" / name
    profile_file = profile_dir / "AGENT.md"

    try:
        profile_dir.mkdir(parents=True, exist_ok=True)

        fm_lines = [f"name: {name}", f"description: {description}"]
        if tools is not None:
            fm_lines.append(f"tools: {', '.join(tools)}")
        if skills is not None:
            fm_lines.append(f"skills: {', '.join(skills)}")

        frontmatter = "\n".join(fm_lines)
        content = f"---\n{frontmatter}\n---\n\n{system_prompt}\n"
        profile_file.write_text(content, encoding="utf-8")

        extras = []
        if tools is not None:
            extras.append(f"tools=[{', '.join(tools)}]")
        if skills is not None:
            extras.append(f"skills=[{', '.join(skills)}]")
        config_note = f" Config: {'; '.join(extras)}." if extras else ""

        result = (
            f"Agent profile '{name}' created at {profile_file}. "
            f"Use spawn_subagent with profile='{name}' to invoke it.{config_note}"
        )
    except Exception as e:
        result = f"Error creating agent profile: {e}"

    emit_return("create_agent_profile", result)
    return result


async def plan_mode(task: str, steps: list[str], directory: str = ".") -> str:
    """Run a dedicated read-only planning subagent for complex tasks.

    The planner's checklist output is automatically parsed into session-scoped
    todos stored in .yaac/todos/{session_id}.json.

    Args:
        task: Short description of the complex task being planned.
        steps: Optional planning prompts or desired phases to consider.
        directory: Directory to treat as the planning workspace context. Defaults to cwd.

    Returns:
        The planning subagent's response and a summary of created todos.
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

    from .todo_tools import _load_store, _save_store, _format_todos

    existing_store = _load_store()
    existing_todos = existing_store.get("todos", [])

    try:
        from ..agent import create_agent

        planning_agent = create_agent(system_prompt_addition=f"\n\n{_PLAN_MODE_SYSTEM_PROMPT}")

        prompt_parts = [
            f"Working directory for planning: {workspace_dir}",
            f"Requirements:\n{task.strip()}",
            "Planning considerations:\n" + "\n".join(f"- {step}" for step in normalized_steps),
        ]
        if existing_todos:
            prompt_parts.append(
                "## Existing session todos (preserve completed tasks):\n\n"
                + _format_todos(existing_todos)
            )

        planning_prompt = "\n\n".join(prompt_parts)
        response = await planning_agent.run(planning_prompt, usage_limits=_UNLIMITED)
        plan_text = response.output

        parsed_todos = _parse_checklist(plan_text)
        if parsed_todos:
            existing_store["todos"] = parsed_todos
            _save_store(existing_store)

        todo_summary = _format_todos(existing_store["todos"]) if existing_store["todos"] else "(no checklist items found)"
        result = f"{plan_text}\n\n--- Session todos ---\n{todo_summary}"
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
