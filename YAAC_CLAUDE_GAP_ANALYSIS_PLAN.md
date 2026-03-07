# YAAC vs Claude Code: Gap Analysis and Efficiency Plan

## Scope
This document compares the current YAAC implementation in this repository against observable Claude Code capabilities available on this machine. It focuses on practical optimizations, workflow efficiency, and tooling completeness.

## Evidence used
- `README.md`
- `yaac/agent.py`
- `yaac/main.py`
- `pyproject.toml`
- `~/.claude/settings.json`
- `~/.claude/projects/...` session artifacts
- `~/.claude/plans/...` planning artifact
- `claude --help`

## Executive summary
YAAC already has several strong foundations Claude Code also values:
- model-agnostic provider support
- file/search/shell/LSP tooling
- planning and subagents
- skills and todos
- persistent history

However, Claude Code appears to be ahead in operational ergonomics, statefulness, ecosystem extensibility, and recovery workflows. The biggest gaps are not basic coding tools, but the surrounding execution system:
- richer session persistence and resume flows
- stronger permission and trust controls
- plugin / MCP ecosystem support
- better artifact persistence for plans, tool outputs, and file history
- more robust non-interactive and structured-output modes
- tighter IDE / worktree / environment integration

If YAAC closes those gaps, it can become both more efficient in practice and more complete as a coding-agent platform.

---

## What Claude Code appears to do that YAAC does not

### 1. Session resume and session identity management
Observed from `claude --help`:
- `--resume`
- `--continue`
- `--session-id`
- `--resume --fork`
- `--from-pr`

Observed from `~/.claude/projects/...`:
- per-project session logs stored as jsonl
- session-specific directories and sidechain/subagent traces

YAAC today:
- persists conversation history in `.yaac/history.json`
- has per-session todo files
- does not expose a first-class CLI for resuming, branching, or forking a past session
- does not appear to persist multiple named sessions per project

Why this matters:
- resumability reduces repeated context rebuilding
- forkable sessions let users explore alternatives cheaply
- project/session indexing makes long-running work much more efficient

### 2. File history / backup snapshots
Observed from `~/.claude/file-history/...` and `.claude/backups/...`:
- versioned file snapshots per session
- backup files for settings/config

YAAC today:
- relies on direct file edits and git if available
- does not appear to maintain automatic file-version history or rollback snapshots

Why this matters:
- safer edits enable more aggressive automation
- rollback increases trust and reduces user hesitation
- diff-aware history improves debugging of agent mistakes

### 3. Persistent project memory
Observed from `~/.claude/projects/.../memory/MEMORY.md`
- project memory exists as a durable artifact
- likely reused across sessions

YAAC today:
- has skills and message history
- does not expose a dedicated first-class project memory artifact like `MEMORY.md`

Why this matters:
- durable project-specific conventions reduce repeated prompting
- memory can store UI conventions, architecture constraints, deployment rules, and reviewer preferences

### 4. Plan artifact storage outside transient context
Observed from `~/.claude/plans/*.md`
- plans are stored as standalone markdown artifacts

YAAC today:
- has `plan_mode` and todos
- does not appear to persist generated plans as first-class reusable artifacts automatically

Why this matters:
- plans should survive context compression and session boundaries
- written plans become execution contracts and review artifacts

### 5. Tool-result artifact persistence
Observed from `.../tool-results/...`
- tool outputs are persisted separately from main transcript

YAAC today:
- trims tool results in history to control context size
- does not seem to maintain a dedicated artifact store for large tool outputs

Why this matters:
- keeping large outputs off the main transcript improves token efficiency
- persisted outputs preserve auditability without bloating context

### 6. Permission modes and trust ergonomics
Observed from `claude --help` and settings:
- `--permission-mode` with choices like `acceptEdits`, `bypassPermissions`, `dontAsk`, `plan`, `auto`
- `skipDangerousModePermissionPrompt`
- allowlist-like permissions in settings

YAAC today:
- has command-permissions work in progress in git branches and safety instructions in prompt
- does not expose similarly rich top-level permission policy modes in the visible CLI/docs

