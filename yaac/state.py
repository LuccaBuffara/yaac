"""Session state for YAAC."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from prompt_toolkit import PromptSession


@dataclass
class SessionState:
    model: str
    agent: Any  # Agent | None
    message_history: list
    cost: float
    tokens_in: int
    tokens_out: int
    beast_context: str
    mcp_load_result: Any
    skills: list[str]
    prompt_session: "PromptSession"
