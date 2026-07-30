import signal
import sys
import logging
from datetime import datetime, timezone
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
You are a sarcastic, cynical network analyst bot. Your job is to output a short network speed test and 24-hour trend report in Telegram HTML format.
You will receive a list of speed tests from the last 24 hours in chronological order (the last line is the latest test).

You must write the report in ENGLISH.
You must follow the EXACT structure below. Do not deviate from this layout, header naming, or formatting.

EXPECTED STRUCTURE:
<b>Network Speed Test Report (24h Analysis)</b>

Client: <b>[Client ISP]</b>
Server: <b>[Server Name]</b>

<b>Latest Test Metrics</b>
<pre>
Download: [Download Speed] Mbps
Upload: [Upload Speed] Mbps
Ping: [Ping Latency] ms
Devices Online: [Device Count]
</pre>

<b>24-Hour Dynamics Analysis</b>
[Analyze the dynamics, drops, and load of the network over the last 24 hours. Note any major drops in download/upload speeds or ping spikes.
Also look at how the device count changed over the same period. ONLY claim a link between device count and speed/latency swings if the numbers actually move together (e.g. speed visibly drops in the same window device count rises). If device count swings around while speed/ping stay flat, say plainly that device count does NOT explain it this period, and point at the ISP/line instead. Never invent a correlation that isn't supported by the numbers.
If ping reads exactly 0.00 ms while download speed is very low (a few Mbps or less), do NOT describe that as a good/perfect ping. That reading means the real ping was too high to register and got floored to zero — call it a red flag, not a strength.
Use a sarcastic, informal tone when describing speed drops, latency spikes, or a sudden herd of new devices, blaming heavy users/leeches on the network or the ISP (e.g. "a bunch of idiots clogging the bandwidth", "ISP dropping the ball", "mice chewing the optic fiber cables", or "yet another gadget joining the freeloader party") — but only when the data actually supports that story.
CRITICAL: Do NOT blame server changes for fluctuations. Assume the server choice is optimal and fluctuations reflect real network load, device count, or ISP issues.
Wrap key numbers in <code> tags, e.g., <code>148.31 Mbps</code>, <code>15.18 ms</code>, or <code>7 devices</code>.]

<b>Data Transfer (Latest Test)</b>
<pre>
Downloaded: [Downloaded MB] MB
Uploaded: [Uploaded MB] MB
</pre>