Why this matters:
- permission policy strongly affects speed, safety, and user trust
- workflow-specific modes reduce friction without removing safeguards

### 7. MCP / external tool ecosystem
Observed from `claude --help`:
- `--mcp-config`
- `mcp` command
- `--strict-mcp-config`

Observed from `.claude/plugins/...`
- marketplace/plugin infrastructure

YAAC today:
- has internal tools, skills, and subagents
- does not expose MCP server integration or a plugin marketplace/registry model

Why this matters:
- MCP dramatically expands available tools without bloating core code
- plugins reduce pressure to ship every feature in-tree
- ecosystem leverage is one of the biggest completeness multipliers

### 8. Non-interactive / machine-readable execution modes
Observed from `claude --help`:
- `--print`
- `--output-format text|json|stream-json`
- `--input-format text|stream-json`
- `--json-schema`
- `--include-partial-messages`
- `--replay-user-messages`
- `--no-session-persistence`
- `--max-budget-usd`

YAAC today:
- is primarily interactive terminal-first
- streams output live for humans
- does not appear to offer a documented automation-grade JSON/stream-JSON interface or structured schema validation
- does not expose a user budget cap in the CLI

Why this matters:
- automation compatibility broadens use cases dramatically
- structured outputs enable CI, scripting, and agent chaining
- budget caps improve predictability

### 9. IDE integration
Observed from `claude --help` and `~/.claude/ide/*.lock`:
- `--ide` support
- IDE connection state

YAAC today:
- works in terminal and has LSP support
- does not appear to expose direct IDE attachment or editor-aware control flow

Why this matters:
- editor attachment can improve cursor/file awareness and review loops
- makes agent behavior feel integrated rather than external

### 10. Git worktree and PR-oriented workflows
Observed from `claude --help`:
- `--worktree`
- `--tmux`
- `--from-pr`

YAAC today:
- can run shell commands, so it can use git indirectly
- does not expose worktree-native orchestration as a product feature

Why this matters:
- isolated worktrees are a major safety and productivity gain for parallel changes
- PR/session linking is valuable for real-world development workflows

### 11. Plugins / extensibility lifecycle
Observed from `claude --help`:
- `plugin` command
- plugin dir support
- marketplace data under `.claude/plugins/marketplaces`

YAAC today:
- supports persistent skills and agent profiles
- lacks a plugin system for executable integrations, packaged tool bundles, update channels, and community distribution

Why this matters:
- skills are instruction-layer extensibility
- plugins are capability-layer extensibility
- both are useful; Claude appears to have both layers

### 12. More granular telemetry / operational artifacts
Observed from `.claude/telemetry`, `stats-cache.json`, `policy-limits.json`, `session-env`, `shell-snapshots`, `tasks`
- Claude stores more operational state and execution metadata

YAAC today:
- tracks session history and token/cost stats in-session
- appears lighter on persisted operational metadata

Why this matters:
- metadata enables better debugging, optimization, resumability, and analytics
- shell snapshots and env/session artifacts improve reproducibility

---

## Where YAAC is already competitive or stronger

These are worth preserving while improving the gaps:
- model-agnostic provider architecture
- explicit LSP integration in the core product
- built-in planning mode
- built-in todo workflow
- built-in skill creation and agent profile creation
- simpler architecture and likely easier hackability
- open implementation with low ceremony

The goal should not be to clone Claude Code exactly. It should be to add the missing high-leverage operating-system features while preserving YAAC's openness and portability.

---

## Root causes of the efficiency gap

### A. YAAC focuses on core agent execution more than execution environment
YAAC has solid tools, but fewer lifecycle features around sessions, artifacts, permissions, and recovery.

### B. Context management is present, but artifact management is lighter
History trimming/compaction helps token efficiency, but without persistent plan/tool/file artifacts, some useful state is lost or hard to reuse.

### C. Extensibility is instruction-centric, not systems-centric
Skills are powerful, but they do not replace plugin/MCP-based capability expansion.

