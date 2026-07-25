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
# This script installs Ookla's official CLI and wraps it so its output
# matches the JSON schema netmon expects (see runner.py's
# _SpeedTestResponse model), so no application code changes are needed.
#
# Unlike an apt-based install, this pulls Ookla's static binary tarball
# directly (https://www.speedtest.net/apps/cli) rather than adding
# Ookla's packagecloud apt repository. That avoids a real failure mode
# on non-mainstream distros/architectures (e.g. Armbian, Orange Pi):
# apt repos are keyed by distro codename + architecture, and Ookla's
# repo does not carry a build for every combination, so an apt-based
# install can fail partway through — after the keyring is already
# added — leaving the system in a half-configured state. A static
# binary has no such dependency: it either matches the machine's CPU
# architecture or it doesn't, and this script verifies that up front
# and makes no system changes at all if the download fails.
#
# Usage: sudo bash install-ookla-speedtest.sh
#        sudo OOKLA_VERSION=1.2.0 bash install-ookla-speedtest.sh   # pin a version

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root (sudo bash install-ookla-speedtest.sh)" >&2
    exit 1
fi

OOKLA_VERSION="${OOKLA_VERSION:-1.2.0}"

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)
        OOKLA_ARCH="x86_64" ;;
    aarch64|arm64)
        OOKLA_ARCH="aarch64" ;;
    armv7l|armv6l)
        OOKLA_ARCH="armhf" ;;
    i386|i686)
        OOKLA_ARCH="i386" ;;
    *)
        echo "Unsupported architecture: ${ARCH}." >&2
        echo "Ookla does not publish a static Linux build for this platform;" >&2
        echo "stick with the default speedtest-cli backend on this machine." >&2
        exit 1
        ;;
esac

URL="https://install.speedtest.net/app/cli/ookla-speedtest-${OOKLA_VERSION}-linux-${OOKLA_ARCH}.tgz"

TMPDIR="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}"' EXIT

echo "==> Downloading Ookla speedtest CLI ${OOKLA_VERSION} for ${OOKLA_ARCH}"
if ! curl -fsSL "${URL}" -o "${TMPDIR}/ookla-speedtest.tgz"; then
    echo "Failed to download: ${URL}" >&2
    echo "No system changes have been made." >&2
    echo "This usually means either version ${OOKLA_VERSION} is no longer current," >&2
    echo "or there's no network route to install.speedtest.net from this machine." >&2
    echo "Check https://www.speedtest.net/apps/cli for the current version and" >&2
    echo "re-run as: sudo OOKLA_VERSION=<version> bash install-ookla-speedtest.sh" >&2
    exit 1
fi

echo "==> Extracting"
tar -xzf "${TMPDIR}/ookla-speedtest.tgz" -C "${TMPDIR}"

if [ ! -f "${TMPDIR}/speedtest" ]; then
    echo "Downloaded archive did not contain a 'speedtest' binary as expected." >&2
    echo "No system changes have been made." >&2
    exit 1
fi

echo "==> Installing binary as /usr/bin/speedtest-ookla"
install -m 755 "${TMPDIR}/speedtest" /usr/bin/speedtest-ookla

echo "==> Accepting Ookla license/GDPR terms (required once for unattended runs)"
/usr/bin/speedtest-ookla --accept-license --accept-gdpr >/dev/null

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
echo
echo "Note: this installed /usr/bin/speedtest directly rather than via a package"
echo "manager, so it isn't tracked by apt/dpkg. A future 'apt install speedtest-cli'"
echo "or similar would overwrite it — if that happens, just re-run this script."
