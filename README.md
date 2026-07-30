<p align="center">
  <img src="assets/logo.png" alt="netmon logo" width="180" />
</p>

<h1 align="center">netmon</h1>

<p align="center">
  <b>Self-hosted local network monitor with 24-hour speed charts & sarcastic AI commentary delivered straight to Telegram or Discord.</b>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-8bc34a?style=for-the-badge" alt="License MIT"></a>
  <img src="https://img.shields.io/badge/Python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/uv-managed-DE5FE9?style=for-the-badge&logo=uv&logoColor=white" alt="uv">
  <img src="https://img.shields.io/badge/Telegram-Bot_API-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram">
  <img src="https://img.shields.io/badge/Discord-Webhook-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord">
  <img src="https://img.shields.io/badge/SQLite-Storage-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/Matplotlib-Graphs-11557c?style=for-the-badge" alt="Matplotlib">
</p>

---

A lightweight local bot that runs a speed test on your network every 30 minutes, scans active devices on your LAN using `nmap`, and logs everything to a local SQLite database.

Every 4 hours, it delivers a **detailed report** complete with a 24-hour trend graph and a sarcastic, LLM-generated commentary on your network's behavior (*"someone's hogging the bandwidth again"*).

> [!NOTE]
> **100% Private & Self-Hosted:** No external metric servers involved — everything runs locally on your machine or Raspberry Pi. Only text reports and graph images are dispatched to your chosen notifier (Telegram or Discord).

---

## Features & Workflow

Every 30 minutes (`SLEEP_TIME` in `main.py`, default 1800 seconds):

