"""Shell execution tools for Helena Code."""

import asyncio

from ..tool_events import emit_call, emit_return


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
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
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

    except Exception as e:
        result = f"Error running command: {e}"

    emit_return("run_bash", result)
    return result
