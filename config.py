import os
import argparse
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_RETENTION_DAYS = 90

class Config:
    def __init__(
        self,
        ai_api_key: str,
        db_path: str,
        model: str,
        base_url: str,
        notifier: str,
        tg_bot_token: str = "",
        tg_chat_id: str = "",
        discord_webhook_url: str = "",
        request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ):
        self.ai_api_key: str = ai_api_key
        self.db_path: str = db_path
        self.model: str = model
        self.base_url: str = base_url
        self.notifier: str = notifier
        self.tg_bot_token: str = tg_bot_token
        self.tg_chat_id: str = tg_chat_id
        self.discord_webhook_url: str = discord_webhook_url
        self.request_timeout: int = request_timeout
        self.retention_days: int = retention_days

    @staticmethod
    def _parse_args():
        parser = argparse.ArgumentParser(description="App configuration")
        parser.add_argument(
            "--env",
            type=str,
            default=".env",
            help="Path to the .env file (default: .env)"
        )
        return parser.parse_args()

    @classmethod
    def init(cls):
        args = cls._parse_args()
        load_dotenv(args.env)

        ai_key = os.getenv("AI_API_KEY", "")
        db_path = os.getenv("DB_PATH", "")
        model = os.getenv("AI_MODEL", "")
        base_url = os.getenv("AI_BASE_URL", "")
        notifier = os.getenv("NOTIFIER", "telegram").strip().lower()

        if ai_key.strip() == "":
            raise RuntimeError("AI_API_KEY not found or empty in environment")
        if db_path.strip() == "":
            raise RuntimeError("DB_PATH not found or empty in environment")
        if model.strip() == "":
            raise RuntimeError("MODEL not found or empty in environment")
        if base_url.strip() == "":
            raise RuntimeError("BASE_URL not found or empty in environment")

        if notifier not in ("telegram", "discord"):
            raise RuntimeError(f"NOTIFIER must be 'telegram' or 'discord', got: {notifier!r}")

        tg_bot_token = os.getenv("TG_BOT_TOKEN", "")
        tg_chat_id = os.getenv("TG_CHAT_ID", "")
        discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")

        request_timeout = int(os.getenv("REQUEST_TIMEOUT", DEFAULT_REQUEST_TIMEOUT))
        if request_timeout <= 0:
            raise RuntimeError(f"REQUEST_TIMEOUT must be positive, got: {request_timeout}")

        try:
            retention_days = int(os.getenv("RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
        except ValueError:
            raise RuntimeError(f"RETENTION_DAYS must be an integer, got: {os.getenv('RETENTION_DAYS')!r}")
        if retention_days <= 0:
            raise RuntimeError(f"RETENTION_DAYS must be positive, got: {retention_days}")

        if notifier == "telegram":
            if tg_bot_token.strip() == "":
                raise RuntimeError("TG_BOT_TOKEN not found or empty in environment")
            if tg_chat_id.strip() == "":
                raise RuntimeError("TG_CHAT_ID not found or empty in environment")
        else:
            if discord_webhook_url.strip() == "":
                raise RuntimeError("DISCORD_WEBHOOK_URL not found or empty in environment")

        return cls(
            ai_key, db_path, model, base_url, notifier,
            tg_bot_token, tg_chat_id, discord_webhook_url,
            request_timeout, retention_days,
        )
