"""Shared utilities for YAAC."""

import asyncio
from typing import Any, Callable, TypeVar

_T = TypeVar("_T")


async def retry_async(
    fn: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    backoff: float = 1.0,
    **kwargs: Any,
) -> Any:
    """Call an async function with exponential backoff retry on transient exceptions.

    Args:
        fn: Async callable to invoke.
        *args: Positional arguments forwarded to fn.
        max_attempts: Total number of attempts (default 3).
        backoff: Base wait time in seconds; doubles each attempt (1s, 2s, 4s, …).
        **kwargs: Keyword arguments forwarded to fn.

    Returns:
        The return value of fn on success.

    Raises:
        The last exception if all attempts fail.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            if attempt == max_attempts:
                raise
            await asyncio.sleep(backoff * (2 ** (attempt - 1)))