### D. Human workflow acceleration features are thinner
Resume/fork/worktree/IDE/structured-output capabilities reduce real-world friction more than raw model quality alone.

---

## Recommended plan to make YAAC more efficient and more complete

## Phase 1 — Highest ROI foundations

### 1. Add first-class session registry and resume/fork support
Deliverables:
- `.yaac/projects/<project-id>/sessions/<session-id>.jsonl`
- CLI flags: `--resume`, `--continue`, `--session-id`, `--fork-session`
- session metadata: cwd, git branch, timestamp, model, status
- interactive session picker for the current project

Benefits:
- immediate productivity gain
- less repeated prompting
- foundation for all later workflow features

Implementation notes:
- keep existing `.yaac/history.json` compatibility initially
- migrate to append-only jsonl transcripts plus compact derived history
- persist subagent lineage in session metadata

### 2. Add persistent project memory
Deliverables:
- `.yaac/memory/MEMORY.md` per project
- `/memory` slash command for view/edit/summarize
- agent prompt includes a compact memory summary rather than full file by default
- optional `memory_write` / `memory_read` tools

Benefits:
- fewer repeated instructions
- stronger long-term adaptation to a codebase

Implementation notes:
- keep memory curated and small
- separate stable conventions from transient session history

### 3. Persist plans as markdown artifacts
Deliverables:
- `.yaac/plans/<timestamp>-<slug>.md`
- optional auto-save from `plan_mode`
- links between plans and todos/session ids

Benefits:
- plans survive compaction
- easier review and execution tracking

Implementation notes:
- allow `plan_mode(save=true)` or auto-save plans over a complexity threshold

### 4. Add tool result artifact storage
Deliverables:
- `.yaac/tool-results/<session-id>/<tool-call-id>.*`
- transcript stores references/summaries instead of huge raw payloads
- helper for reopening referenced artifacts

Benefits:
- much better token efficiency
- preserves large outputs safely

Implementation notes:
- especially useful for grep results, test failures, logs, and generated reports

---

## Phase 2 — Safety and speed ergonomics

### 5. Introduce explicit permission modes
Deliverables:
- CLI flag and config for permission modes:
  - `default`
  - `read-only`
  - `accept-edits`
  - `auto`
  - `plan-only`
  - `bypass-permissions` (with loud safeguards)
- allow/deny lists for tools and shell command classes
- trust model for current workspace

Benefits:
- safer automation
- lower interaction overhead for trusted repos

Implementation notes:
- model this in config, prompt, and tool wrappers consistently
- classify shell commands by risk level

### 6. Add automatic file snapshots and rollback
Deliverables:
- `.yaac/file-history/<session-id>/...`
- pre-edit snapshots for changed files
- `/undo-last-edit` and `/diff-last-edit`

Benefits:
- higher user trust
- easier recovery from agent mistakes

Implementation notes:
- do not snapshot huge binaries by default
- store text diffs when possible, full copy when necessary

### 7. Improve budget and token controls
Deliverables:
- `--max-budget-usd`
- optional token budget per turn/session
- context allocation reporting by category: prompt/history/tools/memory
- warnings before expensive operations

Benefits:
- predictable spend
- better efficiency tuning

Implementation notes:
- expose live stats and hard-stop behaviors cleanly

---

## Phase 3 — Extensibility and ecosystem completeness

### 8. Add MCP client support
Deliverables:
- `--mcp-config`
- MCP server registry loading from json
- tool namespace bridging into agent tools
- per-server permission controls

Benefits:
- massive tooling expansion without core bloat
- parity with an important Claude capability area

Implementation notes:
- start with stdio MCP servers
- keep built-in tools first-class and reliable

### 9. Add a plugin system beyond skills
Deliverables:
- `.yaac/plugins/`
- plugin manifest format
- hooks for CLI commands, tools, slash commands, event listeners
- local plugin dir loading first; marketplace later

Benefits:
- executable extensibility rather than prompt-only extensibility
- community growth surface

