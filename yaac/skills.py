"""Agent Skills implementation for YAAC.

Follows the agentskills.io open format:
- Discovery: scan for SKILL.md files with YAML frontmatter
- Progressive disclosure: only name+description at startup (catalog)
- Activation: full body loaded on-demand via activate_skill() tool

Discovery paths (in priority order):
  Project-level:  <cwd>/.yaac/skills/    |  <cwd>/.agents/skills/  |  <cwd>/skills/
  User-level:     ~/.yaac/skills/         |  ~/.claude/skills/      |  ~/.agents/skills/
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillMeta:
    name: str
    description: str
    path: Path  # absolute path to SKILL.md

    @property
    def directory(self) -> Path:
        return self.path.parent


# Module-level skill registry populated at startup
_registry: dict[str, SkillMeta] = {}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _scan_dirs() -> list[Path]:
    """Return candidate skill directories in priority order."""
    cwd = Path.cwd()
    home = Path.home()
    return [
        cwd / ".yaac" / "skills",
        cwd / ".agents" / "skills",
        cwd / "skills",
        home / ".yaac" / "skills",
        home / ".claude" / "skills",
        home / ".agents" / "skills",
    ]


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML frontmatter and return (fields, body).

    Handles the common case of simple key: value pairs without requiring pyyaml.
    Falls back gracefully on malformed frontmatter.
    """
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    fm_text = text[3:end].strip()
    body = text[end + 4:].strip()

    fields: dict[str, str] = {}
    for line in fm_text.splitlines():
        # Match "key: value" — handle values that contain colons
        match = re.match(r"^(\w[\w\-]*)\s*:\s*(.*)", line)
        if match:
            fields[match.group(1)] = match.group(2).strip().strip('"').strip("'")

    return fields, body


def discover_skills() -> dict[str, SkillMeta]:
    """Scan all candidate directories and return a registry of skills by name."""
    found: dict[str, SkillMeta] = {}

    for base in _scan_dirs():
        if not base.is_dir():
            continue

        for skill_md in sorted(base.glob("*/SKILL.md")):
            try:
                text = skill_md.read_text(encoding="utf-8")
                fields, _ = _parse_frontmatter(text)

                name = fields.get("name", "").strip()
                description = fields.get("description", "").strip()

                if not description:
                    continue  # description is required for catalog disclosure

                if not name:
                    name = skill_md.parent.name  # fall back to directory name

                # Project-level skills override user-level (first found wins
                # since _scan_dirs() is ordered project → user)
                if name not in found:
                    found[name] = SkillMeta(name=name, description=description, path=skill_md)

            except Exception:
                continue  # skip malformed skills

    return found


def init_skills() -> None:
    """Populate the module-level skill registry. Call once at startup."""
    global _registry
    _registry = discover_skills()


def list_skill_names() -> list[str]:
    return sorted(_registry.keys())


def discover_skills_in(dirs: list[Path]) -> dict[str, SkillMeta]:
    """Discover skills from an explicit list of directories.

    Same logic as discover_skills() but limited to the given paths.
    """
    found: dict[str, SkillMeta] = {}
    for base in dirs:
        if not base.is_dir():
            continue
        for skill_md in sorted(base.glob("*/SKILL.md")):
            try:
                text = skill_md.read_text(encoding="utf-8")
                fields, _ = _parse_frontmatter(text)
                name = fields.get("name", "").strip()
                description = fields.get("description", "").strip()
                if not description:
                    continue
                if not name:
                    name = skill_md.parent.name
                if name not in found:
                    found[name] = SkillMeta(name=name, description=description, path=skill_md)
            except Exception:
                continue
    return found


