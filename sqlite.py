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
                jitter_ms      REAL,
                packet_loss_pct REAL,
                timestamp      DATETIME NOT NULL DEFAULT (datetime('now'))
            );
        """)
        self._migrate_metrics_columns()

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS device_scans (
                id             TEXT PRIMARY KEY,
                ips            TEXT NOT NULL,
                latencies      TEXT NOT NULL,
                macs           TEXT NOT NULL DEFAULT '[]',
                vendors        TEXT NOT NULL DEFAULT '[]',
                hostnames      TEXT NOT NULL DEFAULT '[]'
            );
        """)
        self._migrate_device_scans_columns()

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS speedtest (
                id              TEXT PRIMARY KEY,
                device_scans_id TEXT UNIQUE REFERENCES device_scans(id) ON DELETE CASCADE,
                metrics_id      TEXT UNIQUE REFERENCES metrics(id) ON DELETE CASCADE
            );
        """)

    def _migrate_metrics_columns(self):
        # Databases created before jitter/packet-loss tracking was added
        # won't have these columns yet; add them in place. Nullable since
        # only the Ookla CLI backend provides this data -- classic
        # speedtest-cli users will just have NULL here indefinitely, which
        # is expected, not a migration failure.
        cursor = self.conn.execute("PRAGMA table_info(metrics)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col in ("jitter_ms", "packet_loss_pct"):
            if col not in existing_cols:
                self.conn.execute(f"ALTER TABLE metrics ADD COLUMN {col} REAL")

    def _migrate_device_scans_columns(self):
        # Databases created before mac/vendor/hostname tracking was added
        # won't have these columns yet; add them in place so upgrading
        # doesn't require recreating the database.
        cursor = self.conn.execute("PRAGMA table_info(device_scans)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col in ("macs", "vendors", "hostnames"):
            if col not in existing_cols:
                self.conn.execute(
                    f"ALTER TABLE device_scans ADD COLUMN {col} TEXT NOT NULL DEFAULT '[]'"
                )

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
                    bytes_sent, bytes_received, jitter_ms, packet_loss_pct
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(metric.id), metric.download, metric.upload,
                metric.ping, metric.timestamp, metric.share,
                metric.client, metric.server, metric.bytes_sent,
                metric.bytes_received, metric.jitter_ms, metric.packet_loss_pct
            ))

    def add_devices(self, devices: list[models.NetworkDevice]) -> uuid.UUID:
        scan_id   = uuid.UUID(uuid7str())
        ips       = json.dumps([d.ip         for d in devices])
        latencies = json.dumps([d.latency_ms for d in devices])
        macs      = json.dumps([d.mac        for d in devices])
        vendors   = json.dumps([d.vendor     for d in devices])
        hostnames = json.dumps([d.hostname   for d in devices])

        with self.transaction():
            self.conn.execute("""
                INSERT INTO device_scans (id, ips, latencies, macs, vendors, hostnames)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(scan_id), ips, latencies, macs, vendors, hostnames))
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
                        SELECT id, download, upload, ping, timestamp, share, client, server, bytes_sent, bytes_received, jitter_ms, packet_loss_pct
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
                bytes_received=row[9],
                jitter_ms=row[10],
                packet_loss_pct=row[11],
            )
            for row in rows
        ]

    def get_metrics_with_device_counts(self) -> tuple[list[models.NetworkMetric], list[int]]:
        try:
            with closing(self.conn.cursor()) as cursor:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT m.id, m.download, m.upload, m.ping, m.timestamp, m.share, m.client, m.server,
                               m.bytes_sent, m.bytes_received, m.jitter_ms, m.packet_loss_pct, ds.ips
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
                bytes_received=row[9],
                jitter_ms=row[10],
                packet_loss_pct=row[11],
            ))
            device_counts.append(len(json.loads(row[12])))

        return metrics, device_counts

    def get_latest_devices_with_novelty(self, lookback_days: int = 14) -> list[dict]:
        """
        Returns the most recent device scan's devices, each annotated with
        whether its MAC address has been seen in any earlier scan within
        the lookback window — i.e. whether it's new to the network.
        Devices without a resolvable MAC (nmap only resolves MAC for hosts
        on the same local subnet) are never flagged as new, since there's
        no reliable identity to compare against.
        """
        try:
            with closing(self.conn.cursor()) as cursor:
                cursor.execute("""
                    SELECT id, ips, latencies, macs, vendors, hostnames
                    FROM device_scans
                    ORDER BY rowid DESC
                    LIMIT 1
                """)
                latest = cursor.fetchone()
                if latest is None:
                    return []

                latest_id = latest[0]
                ips       = json.loads(latest[1])
                latencies = json.loads(latest[2])
                macs      = json.loads(latest[3])
                vendors   = json.loads(latest[4])
                hostnames = json.loads(latest[5])

                cursor.execute("""
                    SELECT ds.macs
                    FROM device_scans ds
                    JOIN speedtest st ON st.device_scans_id = ds.id
                    JOIN metrics m ON m.id = st.metrics_id
                    WHERE ds.id != ?
                      AND m.timestamp > DATETIME('now', ?)
                """, (latest_id, f'-{lookback_days} days'))

                known_macs: set[str] = set()
                for (macs_json,) in cursor.fetchall():
                    for m in json.loads(macs_json):
                        if m:
                            known_macs.add(m)
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to get latest devices with novelty: {e}")

        devices = []
        for i, ip in enumerate(ips):
            mac = macs[i] if i < len(macs) else None
            devices.append({
                "ip": ip,
                "mac": mac,
                "vendor": vendors[i] if i < len(vendors) else None,
                "hostname": hostnames[i] if i < len(hostnames) else None,
                "latency_ms": latencies[i] if i < len(latencies) else None,
                "is_new": bool(mac) and mac not in known_macs,
            })
        return devices

    def close(self):
        self.conn.close()