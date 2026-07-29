import signal
import sys
import json
import html
import logging
import graphs
import config as cfg
import sqlite
import ai
import tg
import discord_hook
import time
import models
import runner
from notifier import ChatAction, Notifier

REPORT_SYSTEM_PROMPT = """
You are a sarcastic, cynical network analyst bot.

You will receive: (1) a chronological list of network speed test results from the last 24 hours, (2) a device vendor breakdown for the network (vendor name + how many devices of that vendor are currently online), and (3) a list of any devices that are NEW this cycle (their MAC address has not been seen on this network in the last 14 days), each with whatever vendor/hostname/IP is available.

Respond with ONLY a single raw JSON object -- no ```json code fences, no preamble, no explanation before or after it. Just the JSON object, starting with { and ending with }. It must have exactly these three string keys:

{
  "dynamics_analysis": "2-3 short sentences analyzing speed/ping trends and drops over the given period. ONLY claim a link between device count and speed/latency swings if the numbers actually move together in the same window (e.g. speed visibly drops as device count rises). If device count swings while speed/ping stay flat, say plainly that device count does NOT explain it, and point at the ISP/line instead -- never invent a correlation the numbers don't support. If ping reads exactly 0.00 ms while download speed is very low, that means the real ping was too high to register and got floored to zero -- call it a red flag, not a strength, never a good sign. If jitter or packet loss data is present in the readings, treat high jitter (a few ms is normal; tens of ms is notable) or any nonzero packet loss as a sign of bufferbloat/an unstable line -- this matters even when the raw download/upload numbers look fine, since a connection can have great throughput but still feel laggy under load if jitter is high. If jitter/packet loss data is absent from the readings, don't mention it at all. Do NOT blame server changes for fluctuations -- assume the server choice is optimal. Wrap key numbers in <code>...</code> tags, e.g. <code>148.31 Mbps</code>.",
  "device_watch": "1-2 short sentences. If the NEW devices list you were given is empty, say so plainly (e.g. 'No new devices -- same suspects as always.'). Otherwise mention only devices from that NEW list, identified by vendor/hostname if given, otherwise by IP. Call out anything more suspicious than the rest -- e.g. a NEW device with no vendor or hostname info at all is more worth a second glance than a NEW device from a recognizable vendor. Never invent a device, vendor, hostname, or IP not given to you, and do not restate the full vendor breakdown here -- that's background context only, not something to list out.",
  "conclusion": "Exactly 1 short, witty, sarcastic sentence summarizing the network's overall quality/reliability over the period."
}

TONE (this matters more than anything else): sarcastic, informal, and funny throughout. Blame heavy users/leeches on the network or the ISP for problems -- e.g. "a bunch of idiots clogging the bandwidth", "the ISP dropping the ball", "mice chewing the optic fiber cables", "yet another gadget joining the freeloader party" -- but only when the data actually supports that story. A flat, neutral, corporate-analyst tone is a FAILED response even if the JSON is technically valid -- the personality is not optional decoration, it is the entire point of this bot. If in doubt, lean funnier and more informal, not safer and more clinical.

LENGTH LIMITS (hard requirements): "dynamics_analysis" under 500 characters, "device_watch" under 250 characters, "conclusion" under 150 characters.

Output ONLY the JSON object and nothing else -- no markdown formatting, no headers, no bullet points, no explanatory text, no restating of the raw data you were given.
"""

# The AI is only ever asked to produce the three free-text fields above --
# never the surrounding HTML structure. This is deliberate: several
# capable local models (tested: llama3.1:8b, qwen2.5:7b-instruct) reliably
# abandon a long literal HTML template under a rich, multi-constraint
# prompt and fall back to a generic "helpful assistant summarizing data"
# response instead, even with a large context window. Handling the
# skeleton in code guarantees correct, consistent formatting regardless of
# which model is behind AI_BASE_URL, and only requires the model to
# reliably produce three short strings in a JSON object -- a much easier
# and more commonly well-supported task for small/local instruct models
# than exact literal markup reproduction.
REPORT_TEMPLATE_SHELL = """<b>Network Speed Test Report (24h Analysis)</b>

Client: <b>{client}</b>
Server: <b>{server}</b>

<b>Latest Test Metrics</b>
<pre>
Download: {download:.1f} Mbps
Upload: {upload:.1f} Mbps
Ping: {ping:.1f} ms
{jitter_line}Devices Online: {device_count}
</pre>

<b>24-Hour Dynamics Analysis</b>
{dynamics_analysis}

<b>Device Watch</b>
{device_watch}

<b>Data Transfer (Latest Test)</b>
<pre>
Downloaded: {download_mb:.1f} MB
Uploaded: {upload_mb:.1f} MB
</pre>

<b>Conclusion</b>
{conclusion}"""

