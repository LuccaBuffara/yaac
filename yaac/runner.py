"""Agent turn execution — streaming, interrupt handling, and patch display."""
from __future__ import annotations

import os
import shutil
import sys
import time
import threading
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai.messages import PartStartEvent, PartDeltaEvent, TextPartDelta, TextPart, ToolCallPart
from pydantic_ai.usage import UsageLimits
from rich.markdown import Markdown

from .config import get_context_window, calculate_cost
from .history import trim_tool_results, trim_history, prune_old_tool_results, compact_history, _COMPACT_THRESHOLD
from .tool_events import set_handler, reset_handler
from .ui import console, print_info
from .completer import set_toolbar_stats
from .state import SessionState

if TYPE_CHECKING:
    from halo import Halo as HaloType  # type: ignore[import-untyped]
    from prompt_toolkit import PromptSession

_UNLIMITED = UsageLimits(request_limit=None)


# ---------------------------------------------------------------------------
# Interrupt monitor
# ---------------------------------------------------------------------------

class _InterruptMonitor:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._triggered = threading.Event()
        self._thread: threading.Thread | None = None
        self._fd: int | None = None
        self._old_settings: list[Any] | None = None

    def start(self) -> None:
        if os.name == "nt":
            self._thread = threading.Thread(target=self._run_windows, daemon=True)
            self._thread.start()
            return

        try:
            import termios
            import tty

            fd = sys.stdin.fileno()
            if not os.isatty(fd):
                return
            old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            self._fd = fd
            self._old_settings = old_settings
        except Exception:
            return

        self._thread = threading.Thread(target=self._run_posix, daemon=True)
        self._thread.start()

    def triggered(self) -> bool:
        return self._triggered.is_set()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)

        if self._fd is not None and self._old_settings is not None:
            try:
                import termios
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)
            except Exception:
                pass

    def _run_posix(self) -> None:
        import select

        while not self._stop.is_set():
            try:
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                if not ready:
                    continue
                ch = sys.stdin.read(1)
            except Exception:
                return
            if ch.lower() == "i":
                self._triggered.set()
                return

    def _run_windows(self) -> None:
        try:
            import msvcrt
        except Exception:
            return

        while not self._stop.is_set():
            try:
                if not msvcrt.kbhit():
                    self._stop.wait(0.1)
                    continue
                ch = msvcrt.getwch()
            except Exception:
                return
            if ch.lower() == "i":
                self._triggered.set()
                return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def read_followup_instruction(session: PromptSession, previous_instruction: str) -> str:
    console.print("\n[dim]Interrupted. Press Enter to keep the last instruction and add details.[/dim]")
    try:
        extra = await session.prompt_async([("class:prompt", "↩ details> ")])
    except (EOFError, KeyboardInterrupt):
        return ""

    extra = extra.strip()
    if not extra:
        return previous_instruction
    return f"{previous_instruction}\n\nAdditional user details:\n{extra}"


