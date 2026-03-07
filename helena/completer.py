"""Command completion, toolbar hints, and interactive menus for Helena Code."""

from typing import Any

from prompt_toolkit.completion import NestedCompleter
from prompt_toolkit.formatted_text import HTML

# ---------------------------------------------------------------------------
# Model catalog
# ---------------------------------------------------------------------------

PROVIDER_MODELS: dict[str, list[str]] = {
    "anthropic": [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ],
    "openai": [
        "gpt-5.4",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-4o",
        "gpt-4o-mini",
        "o4-mini",
        "o3-mini",
        "o3",
        "o1",
    ],
    "google": [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    ],
    "groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "moonshotai/kimi-k2-instruct-0905",
        "qwen/qwen3-32b",
    ],
    "mistral": [
        "mistral-large-latest",
        "mistral-small-latest",
        "codestral-latest",
    ],
    "ollama": [
        "llama3.2",
        "llama3.1",
        "qwen2.5-coder",
        "mistral",
        "deepseek-r1",
    ],
}

_MODEL_DESCRIPTIONS: dict[str, str] = {
    "claude-opus-4-6":          "Most capable",
    "claude-sonnet-4-6":        "Balanced (default)",
    "claude-haiku-4-5":         "Fast & lightweight",
    "gpt-5.4":                  "Frontier reasoning, 1M ctx",
    "gpt-4.1":                  "Flagship GPT-4.1",
    "gpt-4.1-mini":             "Balanced GPT-4.1",
    "gpt-4.1-nano":             "Fastest, cheapest GPT-4.1",
    "gpt-4o":                   "Flagship multimodal",
    "gpt-4o-mini":              "Fast & cheap",
    "o4-mini":                  "Latest small reasoning",
    "o3-mini":                  "Reasoning model",
    "o3":                       "Powerful reasoning",
    "o1":                       "Advanced reasoning",
    "gemini-2.0-flash":         "Fast, 1M ctx",
    "gemini-2.0-flash-lite":    "Lightest Gemini",
    "gemini-1.5-pro":           "2M context window",
    "gemini-1.5-flash":         "Speed-optimised",
    "llama-3.3-70b-versatile":  "Best Llama on Groq",
    "llama-3.1-8b-instant":     "Ultra-fast",
    "llama-4-scout-17b-16e-instruct":    "Llama 4 Scout (fast, 131k ctx)",
    "llama-4-maverick-17b-128e-instruct": "Llama 4 Maverick (balanced)",
    "gpt-oss-120b":             "GPT OSS 120B (largest)",
    "gpt-oss-20b":              "GPT OSS 20B (fast)",
    "kimi-k2-instruct-0905":    "Kimi K2 (262k ctx)",
    "qwen3-32b":                "Qwen3 32B",
    "mistral-large-latest":     "Flagship Mistral",
    "mistral-small-latest":     "Efficient",
    "codestral-latest":         "Code-specialised",
    "llama3.2":                 "Local default",
    "llama3.1":                 "Local (larger)",
    "qwen2.5-coder":            "Local code model",
    "mistral":                  "Local Mistral",
    "deepseek-r1":              "Local reasoning",
}

# Maps provider → the env var that holds its API key (None = no key needed).
PROVIDER_ENV_VARS: dict[str, str | None] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "google":    "GOOGLE_API_KEY",
    "groq":      "GROQ_API_KEY",
    "mistral":   "MISTRAL_API_KEY",
    "ollama":    None,
}

_PROVIDER_HINTS: dict[str, str] = {
    "anthropic": "Claude models        ANTHROPIC_API_KEY",
    "openai":    "GPT / o-series       OPENAI_API_KEY",
    "google":    "Gemini models        GOOGLE_API_KEY",
    "groq":      "Fast inference       GROQ_API_KEY",
    "mistral":   "Mistral models       MISTRAL_API_KEY",
    "ollama":    "Local models         no API key needed",
}


# ---------------------------------------------------------------------------
# Completer
# ---------------------------------------------------------------------------

