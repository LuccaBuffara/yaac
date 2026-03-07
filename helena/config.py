"""Model configuration for Helena Code."""

import json
import os
from pathlib import Path

CONFIG_PATH = Path.home() / ".helena" / "config.json"
DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"

# Runtime override — set when the user switches models mid-session.
_current_model: str | None = None

# Maps provider name → required environment variable (None = no key needed).
PROVIDER_ENV_KEYS: dict[str, str | None] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "ollama": None,
}

# Context window sizes by model substring (input tokens).
CONTEXT_WINDOWS: dict[str, int] = {
    # Anthropic
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4": 200_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "o1": 200_000,
    "o3": 200_000,
    # Google
    "gemini-2.0-flash": 1_048_576,
    "gemini-1.5-pro": 2_097_152,
    "gemini-1.5-flash": 1_048_576,
    # Groq
    "llama-3.3-70b": 128_000,
    "llama-3.1-8b": 128_000,
    # Mistral
    "mistral-large": 128_000,
    "mistral-small": 32_000,
}


def parse_model_str(model_str: str) -> tuple[str, str]:
    """Parse 'provider:model-id' → (provider, model_id). Bare names default to anthropic."""
    if ":" in model_str:
        provider, model_id = model_str.split(":", 1)
        return provider.lower(), model_id
    return "anthropic", model_str


def load_default_model() -> str:
    """Return the configured default model (env var > config file > built-in default)."""
    if env := os.environ.get("HELENA_MODEL"):
        return env
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
            if model := cfg.get("model"):
                return model
        except Exception:
            pass
    return DEFAULT_MODEL


def get_current_model() -> str:
    """Return the active model for the current session."""
    return _current_model or load_default_model()


def set_current_model(model_str: str) -> None:
    """Set the active model for the current session (does not persist)."""
    global _current_model
    _current_model = model_str


def save_default_model(model_str: str) -> None:
    """Persist the default model to ~/.helena/config.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if CONFIG_PATH.exists():
        try:
            existing = json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    existing["model"] = model_str
    CONFIG_PATH.write_text(json.dumps(existing, indent=2))


def resolve_model(model_str: str):
    """Convert a 'provider:model-id' string to a pydantic-ai model object."""
    provider, model_id = parse_model_str(model_str)

    if provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        return AnthropicModel(model_id)

    if provider == "openai":
        try:
            from pydantic_ai.models.openai import OpenAIModel
        except ImportError:
            raise ImportError("Install OpenAI support: pip install 'pydantic-ai[openai]'")
        return OpenAIModel(model_id)

    if provider in ("google", "gemini"):
        try:
            from pydantic_ai.models.gemini import GeminiModel
        except ImportError:
            raise ImportError("Install Google support: pip install 'pydantic-ai[google]'")
        return GeminiModel(model_id)

    if provider == "groq":
        try:
            from pydantic_ai.models.groq import GroqModel
        except ImportError:
            raise ImportError("Install Groq support: pip install 'pydantic-ai[groq]'")
        return GroqModel(model_id)

    if provider == "mistral":
        try:
            from pydantic_ai.models.mistral import MistralModel
        except ImportError:
            raise ImportError("Install Mistral support: pip install 'pydantic-ai[mistral]'")
        return MistralModel(model_id)

    if provider == "ollama":
        try:
            from pydantic_ai.models.openai import OpenAIModel
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("Install OpenAI support: pip install 'pydantic-ai[openai]'")
        client = AsyncOpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
        return OpenAIModel(model_id, openai_client=client)

    supported = ", ".join(PROVIDER_ENV_KEYS)
    raise ValueError(f"Unknown provider '{provider}'. Supported: {supported}")


def get_context_window(model_str: str) -> int | None:
    """Return the context window size for a model string, or None if unknown."""
    _, model_id = parse_model_str(model_str)
    for key, size in CONTEXT_WINDOWS.items():
        if key in model_id:
            return size
    return None


def check_api_key(model_str: str) -> tuple[bool, str | None]:
    """Check whether the required API key is present for the given model.

    Returns (ok, env_var_name). If ok is False, env_var_name is the missing variable.
    """
    provider, _ = parse_model_str(model_str)
    required = PROVIDER_ENV_KEYS.get(provider)
    if required is None:
        return True, None  # provider needs no key (e.g. ollama)
    if os.environ.get(required):
        return True, None
    return False, required


def load_api_keys() -> None:
    """Load API keys saved in ~/.helena/config.json into os.environ (non-overriding)."""
    if not CONFIG_PATH.exists():
        return
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        for env_var, value in cfg.get("keys", {}).items():
            if value and not os.environ.get(env_var):
                os.environ[env_var] = value
    except Exception:
        pass


def save_api_key(env_var: str, value: str) -> None:
    """Save an API key to ~/.helena/config.json and set it in os.environ."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if CONFIG_PATH.exists():
        try:
            existing = json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    existing.setdefault("keys", {})[env_var] = value
    CONFIG_PATH.write_text(json.dumps(existing, indent=2))
    os.environ[env_var] = value
