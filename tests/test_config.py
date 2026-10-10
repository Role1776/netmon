import sys

import pytest

import config

VARS = ["AI_API_KEY", "DB_PATH", "AI_MODEL", "AI_BASE_URL", "NOTIFIER", "TG_BOT_TOKEN",
        "TG_CHAT_ID", "DISCORD_WEBHOOK_URL", "REQUEST_TIMEOUT"]
TG = {"AI_API_KEY": "k", "DB_PATH": "m.sql", "AI_MODEL": "gpt", "AI_BASE_URL": "http://ai",
      "TG_BOT_TOKEN": "tok", "TG_CHAT_ID": "42"}
DISCORD = {"AI_API_KEY": "k", "DB_PATH": "m.sql", "AI_MODEL": "gpt", "AI_BASE_URL": "http://ai",
           "NOTIFIER": "discord", "DISCORD_WEBHOOK_URL": "http://hook"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    for name in VARS:
        # setenv first so that values loaded from a .env file are undone too
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.setattr(sys, "argv", ["netmon", "--env", str(tmp_path / "missing.env")])

    def apply(values: dict[str, str]):
        for k, v in values.items():
            monkeypatch.setenv(k, v)

    return apply


def test_telegram_config_with_defaults(env):
    env(TG)
    c = config.Config.init()
    assert (c.ai_api_key, c.db_path, c.model, c.base_url) == ("k", "m.sql", "gpt", "http://ai")
    assert (c.notifier, c.tg_bot_token, c.tg_chat_id) == ("telegram", "tok", "42")
    assert c.discord_webhook_url == ""
    assert c.request_timeout == 30


def test_discord_config_does_not_need_telegram_vars(env):
    env(DISCORD)
    c = config.Config.init()
    assert (c.notifier, c.discord_webhook_url, c.tg_bot_token, c.tg_chat_id) == ("discord", "http://hook", "", "")


def test_telegram_config_does_not_need_discord_url(env):
    env(TG | {"NOTIFIER": "telegram"})
    assert config.Config.init().notifier == "telegram"


def test_notifier_is_normalized(env):
    env(DISCORD | {"NOTIFIER": "  Discord "})
    assert config.Config.init().notifier == "discord"


@pytest.mark.parametrize("value", ["slack", "tg", "telegram,discord"])
def test_unknown_notifier_rejected(env, value):
    env(TG | {"NOTIFIER": value})
    with pytest.raises(RuntimeError):
        config.Config.init()


@pytest.mark.parametrize("name", ["AI_API_KEY", "DB_PATH", "AI_MODEL", "AI_BASE_URL", "TG_BOT_TOKEN", "TG_CHAT_ID"])
@pytest.mark.parametrize("blank", [None, "", "   "])
def test_required_telegram_var_missing_or_blank_rejected(env, name, blank):
    env({k: v for k, v in TG.items() if k != name} | ({} if blank is None else {name: blank}))
    with pytest.raises(RuntimeError):
        config.Config.init()


@pytest.mark.parametrize("name", ["AI_API_KEY", "DISCORD_WEBHOOK_URL"])
@pytest.mark.parametrize("blank", [None, "", "   "])
def test_required_discord_var_missing_or_blank_rejected(env, name, blank):
    env({k: v for k, v in DISCORD.items() if k != name} | ({} if blank is None else {name: blank}))
    with pytest.raises(RuntimeError):
        config.Config.init()


def test_request_timeout_is_read_as_int(env):
    env(TG | {"REQUEST_TIMEOUT": "7"})
    assert config.Config.init().request_timeout == 7


@pytest.mark.parametrize("value", ["0", "-5"])
def test_non_positive_request_timeout_rejected(env, value):
    env(TG | {"REQUEST_TIMEOUT": value})
    with pytest.raises(RuntimeError):
        config.Config.init()


@pytest.mark.parametrize("value", ["abc", "1.5", ""])
def test_non_integer_request_timeout_rejected(env, value):
    env(TG | {"REQUEST_TIMEOUT": value})
    with pytest.raises((RuntimeError, ValueError)):
        config.Config.init()


def test_env_file_is_loaded_from_env_argument(env, monkeypatch, tmp_path):
    f = tmp_path / "custom.env"
    f.write_text("\n".join(f"{k}={v}" for k, v in TG.items()))
    monkeypatch.setattr(sys, "argv", ["netmon", "--env", str(f)])
    assert config.Config.init().tg_chat_id == "42"


def test_process_env_wins_over_env_file(env, monkeypatch, tmp_path):
    f = tmp_path / "custom.env"
    f.write_text("\n".join(f"{k}={v}" for k, v in TG.items()))
    monkeypatch.setattr(sys, "argv", ["netmon", "--env", str(f)])
    env({"TG_CHAT_ID": "7"})
    assert config.Config.init().tg_chat_id == "7"