def _erase_raw_streamed(text: str) -> None:
    """Erase raw-streamed text from the terminal so it can be replaced with rendered Markdown."""
    cols = shutil.get_terminal_size().columns or 80
    visual_lines = 0
    for line in text.split("\n"):
        visual_lines += max(1, (len(line) + cols - 1) // cols) if line else 1
    lines_up = visual_lines - 1
    if lines_up > 0:
        sys.stdout.write(f"\r\033[{lines_up}A\033[J")
    else:
        sys.stdout.write("\r\033[J")
    sys.stdout.flush()


def print_patch(path: str, diff: str, language: str | None = None) -> None:
    from rich.syntax import Syntax
    from rich.panel import Panel as RPanel

    filename = path.split("/")[-1]
    diff_text = diff.strip()
    fence = f"```{language}" if language else "```"
    rendered = f"{fence}\n{diff_text}\n```"
    syntax = Syntax(rendered, "markdown", theme="monokai", line_numbers=True, background_color="default", word_wrap=True)
    console.print(RPanel(
        syntax,
        title=f"[cyan]~ patch[/cyan]  [dim]{filename}[/dim]",
        border_style="cyan", padding=(0, 1),
    ))


# ---------------------------------------------------------------------------
# Turn execution
# ---------------------------------------------------------------------------

async def run_turn(state: SessionState, user_input: str) -> None:
    from halo import Halo as _Halo
    from pydantic_ai import Agent as _PydanticAgent

    start_time = time.monotonic()
    spinner: HaloType = _Halo(text="thinking...", spinner="dots", stream=sys.stdout)
    spinner.start()
    streaming_active = False

    def _on_tool_event(event_type: str, tool_name: str, data: Any) -> None:
        nonlocal streaming_active
        if streaming_active:
            sys.stdout.write("\n")
            sys.stdout.flush()
            streaming_active = False

        if event_type == "call" and isinstance(data, dict):
            arg_str = ", ".join(f"{k}={repr(v)[:50]}" for k, v in data.items())
            spinner.stop()
            console.print(f"  ⚙  {tool_name}({arg_str})", style="dim")
            spinner.text = f"{tool_name}..."
            spinner.start()
        elif event_type == "patch" and isinstance(data, dict):
            spinner.stop()
            print_patch(tool_name, data["diff"], data.get("language"))
            spinner.start()
        elif event_type == "return":
            lines = str(data).splitlines()
            preview = lines[0][:120] if lines else ""
            if len(lines) > 1:
                preview += f"  … ({len(lines) - 1} more lines)"
            spinner.stop()
            console.print(f"       {preview}", style="dim")
            spinner.text = "thinking..."
            spinner.start()

    token = set_handler(_on_tool_event)
    usage = None
    run = None
    interrupt_monitor = _InterruptMonitor()
    try:
        interrupt_monitor.start()
        prepared = prune_old_tool_results(trim_history(trim_tool_results(state.message_history)))
        async with state.agent.iter(user_input, message_history=prepared, usage_limits=_UNLIMITED) as run:
            async for node in run:
                if interrupt_monitor.triggered():
                    raise KeyboardInterrupt
                if _PydanticAgent.is_model_request_node(node):
                    turn_text = ""
                    _stream_cm = cast(Any, node.stream(run.ctx))
                    async with _stream_cm as stream:
                        async for event in cast(Any, stream):
                            if interrupt_monitor.triggered():
                                raise KeyboardInterrupt
                            if isinstance(event, PartStartEvent) and isinstance(event.part, ToolCallPart):
                                if streaming_active:
                                    _erase_raw_streamed(turn_text)
                                    console.print(Markdown(turn_text))
                                    turn_text = ""
                                    streaming_active = False
                                spinner.stop()
                                spinner.text = f"building {event.part.tool_name} call..."
                                spinner.start()
                            elif isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                                chunk = event.part.content
                                if chunk:
                                    if not streaming_active:
                                        spinner.stop()
                                        sys.stdout.write("\r\033[2K")
                                        sys.stdout.flush()
                                        streaming_active = True
                                    sys.stdout.write(chunk)
                                    sys.stdout.flush()
                                    turn_text += chunk
                            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                                chunk = event.delta.content_delta
                                if not streaming_active:
                                    spinner.stop()
                                    sys.stdout.write("\r\033[2K")
                                    sys.stdout.flush()
                                    streaming_active = True
                                sys.stdout.write(chunk)
                                sys.stdout.flush()
                                turn_text += chunk
                        if streaming_active and turn_text:
                            spinner.stop()
                            _erase_raw_streamed(turn_text)
                            console.print(Markdown(turn_text))
                            turn_text = ""
                        if streaming_active:
                            streaming_active = False
                    spinner.stop()

                elif _PydanticAgent.is_call_tools_node(node):
                    spinner.text = "thinking..."
                    spinner.start()

                elif _PydanticAgent.is_end_node(node):
                    break

        usage = run.usage() if run is not None else None
        state.message_history[:] = list(run.all_messages()) if run is not None else state.message_history
        elapsed = time.monotonic() - start_time
        spinner.succeed(f"done  {elapsed:.1f}s")
    except KeyboardInterrupt:
        if streaming_active:
            sys.stdout.write("\n")
            sys.stdout.flush()
        spinner.stop()
        raise
    except Exception:
        if streaming_active:
            sys.stdout.write("\n")
            sys.stdout.flush()
        elapsed = time.monotonic() - start_time
        spinner.fail(f"failed  {elapsed:.1f}s")
        raise
    finally:
        interrupt_monitor.stop()
        reset_handler(token)

    elapsed_total = time.monotonic() - start_time
    parts_stats = [f"{elapsed_total:.1f}s"]
    ctx_window = get_context_window(state.model)
    input_pct = 0.0
    if usage:
        in_tok = usage.input_tokens or 0
        out_tok = usage.output_tokens or 0
        state.tokens_in += in_tok
        state.tokens_out += out_tok
        s_total = state.tokens_in + state.tokens_out
        if s_total:
            parts_stats.append(f"in {state.tokens_in:,} · out {state.tokens_out:,} · total {s_total:,} tok")
        if ctx_window and state.tokens_in:
            input_pct = state.tokens_in / ctx_window
            parts_stats.append(f"ctx {input_pct * 100:.1f}%")
        turn_cost = calculate_cost(state.model, in_tok, out_tok)
        if turn_cost is not None:
            state.cost += turn_cost
            cost_str = f"<$0.001" if state.cost < 0.001 else f"${state.cost:.4f}"
            parts_stats.append(cost_str)
    if len(parts_stats) > 1:
        set_toolbar_stats(" · ".join(parts_stats))

    # Compact history when context usage is high to avoid runaway token costs.
    if ctx_window and input_pct >= _COMPACT_THRESHOLD and len(state.message_history) > 2:
        print_info("Compacting conversation history to reduce context size...")
        state.message_history[:] = await compact_history(state.message_history, state.model)
        print_info("History compacted.")
