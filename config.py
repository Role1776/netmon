import os
import argparse
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_SLEEP_TIME = 1800
DEFAULT_REPORT_CYCLE_COUNT = 8

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
        sleep_time: int = DEFAULT_SLEEP_TIME,
        report_cycle_count: int = DEFAULT_REPORT_CYCLE_COUNT,
        test_ai: bool = False,
        ai_context_size: int | None = None,
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
        self.sleep_time: int = sleep_time
        self.report_cycle_count: int = report_cycle_count
        self.test_ai: bool = test_ai
        self.ai_context_size: int | None = ai_context_size

    @staticmethod
    def _parse_args():
        parser = argparse.ArgumentParser(description="App configuration")
        parser.add_argument(
            "--env",
            type=str,
            default=".env",
            help="Path to the .env file (default: .env)"
        )
        parser.add_argument(
            "--test-ai",
            action="store_true",
            help="Force the very first cycle to run the full detailed report "
                 "(AI commentary + graph + notifier delivery), then continue on "
                 "the normal REPORT_CYCLE_COUNT schedule for every cycle after. "
                 "Useful for verifying the AI backend and notifier work without "
                 "waiting for the regular cadence or permanently changing config."
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
            sleep_time = int(os.getenv("SLEEP_TIME", DEFAULT_SLEEP_TIME))
        except ValueError:
            raise RuntimeError(f"SLEEP_TIME must be an integer number of seconds, got: {os.getenv('SLEEP_TIME')!r}")
        if sleep_time <= 0:
            raise RuntimeError(f"SLEEP_TIME must be positive, got: {sleep_time}")

        try:
            report_cycle_count = int(os.getenv("REPORT_CYCLE_COUNT", DEFAULT_REPORT_CYCLE_COUNT))
        except ValueError:
            raise RuntimeError(f"REPORT_CYCLE_COUNT must be an integer, got: {os.getenv('REPORT_CYCLE_COUNT')!r}")
        if report_cycle_count <= 0:
            raise RuntimeError(f"REPORT_CYCLE_COUNT must be positive, got: {report_cycle_count}")

        # Optional and unset by default — only meaningful for local
        # OpenAI-compatible servers like Ollama, whose default context
        # window can silently truncate a long system prompt + a day's
        # worth of history once combined. Left as None, nothing extra is
        # sent, so cloud OpenAI usage is unaffected.
        ai_context_size_raw = os.getenv("AI_CONTEXT_SIZE")
        ai_context_size: int | None = None
        if ai_context_size_raw is not None and ai_context_size_raw.strip() != "":
            try:
                ai_context_size = int(ai_context_size_raw)
            except ValueError:
                raise RuntimeError(f"AI_CONTEXT_SIZE must be an integer, got: {ai_context_size_raw!r}")
            if ai_context_size <= 0:
                raise RuntimeError(f"AI_CONTEXT_SIZE must be positive, got: {ai_context_size}")

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
            request_timeout, sleep_time, report_cycle_count,
            args.test_ai, ai_context_size,
        )