# Defensive per-field caps applied in code regardless of what the prompt
# asked for -- a safety net, not the primary mechanism, since the prompt's
# own instructed limits should normally keep fields well under these.
_DYNAMICS_ANALYSIS_MAX_CHARS = 600
_DEVICE_WATCH_MAX_CHARS = 320
_CONCLUSION_MAX_CHARS = 200


def _clip(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _mini_report_jitter_line(metric: "models.NetworkMetric") -> str:
    # Only the Ookla CLI backend provides jitter/packet loss; classic
    # speedtest-cli users simply won't see this line at all.
    if metric.jitter_ms is None:
        return ""
    parts = [f"Jitter: <b>{metric.jitter_ms:.1f} ms</b>"]
    if metric.packet_loss_pct is not None:
        parts.append(f"Packet loss: <b>{metric.packet_loss_pct:.1f}%</b>")
    return " | ".join(parts) + "\n"


def _shell_jitter_line(metric: "models.NetworkMetric") -> str:
    if metric.jitter_ms is None:
        return ""
    line = f"Jitter: {metric.jitter_ms:.1f} ms"
    if metric.packet_loss_pct is not None:
        line += f" | Packet Loss: {metric.packet_loss_pct:.1f}%"
    return line + "\n"


def _ai_history_jitter_line(m: "models.NetworkMetric") -> str:
    if m.jitter_ms is None:
        return ""
    line = f"- Jitter: {m.jitter_ms:.2f} ms\n"
    if m.packet_loss_pct is not None:
        line += f"- Packet Loss: {m.packet_loss_pct:.2f}%\n"
    return line


REPORT_USER_TEMPLATE = """
Network speed test results:
- Date: {timestamp}
- Download: {download:.2f} Mbps
- Upload: {upload:.2f} Mbps
- Ping: {ping:.2f} ms
{jitter_line}- Client: {client}
- Server: {server}
- Downloaded: {download_mb} MB
- Uploaded: {upload_mb} MB
- Share Link: {share}
- Devices online: {device_count}
"""

VENDOR_COUNT_TEMPLATE = "- {vendor}: {count} device(s)"
NEW_DEVICE_ENTRY_TEMPLATE = "- {ip}{vendor_part}{hostname_part}"


MINI_REPORT_TEMPLATE = """<b>Network Status Update</b>
Here is the latest snapshot of your internet speed:

Time: <b>{timestamp}</b>
ISP: <b>{client}</b> | Server: <b>{server}</b>

Devices online: <b>{device_count}</b>

Download: <b>{download:.1f} Mbps</b>
Upload: <b>{upload:.1f} Mbps</b>
Latency: <b>{ping:.1f} ms</b>
{jitter_line}
Traffic used: <b>{download_mb:.1f} MB</b> down / <b>{upload_mb:.1f} MB</b> up

<b>Current status:</b> {status_text}"""

_ERROR_ALERT_MAX_EXC_CHARS = 500


def _error_alert_message(exc: Exception) -> str:
    # HTML-escaped so a stray < or & in an exception's own message text
    # (e.g. a file path or repr containing special characters) can't break
    # Telegram's HTML parse mode and cause the alert itself to fail to send.
    exc_text = html.escape(_clip(f"{type(exc).__name__}: {exc}", _ERROR_ALERT_MAX_EXC_CHARS))
    return (
        "<b>⚠️ netmon has hit an error and is stopping</b>\n\n"
        f"<code>{exc_text}</code>\n\n"
        "This was not a transient AI hiccup — it's a real problem with the "
        "speed test, device scan, database, or notifier delivery itself, so "
        "the bot is not silently retrying. Check the service logs "
        "(journalctl -u netmon) for full details."
    )

log = logging.getLogger("netmon")


def sigterm_handler(signum, frame):
    log.info(f"Received termination signal: {signum}. Exiting gracefully.")
    sys.exit(0) 



def main():   
    signal.signal(signal.SIGTERM, sigterm_handler)
    signal.signal(signal.SIGINT, sigterm_handler)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    conf = cfg.Config.init()
    t: Notifier
    if conf.notifier == "discord":
        t = discord_hook.Bot.init(conf.discord_webhook_url, conf.request_timeout)
    else:
        t = tg.Bot.init(conf.tg_bot_token, conf.tg_chat_id, conf.request_timeout)
    r = runner.Runner()

    # Normally starts at 0 and climbs to conf.report_cycle_count before the
    # first detailed report fires. --test-ai starts it already at threshold
    # so the very first cycle exercises the AI + graph + notifier path; the
    # detailed-report branch resets counter back to 0 on completion, so
    # every cycle after that follows the normal schedule automatically —
    # no config to remember to revert afterward.
    counter = conf.report_cycle_count if conf.test_ai else 0
    if conf.test_ai:
        log.info("--test-ai passed: forcing a detailed AI report on the first cycle, then resuming normal schedule.")

    with (
        sqlite.DB.init(conf.db_path) as database,
        ai.Client.init(conf.ai_api_key, conf.model, conf.base_url) as netmon_ai,
    ):
        log.info("The bot has been started.")
        while True:
            try:
                t.send_chat_action(ChatAction.TYPING)

                metric = r.run_speedtest()
                all_devices = r.run_devices_scan()

                with database.transaction():
                    database.add_metric(metric)
                    device_scan_id = database.add_devices(all_devices)
                    speedtest = models.SpeedTest.create(metric.id, device_scan_id)
                    database.add_speedtest(speedtest)
                log.info(f"Speedtest has been added: {speedtest}")

                if counter >= conf.report_cycle_count: #send a detailed report with graph every N cycles
                    metrics, device_counts = database.get_metrics_with_device_counts()

                    user_message = ""
                    for m, device_count in zip(metrics, device_counts):
                        user_message += REPORT_USER_TEMPLATE.format(
                            timestamp=m.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                            download=round(m.download / 10**6, 1),
                            upload=round(m.upload / 10**6, 1),
                            ping=m.ping,
                            jitter_line=_ai_history_jitter_line(m),
                            client=m.client,
                            server=m.server,
                            download_mb=round(m.bytes_received / 10**6, 1),
                            upload_mb=round(m.bytes_sent / 10**6, 1),
                            share=m.share,
                            device_count=device_count
                        ) + "\n"

                    device_details = database.get_latest_devices_with_novelty()
                    if device_details:
                        vendor_counts: dict[str, int] = {}
                        for d in device_details:
                            if d["vendor"]:
                                key = d["vendor"]
                            elif d["mac"]:
                                key = "Unknown vendor"
                            else:
                                key = "Unidentified (off-subnet, no MAC resolved)"
                            vendor_counts[key] = vendor_counts.get(key, 0) + 1

                        vendor_lines = [
                            VENDOR_COUNT_TEMPLATE.format(vendor=vendor, count=count)
                            for vendor, count in sorted(vendor_counts.items(), key=lambda kv: -kv[1])
                        ]
                        user_message += "\nDevice vendor breakdown (currently online):\n" + "\n".join(vendor_lines) + "\n"

                        new_devices = [d for d in device_details if d["is_new"]]
                        if new_devices:
                            new_lines = []
                            for d in new_devices:
                                vendor_part = f" | Vendor: {d['vendor']}" if d["vendor"] else " | Vendor: unknown"
                                hostname_part = f" | Hostname: {d['hostname']}" if d["hostname"] else ""
                                new_lines.append(NEW_DEVICE_ENTRY_TEMPLATE.format(
                                    ip=d["ip"],
                                    vendor_part=vendor_part,
                                    hostname_part=hostname_part,
                                ))
                            user_message += "\nNEW devices this cycle:\n" + "\n".join(new_lines) + "\n"
                        else:
                            user_message += "\nNEW devices this cycle: none.\n"
                    else:
                        user_message += "\nDevice vendor breakdown (currently online): none detected this cycle.\nNEW devices this cycle: none.\n"

                    t.send_chat_action(ChatAction.TYPING)
                    raw_response = None
                    try:
                        raw_response = netmon_ai.send_message(user_message, REPORT_SYSTEM_PROMPT, context_size=conf.ai_context_size)

                        # Defensive cleanup: some models wrap JSON in ```json
                        # fences despite being told not to -- strip those if present.
                        cleaned = raw_response.strip()
                        if cleaned.startswith("```"):
                            cleaned = cleaned.strip("`")
                            if cleaned.lower().startswith("json"):
                                cleaned = cleaned[4:]
                            cleaned = cleaned.strip()

                        parsed = json.loads(cleaned)

                        dynamics_analysis = _clip(str(parsed.get("dynamics_analysis", "")), _DYNAMICS_ANALYSIS_MAX_CHARS)
                        device_watch = _clip(str(parsed.get("device_watch", "")), _DEVICE_WATCH_MAX_CHARS)
                        conclusion = _clip(str(parsed.get("conclusion", "")), _CONCLUSION_MAX_CHARS)

                        if not dynamics_analysis or not device_watch or not conclusion:
                            raise ValueError(f"AI response missing one or more required fields: {parsed!r}")

                    except Exception as e:
                        # Covers both AI backend failures (unreachable/misconfigured)
                        # and the model returning malformed/incomplete JSON -- either
                        # way, don't lose the whole report, just fall back to plain
                        # non-AI text for the three commentary fields. The skeleton
                        # itself is unaffected either way since it's built in code.
                        log.error(
                            f"AI report generation failed or returned invalid data: {e}\n"
                            f"Raw AI response was: {raw_response!r}",
                            exc_info=True,
                        )
                        dynamics_analysis = "AI commentary unavailable this cycle — the AI backend could not be reached or returned an unexpected response."
                        device_watch = "AI commentary unavailable this cycle."
                        conclusion = "Raw graph data is attached below."

                    report = REPORT_TEMPLATE_SHELL.format(
                        client=metric.client,
                        server=metric.server,
                        download=metric.download / 10**6,
                        upload=metric.upload / 10**6,
                        ping=metric.ping,
                        jitter_line=_shell_jitter_line(metric),
                        device_count=len(all_devices),
                        dynamics_analysis=dynamics_analysis,
                        device_watch=device_watch,
                        download_mb=metric.bytes_received / 10**6,
                        upload_mb=metric.bytes_sent / 10**6,
                        conclusion=conclusion,
                    )

                    t.send_chat_action(ChatAction.UPLOAD_PHOTO)
                    graph = graphs.NetmonGraph(metrics, device_counts)
                    graph_name = graph.plot()

                    with open(graph_name, "rb") as f:
                        t.send_photo(f.read(), report)

                    log.info("Detailed report has been sent.")
                    counter = 0
                else:
                    dl_speed = metric.download / 10**6
                    ping = metric.ping
                    if dl_speed >= 150 and ping <= 20:
                        status_text = "Good speed and low latency"
                    elif dl_speed < 60 or ping > 40:
                        status_text = "A bunch of idiots decided to stream 4K movies all at once, or the ISP's mice were busy chewing on the fiber line again, whatever"
                    else:
                        status_text = "At least it works, I guess"

                    msg = MINI_REPORT_TEMPLATE.format(
                        timestamp=metric.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                        download=dl_speed,
                        upload=metric.upload / 10**6,
                        ping=ping,
                        jitter_line=_mini_report_jitter_line(metric),
                        device_count=len(all_devices),
                        client=metric.client,
                        server=metric.server,
                        download_mb=metric.bytes_received / 10**6,
                        upload_mb=metric.bytes_sent / 10**6,
                        status_text=status_text,
                    )
                    t.send_message(msg)
                    log.info("Mini report has been sent.")

                counter += 1

            except Exception as e:
                # Real infrastructure failures (speed test, device scan,
                # database, or notifier delivery) are NOT retried silently --
                # per the project's design, they should crash loudly so a
                # persistent problem doesn't go unnoticed. Before crashing,
                # make a best-effort attempt to post an alert to the
                # configured notifier so the failure is visible outside of
                # server logs, then re-raise so the process actually exits
                # (systemd/your process manager handles the restart policy).
                log.error(f"Unrecoverable error during monitoring cycle: {e}", exc_info=True)
                try:
                    t.send_message(_error_alert_message(e))
                except Exception as notify_err:
                    log.error(f"Additionally failed to notify about the error: {notify_err}")
                raise

            time.sleep(conf.sleep_time)

if __name__ == "__main__":
    main()