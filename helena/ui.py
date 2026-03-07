"""Terminal UI utilities for Helena Code."""

from rich.console import Console, Group
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

# ---------------------------------------------------------------------------
# ASCII art
# ---------------------------------------------------------------------------

# Each letter is 6 chars wide; letters separated by 2 spaces → 47 chars total
_HELENA_ART = (
    " ██  ██  ██████  ██      ██████  ██  ██    ██  \n"
    " ██  ██  ██      ██      ██      ███ ██   ████ \n"
    " ██████  ████    ██      ████    ██ ███  ██████\n"
    " ██  ██  ██      ██      ██      ██  ██  ██  ██\n"
    " ██  ██  ██████  ██████  ██████  ██  ██  ██  ██"
)

# B-E-A-S-T, each letter 6 chars wide, separated by 2 spaces → 38 chars total
_BEAST_ART = (
    " ████    ██████    ██     █████  ██████\n"
    " ██  ██  ██       ████   ██        ██  \n"
    " ████    ████    ██████   ████     ██  \n"
    " ██  ██  ██      ██  ██      ██    ██  \n"
    " ████    ██████  ██  ██  █████     ██  "
)


# ---------------------------------------------------------------------------
# Banners
# ---------------------------------------------------------------------------

def print_welcome() -> None:
    art = Text(_HELENA_ART, style="bold cyan")
    info = Text.assemble(
        "\n  ",
        ("C O D E", "bold white"),
        ("  ·  AI Coding Assistant  ·  Powered by Claude", "dim"),
        "\n\n  ",
        ("type a request", "dim"),
        ("  ·  ", "dim"),
        ("/help", "bold dim"),
        ("  ·  ", "dim"),
        ("exit", "bold dim"),
    )
    console.print(Panel(Group(art, info), border_style="cyan", padding=(1, 2)))
    console.print()


def print_beast_banner() -> None:
    art = Text(_BEAST_ART, style="bold red")
    info = Text.assemble(
        "\n  ",
        ("M O D E", "bold white"),
        ("  ·  Multi-agent parallel execution  ·  Powered by Claude", "dim"),
    )
    console.print(Panel(Group(art, info), border_style="red", padding=(1, 2)))
    console.print()


def print_beast_followup_banner() -> None:
    art = Text(_BEAST_ART, style="bold red")
    info = Text.assemble(
        "\n  ",
        ("⚡ Follow-up session", "bold white"),
        ("  ·  Ask about what the agents just completed.", "dim"),
        "\n\n  ",
        ("type a request", "dim"),
        ("  ·  ", "dim"),
        ("exit", "bold dim"),
    )
    console.print(Panel(Group(art, info), border_style="cyan", padding=(1, 2)))
    console.print()


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

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
