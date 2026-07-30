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


def _device_label(device: dict) -> str:
    if device.get("hostname"):
        return device["hostname"]
    if device.get("vendor"):
        return f"{device['vendor']} device"
    return device["mac"]


def _device_missing_alert_message(device: dict, conf: "cfg.Config") -> str:
    label = _device_label(device)
    return (
        "<b>🔌 Device went missing</b>\n\n"
        f"<code>{label}</code> ({device['mac']}) hasn't been seen for "
        f"{conf.device_missing_consecutive_readings} consecutive checks, "
        f"despite being reliably online otherwise. Could be powered off, "
        "rebooting, or actually gone."
    )


def _device_reappeared_alert_message(device: dict, duration_seconds: float) -> str:
    label = _device_label(device)
    minutes = int(duration_seconds // 60)
    if minutes < 60:
        duration_str = f"{minutes} min" if minutes > 0 else "under a minute"
    else:
        duration_str = f"{minutes // 60}h {minutes % 60}m"
    return f"<b>✅ Device is back</b>\n\n<code>{label}</code> reappeared after about {duration_str}."


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

    counter = 0

    # Per-MAC missing-device alerting state -- the counterpart to the
    # new-device novelty check. Keyed by MAC; each entry tracks how many
    # consecutive cycles it's been missing, whether an alert has already
    # fired for this episode (so we don't spam every cycle), and when it
    # was first noticed missing (to report a duration on reappearance).
    missing_device_state: dict[str, dict] = {}

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

            missing_now = database.get_missing_devices(
                conf.device_missing_lookback_days, conf.device_missing_reliability
            )
            missing_now_macs = {d["mac"] for d in missing_now}

            for device in missing_now:
                mac = device["mac"]
                state = missing_device_state.setdefault(mac, {
                    "consecutive_missing": 0,
                    "alerted": False,
                    "missing_since": None,
                    "vendor": device["vendor"],
                    "hostname": device["hostname"],
                })
                state["consecutive_missing"] += 1
                if state["missing_since"] is None:
                    state["missing_since"] = datetime.now(timezone.utc)
                if state["consecutive_missing"] >= conf.device_missing_consecutive_readings and not state["alerted"]:
                    try:
                        t.send_message(_device_missing_alert_message(device, conf))
                    except Exception as notify_err:
                        log.error(f"Failed to send device-missing alert: {notify_err}")
                    state["alerted"] = True

            for mac in list(missing_device_state.keys()):
                if mac in missing_now_macs:
                    continue
                state = missing_device_state.pop(mac)
                if state["alerted"]:
                    duration_seconds = (datetime.now(timezone.utc) - state["missing_since"]).total_seconds()
                    try:
                        t.send_message(_device_reappeared_alert_message(
                            {"mac": mac, "vendor": state["vendor"], "hostname": state["hostname"]},
                            duration_seconds,
                        ))
                    except Exception as notify_err:
                        log.error(f"Failed to send device-reappeared alert: {notify_err}")

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

            time.sleep(SLEEP_TIME)

if __name__ == "__main__":
    main()