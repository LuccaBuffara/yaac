"""Shell execution tools for Helena Code."""

import asyncio

from ..tool_events import emit_call, emit_return

_MAX_OUTPUT_CHARS = 5_000  # bash output larger than this is tail-truncated


async def run_bash(command: str, timeout: int = 30, working_directory: str | None = None) -> str:
    """Execute a bash command and return its output.

    Use this for running tests, build commands, git operations, and other
    shell tasks. Avoid using this for file operations — use the dedicated
    file tools instead.

    Args:
        command: The bash command to execute.
        timeout: Maximum seconds to wait for the command (default 30).
        working_directory: Directory to run the command in. Defaults to cwd.

    Returns:
        Combined stdout and stderr output, with exit code on failure.
    """
    import os
    cwd = working_directory or os.getcwd()

    emit_call("run_bash", {"command": command})

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            start_new_session=True,  # own process group → killpg terminates background children too
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            # Kill the entire process group so background processes spawned by
            # the shell (e.g. `node server.js &`) are also terminated and the
            # stdout/stderr pipes are closed.
            import os
            import signal
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
            try:
                await asyncio.wait_for(proc.communicate(), timeout=5)
            except Exception:
                pass
            result = f"[Command timed out after {timeout} seconds]"
            emit_return("run_bash", result)
            return result

        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")

        output_parts = []
        if stdout:
            output_parts.append(stdout)
        if stderr:
            output_parts.append(f"[stderr]\n{stderr}")

        output = "\n".join(output_parts).strip()

        if proc.returncode != 0:
            result = f"{output}\n\n[Exit code: {proc.returncode}]" if output else f"[Command failed with exit code {proc.returncode}]"
        else:
            result = output or "[Command completed with no output]"

        if len(result) > _MAX_OUTPUT_CHARS:
            kept = result[-_MAX_OUTPUT_CHARS:]
            dropped = len(result) - _MAX_OUTPUT_CHARS
            result = f"[… {dropped} chars truncated from start]\n{kept}"

    except Exception as e:
        result = f"Error running command: {e}"

    emit_return("run_bash", result)
    return result
