#!/usr/bin/env bash
#
# install-ookla-speedtest.sh
#
# netmon calls a "speedtest" binary and parses its --json output. The
# classic Python "speedtest-cli" (sivel/speedtest-cli) tool is single
# threaded and, on fast connections (roughly 500 Mbps+), the read/write
# loop and TLS overhead become the bottleneck rather than your actual
# line speed. On multi-gigabit connections this can under-report your
# real throughput by 5-10x.
#
# This script installs Ookla's official CLI (multi-threaded, written in
# Go, built for gigabit+ links) and wraps it so its output matches the
# JSON schema netmon expects (see runner.py's _SpeedTestResponse model),
# so no application code changes are needed.
#
# Usage: sudo bash install-ookla-speedtest.sh

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root (sudo bash install-ookla-speedtest.sh)" >&2
    exit 1
fi

echo "==> Removing legacy speedtest-cli (if installed) to avoid file conflicts"
apt remove -y speedtest-cli >/dev/null 2>&1 || true
rm -f /usr/local/bin/speedtest

echo "==> Adding Ookla's official apt repository"
curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash

echo "==> Installing Ookla speedtest CLI"
apt install -y speedtest

echo "==> Renaming Ookla binary to avoid clashing with the wrapper"
mv -f /usr/bin/speedtest /usr/bin/speedtest-ookla

echo "==> Accepting Ookla license/GDPR terms (required once for unattended runs)"
speedtest-ookla --accept-license --accept-gdpr >/dev/null

echo "==> Installing JSON-compatibility wrapper at /usr/bin/speedtest"
cat > /usr/bin/speedtest << 'WRAPPER'
#!/usr/bin/env python3
"""
Wraps Ookla's official speedtest CLI and re-emits its result in the
legacy speedtest-cli JSON schema that netmon's runner.py expects.
"""
import json
import subprocess
import sys

raw = subprocess.run(
    ["speedtest-ookla", "--accept-license", "--accept-gdpr", "--format=json"],
    capture_output=True, text=True
)
if raw.returncode != 0:
    sys.stderr.write(raw.stderr)
    sys.exit(raw.returncode)

d = json.loads(raw.stdout)

out = {
    "download": d["download"]["bandwidth"] * 8,   # bytes/s -> bits/s
    "upload": d["upload"]["bandwidth"] * 8,
    "ping": d["ping"]["latency"],
    "timestamp": d["timestamp"],
    "bytes_sent": d["upload"]["bytes"],
    "bytes_received": d["download"]["bytes"],
    "share": d.get("result", {}).get("url"),
    "server": {
        "url": d["server"].get("host", ""),
        "lat": "0", "lon": "0",
        "name": d["server"].get("name", ""),
        "country": d["server"].get("country", ""),
        "cc": d["server"].get("country", "")[:2],
        "sponsor": d["server"].get("name", ""),
        "id": str(d["server"].get("id", "")),
        "host": d["server"].get("host", ""),
        "d": 0.0,
        "latency": d["ping"]["latency"],
    },
    "client": {
        "ip": d.get("interface", {}).get("externalIp", ""),
        "lat": "0", "lon": "0",
        "isp": d.get("isp", ""),
        "isprating": "0", "rating": "0",
        "ispdlavg": "0", "ispulavg": "0",
        "loggedin": "0",
        "country": d["server"].get("country", ""),
    },
}
print(json.dumps(out))
WRAPPER
chmod +x /usr/bin/speedtest

echo "==> Verifying install"
speedtest --secure --single --json | python3 -m json.tool

echo
echo "Done. netmon's existing 'speedtest --secure --single --json' call will"
echo "now be served by Ookla's CLI under the hood, without any Python code changes."
