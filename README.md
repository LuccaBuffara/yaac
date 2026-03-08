# YAAC (Yet Another Agentic Coder)

An AI-powered coding assistant CLI, built with [Pydantic AI](https://ai.pydantic.dev/).

Runs in your terminal, reads and edits your files, executes commands — like Claude Code, but model-agnostic and fully open.

---

## Features

- 🤖 **Multi-provider** — Anthropic, OpenAI, Google Gemini, Groq, Mistral, Ollama
- 🛠 **Full tool suite** — read/write/edit files, run shell commands, search code, LSP diagnostics
- 🧠 **Subagents & planning** — spawn independent subagents, delegate planning to a read-only planner
- 📚 **Skills system** — persistent, reusable instructions discoverable by the agent
- ✅ **Session todos** — per-session task tracking so the agent never loses context mid-task
- 💬 **Persistent history** — conversations saved to `.yaac/history.json`, compacted automatically
- 🔍 **LSP integration** — real type errors and code intelligence (hover, go-to-definition, references)
- 🧠 **Project memory** — durable `.yaac/memory/MEMORY.md` memory that is auto-injected into the agent prompt
- 📋 **Hierarchical AGENTS.md** — Claude-style `AGENTS.md` files loaded from parent directories down to the current workspace
- 🔌 **MCP ecosystem** — Claude-style MCP server configs bridged into YAAC toolsets with `--mcp-config`
- ⚡ **Streaming output** — text streams in real-time; tool calls shown inline
- 🛑 **Interrupt & refine** — press `i` during a run to interrupt and add more details

---

## Installation

### Install from PyPI

```bash
pip install yaacai
```

### Update

```bash
pip install --upgrade yaacai
```

### Local / development install

```bash
pip install -e .

# With optional provider support
pip install -e ".[openai]"     # OpenAI
pip install -e ".[google]"     # Google Gemini
pip install -e ".[groq]"       # Groq
pip install -e ".[mistral]"    # Mistral
pip install -e ".[all]"        # All providers

# With dev dependencies
pip install -e ".[dev]"
```

### Configure and run

```bash
# Set your API key (Anthropic is the default provider)
export ANTHROPIC_API_KEY=sk-ant-...

# Launch
yaac

# Use a specific model
yaac --model openai:gpt-4o
yaac --model google:gemini-2.0-flash
yaac --model groq:llama-4-scout
yaac --model ollama:llama3
```

---

## Usage

Just type your request at the `>` prompt:

```
> read main.py and explain what it does
> add error handling to the parse_input function
> run the tests and fix any failures
> refactor the auth module to use async/await
```

### Built-in commands

| Command | Description |
|---------|-------------|
| `exit` / `quit` / `bye` | Quit YAAC |
| `/clear` | Clear conversation history |
| `/help` | Show help |
| `/skills` | List loaded skills |
| `/model` | Open interactive model picker |
| `/memory` | Show discovered `AGENTS.md` files and project memory |
| `/model <provider:model>` | Switch model (e.g. `openai:gpt-4o`) |
| `/mcp` | Show the active MCP config, loaded servers, and warnings |
| `/key` | Show API key status for current provider |
| `/key <value>` | Set & save the API key for the current provider |

### Interrupt & refine

Press **`i`** while YAAC is running to interrupt the current turn. You'll be prompted to add extra details; pressing Enter continues with the original instruction.

### Environment variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Google Gemini API key |
| `GROQ_API_KEY` | Groq API key |
| `MISTRAL_API_KEY` | Mistral API key |
| `YAAC_MODEL` | Default model (overrides `~/.yaac/config.json`) |
| `YAAC_DEBUG` | Set to `1` for full error tracebacks |
| `YAAC_MCP_CONFIG` | Default MCP config file path |

API keys and the default model are also persisted in `~/.yaac/config.json` when set via `/key` or `/model`.

---

## Supported models

Use the format `provider:model-id` anywhere a model is expected.

| Provider | Example model IDs |
|----------|-------------------|
| `anthropic` | `claude-sonnet-4-6`, `claude-opus-4`, `claude-haiku-4` |
| `openai` | `gpt-4o`, `gpt-4.1`, `o3`, `o4-mini` |
| `google` | `gemini-2.0-flash`, `gemini-1.5-pro` |
| `groq` | `llama-4-scout`, `llama-3.3-70b`, `kimi-k2` |
| `mistral` | `mistral-large`, `mistral-small` |
| `ollama` | any locally running model, e.g. `llama3`, `mistral` |

---

## Tools available to the agent

### File tools
| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with line numbers (supports offset/limit) |
| `write_file` | Create a new file |
| `update_file` | Apply a unified diff with valid `@@ ... @@` hunks to an existing file |
| `list_directory` | List directory contents with sizes |

### Shell & search
| Tool | Description |
|------|-------------|
| `run_bash` | Execute shell commands (tests, git, build, etc.) |
| `glob_search` | Find files by glob pattern |
| `grep_search` | Search file contents by regex |

### LSP & code intelligence
| Tool | Description |
|------|-------------|
| `lsp_diagnostics` | Get real type errors and warnings from a language server |
| `lsp_query` | Hover info, go-to-definition, references, document symbols |

### Agent & planning
| Tool | Description |
|------|-------------|
| `plan_mode` | Delegate planning to a dedicated read-only planning subagent |
| `spawn_subagent` | Spawn an independent subagent with a fresh context |
| `create_skill` | Persist a new reusable skill to `~/.yaac/skills/` |
| `memory_read` | Read the durable project memory file |
| `memory_write` | Create or update the durable project memory file |
| `create_agent_profile` | Persist a new agent profile to `~/.yaac/agents/` |

### Session management
| Tool | Description |
|------|-------------|
| `todo_read` | Read all todos for the current session |
| `todo_write` | Create or update session-scoped todos |

### MCP ecosystem

YAAC can load Claude-style MCP server configs and expose their tools alongside the built-in tool suite.

```bash
# Use an explicit config
yaac --mcp-config .mcp.json

# Or set a default path
export YAAC_MCP_CONFIG=/path/to/mcp.json
yaac
```

If no explicit path is supplied, YAAC checks these locations in order:

1. `YAAC_MCP_CONFIG`
2. `./.mcp.json`
3. `./.yaac/mcp.json`

Config format matches Claude/PydanticAI MCP JSON:

```json
{
  "mcpServers": {
    "docs": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."] }
  }
}
```

There is also a local test example in [`examples/mcp/`](examples/mcp/):

```bash
./venv/bin/pip install mcp
yaac --mcp-config examples/mcp/mcp.sample.json
```

The sample config points at a tiny local stdio MCP server with three test tools:

- `echo(text)`
- `reverse(text)`
- `add(a, b)`

Inside YAAC, run `/mcp` to confirm the server loaded, then try prompts like:

```text
Use the echo MCP tool to repeat: hello from MCP
Use the reverse MCP tool on: abcdef
Use the add MCP tool with 7 and 35
```

See [`examples/mcp/README.md`](examples/mcp/README.md) for full setup notes.

---

## Skills

Skills are persistent, reusable instruction sets discovered automatically. Place a `SKILL.md` file with YAML frontmatter in any of these locations:

```
<project>/.yaac/skills/<skill-name>/SKILL.md   ← project-level (highest priority)
~/.yaac/skills/<skill-name>/SKILL.md           ← user-level (global)
```

**`SKILL.md` format:**

```markdown
---
name: my-skill
description: One-line description shown in the catalog.
---

Full instructions in Markdown...
```

The agent sees only the name and description at startup. Full instructions are loaded on-demand via the `activate_skill` tool when a task matches. Use `/skills` to list all loaded skills, or `create_skill` to let the agent create one automatically.

---

## AGENTS.md and MEMORY.md support

YAAC now supports Claude-style workspace instruction files:

- `AGENTS.md` files are discovered from the filesystem root down to the current working directory.
- More local `AGENTS.md` files are treated as more specific when instructions conflict.
- Project memory is loaded from either:
  - `<project>/MEMORY.md`
  - `<project>/.yaac/memory/MEMORY.md`

Both are injected into the agent system prompt automatically at session startup.

Use:

```bash
/memory
/memory init
```

to inspect the discovered files or create a starter project memory file.

---

## Conversation history & context management

- History is persisted to `.yaac/history.json` in the working directory.
- Tool results are truncated automatically to avoid bloating the context.
- When input token usage exceeds **65 %** of the model's context window, history is compacted automatically.
- Use `/clear` to reset the conversation entirely.

---

## Development

```bash
pip install -e ".[dev]"

# Run without installing
python -m yaac.main
```

---

## Architecture

```
yaac/
├── main.py          # CLI entry point, REPL loop, streaming output
├── agent.py         # Pydantic AI agent creation & system prompt
├── config.py        # Model resolution, pricing, API key management
├── skills.py        # Skill discovery, catalog & activation
├── history.py       # Conversation persistence & compaction
├── completer.py     # Tab-completion, model picker, toolbar
├── ui.py            # Rich console helpers
├── beast.py         # Beast mode (extended context features)
├── tools/
│   ├── file_tools.py    # read_file, write_file, update_file, list_directory
│   ├── shell_tools.py   # run_bash
│   ├── search_tools.py  # glob_search, grep_search
│   ├── lsp_tools.py     # lsp_diagnostics, lsp_query
│   ├── meta_tools.py    # plan_mode, create_skill, create_agent_profile
│   ├── subagent_tools.py # spawn_subagent
│   └── todo_tools.py    # todo_read, todo_write
└── lsp/             # LSP server management
```

## License

MIT