def build_completer() -> NestedCompleter:
    """Return a NestedCompleter covering all Helena slash commands and known model IDs."""
    model_completions: dict[str, None] = {
        f"{provider}:{model}": None
        for provider, models in PROVIDER_MODELS.items()
        for model in models
    }
    return NestedCompleter.from_nested_dict({
        "/help":   None,
        "/clear":  None,
        "/reset":  None,
        "/skills": None,
        "/key":    None,
        "/model":  model_completions,
        "exit":    None,
        "quit":    None,
        "bye":     None,
    })


# ---------------------------------------------------------------------------
# Bottom toolbar
# ---------------------------------------------------------------------------

_toolbar_stats: str = ""


def set_toolbar_stats(stats: str) -> None:
    """Update the stats displayed in the bottom-right corner of the toolbar."""
    global _toolbar_stats
    _toolbar_stats = stats


def get_toolbar() -> HTML:
    """Context-sensitive bottom toolbar; called on every keystroke by prompt_toolkit."""
    import re
    import shutil
    from prompt_toolkit.application import get_app
    try:
        text = get_app().current_buffer.text
    except Exception:
        return HTML("")

    if text.startswith("/model"):
        left = (
            "  <b>/model</b> <i>provider:model-id</i>  ·  "
            "leave blank to open the interactive picker  ·  "
            "Tab to autocomplete"
        )
    elif text.startswith("/key"):
        left = (
            "  <b>/key</b> <i>api-key</i>  ·  "
            "set &amp; save the API key for the current provider"
        )
    elif text.startswith("/clear") or text.startswith("/reset"):
        left = "  <b>/clear</b>  ·  wipe conversation history"
    elif text.startswith("/skills"):
        left = "  <b>/skills</b>  ·  list loaded skill files"
    elif text.startswith("/help"):
        left = "  <b>/help</b>  ·  show all commands"
    elif text.startswith("/"):
        left = (
            "  Commands: "
            "<b>/model</b>  <b>/key</b>  <b>/clear</b>  "
            "<b>/skills</b>  <b>/help</b>  ·  "
            "type <b>exit</b> to quit"
        )
    else:
        left = "  <b>Helena Code</b>  ·  type a request or <b>/help</b> for commands"

    if not _toolbar_stats:
        return HTML(left)

    # Escape XML-special characters in the stats string so prompt_toolkit's HTML parser doesn't choke on e.g. "<$0.001"
    right = f"  {_toolbar_stats}  ".replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    width = shutil.get_terminal_size().columns
    left_display_len = len(re.sub(r"<[^>]+>", "", left).replace("&amp;", "&"))
    right_display_len = len(right.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))
    padding = max(1, width - left_display_len - right_display_len)
    return HTML(left + " " * padding + right)


# ---------------------------------------------------------------------------
# Core keyboard-driven selection primitive
# ---------------------------------------------------------------------------

async def _select(
    title: str,
    subtitle: str,
    items: list[tuple[Any, str]],
) -> Any | None:
    """Inline keyboard-driven selection menu. No mouse required.

    Keys:
      ↑ / k             move up
      ↓ / j             move down
      Enter / Space     confirm selection
      Esc / q / Ctrl-C  cancel

    Returns the value field of the selected item, or None if cancelled.
    """
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    if not items:
        return None

    cursor = [0]
    result: list[Any] = [None]
    confirmed = [False]

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event: Any) -> None:
        cursor[0] = (cursor[0] - 1) % len(items)

    @kb.add("down")
    @kb.add("j")
    def _down(event: Any) -> None:
        cursor[0] = (cursor[0] + 1) % len(items)

    @kb.add("enter")
    @kb.add(" ")
    def _confirm(event: Any) -> None:
        result[0] = items[cursor[0]][0]
        confirmed[0] = True
        event.app.exit()

    @kb.add("escape")
    @kb.add("q")
    @kb.add("c-c")
    def _cancel(event: Any) -> None:
        event.app.exit()

    def _render() -> FormattedText:
        lines: list[tuple[str, str]] = []
        lines.append(("fg:ansicyan bold", f"\n  {title}\n"))
        if subtitle:
            lines.append(("fg:ansibrightblack", f"  {subtitle}\n"))
        lines.append(("", "\n"))
        for i, (_, label) in enumerate(items):
            if i == cursor[0]:
                lines.append(("fg:ansicyan bold", f"  ❯ {label}\n"))
            else:
                lines.append(("fg:ansibrightblack", f"    {label}\n"))
        lines.append(("", "\n"))
        lines.append((
            "fg:ansibrightblack",
            "  ↑ ↓  /  j k  move    Enter  /  Space  confirm    Esc  /  q  cancel\n",
        ))
        return FormattedText(lines)

    layout = Layout(
        Window(
            FormattedTextControl(_render, focusable=True, show_cursor=False),
        )
    )

    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
        mouse_support=False,
    )

    await app.run_async()
    return result[0] if confirmed[0] else None


