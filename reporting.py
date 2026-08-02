"""Deterministic local reporting and web-chat answers.

This module deliberately produces useful answers without an LLM.  That means
the dashboard remains functional during quota resets, AI server maintenance or
a complete decision to run Netmon without AI forever.

An optional AI endpoint is used only by ``web.py`` for questions that the local
intent handlers do not recognise, and by ``collector.py`` for a richer
four-hour narrative when AI has explicitly been enabled.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime
from typing import Any, Sequence

import models


Snapshot = dict[str, Any]


def _download_mbps(snapshot: Snapshot) -> float:
    return float(snapshot["download"]) / 1_000_000


def _upload_mbps(snapshot: Snapshot) -> float:
    return float(snapshot["upload"]) / 1_000_000


def _format_timestamp(value: str | datetime) -> str:
    timestamp = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value)
    )
    return timestamp.astimezone().strftime("%d %b %Y, %H:%M")


def _pearson(values_x: Sequence[float], values_y: Sequence[float]) -> float | None:
    """Return Pearson's r, or None when correlation is not meaningful."""

    if len(values_x) != len(values_y) or len(values_x) < 3:
        return None

    mean_x = statistics.fmean(values_x)
    mean_y = statistics.fmean(values_y)
    delta_x = [value - mean_x for value in values_x]
    delta_y = [value - mean_y for value in values_y]
    denominator = math.sqrt(
        sum(value * value for value in delta_x)
        * sum(value * value for value in delta_y)
    )
    if denominator == 0:
        return None
    return sum(x * y for x, y in zip(delta_x, delta_y, strict=True)) / denominator


def build_status_report(
    metric: models.NetworkMetric,
    *,
    device_count: int,
) -> str:
    """Create the short report shown after every collection cycle."""

    download = metric.download / 1_000_000
    upload = metric.upload / 1_000_000
    if download >= 150 and metric.ping <= 20:
        verdict = "Good speed and low latency."
    elif download < 60 or metric.ping > 40:
        verdict = (
            "Performance is degraded: either the line is struggling or the "
            "network is unusually busy."
        )
    else:
        verdict = "The connection is usable, but not exactly showing off."

    return (
        f"Time: {_format_timestamp(metric.timestamp)}\n"
        f"ISP: {metric.client}\n"
        f"Test server: {metric.server}\n"
        f"Download: {download:.1f} Mbps\n"
        f"Upload: {upload:.1f} Mbps\n"
        f"Latency: {metric.ping:.1f} ms\n"
        f"Devices online: {device_count}\n"
        f"Traffic used by test: {metric.bytes_received / 1_000_000:.1f} MB down, "
        f"{metric.bytes_sent / 1_000_000:.1f} MB up\n\n"
        f"{verdict}"
    )


def build_detailed_report(snapshots: Sequence[Snapshot]) -> str:
    """Summarise the available 24-hour data without contacting any AI."""

    if not snapshots:
        return "No monitoring samples are available yet."

    downloads = [_download_mbps(snapshot) for snapshot in snapshots]
    uploads = [_upload_mbps(snapshot) for snapshot in snapshots]
    pings = [float(snapshot["ping"]) for snapshot in snapshots]
    device_counts = [float(snapshot["device_count"]) for snapshot in snapshots]

    slowest = min(snapshots, key=_download_mbps)
    fastest = max(snapshots, key=_download_mbps)
    highest_ping = max(snapshots, key=lambda item: float(item["ping"]))
    correlation = _pearson(device_counts, downloads)

    if correlation is None:
        relationship = "There is not enough variation to assess device-load correlation."
    elif correlation <= -0.6:
        relationship = (
            "More connected devices strongly coincided with lower download speed "
            f"(correlation {correlation:.2f})."
        )
    elif correlation <= -0.3:
        relationship = (
            "There is a modest association between more devices and lower speed "
            f"(correlation {correlation:.2f})."
        )
    else:
        relationship = (
            "Device count does not convincingly explain the speed changes in this "
            f"period (correlation {correlation:.2f})."
        )

    return (
        f"Samples analysed: {len(snapshots)}\n"
        f"Period: {_format_timestamp(snapshots[0]['timestamp'])} to "
        f"{_format_timestamp(snapshots[-1]['timestamp'])}\n\n"
        f"Average download: {statistics.fmean(downloads):.1f} Mbps\n"
        f"Average upload: {statistics.fmean(uploads):.1f} Mbps\n"
        f"Average latency: {statistics.fmean(pings):.1f} ms\n"
        f"Slowest download: {_download_mbps(slowest):.1f} Mbps at "
        f"{_format_timestamp(slowest['timestamp'])}\n"
        f"Fastest download: {_download_mbps(fastest):.1f} Mbps at "
        f"{_format_timestamp(fastest['timestamp'])}\n"
        f"Highest latency: {float(highest_ping['ping']):.1f} ms at "
        f"{_format_timestamp(highest_ping['timestamp'])}\n"
        f"Peak device count: {int(max(device_counts))}\n\n"
        f"{relationship}"
    )


