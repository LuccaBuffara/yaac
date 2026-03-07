"""YAAC (Yet Another Agentic Coder) - Main CLI entry point."""

import os
import shutil
import sys
import asyncio
import time
import threading
from typing import TYPE_CHECKING, Any, cast

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from pydantic_ai.messages import PartStartEvent, PartDeltaEvent, TextPartDelta, TextPart, ToolCallPart
from pydantic_ai.usage import UsageLimits
from .agent import create_agent
from rich.markdown import Markdown
from .config import (
    check_api_key, get_context_window, calculate_cost, load_api_keys,
    load_default_model, parse_model_str, PROVIDER_ENV_KEYS,
    resolve_model, save_api_key, save_default_model, set_current_model,
)

_UNLIMITED = UsageLimits(request_limit=None)
from .context_files import discover_agents_files, discover_memory_file
from .tools.memory_tools import _memory_path, _DEFAULT_MEMORY_TEMPLATE
from .history import (
    clear_history,
    trim_tool_results, trim_history, prune_old_tool_results, compact_history,
    _COMPACT_THRESHOLD,
)
from .lsp.manager import shutdown_all as _lsp_shutdown
from .skills import list_skill_names
from .tool_events import set_handler, reset_handler
from .ui import console, print_welcome, print_beast_followup_banner, print_error, print_info
from .completer import build_completer, get_toolbar, run_model_picker, set_toolbar_stats

PROMPT_HISTORY_FILE = os.path.expanduser("~/.yaac_prompt_history")

PROMPT_STYLE = Style.from_dict({"prompt": "ansicyan bold"})


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


async def _read_followup_instruction(session: PromptSession, previous_instruction: str) -> str:
    console.print("\n[dim]Interrupted. Press Enter to keep the last instruction and add details.[/dim]")
    try:
        extra = await session.prompt_async([("class:prompt", "↩ details> ")])
    except (EOFError, KeyboardInterrupt):
        return ""

    extra = extra.strip()
    if not extra:
        return previous_instruction
    return f"{previous_instruction}\n\nAdditional user details:\n{extra}"

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage
    from halo import Halo as HaloType  # type: ignore[import-untyped]


def _estimate_history_tokens(message_history: list) -> int:
    """Estimate token count of message history (4 chars ≈ 1 token)."""
    try:
        return sum(len(str(m)) for m in message_history) // 4
    except Exception:
        return 0


async def _run_shell_escape(command: str) -> None:
    """Run a user shell command directly, streaming output to the terminal."""
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=None,
        stderr=None,
    )
    await proc.wait()
    if proc.returncode:
        console.print(f"[dim]exit {proc.returncode}[/dim]")


