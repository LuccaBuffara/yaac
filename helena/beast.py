"""Beast Mode - Multi-agent parallel execution for Helena Code."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from .tool_events import set_handler, reset_handler
from .ui import console

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WORKER_TIMEOUT = 300   # seconds before a stuck agent is cancelled
_MAX_LOG = 100         # max tool-call log entries kept per worker


# ---------------------------------------------------------------------------
# Status primitives
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    PENDING      = "PENDING"
    RUNNING      = "RUNNING"
    DONE         = "DONE"
    FAILED       = "FAILED"
    TIMEOUT      = "TIMEOUT"
    INTERRUPTED  = "INTERRUPTED"


_STATUS_STYLE: dict[str, str] = {
    "PENDING":     "dim",
    "RUNNING":     "bold yellow",
    "DONE":        "bold green",
    "FAILED":      "bold red",
    "TIMEOUT":     "bold magenta",
    "INTERRUPTED": "bold cyan",
}

_STATUS_ICON: dict[str, str] = {
    "PENDING":     "◦",
    "RUNNING":     "◉",
    "DONE":        "✓",
    "FAILED":      "✗",
    "TIMEOUT":     "⏱",
    "INTERRUPTED": "↺",
}


@dataclass
class WorkerState:
    id: int
    task: str
    status: TaskStatus = TaskStatus.PENDING
    current_action: str = ""
    result: str = ""
    error: str = ""
    start_time: float = field(default_factory=time.monotonic)
    end_time: float = 0.0
    log: list[str] = field(default_factory=list)  # chronological tool-call history
    asyncio_task: "asyncio.Task | None" = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Pydantic output models
# ---------------------------------------------------------------------------

class Clarification(BaseModel):
    questions: list[str]   # 0–3 questions; empty list means proceed immediately
    reasoning: str         # internal reasoning (not shown to user)


class Plan(BaseModel):
    goal: str           # clarified overall goal (one sentence)
    subtasks: list[str] # independent parallel subtasks (2–6 items)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_CLARIFICATION_SYSTEM = """\
You are the Beast Mode Orchestrator for Helena Code, a multi-agent coding assistant.

You have just received a task. Before decomposing it into parallel subtasks, decide
whether you need clarification to do the job well.

Ask UP TO 3 short, focused questions if the task is ambiguous in ways that would
significantly change the execution plan (e.g. unknown tech stack, conflicting
constraints, unclear scope).

Do NOT ask questions if:
- The task is already clear enough to proceed
- The answer can be inferred from context
- The question is about minor style preferences

Return an empty questions list to proceed without asking anything.
"""

_ORCHESTRATOR_SYSTEM = """\
You are the Beast Mode Orchestrator for Helena Code, a multi-agent coding assistant.

Your job: analyze the user's task and decompose it into a set of PARALLEL, INDEPENDENT
subtasks that can be executed concurrently by separate coding agents.

Rules:
- Each subtask must be self-contained and independently executable WITHOUT relying on
  the output of any other subtask.
- Each subtask must be a complete, unambiguous instruction a coding agent can execute
  without additional context.
- Aim for 2–5 subtasks. Never more than 6.
- Include all necessary context (file paths, goals, constraints) in each subtask.
- goal: a single sentence describing the overall objective.
"""

_SYNTHESIS_SYSTEM = """\
You are the Beast Mode Synthesis Agent for Helena Code.

Multiple parallel coding agents have completed their assigned subtasks. Your job:
1. Summarize what was accomplished across all agents.
2. Note any conflicts or gaps.
3. List any follow-up actions still required.

