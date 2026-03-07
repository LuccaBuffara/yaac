# YAAC (Yet Another Agentic Coder)

An AI-powered coding assistant CLI, built with [Pydantic AI](https://ai.pydantic.dev/) and Claude.

Inspired by Claude Code — runs in your terminal, reads and edits your files, executes commands.

## Setup

```bash
# Install
pip install -e .

# Set your Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run
yaac
```

## Usage

Just type your request at the `>` prompt:

```
> read the main.py file and explain what it does
> add error handling to the parse_input function
> run the tests and fix any failures
> create a new utils.py file with helper functions for...
```

### Commands

| Command | Description |
|---------|-------------|
| `exit` / `quit` | Quit YAAC |
| `/clear` | Clear conversation history |
| `/help` | Show help |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | **Required.** Your Anthropic API key |
| `YAAC_MODEL` | Claude model to use (default: `claude-sonnet-4-6`) |
| `YAAC_DEBUG` | Set to `1` for full error tracebacks |

## Tools Available to YAAC

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with line numbers |
| `write_file` | Create or overwrite a file |
| `edit_file` | Replace an exact string in a file |
| `list_directory` | List directory contents |
| `run_bash` | Execute shell commands |
| `glob_search` | Find files by glob pattern |
| `grep_search` | Search file contents by regex |

## Development

```bash
# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Run directly without installing
python -m yaac.main
```
