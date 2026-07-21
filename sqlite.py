import json
import models
from contextlib import closing, contextmanager
from contextvars import ContextVar
import sqlite3
import uuid
from datetime import datetime
from uuid_extensions import uuid7str

_tx_depth: ContextVar[int] = ContextVar("tx_depth", default=0)


class DB:
    def __init__(self, conn: sqlite3.Connection):
        self.conn: sqlite3.Connection = conn

    def __enter__(self) -> "DB":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @classmethod
    def init(cls, path: str) -> "DB":
        if not path.strip():
            raise ValueError("Database path cannot be empty")

        try:
            conn = sqlite3.connect(path)
            conn.execute("PRAGMA foreign_keys = ON")

            db = cls(conn)
            with db.transaction():
                db._create_schema()
            return db
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to open database connection: {e}")

    def _create_schema(self):
        self.conn.execute("""
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
            );
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS device_scans (
                id             TEXT PRIMARY KEY,
                ips            TEXT NOT NULL,
                latencies      TEXT NOT NULL
            );
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS speedtest (
                id              TEXT PRIMARY KEY,
                device_scans_id TEXT UNIQUE REFERENCES device_scans(id) ON DELETE CASCADE,
                metrics_id      TEXT UNIQUE REFERENCES metrics(id) ON DELETE CASCADE
            );
        """)

    @contextmanager
    def transaction(self):
        depth = _tx_depth.get()
        _tx_depth.set(depth + 1)

        try:
            if depth == 0:
                with self.conn:
                    yield
            else:
                yield
        except sqlite3.Error as e:
            raise RuntimeError(f"Database transaction failed: {e}")
        finally:
            _tx_depth.set(depth)

    def add_metric(self, metric: models.NetworkMetric):
        with self.transaction():
            self.conn.execute("""
                INSERT INTO metrics (
                    id, download, upload, ping, timestamp, share, client, server,
                    bytes_sent, bytes_received
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(metric.id), metric.download, metric.upload,
                metric.ping, metric.timestamp, metric.share,
                metric.client, metric.server, metric.bytes_sent,
                metric.bytes_received
            ))

    def add_devices(self, devices: list[models.NetworkDevice]) -> uuid.UUID:
        scan_id   = uuid.UUID(uuid7str())
        ips       = json.dumps([d.ip         for d in devices])
        latencies = json.dumps([d.latency_ms for d in devices])

        with self.transaction():
            self.conn.execute("""
                INSERT INTO device_scans (id, ips, latencies)
                VALUES (?, ?, ?)
            """, (str(scan_id), ips, latencies))
        return scan_id

    def add_speedtest(self, speedtest: models.SpeedTest):
        with self.transaction():
            self.conn.execute("""
                INSERT INTO speedtest (id, metrics_id, device_scans_id)
                VALUES (?, ?, ?)
            """, (str(speedtest.id), str(speedtest.metric_id), str(speedtest.device_scan_id)))

    def get_metrics(self) -> list[models.NetworkMetric]:
        try:
            with closing(self.conn.cursor()) as cursor:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT id, download, upload, ping, timestamp, share, client, server, bytes_sent, bytes_received
                        FROM metrics
                        WHERE timestamp > DATETIME('now', '-24 hours')
                        ORDER BY timestamp DESC
                        LIMIT 24
                    ) ORDER BY timestamp ASC;
                """)
                rows = cursor.fetchall()
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to get metrics: {e}")

        if not rows:
            return []

        return [
            models.NetworkMetric(
                id=uuid.UUID(row[0]),
                download=row[1],
                upload=row[2],
                ping=row[3],
                timestamp=datetime.fromisoformat(row[4]),
                share=row[5],
                client=row[6],
                server=row[7],
                bytes_sent=row[8],
                bytes_received=row[9]
            )
            for row in rows
        ]

    def get_metrics_with_device_counts(self) -> tuple[list[models.NetworkMetric], list[int]]:
        try:
            with closing(self.conn.cursor()) as cursor:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT m.id, m.download, m.upload, m.ping, m.timestamp, m.share, m.client, m.server,
                               m.bytes_sent, m.bytes_received, ds.ips
                        FROM metrics m
                        JOIN speedtest st ON st.metrics_id = m.id
                        JOIN device_scans ds ON ds.id = st.device_scans_id
                        WHERE m.timestamp > DATETIME('now', '-24 hours')
                        ORDER BY m.timestamp DESC
                        LIMIT 24
                    ) ORDER BY timestamp ASC;
                """)
                rows = cursor.fetchall()
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to get metrics with device counts: {e}")

        metrics: list[models.NetworkMetric] = []
        device_counts: list[int] = []

        for row in rows:
            metrics.append(models.NetworkMetric(
                id=uuid.UUID(row[0]),
                download=row[1],
                upload=row[2],
                ping=row[3],
                timestamp=datetime.fromisoformat(row[4]),
                share=row[5],
                client=row[6],
                server=row[7],
                bytes_sent=row[8],
                bytes_received=row[9]
            ))
            device_counts.append(len(json.loads(row[10])))

        return metrics, device_counts

    def close(self):
        self.conn.close()