"""Environment-backed configuration shared by the Netmon services.

The local-web edition keeps ordinary runtime paths in ``netmon.env`` while
security-sensitive, operator-managed values live in a separate private JSON
store.  In particular, the administrator password hash and Groq API key are
never written to the Git checkout or returned to the browser.

``collector.py`` and ``web.py`` both load this class, so they cannot silently
drift onto different database, graph, secure-settings or scheduling paths.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from dotenv import load_dotenv


DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_COLLECTION_INTERVAL = 1800
DEFAULT_WEB_HOST = "0.0.0.0"
DEFAULT_WEB_PORT = 8000
DEFAULT_DB_PATH = "/var/lib/netmon/metrics.sql"
DEFAULT_GRAPH_PATH = "/opt/netmon/graphs/network_speed_test.png"
DEFAULT_RUN_NOW_FLAG = "/var/lib/netmon/run-now"
DEFAULT_SECURE_SETTINGS_PATH = "/var/lib/netmon/private-settings.json"


def _positive_int(value: str, *, field_name: str, minimum: int = 1) -> int:
    """Parse a bounded positive integer from an environment variable."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{field_name} must be an integer, got {value!r}") from exc

    if parsed < minimum:
        raise RuntimeError(f"{field_name} must be at least {minimum}, got {parsed}")
    return parsed


@dataclass(frozen=True, slots=True)
class Config:
    """Non-secret runtime configuration shared by collector and dashboard."""

    db_path: str
    graph_path: str
    run_now_flag: str
    secure_settings_path: str
    collection_interval: int
    web_host: str
    web_port: int
    request_timeout: int

    @staticmethod
    def _parse_args() -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="Netmon configuration")
        parser.add_argument(
            "--env",
            default=".env",
            help="Environment file path (default: .env)",
        )
        # parse_known_args keeps imports test-friendly. Test runners and WSGI
        # launchers may add command-line arguments of their own.
        args, _unknown = parser.parse_known_args()
        return args

    @classmethod
    def init(cls) -> "Config":
        """Load, validate and return the process configuration."""

        args = cls._parse_args()
        load_dotenv(args.env)

        db_path = os.getenv("DB_PATH", DEFAULT_DB_PATH).strip()
        graph_path = os.getenv("GRAPH_PATH", DEFAULT_GRAPH_PATH).strip()
        run_now_flag = os.getenv("RUN_NOW_FLAG", DEFAULT_RUN_NOW_FLAG).strip()
        secure_settings_path = os.getenv(
            "SECURE_SETTINGS_PATH",
            DEFAULT_SECURE_SETTINGS_PATH,
        ).strip()
        web_host = os.getenv("WEB_HOST", DEFAULT_WEB_HOST).strip()

        for name, value in (
            ("DB_PATH", db_path),
            ("GRAPH_PATH", graph_path),
            ("RUN_NOW_FLAG", run_now_flag),
            ("SECURE_SETTINGS_PATH", secure_settings_path),
            ("WEB_HOST", web_host),
        ):
            if not value:
                raise RuntimeError(f"{name} cannot be empty")

        collection_interval = _positive_int(
            os.getenv("COLLECTION_INTERVAL", str(DEFAULT_COLLECTION_INTERVAL)),
            field_name="COLLECTION_INTERVAL",
            # A lower bound prevents a typo from hammering the WAN connection.
            minimum=60,
        )
        web_port = _positive_int(
            os.getenv("WEB_PORT", str(DEFAULT_WEB_PORT)),
            field_name="WEB_PORT",
            minimum=1,
        )
        if web_port > 65535:
            raise RuntimeError(f"WEB_PORT must not exceed 65535, got {web_port}")

        request_timeout = _positive_int(
            os.getenv("REQUEST_TIMEOUT", str(DEFAULT_REQUEST_TIMEOUT)),
            field_name="REQUEST_TIMEOUT",
            minimum=1,
        )

        return cls(
            db_path=db_path,
            graph_path=graph_path,
            run_now_flag=run_now_flag,
            secure_settings_path=secure_settings_path,
            collection_interval=collection_interval,
            web_host=web_host,
            web_port=web_port,
            request_timeout=request_timeout,
        )
