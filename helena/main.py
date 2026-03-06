"""Helena Code - Main CLI entry point."""

import os
import sys
import asyncio
import time
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.live import Live
from rich.panel import Panel
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text

from .agent import create_agent
from .history import load_history, save_history, clear_history
from .skills import list_skill_names
from .tool_events import set_handler, reset_handler
from .ui import console, print_welcome, print_error, print_info

PROMPT_HISTORY_FILE = os.path.expanduser("~/.helena_prompt_history")

PROMPT_STYLE = Style.from_dict({"prompt": "ansicyan bold"})

# Context window sizes by model (input tokens)
_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-5": 200_000,
}


def _get_context_window(model_name: str) -> int | None:
    for key, size in _CONTEXT_WINDOWS.items():
        if key in model_name:
            return size
    return None


def _estimate_history_tokens(message_history: list) -> int:
    """Estimate token count of message history (4 chars ≈ 1 token)."""
    try:
        return sum(len(str(m)) for m in message_history) // 4
    except Exception:
        return 0


async def run_session(model: str, beast_context: str = "") -> None:
    agent = create_agent(model, system_prompt_addition=beast_context)
    message_history = load_history()

    session: PromptSession = PromptSession(
        history=FileHistory(PROMPT_HISTORY_FILE),
        style=PROMPT_STYLE,
    )

    if beast_context:
        console.print(Panel(
            Text.assemble(
                ("Helena Code", "bold cyan"), " · ", ("Beast Mode Follow-up", "bold red"),
                "\n\n", ("Ask follow-up questions about the completed task.\n", "dim"),
                ('Type your request, or "exit" to quit.', "dim"),
            ),
            border_style="cyan",
            padding=(1, 2),
        ))
    else:
        print_welcome()

    if message_history and not beast_context:
        print_info(f"Resuming conversation ({len(message_history)} messages in history). Use /clear to start fresh.\n")

    skills = list_skill_names()
    if skills:
        names = ", ".join(f"[cyan]{s}[/cyan]" for s in skills)
        console.print(f"[dim]Skills:[/dim] {names}\n")

    while True:
        try:
            user_input = await session.prompt_async([("class:prompt", "\n> ")])
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "bye"):
            console.print("[dim]Goodbye![/dim]")
            break

        if user_input.lower() in ("/clear", "/reset"):
            clear_history()
            message_history = []
            print_info("Conversation history cleared.")
            continue

        if user_input.lower() == "/help":
            _print_help(skills)
            continue

        if user_input.lower() == "/skills":
            _print_skills(skills)
            continue

        try:
            console.print()
            await _run_turn(agent, user_input, message_history, model)
            save_history(message_history)
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:
            print_error(str(e))
            if os.environ.get("HELENA_DEBUG"):
                import traceback
                traceback.print_exc()


