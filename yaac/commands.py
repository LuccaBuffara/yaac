"""Slash-command handlers and registry for the YAAC REPL."""
from __future__ import annotations

import os
from typing import Any, Callable, Coroutine

from rich.markdown import Markdown

from .agent import create_agent
from .config import (
    check_api_key, get_context_window, get_model_price,
    parse_model_str, PROVIDER_ENV_KEYS,
    resolve_model, save_api_key, save_default_model, set_current_model,
)
from .completer import run_model_picker, set_toolbar_stats
from .context_files import discover_agents_files, discover_memory_file
from .history import clear_history, compact_history
from .mcp import describe_mcp_status
from .tools.memory_tools import _memory_path, _DEFAULT_MEMORY_TEMPLATE
from .ui import console, print_error, print_info
from .state import SessionState


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def _estimate_history_tokens(message_history: list) -> int:
    try:
        return sum(len(str(m)) for m in message_history) // 4
    except Exception:
        return 0


def print_stats(state: SessionState) -> None:
    ctx_window = get_context_window(state.model)
    est_tokens = _estimate_history_tokens(state.message_history)

    console.print(f"\n[bold cyan]Session Stats[/bold cyan]")
    console.print(f"  [dim]Model:[/dim]           [white]{state.model}[/white]")
    if ctx_window:
        pct = est_tokens / ctx_window * 100
        console.print(f"  [dim]Context:[/dim]         ~{est_tokens:,} / {ctx_window:,} tokens ({pct:.1f}%)")
    console.print(f"  [dim]Messages:[/dim]        {len(state.message_history)}")
    if state.tokens_in or state.tokens_out:
        total = state.tokens_in + state.tokens_out
        console.print(f"  [dim]Tokens:[/dim]          in {state.tokens_in:,} · out {state.tokens_out:,} · total {total:,}")
    price = get_model_price(state.model)
    if price:
        console.print(f"  [dim]Pricing:[/dim]         ${price[0]:.2f} / ${price[1]:.2f} per M tokens (in/out)")
    cost_str = f"<$0.001" if 0 < state.cost < 0.001 else f"${state.cost:.4f}"
    console.print(f"  [dim]Session cost:[/dim]    {cost_str}")
    console.print()


def print_skills(skills: list[str]) -> None:
    if not skills:
        console.print("[dim]No skills loaded.[/dim]")
        return
    console.print("\n[bold cyan]Loaded Skills:[/bold cyan]")
    for s in skills:
        console.print(f"  • [cyan]{s}[/cyan]")
    console.print()


def print_help(skills: list[str]) -> None:
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
        "  [cyan]/mcp[/cyan]            Show active MCP config, servers, and warnings\n"
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


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def _cmd_clear(state: SessionState, _args: str) -> None:
    clear_history()
    state.message_history.clear()
    state.cost = 0.0
    state.tokens_in = 0
    state.tokens_out = 0
    set_toolbar_stats("")
    print_info("Conversation history cleared.")


async def _cmd_banner(state: SessionState, _args: str) -> None:
    from .ui import print_welcome
    print_welcome()


async def _cmd_memory(state: SessionState, args: str) -> None:
    if args.lower() == "init":
        path = _memory_path()
        if path.exists():
            print_info(f"Project memory already exists at [bold]{path}[/bold].")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_DEFAULT_MEMORY_TEMPLATE, encoding="utf-8")
            print_info(f"Created project memory at [bold]{path}[/bold].")
        return

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


async def _cmd_stats(state: SessionState, _args: str) -> None:
    print_stats(state)


async def _cmd_compact(state: SessionState, _args: str) -> None:
    if len(state.message_history) <= 2:
        print_info("History is already minimal — nothing to compact.")
    else:
        print_info("Compacting conversation history...")
        state.message_history[:] = await compact_history(state.message_history, state.model)
        print_info("History compacted.")


async def _cmd_help(state: SessionState, _args: str) -> None:
    print_help(state.skills)


async def _cmd_mcp(state: SessionState, _args: str) -> None:
    console.print(describe_mcp_status(state.mcp_load_result))


async def _cmd_skills(state: SessionState, _args: str) -> None:
    print_skills(state.skills)


async def _cmd_model(state: SessionState, args: str) -> None:
    if not args:
        new_model = await run_model_picker(current_model=state.model)
        if new_model is None:
            print_info("Cancelled.")
            return
    else:
        new_model = args

    try:
        resolve_model(new_model)
        state.model = new_model
        set_current_model(state.model)
        save_default_model(state.model)
        try:
            state.agent = create_agent(
                state.model,
                system_prompt_addition=state.beast_context,
                mcp_load_result=state.mcp_load_result,
            )
        except Exception as e:
            state.agent = None
            print_error(f"Could not initialise model: {e}")
        else:
            print_info(f"Model switched to [bold]{state.model}[/bold] and saved as default.")
        ok2, missing2 = check_api_key(state.model)
        if not ok2:
            console.print(
                f"[yellow]⚠ {missing2} is not set. "
                f"Use [cyan]/key <value>[/cyan] to configure it.[/yellow]"
            )
    except (ValueError, ImportError) as e:
        print_error(str(e))


async def _cmd_key(state: SessionState, args: str) -> None:
    provider, _ = parse_model_str(state.model)
    env_var = PROVIDER_ENV_KEYS.get(provider)
    if env_var is None:
        print_info(f"Provider [bold]{provider}[/bold] does not require an API key.")
        return
    if not args:
        is_set = bool(os.environ.get(env_var))
        status = "[green]set[/green]" if is_set else "[red]not set[/red]"
        print_info(f"[bold]{env_var}[/bold] — {status}")
    else:
        save_api_key(env_var, args)
        print_info(f"[bold]{env_var}[/bold] saved.")
        try:
            state.agent = create_agent(state.model, system_prompt_addition=state.beast_context)
        except Exception as e:
            print_error(f"Could not initialise agent: {e}")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Maps slash-command names to their async handlers.
# Keys are lowercase; aliases (e.g. /reset) just point to the same handler.
COMMAND_REGISTRY: dict[str, Callable[[SessionState, str], Coroutine[Any, Any, None]]] = {
    "clear":   _cmd_clear,
    "reset":   _cmd_clear,   # alias
    "banner":  _cmd_banner,
    "memory":  _cmd_memory,
    "stats":   _cmd_stats,
    "compact": _cmd_compact,
    "help":    _cmd_help,
    "mcp":     _cmd_mcp,
    "skills":  _cmd_skills,
    "model":   _cmd_model,
    "key":     _cmd_key,
}