def build_ai_context(snapshots: Sequence[Snapshot]) -> str:
    """Build a compact, trustworthy data block for an optional AI endpoint."""

    if not snapshots:
        return "No monitoring samples are available."

    lines = [
        "Local Netmon measurements, oldest to newest:",
        *[
            (
                f"{snapshot['timestamp']} | "
                f"download={_download_mbps(snapshot):.1f} Mbps | "
                f"upload={_upload_mbps(snapshot):.1f} Mbps | "
                f"ping={float(snapshot['ping']):.1f} ms | "
                f"devices={int(snapshot['device_count'])}"
            )
            for snapshot in snapshots
        ],
    ]
    return "\n".join(lines)


def answer_local_question(
    question: str,
    *,
    snapshots: Sequence[Snapshot],
    latest_devices: Sequence[dict[str, Any]],
) -> tuple[str, bool]:
    """Answer common monitoring questions without an AI dependency.

    The boolean indicates whether a specific intent matched.  ``web.py`` may
    pass unmatched questions to an explicitly configured local AI endpoint.
    """

    text = " ".join(question.lower().split())
    if not snapshots:
        return (
            "There are no measurements yet. Use “Run test now” and check back "
            "after the first collection cycle.",
            True,
        )

    latest = snapshots[-1]
    downloads = [_download_mbps(snapshot) for snapshot in snapshots]
    pings = [float(snapshot["ping"]) for snapshot in snapshots]
    device_counts = [float(snapshot["device_count"]) for snapshot in snapshots]

    if any(word in text for word in ("help", "examples", "what can")):
        return (
            "Try asking: “How is it now?”, “What was the slowest test?”, "
            "“How was the last 24 hours?”, “What was the worst ping?”, "
            "“Which devices are online?” or “Did more devices reduce speed?”",
            True,
        )

    if any(word in text for word in ("now", "current", "latest", "status")):
        return (
            f"The latest test at {_format_timestamp(latest['timestamp'])} measured "
            f"{_download_mbps(latest):.1f} Mbps down, "
            f"{_upload_mbps(latest):.1f} Mbps up and "
            f"{float(latest['ping']):.1f} ms latency, with "
            f"{int(latest['device_count'])} devices online.",
            True,
        )

    if any(word in text for word in ("slowest", "worst speed", "lowest", "drop")):
        slowest = min(snapshots, key=_download_mbps)
        return (
            f"The slowest download in the available period was "
            f"{_download_mbps(slowest):.1f} Mbps at "
            f"{_format_timestamp(slowest['timestamp'])}. "
            f"Upload was {_upload_mbps(slowest):.1f} Mbps, latency was "
            f"{float(slowest['ping']):.1f} ms and "
            f"{int(slowest['device_count'])} devices were online.",
            True,
        )

    if any(word in text for word in ("fastest", "best speed", "highest speed")):
        fastest = max(snapshots, key=_download_mbps)
        return (
            f"The fastest download was {_download_mbps(fastest):.1f} Mbps at "
            f"{_format_timestamp(fastest['timestamp'])}, with "
            f"{_upload_mbps(fastest):.1f} Mbps upload and "
            f"{float(fastest['ping']):.1f} ms latency.",
            True,
        )

    if any(word in text for word in ("ping", "latency")):
        highest = max(snapshots, key=lambda item: float(item["ping"]))
        return (
            f"Average latency was {statistics.fmean(pings):.1f} ms. "
            f"The worst reading was {float(highest['ping']):.1f} ms at "
            f"{_format_timestamp(highest['timestamp'])}; the latest is "
            f"{float(latest['ping']):.1f} ms.",
            True,
        )

    if (
        "device" in text
        and any(word in text for word in ("which", "list", "online", "connected"))
    ):
        if not latest_devices:
            return "The latest device scan is empty.", True
        addresses = ", ".join(device["ip"] for device in latest_devices)
        return (
            f"The latest scan found {len(latest_devices)} active devices: "
            f"{addresses}.",
            True,
        )

    if (
        "device" in text
        and any(word in text for word in ("slow", "speed", "correl", "more"))
    ):
        correlation = _pearson(device_counts, downloads)
        if correlation is None:
            return (
                "There is not enough variation in the current sample set to "
                "calculate a meaningful relationship between device count and speed.",
                True,
            )
        if correlation <= -0.6:
            interpretation = "a strong tendency for speed to fall as device count rose"
        elif correlation <= -0.3:
            interpretation = "a modest tendency for speed to fall as device count rose"
        else:
            interpretation = "no convincing evidence that device count drove the speed changes"
        return (
            f"The device-count/download correlation is {correlation:.2f}, which "
            f"indicates {interpretation}. Correlation is descriptive, not proof "
            f"that a particular device caused the change.",
            True,
        )

    if any(
        phrase in text
        for phrase in ("24 hour", "24-hour", "overnight", "today", "summary", "average")
    ):
        return build_detailed_report(snapshots), True

    return (
        "I can answer common questions from the local measurements, but I did "
        "not recognise that one. Ask “help” to see examples. Free-form answers "
        "will become available when an optional local AI endpoint is enabled.",
        False,
    )
