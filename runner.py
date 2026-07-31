import re
import subprocess
import xml.etree.ElementTree as ET
import models
from typing import Optional
from pydantic import BaseModel, field_validator
from datetime import datetime

_ETHERNET_SUBNET_RE = re.compile(r"(\d+\.\d+\.\d+\.\d+/\d+)\s+ethernet\s+up")


class _ServerInfo(BaseModel):
    url: str
    lat: str
    lon: str
    name: str
    country: str
    cc: str
    sponsor: str
    id: str
    host: str
    d: float
    latency: float

class _ClientInfo(BaseModel):
    ip: str
    lat: str
    lon: str
    isp: str
    isprating: str
    rating: str
    ispdlavg: str
    ispulavg: str
    loggedin: str
    country: str


class _SpeedTestResponse(BaseModel):
    download: float
    upload: float
    ping: float
    server: _ServerInfo
    timestamp: datetime
    bytes_sent: int
    bytes_received: int
    share: Optional[str]
    client: _ClientInfo

    @field_validator('timestamp', mode='before')
    @classmethod
    def parse_timestamp(cls, v: str) -> str:
        if v.endswith('Z') and ('+' in v or '-' in v[10:]):
            return v[:-1]
        return v



class Runner:
    def run_speedtest(self) -> models.NetworkMetric:
        args = ["speedtest", "--secure", "--single", "--json"]

        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Speedtest failed (code {result.returncode}): {result.stderr or result.stdout}")
        
        parsed_result = _SpeedTestResponse.model_validate_json(result.stdout)
        return models.NetworkMetric.create(
            download=parsed_result.download,
            upload=parsed_result.upload,
            ping=parsed_result.ping if parsed_result.ping < 1000 else 0, # if ping is too high, set it to 0
            share=parsed_result.share or "N/A", # if share is None, set it to "N/A"
            client=parsed_result.client.isp,
            server=parsed_result.server.name,
            bytes_sent=parsed_result.bytes_sent,
            bytes_received=parsed_result.bytes_received
        )

    @staticmethod
    def _parse_device(host: ET.Element) -> models.NetworkDevice | None:
        status = host.find("status")
        if status is None or status.get("state") != "up":
            return None

        ip: str | None = None
        mac: str | None = None
        vendor: str | None = None
        for addr in host.findall("address"):
            addrtype = addr.get("addrtype")
            if addrtype == "ipv4":
                ip = addr.get("addr")
            elif addrtype == "mac":
                # nmap only reports a MAC (and resolves vendor from its
                # built-in OUI database) for hosts on the same local subnet
                # it can ARP directly — this needs no extra scan flags,
                # since the existing sudo ARP scan already returns it.
                mac = addr.get("addr")
                vendor = addr.get("vendor") or None

        if not ip:
            return None

        hostname: str | None = None
        hostnames_el = host.find("hostnames")
        if hostnames_el is not None:
            hostname_el = hostnames_el.find("hostname")
            if hostname_el is not None:
                hostname = hostname_el.get("name") or None

        times  = host.find("times")
        srtt   = times.get("srtt") if times is not None else None
        latency_ms = round(int(srtt) / 1000, 2) if srtt is not None else 0

        return models.NetworkDevice.create(
            ip=ip,
            latency_ms=latency_ms,
            mac=mac,
            vendor=vendor,
            hostname=hostname,
        )

    def run_devices_scan(self) -> list[models.NetworkDevice]:
        iflist = subprocess.check_output("nmap --iflist", shell=True, text=True)
        match = _ETHERNET_SUBNET_RE.search(iflist)
        if match is None:
            raise RuntimeError("No active ethernet interface found via nmap --iflist")

        subnet = match.group(1)
        result = subprocess.run(
            ["sudo", "-n", "nmap", "-sn", "-oX", "-", subnet],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Device scan failed (code {result.returncode}): {result.stderr or result.stdout}. "
                "This scan needs passwordless sudo for nmap (raw-socket ARP access) - see README setup instructions."
            )
        xml_out = result.stdout

        devices = [
            d for host in ET.fromstring(xml_out).findall("host")
            if (d := self._parse_device(host)) is not None
        ]

        return devices
