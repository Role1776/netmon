"""Long-running Netmon measurement collector.

The collector owns WAN speed tests, LAN scans, graph generation and report
creation. It never sends a report to Telegram or Discord. Results are written
to the local SQLite database for the authenticated web process to display.

Remote AI is optional and dynamically controlled by the private settings file.
The collector rereads that file only when a four-hour narrative is due, so the
web switch takes effect without a service restart while ordinary local
monitoring remains independent of Groq availability.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path

import ai
import config as cfg
import graphs
import models
import reporting
import runner
import secure_settings
import sqlite


log = logging.getLogger("netmon.collector")

AI_REPORT_SYSTEM_PROMPT = """You are a concise network analyst.
Use only the supplied measurements. Do not invent causes or correlations.
Write a plain-text 24-hour report in no more than 180 words.
Include averages, the worst meaningful event, device-count context and one
brief dry or sarcastic closing sentence. Do not use HTML or Markdown tables.
"""


class Collector:
    """Coordinate one measurement cycle and the persistent scheduling loop."""

    def __init__(self, conf: cfg.Config):
        self.conf = conf
        self.runner = runner.Runner()
        self.stop_event = threading.Event()
        self.settings_store = secure_settings.SettingsStore(
            conf.secure_settings_path
        )

    def request_stop(self, signum: int, _frame: object) -> None:
        log.info("Received signal %s; stopping cleanly.", signum)
        self.stop_event.set()

    def _write_error_report(self, message: str) -> None:
        """Make collection failures visible in the dashboard, not just journald."""

        try:
            with sqlite.DB.init(self.conf.db_path) as database:
                database.add_report(
                    kind="error",
                    title="Monitoring cycle failed",
                    body=message,
                )
        except Exception:
            # Logging the secondary failure avoids hiding the original error.
            log.exception("Could not persist the collector error report.")

    def _build_detailed_report(
        self,
        snapshots: list[dict[str, object]],
    ) -> str:
        """Use verified Remote AI when enabled, otherwise return local analysis."""

        local_report = reporting.build_detailed_report(snapshots)
        settings = self.settings_store.load()
        if not settings.ai_enabled or not settings.ai_key_active:
            return local_report

        try:
            with ai.Client.init(
                settings.ai_api_key,
                settings.ai_model,
                settings.ai_base_url,
                self.conf.request_timeout,
            ) as client:
                return client.send_message(
                    reporting.build_ai_context(snapshots),
                    AI_REPORT_SYSTEM_PROMPT,
                )
        except Exception as exc:
            # Monitoring must never fail merely because optional commentary is
            # unavailable. Disable nothing here: a transient WAN fault should
            # not silently alter an explicit operator setting.
            log.exception("AI report generation failed; using local summary.")
            return (
                f"{local_report}\n\n"
                f"Remote AI commentary was unavailable for this cycle: {exc}"
            )

    def run_cycle(self) -> None:
        """Run one complete and transactionally persisted monitoring cycle."""

        log.info("Starting network measurement cycle.")
        metric = self.runner.run_speedtest()
        devices = self.runner.run_devices_scan()

        with sqlite.DB.init(self.conf.db_path) as database:
            with database.transaction():
                database.add_metric(metric)
                scan_id = database.add_devices(devices)
                database.add_speedtest(
                    models.SpeedTest.create(metric.id, scan_id)
                )

            metrics, device_counts = database.get_metrics_with_device_counts()
            graph_path: str | None = None
            if metrics:
                # ``graphs.py`` writes one stable filename. Recreating it each
                # cycle keeps the browser view current without accumulating
                # thousands of historical PNG files.
                graph_path = graphs.NetmonGraph(metrics, device_counts).plot()

            database.add_report(
                kind="status",
                title="Network status",
                body=reporting.build_status_report(
                    metric,
                    device_count=len(devices),
                ),
                graph_path=graph_path,
            )

            if database.detailed_report_due(hours=4):
                snapshots = database.get_recent_snapshots(hours=24, limit=96)
                database.add_report(
                    kind="detailed",
                    title="24-hour network analysis",
                    body=self._build_detailed_report(snapshots),
                    graph_path=graph_path,
                )

        log.info(
            "Measurement complete: %.1f Mbps down, %.1f Mbps up, %.1f ms, "
            "%d devices.",
            metric.download / 1_000_000,
            metric.upload / 1_000_000,
            metric.ping,
            len(devices),
        )

    def _manual_run_requested(self) -> bool:
        """Atomically consume the flag written by the web dashboard."""

        flag = Path(self.conf.run_now_flag)
        try:
            flag.unlink()
            return True
        except FileNotFoundError:
            return False

    def run_forever(self) -> None:
        """Run immediately, then on schedule or when the web UI requests it."""

        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)

        # Running immediately gives a new installation useful dashboard data
        # without making the operator wait for the first 30-minute boundary.
        next_scheduled_run = 0.0

        while not self.stop_event.is_set():
            now = time.monotonic()
            manual_run = self._manual_run_requested()
            if manual_run or now >= next_scheduled_run:
                try:
                    self.run_cycle()
                except Exception as exc:
                    log.exception("Monitoring cycle failed.")
                    self._write_error_report(str(exc))
                finally:
                    next_scheduled_run = (
                        time.monotonic() + self.conf.collection_interval
                    )

            # A two-second polling interval makes Run test now responsive while
            # remaining negligible compared with an actual speed test.
            self.stop_event.wait(timeout=2)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    Collector(cfg.Config.init()).run_forever()


if __name__ == "__main__":
    main()
