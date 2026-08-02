# Netmon Linux installation

This guide installs Netmon on a normal Debian or Ubuntu Linux system.

Proxmox is not required.

## 1. Recommended resources

A small system is sufficient:

- 1–2 CPU cores
- 1 GB RAM
- 4 GB or more available storage
- a bridged or ordinary LAN interface

The speed-test process may temporarily use additional memory and CPU.

## 2. Install operating-system packages

```bash
sudo apt update

sudo apt install -y \
    ca-certificates \
    curl \
    fontconfig \
    fonts-dejavu-core \
    git \
    nmap \
    speedtest-cli \
    sudo \
    tzdata
```

Confirm that the expected speed-test command exists:

```bash
command -v speedtest || command -v speedtest-cli
```

When the distribution installs only `speedtest-cli`, create a compatibility
link if required:

```bash
sudo ln -s "$(command -v speedtest-cli)" /usr/local/bin/speedtest
```

## 3. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh |
    sudo env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
```

Verify it:

```bash
/usr/local/bin/uv --version
```

## 4. Create the service account

```bash
sudo useradd \
    --system \
    --user-group \
    --home-dir /var/lib/netmon \
    --create-home \
    --shell /usr/sbin/nologin \
    netmon
```

Create writable runtime directories:

```bash
sudo install -d -o netmon -g netmon -m 0750 /var/lib/netmon
sudo install -d -o netmon -g netmon -m 0750 /var/lib/netmon/.cache
sudo install -d -o netmon -g netmon -m 0750 /var/lib/netmon/.cache/matplotlib
sudo install -d -o netmon -g netmon -m 0750 /var/lib/netmon/.cache/pycache
```

## 5. Clone and install Netmon

Clone the repository:

```bash
sudo git clone https://github.com/davem1980/netmon.git /opt/netmon
```

While this work remains on its feature branch, select it explicitly:

```bash
sudo git -C /opt/netmon checkout feature/local-web-dashboard
```

Install the locked runtime environment:

```bash
sudo chown -R netmon:netmon /opt/netmon

sudo -u netmon env \
    HOME=/var/lib/netmon \
    UV_CACHE_DIR=/var/lib/netmon/.cache/uv \
    /usr/local/bin/uv sync \
        --project /opt/netmon \
        --frozen \
        --no-dev
```

The source may then be made read-only to the service account:

```bash
sudo chown -R root:root /opt/netmon
sudo install -d -o netmon -g netmon -m 0750 /opt/netmon/graphs
```

## 6. Permit the LAN scan

Netmon uses an `nmap` discovery scan requiring raw-network access.

Grant the service account passwordless access only to the `nmap` executable:

```bash
echo 'netmon ALL=(root) NOPASSWD: /usr/bin/nmap' |
    sudo tee /etc/sudoers.d/netmon-nmap >/dev/null

sudo chmod 0440 /etc/sudoers.d/netmon-nmap
sudo visudo -cf /etc/sudoers.d/netmon-nmap
```

This does not grant unrestricted passwordless sudo.

## 7. Install the public configuration

Create the configuration directory:

```bash
sudo install -d -o root -g netmon -m 0750 /etc/netmon
```

Copy the example:

```bash
sudo cp /opt/netmon/.env.example /etc/netmon/netmon.env
sudo chown root:netmon /etc/netmon/netmon.env
sudo chmod 0640 /etc/netmon/netmon.env
```

Review the file:

```bash
sudo nano /etc/netmon/netmon.env
```

The database should normally remain outside the repository:

```text
DB_PATH=/var/lib/netmon/metrics.sql
```

Remote AI can remain disabled. No API key is required for ordinary monitoring.

## 8. Install the systemd services

```bash
sudo cp \
    /opt/netmon/deploy/systemd/netmon-collector.service \
    /etc/systemd/system/

sudo cp \
    /opt/netmon/deploy/systemd/netmon-web.service \
    /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now netmon-collector.service
sudo systemctl enable --now netmon-web.service
```

## 9. Verify operation

Check both services:

```bash
sudo systemctl status netmon-collector.service --no-pager
sudo systemctl status netmon-web.service --no-pager
```

Test the health endpoint locally:

```bash
curl http://127.0.0.1:8000/healthz
```

Expected response:

```json
{"status":"ok"}
```

## 10. Create the administrator password

Open the dashboard from another machine on the LAN:

```text
http://NETMON_HOST_IP:8000
```

The first page requires creation and confirmation of an administrator password.

There is no default password.

## 11. HTTPS and remote access

The direct dashboard listens over HTTP.

For use beyond a trusted private LAN, place Netmon behind an HTTPS reverse
proxy. Do not forward port 8000 directly from the internet.

## 12. Updating

Stop the services:

```bash
sudo systemctl stop netmon-collector.service netmon-web.service
```

Update the checkout and dependencies:

```bash
sudo git -C /opt/netmon pull
sudo chown -R netmon:netmon /opt/netmon

sudo -u netmon env \
    HOME=/var/lib/netmon \
    UV_CACHE_DIR=/var/lib/netmon/.cache/uv \
    /usr/local/bin/uv sync \
        --project /opt/netmon \
        --frozen \
        --no-dev

sudo chown -R root:root /opt/netmon
sudo install -d -o netmon -g netmon -m 0750 /opt/netmon/graphs
```

Restart:

```bash
sudo systemctl start netmon-collector.service netmon-web.service
```
