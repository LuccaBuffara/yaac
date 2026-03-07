"""Terminal UI utilities for Helena Code."""

from rich.console import Console, Group
from rich.columns import Columns
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

HELENA_THEME = Theme(
    {
        "helena.prompt": "bold cyan",
        "helena.tool": "dim #FFD700",
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

# Slim BEAST
_BEAST_ART = """\
 ████    ██████    ▄█▄    █████  ██████
 █   █   █        █ █   ▀█         █  
 ████    ████    █████    ████      █  
 █   █   █       █   █       █     █  
 ████    ██████  █   █   █████      █  """

_BEAST_COLORS = [
    "#FF4040",
    "#FF5533",
    "#FF6600",
    "#FF3355",
    "#FF1040",
]

def _gradient_art(art: str, colors: list[str]) -> Text:
    """Render ASCII art with a per-row colour gradient."""
    t = Text()
    for i, line in enumerate(art.splitlines()):
        color = colors[min(i, len(colors) - 1)]
        t.append(line + ("\n" if i < art.count("\n") else ""), style=f"bold {color}")
    return t


# ---------------------------------------------------------------------------
# Banners
# ---------------------------------------------------------------------------


def print_welcome() -> None:
    wordmark = Text.assemble(
        ("Helena", "bold #00BFFF"),
        (" Code", "bold #7B61FF"),
        ("  ·  ", "dim #333366"),
        ("AI Coding Agent", "dim white"),
    )
    hint = Text.assemble(
        (" ⌨  ", "dim #00BFFF"),
        ("type a request", "dim"),
        ("  ·  ", "dim"),
        ("/help", "bold dim"),
        ("  ·  ", "dim"),
        ("exit", "bold #BF5FFF"),
    )
    console.print(
        Panel(
            Group(wordmark, hint),
            border_style="#7B61FF",
            padding=(0, 2),
        )
    )
    console.print()


def print_beast_banner() -> None:
    art = _gradient_art(_BEAST_ART, _BEAST_COLORS)
    badge_line = Text.assemble(
        (" ◈ ", "bold #FF4040"),
        ("M O D E", "bold white"),
        ("  ", ""),
        ("Multi-agent parallel execution", "bold #FF6600"),
    )
    console.print(Panel(Group(art, Text(""), badge_line), border_style="#FF4040", padding=(1, 3)))
    console.print()


def print_beast_followup_banner() -> None:
    art = _gradient_art(_BEAST_ART, _BEAST_COLORS)
    badge_line = Text.assemble(
        (" ⚡ ", "bold #FF6600"),
        ("Follow-up session", "bold white"),
        ("  —  ", "dim"),
        ("Ask about what the agents just completed.", "dim"),
    )
    hint = Text.assemble(
        (" ⌨  ", "dim #00BFFF"),
        ("type a request", "dim"),
        ("  ·  ", "dim"),
        ("exit", "bold #BF5FFF"),
    )
    console.print(
        Panel(
            Group(art, Text(""), badge_line, Text(""), hint),
            border_style="#FF4040",
            padding=(1, 3),
            subtitle="[dim #443333]  ⬡  BEAST/MODE  ⬡  [/]",
        )
    )
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
