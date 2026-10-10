import json
import subprocess
import xml.etree.ElementTree as ET

import pydantic
import pytest

import runner

SPEEDTEST_CMD = ["speedtest", "--secure", "--single", "--json"]


@pytest.fixture
def proc(monkeypatch):
    class Proc:
        def __init__(self):
            self.run_calls: list[list[str]] = []
            self.shell_calls: list[str] = []
            self.result = subprocess.CompletedProcess([], 0, "", "")
            self.iflist = ""

        def run(self, args, **kwargs):
            self.run_calls.append(args)
            return self.result

        def check_output(self, cmd, **kwargs):
            self.shell_calls.append(cmd)
            return self.iflist

    p = Proc()
    monkeypatch.setattr(subprocess, "run", p.run)
    monkeypatch.setattr(subprocess, "check_output", p.check_output)
    return p


@pytest.fixture
def speedtest(proc, fixture_text):
    proc.result = subprocess.CompletedProcess([], 0, fixture_text("speedtest.json"), "")
    return proc


def with_output(proc, **overrides):
    data = json.loads(proc.result.stdout) | overrides
    proc.result = subprocess.CompletedProcess([], 0, json.dumps(data), "")


def test_speedtest_parses_cli_json(speedtest):
    m = runner.Runner().run_speedtest()
    assert (m.download, m.upload, m.ping) == (93842310.52, 21457893.11, 14.327)
    assert (m.client, m.server) == ("Example Telecom", "Berlin")
    assert (m.bytes_sent, m.bytes_received) == (26870784, 118161192)
    assert speedtest.run_calls == [SPEEDTEST_CMD]


def test_speedtest_missing_share_becomes_na(speedtest):
    assert runner.Runner().run_speedtest().share == "N/A"


def test_speedtest_share_url_is_kept(speedtest):
    with_output(speedtest, share="http://www.speedtest.net/result/123.png")
    assert runner.Runner().run_speedtest().share == "http://www.speedtest.net/result/123.png"


@pytest.mark.parametrize("ping,expected", [(0, 0), (999.9, 999.9), (1000, 0), (25000.5, 0)])
def test_speedtest_implausible_ping_is_zeroed(speedtest, ping, expected):
    with_output(speedtest, ping=ping)
    assert runner.Runner().run_speedtest().ping == expected


@pytest.mark.parametrize("stderr,stdout", [("boom", ""), ("", "ERROR: cannot retrieve config")])
def test_speedtest_nonzero_exit_raises(proc, stderr, stdout):
    proc.result = subprocess.CompletedProcess([], 1, stdout, stderr)
    with pytest.raises(RuntimeError):
        runner.Runner().run_speedtest()


@pytest.mark.parametrize("stdout", ["", "not json", "{}", "[]"])
def test_speedtest_unparsable_output_raises(proc, stdout):
    proc.result = subprocess.CompletedProcess([], 0, stdout, "")
    with pytest.raises(pydantic.ValidationError):
        runner.Runner().run_speedtest()


@pytest.mark.parametrize("field", ["download", "upload", "ping", "server", "client", "bytes_sent", "bytes_received"])
def test_speedtest_missing_field_raises(speedtest, field):
    data = json.loads(speedtest.result.stdout)
    del data[field]
    speedtest.result = subprocess.CompletedProcess([], 0, json.dumps(data), "")
    with pytest.raises(pydantic.ValidationError):
        runner.Runner().run_speedtest()


def test_speedtest_negative_value_raises_value_error(speedtest):
    with_output(speedtest, download=-1)
    with pytest.raises(ValueError):
        runner.Runner().run_speedtest()


@pytest.fixture
def scan(proc, fixture_text):
    proc.iflist = fixture_text("nmap_iflist.txt")
    proc.result = subprocess.CompletedProcess([], 0, fixture_text("nmap_scan.xml"), "")
    return proc


def test_scan_returns_only_up_hosts_with_ipv4_and_latency(scan):
    devices = runner.Runner().run_devices_scan()
    assert [(d.ip, d.latency_ms) for d in devices] == [
        ("192.168.1.1", 2.35), ("192.168.1.77", 120.46), ("192.168.1.23", 0)]


def test_scan_runs_nmap_iflist_then_sudo_nmap_on_ethernet_subnet(scan):
    runner.Runner().run_devices_scan()
    assert scan.shell_calls == ["nmap --iflist"]
    assert scan.run_calls == [["sudo", "-n", "nmap", "-sn", "-oX", "-", "192.168.1.23/24"]]


def test_scan_without_hosts_returns_empty_list(scan, fixture_text):
    scan.result = subprocess.CompletedProcess([], 0, fixture_text("nmap_scan_empty.xml"), "")
    assert runner.Runner().run_devices_scan() == []


def test_scan_without_active_ethernet_interface_raises(scan, fixture_text):
    scan.iflist = fixture_text("nmap_iflist_no_ethernet.txt")
    with pytest.raises(RuntimeError):
        runner.Runner().run_devices_scan()
    assert scan.run_calls == []


def test_scan_nonzero_exit_raises(scan):
    scan.result = subprocess.CompletedProcess([], 1, "", "sudo: a password is required")
    with pytest.raises(RuntimeError):
        runner.Runner().run_devices_scan()


def test_scan_malformed_xml_raises(scan):
    scan.result = subprocess.CompletedProcess([], 0, "<nmaprun><host>", "")
    with pytest.raises(ET.ParseError):
        runner.Runner().run_devices_scan()


@pytest.mark.parametrize("host,expected", [
    ('<host><status state="up"/><address addr="10.0.0.2"/><times srtt="1500"/></host>', ("10.0.0.2", 1.5)),
    ('<host><status state="up"/><address addr="10.0.0.2"/><times srtt="0"/></host>', ("10.0.0.2", 0)),
    ('<host><status state="up"/><address addr="10.0.0.2"/></host>', ("10.0.0.2", 0)),
    ('<host><status state="up"/><address addr="10.0.0.2"/><times/></host>', ("10.0.0.2", 0)),
    ('<host><status state="down"/><address addr="10.0.0.2"/><times srtt="1500"/></host>', None),
    ('<host><status state="unknown"/><address addr="10.0.0.2"/></host>', None),
    ('<host><address addr="10.0.0.2"/></host>', None),
    ('<host><status state="up"/></host>', None),
])
def test_scan_parses_single_host(host, expected, scan):
    scan.result = subprocess.CompletedProcess([], 0, f"<nmaprun>{host}</nmaprun>", "")
    devices = runner.Runner().run_devices_scan()
    assert [(d.ip, d.latency_ms) for d in devices] == ([] if expected is None else [expected])
