import signal
import sys
import logging
import graphs
import config as cfg
import sqlite
import ai
import tg
import time
import models
import runner

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

SLEEP_TIME = 3600

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
    t = tg.Bot.init(conf.tg_bot_token, conf.tg_chat_id) 
    r = runner.Runner()

    counter = 0

    with (
        sqlite.DB.init(conf.db_path) as database,
        ai.Client.init(conf.ai_api_key, conf.model, conf.base_url) as netmon_ai,
    ):
        log.info("The bot has been started.")
        while True:

            t.send_chat_action(tg.ChatAction.TYPING)

            metric = r.run_speedtest()
            all_devices = r.run_devices_scan()

            with database.transaction():
                database.add_metric(metric)
                device_scan_id = database.add_devices(all_devices)
                speedtest = models.SpeedTest.create(metric.id, device_scan_id)
                database.add_speedtest(speedtest)
            log.info(f"Speedtest has been added: {speedtest}")

            if counter >= 4: #send a detailed report with graph every 4 hours
                metrics, device_counts = database.get_metrics_with_device_counts()

                user_message = ""
                for m, device_count in zip(metrics, device_counts):
                    user_message += REPORT_USER_TEMPLATE.format(
                        timestamp=m.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
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
        
                t.send_chat_action(tg.ChatAction.TYPING)
                report = netmon_ai.send_message(user_message, REPORT_SYSTEM_PROMPT)
                report = report.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")

                t.send_chat_action(tg.ChatAction.UPLOAD_PHOTO)
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
                    timestamp=metric.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
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
            
            counter +=1
            
            
            time.sleep(SLEEP_TIME)

if __name__ == "__main__":
    main()