async def _run_turn(agent: Any, user_input: str, message_history: list, model: str = "") -> None:
    from rich.console import Group

    start_time = time.monotonic()
    response_text = ""
    tool_lines: list[str] = []

    def _on_tool_event(event_type: str, tool_name: str, data: Any) -> None:
        """Called synchronously by tools as they run."""
        if event_type == "call":
            arg_str = ", ".join(f"{k}={repr(v)[:60]}" for k, v in data.items())
            tool_lines.append(f"  ⚙ [dim yellow]{tool_name}({arg_str})[/dim yellow]")
        elif event_type == "return":
            lines = str(data).splitlines()
            preview = "\n    ".join(lines[:4])
            if len(lines) > 4:
                preview += f"\n    ... ({len(lines) - 4} more lines)"
            tool_lines.append(f"    [dim green]{preview}[/dim green]")

    def _render(live: Live) -> None:
        elapsed = time.monotonic() - start_time
        spinner = Spinner("dots")
        parts: list[Any] = []

        for tl in tool_lines:
            parts.append(Text.from_markup(tl))

        if response_text:
            if tool_lines:
                parts.append(Text(""))
            parts.append(Markdown(response_text))
            parts.append(Text(f"  {elapsed:.1f}s", style="dim cyan"))
        else:
            parts.append(
                Text.assemble(spinner.render(time.monotonic()), ("  thinking...  ", "dim"), (f"{elapsed:.1f}s", "dim cyan"))
            )

        live.update(Group(*parts))

    async def _ticker(live: Live) -> None:
        """Refresh the spinner/timer every 100ms while the agent is running."""
        while True:
            _render(live)
            await asyncio.sleep(0.1)

    token = set_handler(_on_tool_event)
    usage = None
    try:
        with Live(console=console, refresh_per_second=20, transient=False) as live:
            ticker = asyncio.create_task(_ticker(live))
            try:
                result = await agent.run(
                    user_input,
                    message_history=message_history,
                )
                response_text = result.output
                usage = result.usage()
                message_history[:] = list(result.all_messages())
                _render(live)
            finally:
                ticker.cancel()
                _render(live)
    finally:
        reset_handler(token)

    elapsed_total = time.monotonic() - start_time

    # Live display with transient=False already committed the final render.
    # Only print the stats line.
    parts_stats = [f"{elapsed_total:.1f}s"]
    if usage:
        if usage.input_tokens:
            parts_stats.append(f"in {usage.input_tokens:,}")
        if usage.output_tokens:
            parts_stats.append(f"out {usage.output_tokens:,}")
        if usage.total_tokens:
            parts_stats.append(f"total {usage.total_tokens:,} tokens")
        ctx_window = _get_context_window(model)
        if ctx_window and message_history:
            est = _estimate_history_tokens(message_history)
            pct = est / ctx_window * 100
            parts_stats.append(f"~{pct:.1f}% ctx")
    console.print(Text("  " + " · ".join(parts_stats), style="dim"))



def _print_skills(skills: list[str]) -> None:
    if not skills:
        console.print("[dim]No skills loaded.[/dim]")
        return
    console.print("\n[bold cyan]Loaded Skills:[/bold cyan]")
    for s in skills:
        console.print(f"  • [cyan]{s}[/cyan]")
    console.print()


def _print_help(skills: list[str]) -> None:
    console.print(
        "\n[bold cyan]Helena Code[/bold cyan] — Commands:\n"
        "  [cyan]/clear[/cyan]    Clear conversation history\n"
        "  [cyan]/skills[/cyan]   List loaded skills\n"
        "  [cyan]/help[/cyan]     Show this help\n"
        "  [cyan]exit[/cyan]      Quit\n\n"
        "Set [yellow]HELENA_DEBUG=1[/yellow] for full error tracebacks.\n"
        "Set [yellow]HELENA_MODEL=<model-id>[/yellow] to change the Claude model.\n"
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="helena",
        description="Helena Code — AI Coding Assistant",
        add_help=True,
    )
    parser.add_argument(
        "--beast",
        nargs="?",
        const=True,
        metavar="TASK",
        help="Beast Mode: spawn multiple parallel agents to tackle a task. "
             "Provide the task inline or omit to be prompted.",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL_ID",
        help="Override the Claude model (default: claude-sonnet-4-6).",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    model = args.model or os.environ.get("HELENA_MODEL", "claude-sonnet-4-6")

    if args.beast is not None:
        from .beast import run_beast_mode

        if isinstance(args.beast, str) and args.beast:
            task = args.beast
        else:
            try:
                task = input("\n⚡ Beast Mode — Enter task: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.", file=sys.stderr)
                sys.exit(0)
            if not task:
                print("No task provided.", file=sys.stderr)
                sys.exit(1)

        try:
            beast_context = asyncio.run(run_beast_mode(task, model))
        except KeyboardInterrupt:
            beast_context = ""

        # Drop into interactive session so the user can follow up
        console.print()
        try:
            asyncio.run(run_session(model, beast_context=beast_context))
        except KeyboardInterrupt:
            pass
        return

    try:
        asyncio.run(run_session(model))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
