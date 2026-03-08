"""MCP ecosystem support for YAAC.

Loads Claude-style MCP server configs, exposes resolved server metadata to the
prompt, and returns pydantic-ai MCP toolsets for agent wiring.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_ai.mcp import MCPServer, load_mcp_servers

from .config import CONFIG_PATH

DEFAULT_PROJECT_MCP_CONFIG = ".mcp.json"
DEFAULT_PROJECT_YAAC_MCP_CONFIG = ".yaac/mcp.json"
DEFAULT_HOME_YAAC_MCP_CONFIG = Path.home() / ".yaac" / "mcp.json"


def _load_mcp_config_path_from_yaac_config() -> Path | None:
    """Return an MCP config path defined in ~/.yaac/config.json, if present."""
    if not CONFIG_PATH.exists():
        return None

    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception:
        return None

    mcp_value = cfg.get("mcp_config") or cfg.get("mcpConfig")
    if isinstance(mcp_value, str) and mcp_value.strip():
        return _expand_path(mcp_value.strip())
    return None


@dataclass(slots=True)
class MCPServerRuntime:
    """Runtime wrapper for a configured MCP server."""

    name: str
    server: MCPServer
    source: Path


@dataclass(slots=True)
class MCPLoadResult:
    """Loaded MCP server state for the current session."""

    config_path: Path | None
    servers: list[MCPServerRuntime]
    warnings: list[str]


def _expand_path(raw_path: str) -> Path:
    return Path(os.path.expandvars(raw_path)).expanduser().resolve()


def discover_mcp_config(explicit_path: str | None = None) -> Path | None:
    """Resolve the MCP config path from CLI input, env, ~/.yaac/config.json, home, or project defaults."""
    candidates: list[Path] = []

    if explicit_path:
        candidates.append(_expand_path(explicit_path))

    env_path = os.environ.get("YAAC_MCP_CONFIG")
    if env_path:
        candidates.append(_expand_path(env_path))

    yaac_config_path = _load_mcp_config_path_from_yaac_config()
    if yaac_config_path:
        candidates.append(yaac_config_path)

    cwd = Path.cwd()
    candidates.extend(
        [
            DEFAULT_HOME_YAAC_MCP_CONFIG.resolve(),
            (cwd / DEFAULT_PROJECT_MCP_CONFIG).resolve(),
            (cwd / DEFAULT_PROJECT_YAAC_MCP_CONFIG).resolve(),
        ]
    )

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate
    return candidates[0] if explicit_path else None


def load_mcp_ecosystem(explicit_path: str | None = None) -> MCPLoadResult:
    """Load MCP servers from config, returning warnings instead of raising."""
    config_path = discover_mcp_config(explicit_path)
    if config_path is None:
        return MCPLoadResult(config_path=None, servers=[], warnings=[])

    if not config_path.exists():
        return MCPLoadResult(
            config_path=config_path,
            servers=[],
            warnings=[f"MCP config file not found: {config_path}"],
        )

    try:
        servers = load_mcp_servers(config_path)
    except Exception as exc:
        return MCPLoadResult(
            config_path=config_path,
            servers=[],
            warnings=[f"Failed to load MCP config {config_path}: {exc}"],
        )

    runtimes = [
        MCPServerRuntime(name=getattr(server, "id", f"server-{i+1}"), server=server, source=config_path)
        for i, server in enumerate(servers)
    ]
    return MCPLoadResult(config_path=config_path, servers=runtimes, warnings=[])


def build_mcp_prompt_section(load_result: MCPLoadResult) -> str:
    """Return a prompt section describing available MCP servers/tools."""
    if not load_result.servers and not load_result.warnings:
        return ""

    lines = ["\n\n## MCP ecosystem\n"]

    if load_result.config_path:
        lines.append(f"Active MCP config: {load_result.config_path}")

    if load_result.servers:
        lines.append("Configured MCP servers:")
        for runtime in load_result.servers:
            tool_prefix = getattr(runtime.server, "tool_prefix", runtime.name)
            lines.append(f"- {runtime.name} (tool prefix: {tool_prefix})")
        lines.append(
            "Use MCP tools exactly like built-in tools when relevant. Prefer built-in tools for local file operations unless an MCP server is clearly better suited."
        )

    if load_result.warnings:
        lines.append("MCP warnings:")
        lines.extend(f"- {warning}" for warning in load_result.warnings)

    return "\n".join(lines)


def describe_mcp_status(load_result: MCPLoadResult) -> str:
    """Return a human-readable status string for CLI display."""
    payload: dict[str, Any] = {
        "config_path": str(load_result.config_path) if load_result.config_path else None,
        "servers": [
            {
                "name": runtime.name,
                "tool_prefix": getattr(runtime.server, "tool_prefix", runtime.name),
                "source": str(runtime.source),
            }
            for runtime in load_result.servers
        ],
        "warnings": load_result.warnings,
    }
    return json.dumps(payload, indent=2)