<b>Conclusion</b>
[A sarcastic, witty 1 short sentence summary of the network's overall quality and reliability over the past day.]


TEMPLATE EXAMPLE OF THE OUTPUT:
<b>Network Speed Test Report (24h Analysis)</b>

Client: <b>nameserver</b>
Server: <b>New York</b>

<b>Latest Test Metrics</b>
<pre>
Download: 140.3 Mbps
Upload: 62.8 Mbps
Ping: 15.2 ms
Devices Online: 7
</pre>

<b>24-Hour Dynamics Analysis</b>
Over the last 24 hours, the download speed averaged <code>140 Mbps</code>, but we saw a massive drop to <code>20 Mbps</code> at 8:00 PM right as device count jumped from <code>4</code> to <code>11 devices</code>. Clearly, a bunch of idiots decided to stream 4K movies all at once, or the ISP's mice were busy chewing on the fiber line again. Latency remained stable except for a brief spike to <code>95 ms</code> during the speed dip.

<b>Data Transfer (Latest Test)</b>
<pre>
Downloaded: 160.0 MB
Uploaded: 70.0 MB
</pre>

<b>Conclusion</b>
Expect periodic speed deaths whenever the local leechers wake up or the ISP fails to maintain their potato infrastructure.


CRITICAL RULES:
1. Do NOT use <br> or <br/> tags. For line breaks, use normal newlines.
2. The entire report must be in English.
3. Keep the "24-Hour Dynamics Analysis" to exactly 2-3 short sentences.
4. Do NOT write any description text below the "Data Transfer (Latest Test)" pre-block.
5. Keep the "Conclusion" to exactly 1 short sentence.
6. Highlight all numeric metric values in the text using <code>[Value]</code>.
7. Do NOT output any markdown blocks like ```html. Output raw HTML tags directly.
8. Make sure all HTML tags are closed correctly.
9. Be sarcastic, informal, and funny when describing performance dips or network load.
10. The entire output MUST be under 800 characters to ensure it easily fits within Telegram limits.
"""

REPORT_USER_TEMPLATE = """
Network speed test results:
- Date: {timestamp}
- Download: {download:.2f} Mbps
- Upload: {upload:.2f} Mbps
- Ping: {ping:.2f} ms
- Client: {client}
- Server: {server}
- Downloaded: {download_mb} MB
- Uploaded: {upload_mb} MB
- Share Link: {share}
- Devices online: {device_count}
"""

MINI_REPORT_TEMPLATE = """<b>Network Status Update</b>
Here is the latest snapshot of your internet speed:

Time: <b>{timestamp}</b>
ISP: <b>{client}</b> | Server: <b>{server}</b>

Devices online: <b>{device_count}</b>

Download: <b>{download:.1f} Mbps</b>
Upload: <b>{upload:.1f} Mbps</b>
Latency: <b>{ping:.1f} ms</b>

Traffic used: <b>{download_mb:.1f} MB</b> down / <b>{upload_mb:.1f} MB</b> up

<b>Current status:</b> {status_text}"""

SLEEP_TIME = 1800

log = logging.getLogger("netmon")


def sigterm_handler(signum, frame):
    log.info(f"Received termination signal: {signum}. Exiting gracefully.")
    sys.exit(0)


def _heartbeat_down_alert_message(conf: "cfg.Config") -> str:
    return (
        "<b>🔴 Connectivity heartbeat unreachable</b>\n\n"
        f"{conf.heartbeat_consecutive_failures} consecutive checks against "
        f"<code>{conf.heartbeat_host}:{conf.heartbeat_port}</code> have failed "
        "between full speed test cycles. This looks like the connection is "
        "down right now -- a full report will follow on the next scheduled cycle."
    )


def _heartbeat_recovered_alert_message(duration_seconds: float) -> str:
    minutes = int(duration_seconds // 60)
    if minutes < 60:
        duration_str = f"{minutes} min" if minutes > 0 else "under a minute"
    else:
        duration_str = f"{minutes // 60}h {minutes % 60}m"
    return f"<b>✅ Connectivity heartbeat recovered</b>\n\nReachable again after about {duration_str}."


def _wait_with_heartbeat(t: Notifier, r: runner.Runner, conf: "cfg.Config", heartbeat_state: dict, total_seconds: float):
    """
    Sleeps for total_seconds like the plain time.sleep() this replaces, but
    in heartbeat_interval_seconds chunks, doing a lightweight TCP-connect
    reachability check after each chunk. This exists to catch and alert on
    short outages that would otherwise resolve before the next full speed
    test cycle -- SLEEP_TIME can be 30+ minutes, but a real outage lasting
    a few minutes is exactly the kind of thing this tool should still
    notice. Deliberately single-threaded (no background thread) to match
    the rest of this codebase and avoid any concurrency concerns with the
    shared sqlite connection or notifier HTTP calls.
    """
    elapsed = 0.0
    while elapsed < total_seconds:
        chunk = min(conf.heartbeat_interval_seconds, total_seconds - elapsed)
        time.sleep(chunk)
        elapsed += chunk

        latency = r.ping_host(conf.heartbeat_host, conf.heartbeat_port)
        if latency is None:
            heartbeat_state["consecutive_failures"] += 1
            if heartbeat_state["down_since"] is None:
                heartbeat_state["down_since"] = datetime.now(timezone.utc)
            if (
                heartbeat_state["consecutive_failures"] >= conf.heartbeat_consecutive_failures
                and not heartbeat_state["alerted"]
            ):
                try:
                    t.send_message(_heartbeat_down_alert_message(conf))
                except Exception as notify_err:
                    log.error(f"Failed to send heartbeat-down alert: {notify_err}")
                heartbeat_state["alerted"] = True
        else:
            if heartbeat_state["alerted"]:
                duration_seconds = (datetime.now(timezone.utc) - heartbeat_state["down_since"]).total_seconds()
                try:
                    t.send_message(_heartbeat_recovered_alert_message(duration_seconds))
                except Exception as notify_err:
                    log.error(f"Failed to send heartbeat-recovered alert: {notify_err}")
            heartbeat_state["consecutive_failures"] = 0
            heartbeat_state["alerted"] = False
            heartbeat_state["down_since"] = None



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

    counter = 0

    # Connectivity heartbeat state, tracked across loop iterations.
    heartbeat_state = {
        "consecutive_failures": 0,
        "alerted": False,
        "down_since": None,
    }

    with (
        sqlite.DB.init(conf.db_path) as database,
        ai.Client.init(conf.ai_api_key, conf.model, conf.base_url) as netmon_ai,
    ):
        log.info("The bot has been started.")
        while True:
            t.send_chat_action(ChatAction.TYPING)

            metric = r.run_speedtest()
            all_devices = r.run_devices_scan()

            with database.transaction():
                database.add_metric(metric)
                device_scan_id = database.add_devices(all_devices)
                speedtest = models.SpeedTest.create(metric.id, device_scan_id)
                database.add_speedtest(speedtest)
            log.info(f"Speedtest has been added: {speedtest}")

            if counter >= 8: #send a detailed report with graph every 4 hours
                metrics, device_counts = database.get_metrics_with_device_counts()

                user_message = ""
                for m, device_count in zip(metrics, device_counts):
                    user_message += REPORT_USER_TEMPLATE.format(
                        timestamp=m.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                        download=round(m.download / 10**6, 1),
                        upload=round(m.upload / 10**6, 1),
                        ping=m.ping,
                        client=m.client,
                        server=m.server,
                        download_mb=round(m.bytes_received / 10**6, 1),
                        upload_mb=round(m.bytes_sent / 10**6, 1),
                        share=m.share,
                        device_count=device_count
                    ) + "\n"

                t.send_chat_action(ChatAction.TYPING)
                try:
                    report = netmon_ai.send_message(user_message, REPORT_SYSTEM_PROMPT)
                    report = report.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
                except Exception as e:
                    # AI backend down/unreachable/misconfigured: don't lose the
                    # whole report, just send the graph with a plain notice
                    # instead of a sarcastic AI-written one.
                    log.error(f"AI report generation failed, sending graph without commentary: {e}")
                    report = (
                        "<b>Network Speed Test Report (24h Analysis)</b>\n\n"
                        "<i>AI commentary unavailable this cycle — the AI backend "
                        "could not be reached. Raw graph data is attached below.</i>"
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

            _wait_with_heartbeat(t, r, conf, heartbeat_state, SLEEP_TIME)

if __name__ == "__main__":
    main()