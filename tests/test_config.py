import json
import stat

import pytest

from yaac import config


@pytest.fixture(autouse=True)
def config_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / ".yaac" / "config.json")
    yield config.CONFIG_PATH


def test_save_api_key_is_owner_only(config_in_tmp, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config.save_api_key("ANTHROPIC_API_KEY", "sk-test")

    mode = stat.S_IMODE(config_in_tmp.stat().st_mode)
    assert mode == 0o600
    assert stat.S_IMODE(config_in_tmp.parent.stat().st_mode) == 0o700
    assert json.loads(config_in_tmp.read_text())["keys"]["ANTHROPIC_API_KEY"] == "sk-test"


def test_save_default_model_preserves_keys(config_in_tmp):
    config.save_api_key("OPENAI_API_KEY", "sk-openai")
    config.save_default_model("openai:gpt-4o")

    cfg = json.loads(config_in_tmp.read_text())
    assert cfg["model"] == "openai:gpt-4o"
    assert cfg["keys"]["OPENAI_API_KEY"] == "sk-openai"


def test_corrupt_config_falls_back_to_default(config_in_tmp, monkeypatch):
    monkeypatch.delenv("YAAC_MODEL", raising=False)
    config_in_tmp.parent.mkdir(parents=True)
    config_in_tmp.write_text("{not json")

    assert config.load_default_model() == config.DEFAULT_MODEL
    assert config._read_config() == {}


def test_load_api_keys_does_not_override_environment(monkeypatch):
    config.save_api_key("GROQ_API_KEY", "from-file")
    monkeypatch.setenv("GROQ_API_KEY", "from-env")

    config.load_api_keys()

    import os
    assert os.environ["GROQ_API_KEY"] == "from-env"
