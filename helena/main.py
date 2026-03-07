"""Helena Code - Main CLI entry point."""

import os
import sys
import asyncio
import time
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from pydantic_ai.usage import UsageLimits
from .agent import create_agent
from .config import (
    check_api_key, get_context_window, calculate_cost, load_api_keys,
    load_default_model, parse_model_str, PROVIDER_ENV_KEYS,
    resolve_model, save_api_key, save_default_model, set_current_model,
)

_UNLIMITED = UsageLimits(request_limit=None)
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

PROMPT_HISTORY_FILE = os.path.expanduser("~/.helena_prompt_history")

PROMPT_STYLE = Style.from_dict({"prompt": "ansicyan bold"})


def _estimate_history_tokens(message_history: list) -> int:
    """Estimate token count of message history (4 chars ≈ 1 token)."""
    try:
        return sum(len(str(m)) for m in message_history) // 4
    except Exception:
        return 0


async def run_session(model: str, beast_context: str = "") -> None:
    set_current_model(model)
    try:
        agent = create_agent(model, system_prompt_addition=beast_context)
    except Exception as e:
        agent = None
        _init_error = str(e)
    else:
        _init_error = ""
    message_history = []

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

        try:
            console.print()
            await _run_turn(agent, user_input, message_history, model, session_cost, session_tokens)
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
            try:
                new_instr = input("  ↩  New instruction (or Enter to cancel): ").strip()
            except (EOFError, KeyboardInterrupt):
                new_instr = ""
            if new_instr:
                try:
                    console.print()
                    combined = (
                        f"You were working on the following task but were interrupted:\n{user_input}\n\n"
                        f"New instruction from user:\n{new_instr}"
                    )
                    await _run_turn(agent, combined, message_history, model, session_cost, session_tokens)
                except KeyboardInterrupt:
                    console.print("\n[dim]Interrupted.[/dim]")
                except Exception as e:
                    print_error(str(e))
        except Exception as e:
            err_str = str(e)
            # Detect missing / invalid API key errors from any provider
            auth_hints = ("api key", "apikey", "api_key", "authentication", "401", "unauthorized", "permission")
            if any(h in err_str.lower() for h in auth_hints):
                _, missing_key = check_api_key(model)
                env_hint = f"  Set it with: [cyan]/key <your-api-key>[/cyan]" if missing_key else ""
                print_error(f"Authentication failed — check your API key.\n{env_hint}")
            else:
                print_error(err_str)
            if os.environ.get("HELENA_DEBUG"):
                import traceback
                traceback.print_exc()


async def _run_turn(agent: Any, user_input: str, message_history: list, model: str = "", session_cost: list[float] | None = None, session_tokens: list[int] | None = None) -> None:
    from halo import Halo
    from pydantic_ai import Agent as _PydanticAgent

    start_time = time.monotonic()
    spinner = Halo(text="thinking...", spinner="dots2", stream=sys.stdout)
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
            _print_patch(tool_name, data["diff"])
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
    try:
        prepared = prune_old_tool_results(trim_history(trim_tool_results(message_history)))
        async with agent.iter(user_input, message_history=prepared, usage_limits=_UNLIMITED) as run:
            async for node in run:
                if _PydanticAgent.is_model_request_node(node):
                    turn_text = ""
                    first_chunk = True
                    async with node.stream(run.ctx) as stream:
                        async for chunk in stream.stream_text(delta=True):
                            if first_chunk:
                                spinner.stop()
                                streaming_active = True
                                first_chunk = False
                            turn_text += chunk
                            sys.stdout.write(chunk)
                            sys.stdout.flush()
                        # Text chunks exhausted; model may still be generating
                        # tool call arguments (e.g. a large patch diff).
                        # Restart the spinner so the terminal doesn't go blank.
                        if streaming_active:
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                            streaming_active = False
                        spinner.text = "generating..."
                        spinner.start()
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



def _print_patch(path: str, diff: str) -> None:
    from rich.syntax import Syntax
    from rich.panel import Panel as RPanel

    filename = path.split("/")[-1]
    syntax = Syntax(
        diff.strip(), "diff",
        theme="monokai", line_numbers=True,
        background_color="default", word_wrap=True,
    )
    console.print(RPanel(
        syntax,
        title=f"[cyan]~ patch[/cyan]  [dim]{filename}[/dim]",
        border_style="cyan", padding=(0, 1),
    ))



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
        "  [cyan]/clear[/cyan]          Clear conversation history\n"
        "  [cyan]/skills[/cyan]         List loaded skills\n"
        "  [cyan]/model[/cyan]          Open interactive provider/model picker\n"
        "  [cyan]/model <id>[/cyan]     Switch model directly (e.g. [dim]openai:gpt-4o[/dim])\n"
        "  [cyan]/key[/cyan]            Show API key status for the current provider\n"
        "  [cyan]/key <value>[/cyan]    Set & save the API key for the current provider\n"
        "  [cyan]/help[/cyan]           Show this help\n"
        "  [cyan]exit[/cyan]            Quit\n\n"
        "Model format: [yellow]provider:model-id[/yellow]\n"
        "  Providers: [yellow]anthropic, openai, google, groq, mistral, ollama[/yellow]\n\n"
        "Config file: [yellow]~/.helena/config.json[/yellow]  "
        "(keys and default model are persisted here)\n"
        "Env var override: [yellow]HELENA_MODEL[/yellow]\n"
        "Set [yellow]HELENA_DEBUG=1[/yellow] for full error tracebacks.\n"
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
        metavar="PROVIDER:MODEL_ID",
        help=(
            "Model to use, as provider:model-id "
            "(e.g. anthropic:claude-sonnet-4-6, openai:gpt-4o, google:gemini-2.0-flash). "
            "Defaults to HELENA_MODEL env var or ~/.helena/config.json."
        ),
    )
    args = parser.parse_args()

    # Load any API keys saved in ~/.helena/config.json into the environment first.
    load_api_keys()

    model = args.model or load_default_model()

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
