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


async def run_session(model: str) -> None:
    agent = create_agent(model)
    message_history = load_history()

    session: PromptSession = PromptSession(
        history=FileHistory(PROMPT_HISTORY_FILE),
        style=PROMPT_STYLE,
    )

    print_welcome()

    if message_history:
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
            await _run_turn(agent, user_input, message_history)
            save_history(message_history)
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:
            print_error(str(e))
            if os.environ.get("HELENA_DEBUG"):
                import traceback
                traceback.print_exc()


async def _run_turn(agent: Any, user_input: str, message_history: list) -> None:
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
    try:
        with Live(console=console, refresh_per_second=20, transient=False) as live:
            ticker = asyncio.create_task(_ticker(live))
            try:
                async with agent.run_stream(
                    user_input,
                    message_history=message_history,
                ) as result:
                    async for chunk in result.stream_text(delta=True):
                        response_text += chunk
                        _render(live)
                    usage = result.usage()
                    message_history[:] = list(result.all_messages())
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
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    model = os.environ.get("HELENA_MODEL", "claude-sonnet-4-6")

    try:
        asyncio.run(run_session(model))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