Implementation notes:
- define a constrained, safe plugin API
- avoid arbitrary import execution without trust prompts

### 10. Add project-local agents/tool bundles
Deliverables:
- project-level packaged bundles combining:
  - skills
  - agent profiles
  - plugins
  - MCP configs
  - memory seed

Benefits:
- reproducible team workflows
- smoother onboarding

---

## Phase 4 — Automation and workflow polish

### 11. Add structured non-interactive mode
Deliverables:
- `yaac --print`
- `--output-format text|json|stream-json`
- `--input-format text|stream-json`
- `--json-schema`
- `--no-session-persistence`

Benefits:
- CI/CD compatibility
- easier composition with other tools
- unlocks YAAC as infrastructure, not just a REPL

Implementation notes:
- emit tool calls, partial deltas, usage stats, and final result as structured events

### 12. Add IDE integration hooks
Deliverables:
- optional editor attachment mode
- current file/selection awareness where supported
- open-diff / jump-to-location integration

Benefits:
- smoother developer experience
- faster review loops

Implementation notes:
- begin with VS Code-compatible URI/open hooks before deep integration

### 13. Add worktree-native workflows
Deliverables:
- `--worktree [name]`
- per-session isolated git worktree creation
- optional tmux support for long-running sessions

Benefits:
- safer parallel experimentation
- better support for multi-branch agent work

Implementation notes:
- make worktree lifecycle explicit and reversible

### 14. Add PR / issue linked sessions
Deliverables:
- session metadata linking to issue/PR URLs or IDs
- resume by PR/issue shortcut
- session summaries suitable for PR comments

Benefits:
- better real-world collaboration
- easier recovery of prior reasoning

---

## Cross-cutting technical improvements

### A. Move from transcript-first to artifact-first context design
Current YAAC appears history-centric. Improve efficiency by storing bulky outputs outside prompt history and reinjecting only summaries + references.

### B. Add an event bus for all tool/runtime actions
Use a unified event stream for:
- tool start/end
- file edits
- permission prompts
- usage updates
- snapshots
- plan saves
- subagent lifecycle

This becomes the basis for structured output mode, plugins, telemetry, and IDE integration.

### C. Create a small internal metadata schema
Standardize:
- session metadata
- plan metadata
- tool result metadata
- file snapshot metadata
- memory metadata

This avoids one-off state formats and makes future migration easier.

### D. Strengthen observability
Persist:
- session stats
- average tool latency
- compaction events
- token usage by source
- common failure classes

This makes optimization evidence-based.

---

## Suggested implementation order

1. Session registry + resume/fork
2. Plan persistence
3. Project memory
4. Tool-result artifact store
5. Permission modes
6. File snapshots + rollback
7. Budget controls
8. Structured output / print mode
9. MCP support
10. Plugin system
11. Worktree workflows
12. IDE integration
13. PR/issue-linked sessions

This order gives YAAC practical efficiency improvements early, then expands completeness.

---

## Minimal milestone definition for “YAAC 2.0”
A strong next milestone would include:
- resumable sessions
- persisted plans
- project memory
- file snapshots
- permission modes
- structured JSON output mode
- tool-result artifact storage

That bundle would materially narrow the most visible gap with Claude Code while keeping scope realistic.

---

## Risks and guardrails

### Risks
- feature creep from trying to match every Claude capability
- context pollution from over-persisting artifacts
- security issues from plugins/MCP without trust boundaries
- maintenance burden from too many state formats

### Guardrails
- keep defaults simple
- make advanced features opt-in
- design around clear metadata schemas
- treat plugins/MCP as sandboxed/trusted features, not implicit defaults
- preserve YAAC’s model-agnostic identity

---

## Final recommendation
Do not prioritize adding more ad hoc built-in tools first. YAAC’s bigger gap is the operating layer around the agent: resumability, recoverability, artifact persistence, permissioning, extensibility, and automation interfaces. Closing those gaps will make YAAC feel dramatically more efficient even if the underlying model and basic tool list stay mostly the same.