async def run_session(model: str, beast_context: str = "") -> None:
    from .session import init_session
    init_session()

    set_current_model(model)
    try:
        agent = create_agent(model, system_prompt_addition=beast_context)
    except Exception as e:
        agent = None
        _init_error = str(e)
    else:
        _init_error = ""
    message_history: list[ModelMessage] = []

    session: PromptSession = PromptSession(
        history=FileHistory(PROMPT_HISTORY_FILE),
        style=PROMPT_STYLE,
        completer=build_completer(),
        complete_while_typing=True,
        bottom_toolbar=get_toolbar,
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

    skills = list_skill_names()
    if skills:
        names = ", ".join(f"[cyan]{s}[/cyan]" for s in skills)
        console.print(f"[dim]Skills:[/dim] {names}\n")

    session_cost: list[float] = [0.0]      # mutable accumulators passed into _run_turn
    session_tokens: list[int] = [0, 0]    # [input_total, output_total]

    while True:
        try:
            user_input = await session.prompt_async([("class:prompt", "\n> ")])
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

        if user_input.lower() in ("/clear", "/reset"):
            clear_history()
            message_history = []
            session_cost[0] = 0.0
            session_tokens[0] = 0
            session_tokens[1] = 0
            set_toolbar_stats("")
            print_info("Conversation history cleared.")
            continue

        if user_input.lower() == "/banner":
            print_welcome()
            continue

        if user_input.lower().startswith("/memory"):
            if user_input.lower().strip() == "/memory init":
                path = _memory_path()
                if path.exists():
                    print_info(f"Project memory already exists at [bold]{path}[/bold].")
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(_DEFAULT_MEMORY_TEMPLATE, encoding="utf-8")
                    print_info(f"Created project memory at [bold]{path}[/bold].")
                continue

            agents_files = discover_agents_files()
            memory_file = discover_memory_file()
            if agents_files:
                console.print("\n[bold cyan]AGENTS.md files[/bold cyan]")
                for path in agents_files:
                    console.print(f"  • [white]{path}[/white]")
            else:
                console.print("\n[dim]No AGENTS.md files discovered in this workspace lineage.[/dim]")
            if memory_file and memory_file.exists():
                console.print(f"\n[bold cyan]Project memory[/bold cyan]\n  • [white]{memory_file}[/white]\n")
                console.print(Markdown(memory_file.read_text(encoding="utf-8")))
            else:
                console.print(f"\n[dim]No project memory found. Suggested path: {_memory_path()}[/dim]\n")
            continue

        if user_input.lower() == "/stats":
            _print_stats(model, message_history, session_cost, session_tokens)
            continue

        if user_input.lower() == "/compact":
            if len(message_history) <= 2:
                print_info("History is already minimal — nothing to compact.")
            else:
                print_info("Compacting conversation history...")
                message_history[:] = await compact_history(message_history, model)
                print_info("History compacted.")
            continue

        if user_input.lower() == "/help":
            _print_help(skills)
            continue

        if user_input.lower() == "/skills":
            _print_skills(skills)
            continue

        if user_input.lower().startswith("/model"):
            parts = user_input.split(None, 1)
            if len(parts) == 1:
                # No argument — open the interactive picker
                new_model = await run_model_picker(current_model=model)
                if new_model is None:
                    print_info("Cancelled.")
                    continue
            else:
                new_model = parts[1].strip()

            try:
                resolve_model(new_model)  # validate provider/model before accepting
                model = new_model
                set_current_model(model)
                save_default_model(model)
                try:
                    agent = create_agent(model, system_prompt_addition=beast_context)
                except Exception as e:
                    agent = None
                    print_error(f"Could not initialise model: {e}")
                else:
                    print_info(f"Model switched to [bold]{model}[/bold] and saved as default.")
                # Warn immediately if the new model lacks a key
                ok2, missing2 = check_api_key(model)
                if not ok2:
                    console.print(
                        f"[yellow]⚠ {missing2} is not set. "
                        f"Use [cyan]/key <value>[/cyan] to configure it.[/yellow]"
                    )
            except (ValueError, ImportError) as e:
                print_error(str(e))
            continue

        if user_input.lower().startswith("/key"):
            provider, _ = parse_model_str(model)
            env_var = PROVIDER_ENV_KEYS.get(provider)
            if env_var is None:
                print_info(f"Provider [bold]{provider}[/bold] does not require an API key.")
                continue
            parts = user_input.split(None, 1)
            if len(parts) == 1:
                is_set = bool(os.environ.get(env_var))
                status = "[green]set[/green]" if is_set else "[red]not set[/red]"
                print_info(f"[bold]{env_var}[/bold] — {status}")
            else:
                key_value = parts[1].strip()
                save_api_key(env_var, key_value)
                print_info(f"[bold]{env_var}[/bold] saved.")
                # Recreate agent now that the key is available
                try:
                    agent = create_agent(model, system_prompt_addition=beast_context)
                except Exception as e:
                    print_error(f"Could not initialise agent: {e}")
            continue

        if agent is None:
            _, missing_key = check_api_key(model)
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
                await _run_turn(agent, pending_input, message_history, model, session_cost, session_tokens)
                pending_input = ""
            except KeyboardInterrupt:
                pending_input = await _read_followup_instruction(session, pending_input)
            except Exception as e:
                err_str = str(e)
                # Detect missing / invalid API key errors from any provider
                auth_hints = ("api key", "apikey", "api_key", "authentication", "401", "unauthorized", "permission")
                if any(h in err_str.lower() for h in auth_hints):
                    _, missing_key = check_api_key(model)
                    env_hint = f"  Set it with: [cyan]/key <your-api-key>[/cyan]" if missing_key else ""
                    print_error(f"Authentication failed — check your API key.\n{env_hint}")
                else:
                    # Detect transient JSON/connection errors and offer auto-retry
                    transient_hints = (
                        "eof while parsing",
                        "unexpected eof",
                        "incomplete chunked read",
                        "connection reset",
                        "connection closed",
                        "remoteprotocolerror",
                        "readtimeout",
                        "server disconnected",
                    )
                    is_transient = any(h in err_str.lower() for h in transient_hints)
                    if is_transient:
                        print_error(f"{err_str}\n  (transient connection/parsing failure — retrying automatically)")
                        console.print()
                        try:
                            await _run_turn(agent, pending_input, message_history, model, session_cost, session_tokens)
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


async def _run_turn(agent: Any, user_input: str, message_history: list, model: str = "", session_cost: list[float] | None = None, session_tokens: list[int] | None = None) -> None:
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
            _print_patch(tool_name, data["diff"], data.get("language"))
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
        prepared = prune_old_tool_results(trim_history(trim_tool_results(message_history)))
        async with agent.iter(user_input, message_history=prepared, usage_limits=_UNLIMITED) as run:
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
        message_history[:] = list(run.all_messages()) if run is not None else message_history
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
    ctx_window = get_context_window(model)
    input_pct = 0.0
    if usage:
        in_tok = usage.input_tokens or 0
        out_tok = usage.output_tokens or 0
        if session_tokens is not None:
            session_tokens[0] += in_tok
            session_tokens[1] += out_tok
        s_in = session_tokens[0] if session_tokens else in_tok
        s_out = session_tokens[1] if session_tokens else out_tok
        s_total = s_in + s_out
        if s_total:
            parts_stats.append(f"in {s_in:,} · out {s_out:,} · total {s_total:,} tok")
        if ctx_window and s_in:
            input_pct = s_in / ctx_window
            parts_stats.append(f"ctx {input_pct * 100:.1f}%")
        turn_cost = calculate_cost(model, in_tok, out_tok)
        if turn_cost is not None:
            if session_cost is not None:
                session_cost[0] += turn_cost
            total_cost = session_cost[0] if session_cost else turn_cost
            cost_str = f"<$0.001" if total_cost < 0.001 else f"${total_cost:.4f}"
            parts_stats.append(cost_str)
    if len(parts_stats) > 1:
        set_toolbar_stats(" · ".join(parts_stats))

    # Compact history when context usage is high to avoid runaway token costs.
    if ctx_window and input_pct >= _COMPACT_THRESHOLD and len(message_history) > 2:
        print_info("Compacting conversation history to reduce context size...")
        message_history[:] = await compact_history(message_history, model)
        print_info("History compacted.")



def _print_patch(path: str, diff: str, language: str | None = None) -> None:
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



def _print_stats(
    model: str,
    message_history: list,
    session_cost: list[float],
    session_tokens: list[int],
) -> None:
    from .config import get_context_window, get_model_price

    turns = len([m for m in message_history if hasattr(m, 'parts') and any(
        hasattr(p, 'content') and not hasattr(p, 'tool_name') for p in m.parts
    )]) // 2 or len(message_history) // 2
    ctx_window = get_context_window(model)
    est_tokens = _estimate_history_tokens(message_history)

    console.print(f"\n[bold cyan]Session Stats[/bold cyan]")
    console.print(f"  [dim]Model:[/dim]           [white]{model}[/white]")
    if ctx_window:
        pct = est_tokens / ctx_window * 100
        console.print(f"  [dim]Context:[/dim]         ~{est_tokens:,} / {ctx_window:,} tokens ({pct:.1f}%)")
    console.print(f"  [dim]Messages:[/dim]        {len(message_history)}")
    s_in, s_out = session_tokens
    if s_in or s_out:
        console.print(f"  [dim]Tokens:[/dim]          in {s_in:,} · out {s_out:,} · total {s_in + s_out:,}")
    price = get_model_price(model)
    if price:
        console.print(f"  [dim]Pricing:[/dim]         ${price[0]:.2f} / ${price[1]:.2f} per M tokens (in/out)")
    cost = session_cost[0]
    cost_str = f"<$0.001" if 0 < cost < 0.001 else f"${cost:.4f}"
    console.print(f"  [dim]Session cost:[/dim]    {cost_str}")
    console.print()


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
        "\n[bold cyan]YAAC[/bold cyan] — Commands:\n"
        "  [cyan]/memory[/cyan]         Show the durable project memory file path and contents if present\n"
        "  [cyan]/memory init[/cyan]    Create a starter .yaac/memory/MEMORY.md if missing\n"
        "  [cyan]/clear[/cyan]          Clear conversation history and reset costs\n"
        "  [cyan]/model[/cyan]          Open interactive provider/model picker\n"
        "  [cyan]/model <id>[/cyan]     Switch model directly (e.g. [dim]openai:gpt-4o[/dim])\n"
        "  [cyan]/key[/cyan]            Show API key status for the current provider\n"
        "  [cyan]/key <value>[/cyan]    Set & save the API key for the current provider\n"
        "  [cyan]/stats[/cyan]          Show session statistics (tokens, cost, context usage)\n"
        "  [cyan]/compact[/cyan]        Summarize old history to free up context space\n"
        "  [cyan]/banner[/cyan]         Show the welcome banner\n"
        "  [cyan]/skills[/cyan]         List loaded skills\n"
        "  [cyan]!<cmd>[/cyan]          Run a shell command directly (e.g. [dim]!git status[/dim])\n"
        "  [cyan]i[/cyan]               Interrupt the current run and add more details\n"
        "  [cyan]/help[/cyan]           Show this help\n"
        "  [cyan]exit[/cyan]            Quit\n\n"
        "Model format: [yellow]provider:model-id[/yellow]\n"
        "  Providers: [yellow]anthropic, openai, google, groq, mistral, ollama[/yellow]\n\n"
        "Config file: [yellow]~/.yaac/config.json[/yellow]  "
        "(keys and default model are persisted here)\n"
        "Env var override: [yellow]YAAC_MODEL[/yellow]\n"
        "Set [yellow]YAAC_DEBUG=1[/yellow] for full error tracebacks.\n"
    )


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
    args = parser.parse_args()

    # Load any API keys saved in ~/.yaac/config.json into the environment first.
    load_api_keys()

    model = args.model or load_default_model()

    try:
        asyncio.run(run_session(model))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
