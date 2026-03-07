"""Session identity for YAAC.

Each interactive run gets a unique session ID so that session-scoped data
(todos, scratch files, etc.) can be isolated per session without conflicts.
"""

import uuid

_session_id: str | None = None


def init_session() -> str:
    """Generate and store a new session ID. Call once at the start of run_session."""
    global _session_id
    _session_id = uuid.uuid4().hex[:12]
    return _session_id


def get_session_id() -> str:
    """Return the current session ID, generating one if needed."""
    if _session_id is None:
        return init_session()
    return _session_id
