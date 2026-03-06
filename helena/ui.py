"""Terminal UI utilities for Helena Code."""

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

HELENA_THEME = Theme(
    {
        "helena.prompt": "bold cyan",
        "helena.tool": "dim yellow",
        "helena.tool_result": "dim green",
        "helena.error": "bold red",
        "helena.success": "bold green",
        "helena.info": "dim white",
        "helena.assistant": "white",
    }
)

console = Console(theme=HELENA_THEME)


def print_welcome() -> None:
    panel = Panel(
        Text.assemble(
            ("Helena Code", "bold cyan"),
            " · ",
            ("AI Coding Assistant", "dim white"),
            "\n\n",
            ("Powered by Pydantic AI + Claude\n", "dim"),
            ('Type your request, or "exit" to quit.', "dim"),
        ),
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)


def print_assistant_message(text: str) -> None:
    console.print(Markdown(text), style="helena.assistant")


def print_tool_call(tool_name: str, args: dict) -> None:
    arg_str = ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items())
    console.print(f"  ⚙ [helena.tool]{tool_name}({arg_str})[/helena.tool]")


def print_tool_result(result: str, max_lines: int = 5) -> None:
    lines = result.splitlines()
    preview = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        preview += f"\n  ... ({len(lines) - max_lines} more lines)"
    console.print(f"  [helena.tool_result]{preview}[/helena.tool_result]")


def print_error(message: str) -> None:
    console.print(f"[helena.error]Error:[/helena.error] {message}")


def print_info(message: str) -> None:
    console.print(f"[helena.info]{message}[/helena.info]")