def build_scoped_registry(
    allowed_names: list[str] | None = None,
    extra_dirs: list[Path] | None = None,
) -> dict[str, SkillMeta]:
    """Build a skill registry for a subagent.

    Args:
        allowed_names: If provided, only include these skills from the global
            registry. ``None`` means include all global skills.
        extra_dirs: Additional directories to scan for profile-exclusive skills.

    Returns:
        A merged registry containing the selected global skills plus any
        profile-exclusive skills.
    """
    if allowed_names is not None:
        registry = {k: v for k, v in _registry.items() if k in allowed_names}
    else:
        registry = dict(_registry)

    if extra_dirs:
        extra = discover_skills_in(extra_dirs)
        for k, v in extra.items():
            registry.setdefault(k, v)

    return registry


# ---------------------------------------------------------------------------
# Catalog (Tier 1 — injected into system prompt)
# ---------------------------------------------------------------------------

def build_catalog(registry: dict[str, SkillMeta] | None = None) -> str:
    """Build the XML skill catalog for injection into the system prompt.

    Args:
        registry: Skill registry to build the catalog from. Defaults to the
            global registry when ``None``.

    Returns empty string if no skills are available.
    """
    source = registry if registry is not None else _registry
    if not source:
        return ""

    skill_tags = "\n".join(
        f"  <skill>\n    <name>{s.name}</name>\n    <description>{s.description}</description>\n  </skill>"
        for s in source.values()
    )

    return f"""

## Available Skills

You have access to specialized skills. When a task matches a skill's description, call `activate_skill` with the skill's name to load its full instructions before proceeding.

<available_skills>
{skill_tags}
</available_skills>
"""


# ---------------------------------------------------------------------------
# Activation tool (Tier 2 — called on-demand by the agent)
# ---------------------------------------------------------------------------

def _activate_from_registry(registry: dict[str, SkillMeta], name: str) -> str:
    """Core activation logic that works with any registry."""
    skill = registry.get(name)
    if not skill:
        available = ", ".join(registry.keys()) or "none"
        return f"Skill '{name}' not found. Available skills: {available}"

    try:
        text = skill.path.read_text(encoding="utf-8")
        _, body = _parse_frontmatter(text)

        resources = _list_resources(skill.directory)
        resources_section = ""
        if resources:
            resource_tags = "\n".join(f"  <file>{r}</file>" for r in resources)
            resources_section = f"\n<skill_resources>\n{resource_tags}\n</skill_resources>"

        return (
            f'<skill_content name="{name}">\n'
            f"{body}\n\n"
            f"Skill directory: {skill.directory}\n"
            f"Relative paths in this skill are relative to the skill directory."
            f"{resources_section}\n"
            f"</skill_content>"
        )
    except Exception as e:
        return f"Error loading skill '{name}': {e}"


def activate_skill(name: str) -> str:
    """Load the full instructions for a skill by name.

    Call this when a task matches a skill's description. The skill's complete
    instructions will be returned and you should follow them for the task.

    Args:
        name: The skill name as listed in the available_skills catalog.

    Returns:
        Full skill instructions wrapped in skill_content tags,
        or an error message if the skill is not found.
    """
    return _activate_from_registry(_registry, name)


def make_scoped_activate_skill(registry: dict[str, SkillMeta]):
    """Return an activate_skill function bound to a specific registry.

    Used to give subagents their own independent skill set.
    """

    async def scoped_activate_skill(name: str) -> str:
        """Load the full instructions for a skill by name.

        Call this when a task matches a skill's description. The skill's complete
        instructions will be returned and you should follow them for the task.

        Args:
            name: The skill name as listed in the available_skills catalog.

        Returns:
            Full skill instructions wrapped in skill_content tags,
            or an error message if the skill is not found.
        """
        return _activate_from_registry(registry, name)

    return scoped_activate_skill


def _list_resources(skill_dir: Path) -> list[str]:
    """List non-SKILL.md files in the skill directory (relative paths)."""
    resources = []
    for p in sorted(skill_dir.rglob("*")):
        if p.is_file() and p.name != "SKILL.md":
            resources.append(str(p.relative_to(skill_dir)))
    return resources
