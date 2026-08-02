<p align="center">
  <img src="assets/logo.png" alt="Netmon logo" width="180">
</p>

<h1 align="center">Netmon</h1>

<p align="center">
  <strong>
    A private, self-hosted Linux network monitor with an authenticated local
    web dashboard, speed history, LAN-device discovery and optional remote-AI
    analysis.
  </strong>
</p>

## About this fork

This fork replaces the original Telegram and Discord notification design with
a fully local web interface.

Monitoring data, graphs, chat history and configuration remain on the Netmon
host. Telegram and Discord are not required.

Proxmox is not required. Netmon can run on an ordinary Debian or Ubuntu
machine, a virtual machine, a compatible Linux container, or a Raspberry
Pi-class system.

## Main features

- Scheduled internet speed tests
- Manual **Run test now** control
- LAN host discovery using `nmap`
- SQLite measurement history
- Current download, upload, latency and device-count cards
- Historical graphs and detailed reports
- Local deterministic data-question support
- Optional OpenAI-compatible remote AI
- Optional Groq configuration through the protected interface
- First-run administrator password setup
- Salted password hashing
- Authenticated dashboard and API
- CSRF protection for state-changing requests
- Server-side API-key storage
- Separate collector and web services
- No Telegram or Discord dependency

## Privacy model

By default, Netmon operates locally:

- measurements are written to a local SQLite database;
- the dashboard is served from the Netmon machine;
- remote AI starts disabled;
- no AI API key is required;
- no information is sent to Telegram or Discord.

When optional remote AI is enabled, Netmon sends the question and relevant
measurement context to the configured OpenAI-compatible provider. Stored API
keys are never returned to the browser.

## Platform requirements

Netmon currently targets Linux.

A typical installation requires:

- Debian or Ubuntu Linux
- `nmap`
- `speedtest-cli`
- `sudo`
- `uv`
- Python selected by `.python-version`
- systemd for the supplied service examples

The application is not tied to Proxmox. Proxmox LXC was simply one deployment
environment used during development.

## Architecture

Netmon runs as two independent processes.

### `netmon-collector`

Runs internet speed tests and LAN scans, then stores the resulting measurements
in SQLite.

### `netmon-web`

Serves the authenticated dashboard, graph, local data chat, manual-test control
and optional remote-AI settings.

Keeping these processes separate means restarting the web interface does not
stop scheduled monitoring.

## Installation

See [`docs/INSTALL-LINUX.md`](docs/INSTALL-LINUX.md).

Generic systemd unit examples are supplied under `deploy/systemd/`.

## First run

After installation, open:

```text
http://NETMON_HOST:8000
```

The first page requires creation and confirmation of an administrator password.
No default password is supplied.

Remote AI remains disabled and no API key is required.

## Security

The built-in server is suitable for a trusted private LAN.

The default direct connection uses HTTP. For remote access or use across an
untrusted network, place Netmon behind an HTTPS reverse proxy and suitable
access controls.

Do not expose port 8000 directly to the public internet.

## Optional remote AI

Remote AI is optional and switchable.

With remote AI disabled, monitoring, graphs, reports and recognised local data
questions continue to work normally.

The protected settings interface supports:

- entering and testing an API key;
- showing only **API key active** after successful storage;
- replacing or removing the key;
- enabling or disabling remote AI;
- testing the active connection.

Netmon uses an OpenAI-compatible API interface, so it can work with providers
such as Groq or a compatible local inference server.

## Repository layout

```text
netmon/
├── collector.py                  Measurement collector service
├── web.py                        Authenticated web application
├── reporting.py                  Local reports and deterministic answers
├── secure_settings.py            Password and private-setting storage
├── ai.py                         Optional OpenAI-compatible AI client
├── sqlite.py                     SQLite persistence
├── runner.py                     Speedtest and nmap execution
├── graphs.py                     Historical graph generation
├── templates/                    HTML templates
├── static/                       Browser JavaScript and CSS
├── deploy/systemd/               Generic systemd examples
├── docs/INSTALL-LINUX.md         Generic Linux installation guide
├── pyproject.toml                Python project definition
└── uv.lock                       Locked dependencies
```

## Development

Install all dependencies, including the development group:

```bash
uv sync
```

Run lint checks:

```bash
uv run ruff check .
```

Run the dashboard manually:

```bash
uv run web.py --env .env
```

Run the collector manually:

```bash
uv run collector.py --env .env
```

## License

Distributed under the MIT License. See `LICENSE`.