# ---------------------------------------------------------------------------
# Inline text prompt (keyboard-only, no mouse)
# ---------------------------------------------------------------------------

async def _prompt_text(label: str, default: str = "") -> str | None:
    """Single-line text input prompt. Returns the entered text or None if cancelled."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings

    kb = KeyBindings()
    cancelled = [False]

    @kb.add("escape")
    def _esc(event: Any) -> None:
        cancelled[0] = True
        event.app.current_buffer.text = ""
        event.app.exit()

    session: Any = PromptSession(mouse_support=False, key_bindings=kb)
    try:
        value = await session.prompt_async(label, default=default)
    except (EOFError, KeyboardInterrupt):
        return None

    if cancelled[0]:
        return None
    return value.strip() or None


# ---------------------------------------------------------------------------
# Interactive model picker  (provider → model → optional API key)
# ---------------------------------------------------------------------------

async def run_model_picker(current_model: str = "") -> str | None:
    """Three-step keyboard-driven picker: provider → model → API key (if needed).

    Returns 'provider:model-id', or None if cancelled at any step.
    The API key (if entered) is saved immediately via config.save_api_key.
    """
    import os

    # ── Step 1: provider ─────────────────────────────────────────────────────
    provider_items = [
        (p, f"{p:<12}  {_PROVIDER_HINTS.get(p, '')}")
        for p in PROVIDER_MODELS
    ]
    provider = await _select(
        "Select Provider",
        "Step 1 of 2  —  ↑↓ / j k  move    Enter confirm    Esc cancel",
        provider_items,
    )
    if provider is None:
        return None

    # ── Step 2: model ────────────────────────────────────────────────────────
    models = PROVIDER_MODELS[provider]
    model_items: list[tuple[str, str]] = [
        (m, f"{m:<42} {_MODEL_DESCRIPTIONS.get(m, '')}")
        for m in models
    ] + [("__custom__", "Enter a custom model ID...")]

    model_id = await _select(
        f"{provider.capitalize()}  —  Select Model",
        "Step 2 of 2  —  ↑↓ / j k  move    Enter confirm    Esc back",
        model_items,
    )
    if model_id is None:
        return None

    # ── Optional: custom model ID ─────────────────────────────────────────────
    if model_id == "__custom__":
        custom = await _prompt_text(f"  {provider} model ID: ")
        if not custom:
            return None
        model_id = custom

    # ── Step 3: API key (only if missing for this provider) ───────────────────
    env_var = PROVIDER_ENV_VARS.get(provider)
    if env_var and not os.environ.get(env_var):
        key_items: list[tuple[str, str]] = [
            ("enter", f"Enter {env_var} now"),
            ("skip",  "Skip  (configure later with /key)"),
        ]
        action = await _select(
            f"{provider.capitalize()}  —  API Key",
            f"{env_var} is not set",
            key_items,
        )
        if action == "enter":
            key_value = await _prompt_text(f"  {env_var}: ")
            if key_value:
                from .config import save_api_key
                save_api_key(env_var, key_value)

    return f"{provider}:{model_id}"
