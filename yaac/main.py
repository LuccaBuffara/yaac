"""YAAC (Yet Another Agentic Coder) - Main CLI entry point."""

import asyncio
import os

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from .agent import create_agent
from .commands import COMMAND_REGISTRY
from .config import check_api_key, load_api_keys, load_default_model, set_current_model
from .lsp.manager import shutdown_all as _lsp_shutdown
from .mcp import load_mcp_ecosystem
from .runner import read_followup_instruction, run_turn
from .skills import list_skill_names
from .state import SessionState
from .ui import console, print_beast_followup_banner, print_error, print_welcome
from .completer import build_completer, get_toolbar

PROMPT_HISTORY_FILE = os.path.expanduser("~/.yaac_prompt_history")
PROMPT_STYLE = Style.from_dict({"prompt": "ansicyan bold"})


async def _run_shell_escape(command: str) -> None:
    proc = await asyncio.create_subprocess_shell(command, stdout=None, stderr=None)
    await proc.wait()
    if proc.returncode:
        console.print(f"[dim]exit {proc.returncode}[/dim]")


async def run_session(model: str, beast_context: str = "", mcp_config: str | None = None) -> None:
    from .session import init_session
    init_session()

    set_current_model(model)
    mcp_load_result = load_mcp_ecosystem(mcp_config)
    try:
        agent = create_agent(model, system_prompt_addition=beast_context, mcp_load_result=mcp_load_result)
    except Exception as e:
        agent = None
        _init_error = str(e)
    else:
        _init_error = ""

    skills = list_skill_names()
    prompt_session: PromptSession = PromptSession(
        history=FileHistory(PROMPT_HISTORY_FILE),
        style=PROMPT_STYLE,
        completer=build_completer(),
        complete_while_typing=True,
        bottom_toolbar=get_toolbar,
    )
    state = SessionState(
        model=model,
        agent=agent,
        message_history=[],
        cost=0.0,
        tokens_in=0,
        tokens_out=0,
        beast_context=beast_context,
        mcp_load_result=mcp_load_result,
        skills=skills,
        prompt_session=prompt_session,
    )

    if beast_context:
        print_beast_followup_banner()
    else:
        print_welcome()

    if _init_error:
        print_error(f"Failed to initialise model [bold]{model}[/bold]: {_init_error}")
        console.print(
            "  Use [cyan]/model <provider:model-id>[/cyan] to switch to a different model.\n"
            "  Use [cyan]/key <value>[/cyan] to set the API key for the current provider.\n"
        )
    else:
        ok, missing_key = check_api_key(model)
        if not ok:
            console.print(
                f"[bold yellow]⚠ Not configured.[/bold yellow]  "
                f"Model [bold]{model}[/bold] requires [bold yellow]{missing_key}[/bold yellow].\n"
                f"  Set it now:  [cyan]/key <your-api-key>[/cyan]\n"
                f"  Switch model: [cyan]/model <provider:model-id>[/cyan]  "
                f"(e.g. [dim]openai:gpt-4o[/dim])\n"
            )

    if skills:
        names = ", ".join(f"[cyan]{s}[/cyan]" for s in skills)
        console.print(f"[dim]Skills:[/dim] {names}\n")

    if mcp_load_result.config_path or mcp_load_result.warnings:
        if mcp_load_result.servers:
            server_names = ", ".join(f"[cyan]{r.name}[/cyan]" for r in mcp_load_result.servers)
            console.print(f"[dim]MCP servers:[/dim] {server_names}")
        for warning in mcp_load_result.warnings:
            console.print(f"[yellow]MCP warning:[/yellow] {warning}")

    while True:
        try:
            user_input = await prompt_session.prompt_async([("class:prompt", "\n> ")])
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            await _lsp_shutdown()
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "bye"):
            console.print("[dim]Goodbye![/dim]")
            break

        if user_input.startswith("!"):
            shell_cmd = user_input[1:].strip()
            if shell_cmd:
                await _run_shell_escape(shell_cmd)
            continue

        if user_input.startswith("/"):
            cmd, _, args = user_input[1:].partition(" ")
            handler = COMMAND_REGISTRY.get(cmd.lower())
            if handler is not None:
                await handler(state, args.strip())
                continue
            # Unknown slash command — fall through to agent

        if state.agent is None:
            _, missing_key = check_api_key(state.model)
            if missing_key:
                print_error(
                    f"No agent — [bold]{missing_key}[/bold] is not set. "
                    f"Use [cyan]/key <value>[/cyan] to configure it."
                )
            else:
                print_error("No agent — use [cyan]/model <id>[/cyan] to reconfigure.")
            continue

        pending_input = user_input
        while pending_input:
            try:
                console.print()
                await run_turn(state, pending_input)
                pending_input = ""
            except KeyboardInterrupt:
                pending_input = await read_followup_instruction(prompt_session, pending_input)
            except Exception as e:
                err_str = str(e)
                auth_hints = ("api key", "apikey", "api_key", "authentication", "401", "unauthorized", "permission")
                if any(h in err_str.lower() for h in auth_hints):
                    _, missing_key = check_api_key(state.model)
                    env_hint = "  Set it with: [cyan]/key <your-api-key>[/cyan]" if missing_key else ""
                    print_error(f"Authentication failed — check your API key.\n{env_hint}")
                else:
                    transient_hints = (
                        "eof while parsing", "unexpected eof", "incomplete chunked read",
                        "connection reset", "connection closed", "remoteprotocolerror",
                        "readtimeout", "server disconnected",
                    )
                    is_transient = any(h in err_str.lower() for h in transient_hints)
                    if is_transient:
                        print_error(f"{err_str}\n  (transient connection/parsing failure — retrying automatically)")
                        console.print()
                        try:
                            await run_turn(state, pending_input)
                            pending_input = ""
                            continue
                        except Exception as retry_err:
                            print_error(f"Retry also failed: {retry_err}")
                    else:
                        print_error(err_str)
                if os.environ.get("YAAC_DEBUG"):
                    import traceback
                    traceback.print_exc()
                pending_input = ""


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="yaac",
        description="YAAC (Yet Another Agentic Coder) — AI Coding Assistant",
        add_help=True,
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="PROVIDER:MODEL_ID",
        help=(
            "Model to use, as provider:model-id "
            "(e.g. anthropic:claude-sonnet-4-6, openai:gpt-4o, google:gemini-2.0-flash). "
            "Defaults to YAAC_MODEL env var or ~/.yaac/config.json."
        ),
    )
    parser.add_argument(
        "--mcp-config",
        default=None,
        metavar="PATH",
        help=(
            "Claude-style MCP config JSON path. If omitted, YAAC checks YAAC_MCP_CONFIG, "
            "~/.yaac/config.json, ./.mcp.json, and ./.yaac/mcp.json."
        ),
    )
    args = parser.parse_args()

    load_api_keys()
    model = args.model or load_default_model()

    try:
        asyncio.run(run_session(model, mcp_config=args.mcp_config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