Be concise and actionable. Use markdown.
"""


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _render_dashboard(
    goal: str,
    workers: list[WorkerState],
    phase: str,
    elapsed: float,
    orchestrator_status: str,
    selected_id: int | None = None,
) -> Panel:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(width=2)   # icon
    grid.add_column(width=14)  # label
    grid.add_column()          # task / action
    grid.add_column(width=8)   # elapsed

    # Orchestrator row
    if phase == "planning":
        orch_icon: object = Spinner("dots").render(time.monotonic())
        orch_style = "bold yellow"
    elif phase == "done":
        orch_icon = Text("✓", style="bold green")
        orch_style = "bold green"
    else:
        orch_icon = Text("◉", style="bold cyan")
        orch_style = "bold cyan"

    grid.add_row(
        orch_icon,
        Text("Orchestrator", style=orch_style),
        Text(orchestrator_status, style="dim"),
        Text(f"{elapsed:.1f}s", style="dim cyan"),
    )

    if workers:
        grid.add_row("", "", "", "")  # spacer

    for w in workers:
        st = w.status.value
        selected = (w.id == selected_id)

        if w.status == TaskStatus.RUNNING:
            icon: object = Spinner("dots2").render(time.monotonic())
        else:
            icon = Text(_STATUS_ICON[st], style=_STATUS_STYLE[st])

        if selected:
            label = Text(f" Agent-{w.id} ", style="bold white on dark_orange")
        else:
            label = Text(f"Agent-{w.id}", style=_STATUS_STYLE[st])

        if w.status == TaskStatus.RUNNING:
            action = w.current_action or w.task[:70]
            detail = Text(action[:70], style="dim yellow")
        elif w.status == TaskStatus.DONE:
            detail = Text(w.task[:70], style="dim green")
        elif w.status == TaskStatus.FAILED:
            detail = Text((w.error or w.task)[:70], style="dim red")
        elif w.status == TaskStatus.TIMEOUT:
            detail = Text(w.error[:70], style="dim magenta")
        else:
            detail = Text(w.task[:70], style="dim")

        if w.status == TaskStatus.RUNNING:
            t = time.monotonic() - w.start_time
        elif w.end_time:
            t = w.end_time - w.start_time
        else:
            t = 0.0

        grid.add_row(icon, label, detail, Text(f"{t:.1f}s" if t else "", style="dim cyan"))

    # Key hint (shown once agents exist)
    if workers and phase not in ("planning",):
        n = len(workers)
        hint = f"  Press 1–{n} to inspect  ·  i to interrupt  ·  0 to close"
        grid.add_row("", "", Text(hint, style="dim"), "")

    title = Text.assemble(
        ("⚡ BEAST MODE", "bold red"),
        ("  ·  ", "dim"),
        (goal[:70], "bold white"),
    )
    return Panel(grid, title=title, border_style="red", padding=(0, 1))


def _render_detail(worker: WorkerState) -> Panel:
    """Expanded detail panel for a selected agent."""
    from rich.console import Group as RGroup
    from rich.markdown import Markdown

    parts: list = [
        Text.assemble(("Task: ", "bold dim"), (worker.task, "white")),
        Text(""),
    ]

    if worker.log:
        parts.append(Text("Activity log:", style="bold dim"))
        for entry in worker.log[-25:]:
            style = "dim yellow" if entry.startswith("⚙") else "dim green"
            parts.append(Text(f"  {entry}", style=style))

    terminal = (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.TIMEOUT)
    if worker.result and worker.status in terminal:
        parts.append(Text(""))
        parts.append(Rule(style="dim"))
        parts.append(Text("Result:", style="bold dim"))
        parts.append(Markdown(worker.result[:800]))

    st = worker.status.value
    close_hint = "  ·  press i to interrupt  ·  0 to close" if worker.status == TaskStatus.RUNNING else "  ·  press 0 to close"
    title = Text.assemble(
        (f" Agent-{worker.id} ", "bold white on dark_orange"),
        ("  ", ""),
        (st, _STATUS_STYLE[st]),
        (close_hint, "dim"),
    )
    return Panel(RGroup(*parts), title=title, border_style="dark_orange", padding=(0, 1))


# ---------------------------------------------------------------------------
# Keyboard input (non-blocking, asyncio)
# ---------------------------------------------------------------------------

async def _read_keys(
    selected_id: list[int | None],
    done_event: asyncio.Event,
    interrupt_queue: "asyncio.Queue[int]",
    pause_event: asyncio.Event,
    pause_ready: asyncio.Event,
    resume_event: asyncio.Event,
    n_workers: int,
) -> None:
    """Read single keystrokes to select/deselect/interrupt agents while Live is running."""
    import tty
    import termios

    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        return

    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)  # keeps OPOST so Rich cursor escapes work correctly

    loop = asyncio.get_event_loop()
    key_queue: asyncio.Queue[str] = asyncio.Queue()

    def _on_readable() -> None:
        try:
            ch = os.read(fd, 4).decode("utf-8", errors="replace")
            key_queue.put_nowait(ch)
        except Exception:
            pass

    loop.add_reader(fd, _on_readable)
    try:
        while not done_event.is_set():
            # Yield to _handle_interrupts when it needs the terminal
            if pause_event.is_set():
                loop.remove_reader(fd)
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                except Exception:
                    pass
                pause_ready.set()
                await resume_event.wait()
                resume_event.clear()
                tty.setcbreak(fd)
                loop.add_reader(fd, _on_readable)

            try:
                ch = await asyncio.wait_for(key_queue.get(), timeout=0.1)
                if ch == "0":
                    selected_id[0] = None
                elif ch.isdigit():
                    n = int(ch)
                    if 1 <= n <= n_workers:
                        selected_id[0] = n
                elif ch in ("i", "I"):
                    if selected_id[0] is not None:
                        await interrupt_queue.put(selected_id[0])
                elif ch in ("\x1b", "q"):
                    selected_id[0] = None
                elif ch == "\x03":  # Ctrl-C — let the outer handler deal with it
                    break
            except asyncio.TimeoutError:
                continue
    finally:
        loop.remove_reader(fd)
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Core async functions
# ---------------------------------------------------------------------------

async def _ask_clarifications(task: str, model_name: str) -> list[str]:
    """Return a list of clarifying questions (may be empty)."""
    agent: Agent[None, Clarification] = Agent(
        model=AnthropicModel(model_name),
        system_prompt=_CLARIFICATION_SYSTEM,
        output_type=Clarification,
    )
    result = await agent.run(task)
    return result.output.questions


async def _plan(task: str, model_name: str) -> Plan:
    """Ask the orchestrator to decompose the task into a parallel plan."""
    orchestrator: Agent[None, Plan] = Agent(
        model=AnthropicModel(model_name),
        system_prompt=_ORCHESTRATOR_SYSTEM,
        output_type=Plan,
    )
    result = await orchestrator.run(task)
    return result.output


async def _run_worker(worker: WorkerState, model_name: str) -> None:
    """Run a single worker agent to completion."""
    from .agent import create_agent  # local import to avoid circular

    worker.status = TaskStatus.RUNNING
    worker.start_time = time.monotonic()

    def _on_event(event_type: str, tool_name: str, data: dict | str) -> None:
        if event_type == "call" and isinstance(data, dict):
            arg_str = ", ".join(f"{k}={repr(v)[:40]}" for k, v in data.items())
            entry = f"⚙ {tool_name}({arg_str})"
            worker.current_action = entry
            worker.log.append(entry)
            if len(worker.log) > _MAX_LOG:
                worker.log.pop(0)
        elif event_type == "return":
            preview = str(data)[:120].replace("\n", " ")
            entry = f"← {tool_name}: {preview}"
            worker.current_action = f"← {tool_name}"
            worker.log.append(entry)
            if len(worker.log) > _MAX_LOG:
                worker.log.pop(0)

    token = set_handler(_on_event)
    try:
        agent = create_agent(model_name)
        result = await asyncio.wait_for(agent.run(worker.task), timeout=WORKER_TIMEOUT)
        worker.result = result.output
        worker.status = TaskStatus.DONE
    except asyncio.TimeoutError:
        worker.error = f"Agent timed out after {WORKER_TIMEOUT}s"
        worker.result = f"TIMEOUT: agent exceeded {WORKER_TIMEOUT}s limit"
        worker.status = TaskStatus.TIMEOUT
    except Exception as exc:
        worker.error = str(exc)
        worker.result = f"FAILED: {exc}"
        worker.status = TaskStatus.FAILED
    finally:
        reset_handler(token)
        worker.end_time = time.monotonic()
        worker.current_action = ""


async def _synthesize(goal: str, workers: list[WorkerState], model_name: str) -> str:
    """Ask the synthesis agent to produce a final summary."""
    synthesizer: Agent[None, str] = Agent(
        model=AnthropicModel(model_name),
        system_prompt=_SYNTHESIS_SYSTEM,
    )
    sections = "\n\n".join(
        f"## Agent-{w.id}: {w.task}\n\nStatus: {w.status.value}\n\n{w.result}"
        for w in workers
    )
    result = await synthesizer.run(f"Overall goal: {goal}\n\n{sections}")
    return result.output


# ---------------------------------------------------------------------------
# Clarification Q&A (interactive, before Live starts)
# ---------------------------------------------------------------------------

def _run_clarification_qa(questions: list[str]) -> str:
    """Print questions and collect answers synchronously. Returns answers block."""
    if not questions:
        return ""

    console.print()
    console.print(Panel(
        Text("The orchestrator has a few questions before starting.", style="dim"),
        title="[bold yellow]⚡ Beast Mode — Clarification[/bold yellow]",
        border_style="yellow",
        padding=(0, 1),
    ))
    console.print()

    answers: list[str] = []
    for i, q in enumerate(questions, 1):
        console.print(Text(f"  {i}. {q}", style="bold white"))
        try:
            answer = input("     > ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = "(no answer)"
        answers.append(answer)
        console.print()

    block = "\n".join(
        f"Q{i}: {q}\nA{i}: {a}"
        for i, (q, a) in enumerate(zip(questions, answers), 1)
    )
    return f"\n\nClarifications from user:\n{block}"


# ---------------------------------------------------------------------------
# Interrupt handler
# ---------------------------------------------------------------------------

async def _handle_interrupts(
    live: "Live",
    workers: list[WorkerState],
    model_name: str,
    interrupt_queue: "asyncio.Queue[int]",
    done_event: asyncio.Event,
    pause_event: asyncio.Event,
    pause_ready: asyncio.Event,
    resume_event: asyncio.Event,
) -> None:
    """Wait for interrupt requests, prompt for new instructions, and restart workers."""
    while not done_event.is_set():
        try:
            agent_id = await asyncio.wait_for(interrupt_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        worker = next((w for w in workers if w.id == agent_id), None)
        if worker is None or worker.status != TaskStatus.RUNNING:
            continue

        # Pause the key reader so it releases the terminal
        pause_event.set()
        pause_ready.clear()
        await pause_ready.wait()

        # Stop the live display and get input normally
        live.stop()
        try:
            print(f"\n  Interrupting Agent-{agent_id}...")
            print(f"  Current task: {worker.task[:80]}")
            new_instruction = input(f"  New instruction for Agent-{agent_id}: ").strip()
        except (EOFError, KeyboardInterrupt):
            new_instruction = ""
        finally:
            live.start()
            pause_event.clear()
            resume_event.set()

        if not new_instruction:
            continue

        # Cancel the running task
        old_task = worker.asyncio_task
        if old_task and not old_task.done():
            old_task.cancel()
            try:
                await old_task
            except (asyncio.CancelledError, Exception):
                pass

        # Reset worker state with new instruction
        worker.task = new_instruction
        worker.status = TaskStatus.PENDING
        worker.result = ""
        worker.error = ""
        worker.log = []
        worker.current_action = ""
        worker.end_time = 0.0
        worker.start_time = time.monotonic()

        # Relaunch
        new_task = asyncio.create_task(_run_worker(worker, model_name))
        worker.asyncio_task = new_task


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_beast_mode(task: str, model_name: str) -> str:
    """Run Helena Code in Beast Mode — orchestrate multiple parallel agents."""
    from rich.console import Group as RGroup
    from rich.markdown import Markdown

    # ── Phase 0: Clarification (interactive, before Live) ───────────────────
    console.print()
    console.print(Text("  Checking whether clarification is needed...", style="dim"))
    questions = await _ask_clarifications(task, model_name)
    clarification_ctx = _run_clarification_qa(questions)
    full_task = task + clarification_ctx

    # ── Live display setup ───────────────────────────────────────────────────
    start_time = time.monotonic()
    workers: list[WorkerState] = []
    phase = "planning"
    orchestrator_status = "Analyzing task and creating execution plan..."
    goal = task[:70]
    synthesis = ""
    selected_id: list[int | None] = [None]
    done_event = asyncio.Event()
    interrupt_queue: asyncio.Queue[int] = asyncio.Queue()
    pause_event = asyncio.Event()
    pause_ready = asyncio.Event()
    resume_event = asyncio.Event()

    async def _ticker(live: Live) -> None:
        while True:
            elapsed = time.monotonic() - start_time
            dashboard = _render_dashboard(
                goal, workers, phase, elapsed, orchestrator_status, selected_id[0]
            )
            if selected_id[0] is not None:
                w = next((w for w in workers if w.id == selected_id[0]), None)
                live.update(RGroup(dashboard, _render_detail(w)) if w else dashboard)
            else:
                live.update(dashboard)
            await asyncio.sleep(0.05)

    with Live(console=console, refresh_per_second=20, transient=False) as live:
        ticker = asyncio.create_task(_ticker(live))
        key_reader = asyncio.create_task(_read_keys(
            selected_id, done_event, interrupt_queue,
            pause_event, pause_ready, resume_event,
            n_workers=0,  # updated below after planning
        ))
        interrupt_handler = asyncio.create_task(_handle_interrupts(
            live, workers, model_name, interrupt_queue,
            done_event, pause_event, pause_ready, resume_event,
        ))

        try:
            # ── Phase 1: Plan ────────────────────────────────────────────────
            plan = await _plan(full_task, model_name)
            goal = plan.goal[:70]
            orchestrator_status = f"Plan ready · spawning {len(plan.subtasks)} agents"
            phase = "executing"

            workers.extend(
                WorkerState(id=i + 1, task=subtask)
                for i, subtask in enumerate(plan.subtasks)
            )

            # Patch key_reader's n_workers via closure isn't possible; cancel and relaunch
            key_reader.cancel()
            try:
                await key_reader
            except (asyncio.CancelledError, Exception):
                pass
            key_reader = asyncio.create_task(_read_keys(
                selected_id, done_event, interrupt_queue,
                pause_event, pause_ready, resume_event,
                n_workers=len(workers),
            ))

            # ── Phase 2: Execute all agents in parallel ──────────────────────
            for w in workers:
                t = asyncio.create_task(_run_worker(w, model_name))
                w.asyncio_task = t

            # Wait for all workers to finish (may be restarted by interrupt handler)
            terminal = {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.TIMEOUT}
            while any(w.status not in terminal for w in workers):
                await asyncio.sleep(0.1)

            # ── Phase 3: Synthesize ──────────────────────────────────────────
            phase = "synthesizing"
            orchestrator_status = "Synthesizing agent results..."
            selected_id[0] = None  # close any open panel during synthesis

            synthesis = await _synthesize(goal, workers, model_name)

            phase = "done"
            orchestrator_status = "Complete"

        except Exception as exc:
            phase = "done"
            orchestrator_status = f"Error: {exc}"
        finally:
            done_event.set()
            ticker.cancel()
            key_reader.cancel()
            interrupt_handler.cancel()
            elapsed = time.monotonic() - start_time
            live.update(
                _render_dashboard(goal, workers, phase, elapsed, orchestrator_status)
            )

    total = time.monotonic() - start_time

    if synthesis:
        console.print()
        console.print(Panel(
            Markdown(synthesis),
            title="[bold green]Beast Mode Complete[/bold green]",
            border_style="green",
        ))

    done   = sum(1 for w in workers if w.status == TaskStatus.DONE)
    failed = sum(1 for w in workers if w.status == TaskStatus.FAILED)
    console.print(Text(
        f"  {done} succeeded · {failed} failed · {total:.1f}s total",
        style="dim",
    ))

    # Build a context block that the follow-up session will inject into the
    # agent's system prompt so it knows what was accomplished.
    agent_results = "\n\n".join(
        f"Agent-{w.id} ({w.status.value}): {w.task}\n{w.result[:400]}"
        for w in workers
    )
    context = (
        f"## Beast Mode just completed\n\n"
        f"**Goal:** {goal}\n\n"
        f"**Agent results:**\n{agent_results}\n\n"
        f"**Summary:**\n{synthesis}"
    )
    return context
