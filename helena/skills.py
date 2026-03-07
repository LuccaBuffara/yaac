"""Agent Skills implementation for Helena Code.

Follows the agentskills.io open format:
- Discovery: scan for SKILL.md files with YAML frontmatter
- Progressive disclosure: only name+description at startup (catalog)
- Activation: full body loaded on-demand via activate_skill() tool

Discovery paths (in priority order):
  Project-level:  <cwd>/.helena/skills/  |  <cwd>/.agents/skills/  |  <cwd>/skills/
  User-level:     ~/.helena/skills/       |  ~/.claude/skills/      |  ~/.agents/skills/
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
        cwd / ".helena" / "skills",
        cwd / ".agents" / "skills",
        cwd / "skills",
        home / ".helena" / "skills",
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


# ---------------------------------------------------------------------------
# Catalog (Tier 1 — injected into system prompt)
# ---------------------------------------------------------------------------

def build_catalog() -> str:
    """Build the XML skill catalog for injection into the system prompt.

    Returns empty string if no skills are available.
    """
    if not _registry:
        return ""

    skill_tags = "\n".join(
        f"  <skill>\n    <name>{s.name}</name>\n    <description>{s.description}</description>\n  </skill>"
        for s in _registry.values()
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
    skill = _registry.get(name)
    if not skill:
        available = ", ".join(_registry.keys()) or "none"
        return f"Skill '{name}' not found. Available skills: {available}"

    try:
        text = skill.path.read_text(encoding="utf-8")
        _, body = _parse_frontmatter(text)

        # List any bundled resources (scripts, references, assets)
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


def _list_resources(skill_dir: Path) -> list[str]:
    """List non-SKILL.md files in the skill directory (relative paths)."""
    resources = []
    for p in sorted(skill_dir.rglob("*")):
        if p.is_file() and p.name != "SKILL.md":
            resources.append(str(p.relative_to(skill_dir)))
    return resources
