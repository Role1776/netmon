"""SQLite persistence shared by the Netmon collector and web dashboard.

The database is intentionally the integration boundary between the two
processes.  The collector owns measurements and reports; the web process reads
those records and writes only chat history plus a tiny manual-run flag outside
SQLite.

WAL mode allows the dashboard to keep reading while a measurement transaction
is committed.  A busy timeout prevents brief lock contention from becoming a
spurious HTTP 500 response.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import models
from uuid_extensions import uuid7str


_tx_depth: ContextVar[int] = ContextVar("tx_depth", default=0)


class DB:
    """Small repository layer around a single SQLite connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> "DB":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @classmethod
    def init(cls, path: str) -> "DB":
        """Open the database, enable concurrency pragmas and migrate schema."""

        if not path.strip():
            raise ValueError("Database path cannot be empty")

        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            conn = sqlite3.connect(db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA busy_timeout = 10000")

            db = cls(conn)
            with db.transaction():
                db._create_schema()
                db._apply_compatible_migrations()
            return db
        except sqlite3.Error as exc:
            raise RuntimeError(f"Failed to open database connection: {exc}") from exc

    def _create_schema(self) -> None:
        """Create every table used by either service on a fresh install."""

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metrics (
                id             TEXT PRIMARY KEY,
                download       REAL NOT NULL,
                upload         REAL NOT NULL,
                ping           REAL NOT NULL,
                share          TEXT,
                client         TEXT NOT NULL,
                server         TEXT NOT NULL,
                bytes_sent     INTEGER NOT NULL,
                bytes_received INTEGER NOT NULL,
                timestamp      DATETIME NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS device_scans (
                id         TEXT PRIMARY KEY,
                ips        TEXT NOT NULL,
                latencies  TEXT NOT NULL,
                timestamp  DATETIME NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS speedtest (
                id              TEXT PRIMARY KEY,
                device_scans_id TEXT UNIQUE
                    REFERENCES device_scans(id) ON DELETE CASCADE,
                metrics_id      TEXT UNIQUE
                    REFERENCES metrics(id) ON DELETE CASCADE
            )
            """
        )

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id          TEXT PRIMARY KEY,
                kind        TEXT NOT NULL,
                title       TEXT NOT NULL,
                body        TEXT NOT NULL,
                graph_path  TEXT,
                created_at  DATETIME NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id          TEXT PRIMARY KEY,
                role        TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                body        TEXT NOT NULL,
                created_at  DATETIME NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_metrics_timestamp "
            "ON metrics(timestamp)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_created_at "
            "ON reports(created_at)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_created_at "
            "ON chat_messages(created_at)"
        )

    def _apply_compatible_migrations(self) -> None:
        """Upgrade databases created by the notifier-based version in place."""

        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(device_scans)")
        }
        if "timestamp" not in columns:
            self.conn.execute(
                "ALTER TABLE device_scans "
                "ADD COLUMN timestamp DATETIME"
            )
            self.conn.execute(
                "UPDATE device_scans SET timestamp = datetime('now') "
                "WHERE timestamp IS NULL"
            )

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Provide a nestable transaction boundary for related writes."""

        depth = _tx_depth.get()
        token = _tx_depth.set(depth + 1)
        try:
            if depth == 0:
                with self.conn:
                    yield
            else:
                yield
        except sqlite3.Error as exc:
            raise RuntimeError(f"Database transaction failed: {exc}") from exc
        finally:
            _tx_depth.reset(token)

    def add_metric(self, metric: models.NetworkMetric) -> None:
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO metrics (
                    id, download, upload, ping, timestamp, share, client, server,
                    bytes_sent, bytes_received
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(metric.id),
                    metric.download,
                    metric.upload,
                    metric.ping,
                    metric.timestamp.isoformat(),
                    metric.share,
                    metric.client,
                    metric.server,
                    metric.bytes_sent,
                    metric.bytes_received,
                ),
            )

    def add_devices(self, devices: list[models.NetworkDevice]) -> uuid.UUID:
        scan_id = uuid.UUID(uuid7str())
        ips = json.dumps([device.ip for device in devices])
        latencies = json.dumps([device.latency_ms for device in devices])

        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO device_scans (id, ips, latencies, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(scan_id),
                    ips,
                    latencies,
                    datetime.now().astimezone().isoformat(),
                ),
            )
        return scan_id

    def add_speedtest(self, speedtest: models.SpeedTest) -> None:
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO speedtest (id, metrics_id, device_scans_id)
                VALUES (?, ?, ?)
                """,
                (
                    str(speedtest.id),
                    str(speedtest.metric_id),
                    str(speedtest.device_scan_id),
                ),
            )

    def add_report(
        self,
        *,
        kind: str,
        title: str,
        body: str,
        graph_path: str | None = None,
    ) -> None:
        """Store a dashboard report instead of sending it off the machine."""

        if kind not in {"status", "detailed", "error"}:
            raise ValueError(f"Unsupported report kind: {kind!r}")
        if not title.strip():
            raise ValueError("Report title cannot be empty")
        if not body.strip():
            raise ValueError("Report body cannot be empty")

        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO reports (id, kind, title, body, graph_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (uuid7str(), kind, title, body, graph_path),
            )

    def add_chat_message(self, *, role: str, body: str) -> None:
        """Persist local chat history for continuity across browser refreshes."""

        if role not in {"user", "assistant"}:
            raise ValueError(f"Unsupported chat role: {role!r}")
        if not body.strip():
            raise ValueError("Chat message cannot be empty")

        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO chat_messages (id, role, body)
                VALUES (?, ?, ?)
                """,
                (uuid7str(), role, body),
            )

    @staticmethod
    def _metric_from_row(row: sqlite3.Row) -> models.NetworkMetric:
        return models.NetworkMetric(
            id=uuid.UUID(row["id"]),
            download=row["download"],
            upload=row["upload"],
            ping=row["ping"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            share=row["share"] or "N/A",
            client=row["client"],
            server=row["server"],
            bytes_sent=row["bytes_sent"],
            bytes_received=row["bytes_received"],
        )

    def get_metrics(self) -> list[models.NetworkMetric]:
        """Return up to 96 measurements from the last 24 hours."""

        rows = self.conn.execute(
            """
            SELECT id, download, upload, ping, timestamp, share, client, server,
                   bytes_sent, bytes_received
            FROM metrics
            WHERE datetime(timestamp) > datetime('now', '-24 hours')
            ORDER BY datetime(timestamp) ASC
            LIMIT 96
            """
        ).fetchall()
        return [self._metric_from_row(row) for row in rows]

    def get_metrics_with_device_counts(
        self,
    ) -> tuple[list[models.NetworkMetric], list[int]]:
        """Return aligned metric and device-count sequences for graphing."""

        rows = self.conn.execute(
            """
            SELECT m.id, m.download, m.upload, m.ping, m.timestamp, m.share,
                   m.client, m.server, m.bytes_sent, m.bytes_received, ds.ips
            FROM metrics AS m
            JOIN speedtest AS st ON st.metrics_id = m.id
            JOIN device_scans AS ds ON ds.id = st.device_scans_id
            WHERE datetime(m.timestamp) > datetime('now', '-24 hours')
            ORDER BY datetime(m.timestamp) ASC
            LIMIT 96
            """
        ).fetchall()

        metrics: list[models.NetworkMetric] = []
        counts: list[int] = []
        for row in rows:
            metrics.append(self._metric_from_row(row))
            counts.append(len(json.loads(row["ips"])))
        return metrics, counts

    def get_recent_snapshots(
        self,
        *,
        hours: int = 24,
        limit: int = 96,
    ) -> list[dict[str, Any]]:
        """Return JSON-ready monitoring snapshots in chronological order."""

        if hours < 1:
            raise ValueError("hours must be positive")
        if limit < 1:
            raise ValueError("limit must be positive")

        modifier = f"-{hours} hours"
        rows = self.conn.execute(
            """
            SELECT m.id, m.download, m.upload, m.ping, m.timestamp, m.client,
                   m.server, m.bytes_sent, m.bytes_received, ds.ips
            FROM metrics AS m
            JOIN speedtest AS st ON st.metrics_id = m.id
            JOIN device_scans AS ds ON ds.id = st.device_scans_id
            WHERE datetime(m.timestamp) > datetime('now', ?)
            ORDER BY datetime(m.timestamp) DESC
            LIMIT ?
            """,
            (modifier, limit),
        ).fetchall()

        snapshots = [
            {
                "id": row["id"],
                "download": row["download"],
                "upload": row["upload"],
                "ping": row["ping"],
                "timestamp": row["timestamp"],
                "client": row["client"],
                "server": row["server"],
                "bytes_sent": row["bytes_sent"],
                "bytes_received": row["bytes_received"],
                "device_count": len(json.loads(row["ips"])),
            }
            for row in rows
        ]
        snapshots.reverse()
        return snapshots

    def get_latest_devices(self) -> list[dict[str, Any]]:
        """Return IP addresses and measured ARP latency from the latest scan."""

        row = self.conn.execute(
            """
            SELECT ds.ips, ds.latencies, m.timestamp
            FROM device_scans AS ds
            JOIN speedtest AS st ON st.device_scans_id = ds.id
            JOIN metrics AS m ON m.id = st.metrics_id
            ORDER BY datetime(m.timestamp) DESC
            LIMIT 1
            """
        ).fetchone()

        if row is None:
            return []

        ips = json.loads(row["ips"])
        latencies = json.loads(row["latencies"])
        return [
            {
                "ip": ip,
                "latency_ms": latency,
                "timestamp": row["timestamp"],
            }
            for ip, latency in zip(ips, latencies, strict=False)
        ]

    def get_recent_reports(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, kind, title, body, graph_path, created_at
            FROM reports
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_chat_messages(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, role, body, created_at
            FROM chat_messages
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        messages = [dict(row) for row in rows]
        messages.reverse()
        return messages

    def detailed_report_due(self, *, hours: int = 4) -> bool:
        """Return true when no detailed report was written in the interval."""

        if hours < 1:
            raise ValueError("hours must be positive")
        modifier = f"-{hours} hours"
        row = self.conn.execute(
            """
            SELECT 1
            FROM reports
            WHERE kind = 'detailed'
              AND datetime(created_at) > datetime('now', ?)
            LIMIT 1
            """,
            (modifier,),
        ).fetchone()
        return row is None

    def close(self) -> None:
        self.conn.close()