1. **Speed Test:** Measures download/upload speeds, ping latency, ISP, and test server details using `speedtest-cli` (see [the note on measurement mode](#a-note-on-measurement-mode)).
2. **LAN Scan:** Scans the local subnet using `nmap` ARP scan to identify active devices, including MAC address, vendor, and hostname where resolvable (see [Device Watch](#device-watch)).
3. **Local Storage:** Saves metrics & device details directly to a local `metrics.sql` SQLite database.
4. **Status Alert:** Sends a concise status update to your chosen notifier (*"all good"* or *"line is dying"*).
5. **24h AI Report:** Every 8th cycle (every 4h), generates a **24-hour trend graph** via `matplotlib` alongside a sarcastic LLM analysis of network load, speed fluctuations, and any notable new devices on the network.

---

## Tech Stack

| Technology | Purpose |
| :--- | :--- |
| **Python 3.13+** (via `uv`) | Core runtime |
| **SQLite** | Local metrics persistence (`metrics.sql`) |
| **`speedtest-cli`** | Network bandwidth and ping measurements |
| **`nmap`** | Subnet ARP scanning for device discovery |
| **`matplotlib`** | 24-hour metrics visualization |
| **OpenAI-compatible API** | Sarcastic report & trend analysis (cloud OpenAI or a local LLM) |
| **Telegram API / Discord Webhooks** | Alert and graph report delivery |

---

## Requirements

* **OS:** macOS or Linux (`nmap --iflist` required; Windows not supported out of the box).
* **[uv](https://docs.astral.sh/uv/)** — manages the Python version, virtualenv, and locked dependencies for you. No manual `python3`/`venv`/`pip` juggling.
* **System Binaries:** `nmap` and `speedtest-cli` installed system-wide.
* **Passwordless `sudo` for `nmap`** — device counting needs a real ARP scan (raw sockets), which requires root; see one-time setup below.
* **Tokens:** either a Telegram Bot Token + Chat ID, *or* a Discord Webhook URL (see [Notifications](#notifications-telegram-or-discord)), plus an API key for your OpenAI-compatible provider (not needed if you point `AI_BASE_URL` at a local LLM server).

---

## Quick Start

### 1. System Dependencies

**macOS (Homebrew):**
```bash
brew install nmap speedtest-cli
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt update && sudo apt install -y nmap speedtest-cli
```

### 2. Allow Passwordless `nmap` (one-time)

Device counting runs `nmap` as root for a real ARP scan — without it, host discovery silently falls back to ordinary TCP probing and undercounts devices that don't answer on common ports. Since the bot runs unattended, `sudo` needs to work without a password prompt on every cycle:

```bash
echo "$(whoami) ALL=(root) NOPASSWD: $(command -v nmap)" | sudo tee /etc/sudoers.d/netmon-nmap
sudo chmod 440 /etc/sudoers.d/netmon-nmap
```

This grants passwordless `sudo` only for the `nmap` binary — not your whole account.

### 3. Clone & Setup Environment

Install [`uv`](https://docs.astral.sh/uv/) if you don't have it yet:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then:

```bash
git clone https://github.com/Role1776/netmon.git
cd netmon
uv sync
```

`uv sync` downloads the pinned Python version (see `.python-version`) if you don't already have it, creates `.venv`, and installs the exact locked dependency versions from `uv.lock`. No system `python3`, no manual venv activation.

### 4. Configure `.env`

Copy the template file and fill in your secrets:

```bash
cp .env.example .env
```

`.env` variables:

| Variable | Description |
| :--- | :--- |
| `AI_API_KEY` | Your LLM provider API key (any string works for most local servers) |
| `AI_MODEL` | Model name (e.g. `gpt-4o-mini`, or a local model name — see below) |
| `AI_BASE_URL` | Base API URL (e.g., `https://api.openai.com/v1`, or your local server's URL) |
| `NOTIFIER` | `telegram` (default) or `discord` — picks which service receives alerts |
| `TG_BOT_TOKEN` | Telegram bot token from `@BotFather` — required if `NOTIFIER=telegram` |
| `TG_CHAT_ID` | Your Telegram Chat ID — required if `NOTIFIER=telegram` |
| `DISCORD_WEBHOOK_URL` | Discord channel webhook URL — required if `NOTIFIER=discord` |
| `DB_PATH` | SQLite database file path (e.g. `metrics.sql`) |
| `REQUEST_TIMEOUT` | *Optional.* HTTP timeout in seconds for Telegram/Discord requests (positive integer, default `30`) |

> [!TIP]
> **You're not locked into OpenAI.** `ai.py` talks to any OpenAI-compatible endpoint, so a local inference server (e.g. [Ollama](https://ollama.com), LM Studio) works too — just point `AI_BASE_URL` at it. For report quality that holds up, use a model with **at least ~7B parameters**; a solid local pick is **Gemma 4 12B at 4-bit (QAT) quantization** (`gemma4:12b-it-qat` via Ollama), which fits comfortably on 16GB of RAM.

### 5. Run the Bot

```bash
uv run main.py
```

`uv run` always uses this project's own `.venv` and pinned Python version, so it can't accidentally run against your system `python3`.

> [!TIP]
> Run the bot inside `tmux`/`screen` or set it up as a system service (`systemd`/`launchd`) to keep it running 24/7 in the background.

---

## Notifications: Telegram or Discord

netmon supports two notification backends, selected via the `NOTIFIER` variable in `.env`. Only one is needed.

### Telegram (default)

1. Message [`@BotFather`](https://t.me/botfather) on Telegram and send `/newbot`, following the prompts to get a **bot token**.
2. Get your **Chat ID** — the simplest way is to message your new bot, then visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and read the `chat.id` field from the JSON response.
3. In `.env`:
   ```
   NOTIFIER=telegram
   TG_BOT_TOKEN=123456789:AAHfoo...
   TG_CHAT_ID=987654321
   ```

If `NOTIFIER` is left unset, netmon defaults to Telegram, so existing setups keep working with no changes.

### Discord

1. In your target Discord channel: **Server Settings → Integrations → Webhooks → New Webhook**, then copy the webhook URL. No bot invite or permissions setup needed.
2. In `.env`:
   ```
   NOTIFIER=discord
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxx/yyyy
   ```

Discord delivery reuses the same report content as Telegram — the existing HTML formatting (`<b>`, `<code>`, `<pre>`) is automatically converted to Discord markdown, so reports render correctly in either service without any changes to the AI prompt.

> [!WARNING]
> Treat both the Telegram bot token and the Discord webhook URL as secrets — anyone with either can post messages through your bot/webhook. Don't commit them to version control (`.env` is already git-ignored).

---

## A Note on Measurement Mode

netmon runs `speedtest --secure --single --json` (see `runner.py`) — the `--single` flag means the test uses **one TCP connection**. This is deliberate: a single stream approximates what one real application on your network would actually get, since it is subject to the same window-size and packet-loss limits any ordinary download faces.

Multi-threaded speed tests (including Ookla's official CLI, and the speedtest.net web UI) open many parallel connections instead. That measures something different — the practical ceiling of your line — and will report noticeably higher numbers on fast connections. Neither figure is "wrong"; they answer different questions.

Two consequences worth knowing:

* **Don't compare netmon's numbers directly against speedtest.net in a browser.** The browser test is multi-threaded and will read higher. That gap is methodology, not a fault in your line.
* **On very fast links (roughly 500 Mbps+), expect single-stream figures to sit well below your subscribed speed.** Beyond the methodology gap, `speedtest-cli` is pure Python, so at gigabit speeds its own CPU overhead starts contributing too.

Since netmon exists to track *trends*, consistency matters more than peak numbers: keep one measurement method for the lifetime of your database. Swapping the backend mid-history puts a step change in your 24-hour graph that the AI commentary will faithfully report as a real speed jump.

### Jitter & Bufferbloat (Ookla backend only)

Classic `speedtest-cli` has no jitter or packet-loss data. If you instead run netmon against an Ookla-compatible speed test backend that reports those fields, netmon picks them up automatically and surfaces them in both mini and detailed reports, alongside a note from the AI treating high jitter or nonzero packet loss as a sign of bufferbloat — a connection can have great raw Mbps numbers and still feel laggy under load if jitter is high. This is entirely additive: nothing changes in reports if your backend doesn't provide this data.

---

## Device Watch

Every device scan records each device's MAC address, vendor (resolved from `nmap`'s built-in OUI database), and hostname where available. `nmap` can only resolve a MAC for hosts on the same local subnet it can ARP directly — off-subnet or otherwise hidden devices are still counted, just not identified.

Using MAC address history, the detailed AI report includes a **Device Watch** section that flags any device whose MAC hasn't been seen on the network in the last 14 days, alongside a vendor-count breakdown of everything currently online. A device with no resolvable MAC is never flagged as new, since there's no reliable identity to compare against.

---

## Example Output

### Hourly Short Status Update

```text
Network Status Update
Time: 2026-07-21 14:00:00
ISP: MyISP | Server: New York

Devices online: 7
Download: 145.2 Mbps
Upload: 62.1 Mbps
Latency: 14.8 ms

Traffic used: 160.0 MB down / 70.0 MB up

Current status: Good speed and low latency
```

### 4-Hour Detailed Report (With Graph & AI Analysis)

Every 4 hours, the bot sends a **24-hour matplotlib graph** accompanied by a sarcastic LLM-generated report:

<p align="center">
  <img src="assets/example_graph.png" alt="24h Network Speed Test Graph" width="650" />
</p>

```html
<b>Network Speed Test Report (24h Analysis)</b>

Client: <b>MyISP</b>
Server: <b>New York</b>

<b>Latest Test Metrics</b>
<pre>
Download: 178.5 Mbps
Upload: 45.2 Mbps
Ping: 23.1 ms
Jitter: 4.2 ms | Packet Loss: 0.0%
Devices Online: 9
</pre>

<b>24-Hour Dynamics Analysis</b>
Over the last 24 hours, the download speed averaged <code>140 Mbps</code>, but we saw a massive drop to <code>20 Mbps</code> at 8:00 PM right as device count jumped from <code>4</code> to <code>11 devices</code>. Clearly, someone's hogging the bandwidth or the ISP's mice were busy chewing on the fiber line again. Latency remained stable except for a brief spike during peak hours.

<b>Device Watch</b>
One new gadget joined the party today: a device with no vendor or hostname info at all — worth a second glance. Everything else is the same suspects as always.

<b>Data Transfer (Latest Test)</b>
<pre>
Downloaded: 160.0 MB
Uploaded: 70.0 MB
</pre>

<b>Conclusion</b>
Expect periodic speed drops whenever local freeloaders stream 4K movies or the ISP potato infrastructure struggles.
```

> [!NOTE]
> The AI is only ever asked for three short text fields (the dynamics analysis, the Device Watch line, and the conclusion) — the surrounding HTML structure above is assembled deterministically in code, not generated by the model. This keeps report formatting consistent regardless of which LLM is behind `AI_BASE_URL`, including smaller local models that would otherwise struggle to reproduce a long literal template reliably. The `Jitter` line only appears when your speed test backend reports it (see [Jitter & Bufferbloat](#jitter--bufferbloat-ookla-backend-only)) — it's silently omitted otherwise.

---

## Project Structure

```text
netmon/
├── assets/                        # Logo & documentation media assets
├── graphs/                        # Generated 24h matplotlib graph images
├── main.py                        # Main execution loop & orchestrator
├── runner.py                      # Speedtest-cli and nmap scan execution & parsing
├── sqlite.py                      # SQLite database operations & schema management
├── models.py                      # Domain data models (NetworkMetric, SpeedTest)
├── graphs.py                      # Matplotlib graph rendering engine
├── ai.py                          # OpenAI API client & sarcastic text generator
├── tg.py                          # Telegram bot dispatch helper
├── discord_hook.py                # Discord webhook dispatch helper
├── config.py                      # Environment variable validation & config
├── notifier.py                    # Notifier protocol & shared chat-action enum
├── pyproject.toml                 # Project metadata & dependencies
├── uv.lock                        # Locked, reproducible dependency versions
└── LICENSE                        # MIT License file
```

---

## License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more details.
