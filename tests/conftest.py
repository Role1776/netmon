import dataclasses
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import requests

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text()


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def db():
    import sqlite

    database = sqlite.DB.init(":memory:")
    ref = sqlite3.connect(":memory:")

    def frozen_datetime(*args):
        args = (NOW.strftime("%Y-%m-%d %H:%M:%S"), *args[1:]) if args[0] == "now" else args
        return ref.execute(f"SELECT datetime({','.join('?' * len(args))})", args).fetchone()[0]

    database.conn.create_function("datetime", -1, frozen_datetime)
    with database:
        yield database
    ref.close()


@pytest.fixture
def make_metric():
    import models

    def make(age_hours: float = 1, **kw):
        base: dict[str, Any] = dict(download=100.0, upload=20.0, ping=10.0, share="N/A", client="isp",
                    server="srv", bytes_sent=1, bytes_received=2)
        m = models.NetworkMetric.create(**(base | kw))
        return dataclasses.replace(m, timestamp=NOW - timedelta(hours=age_hours))

    return make


class FakeHTTP:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.status = 200
        self.text = "ok"

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return type("Response", (), {"status_code": self.status, "text": self.text})()


@pytest.fixture
def http(monkeypatch):
    fake = FakeHTTP()
    monkeypatch.setattr(requests, "post", fake.post)
    return fake
