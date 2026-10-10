"""Characterization tests for the main loop: they drive the real main.main()
and pin what it does today, bugs included. Expected values were observed from
the current behavior, not derived from a spec."""
import json
import sqlite3
import subprocess
import sys
import time

import pytest
import requests

import ai
import main

SLEEP_TIME = 1800
RETRY_DELAY = 60

STATUS_GOOD = "Good speed and low latency"
STATUS_BAD = ("A bunch of idiots decided to stream 4K movies all at once, "
              "or the ISP's mice were busy chewing on the fiber line again, whatever")
STATUS_MIDDLE = "At least it works, I guess"

FALLBACK_CAPTION = (
    "<b>Network Speed Test Report (24h Analysis)</b>\n\n"
    "<i>AI commentary unavailable this cycle — the AI backend "
    "could not be reached. Raw graph data is attached below.</i>"
)


class _Stop(Exception):
    pass


class Harness:
    def __init__(self, monkeypatch, tmp_path, http, fixture_text):
        self.http = http
        self.db_path = tmp_path / "metrics.db"
        self.sleeps: list[int] = []
        self.speedtest_calls = 0
        self.nmap_calls = 0
        self.ai_calls: list[list[dict]] = []
        # Consumed one per speedtest invocation: "fail" or a dict of JSON overrides.
        self.speedtests: list = []
        self.ai_reply: str | Exception = "<b>AI report</b>"
        self.loop_iterations = 0
        self._speedtest_json = json.loads(fixture_text("speedtest.json"))
        self._iflist = fixture_text("nmap_iflist.txt")
        self._nmap_xml = fixture_text("nmap_scan.xml")

        monkeypatch.chdir(tmp_path)  # graphs/ and any .env lookups land here
        monkeypatch.setattr(sys, "argv", ["main"])
        for var in ("NOTIFIER", "DISCORD_WEBHOOK_URL", "REQUEST_TIMEOUT"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("AI_API_KEY", "key")
        monkeypatch.setenv("AI_MODEL", "model")
        monkeypatch.setenv("AI_BASE_URL", "http://ai.invalid/v1")
        monkeypatch.setenv("DB_PATH", str(self.db_path))
        monkeypatch.setenv("TG_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TG_CHAT_ID", "42")

        # main() installs process-wide signal handlers; keep pytest's own.
        monkeypatch.setattr("signal.signal", lambda *a: None)
        monkeypatch.setattr(time, "sleep", self._sleep)
        monkeypatch.setattr(subprocess, "run", self._run)
        monkeypatch.setattr(subprocess, "check_output", lambda cmd, **kw: self._iflist)
        monkeypatch.setattr(ai, "OpenAI", self._openai)

    # --- fakes at process boundaries ---

    def _sleep(self, seconds):
        self.sleeps.append(seconds)
        if seconds == SLEEP_TIME and self.sleeps.count(SLEEP_TIME) >= self.loop_iterations:
            raise _Stop

    def _run(self, args, **kwargs):
        if args[0] == "speedtest":
            self.speedtest_calls += 1
            item = self.speedtests.pop(0) if self.speedtests else {}
            if item == "fail":
                return subprocess.CompletedProcess(args, 1, "", "speedtest boom")
            return subprocess.CompletedProcess(args, 0, json.dumps(self._speedtest_json | item), "")
        assert args[:3] == ["sudo", "-n", "nmap"], args
        self.nmap_calls += 1
        return subprocess.CompletedProcess(args, 0, self._nmap_xml, "")

    def _openai(self, **kwargs):
        harness = self

        class Completions:
            def create(self, model, messages):
                harness.ai_calls.append(messages)
                if isinstance(harness.ai_reply, Exception):
                    raise harness.ai_reply
                message = type("M", (), {"content": harness.ai_reply})()
                return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

        class Chat:
            completions = Completions()

        class Conn:
            chat = Chat()

            def close(self):
                pass

        return Conn()

    # --- driving and observing ---

    def run(self, iterations: int):
        self.loop_iterations = iterations
        with pytest.raises(_Stop):
            main.main()

    def sent(self) -> list[tuple[str, dict]]:
        """Notifier calls other than chat actions, as (method, kwargs)."""
        out = []
        for url, kwargs in self.http.calls:
            method = url.rsplit("/", 1)[1]
            if method != "sendChatAction":
                out.append((method, kwargs))
        return out

    def kinds(self) -> list[str]:
        return [m for m, _ in self.sent()]

    def chat_actions(self) -> list[str]:
        return [str(kw["data"]["action"]) for url, kw in self.http.calls if url.endswith("/sendChatAction")]

    def rows(self, table: str) -> list[tuple]:
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(f"SELECT * FROM {table}").fetchall()
        finally:
            conn.close()


@pytest.fixture
def loop(monkeypatch, tmp_path, http, fixture_text):
    return Harness(monkeypatch, tmp_path, http, fixture_text)


def test_detailed_report_every_eighth_cycle_after_first_eight_minis(loop):
    loop.run(17)

    assert loop.kinds() == (["sendMessage"] * 8 + ["sendPhoto"] + ["sendMessage"] * 7 + ["sendPhoto"])
    assert loop.sleeps == [SLEEP_TIME] * 17
    assert len(loop.rows("metrics")) == 17
    assert len(loop.rows("device_scans")) == 17
    assert len(loop.rows("speedtest")) == 17
    # The AI is only consulted for detailed reports.
    assert len(loop.ai_calls) == 2


def test_mini_report_text_and_typing_indicator(loop):
    loop.run(1)

    (method, kwargs), = loop.sent()
    lines = kwargs["data"]["text"].split("\n")
    assert method == "sendMessage"
    assert kwargs["data"]["parse_mode"] == "HTML"
    assert lines[:3] == ["<b>Network Status Update</b>",
                         "Here is the latest snapshot of your internet speed:", ""]
    assert lines[3].startswith("Time: <b>20")
    assert lines[4:] == [
        "ISP: <b>Example Telecom</b> | Server: <b>Berlin</b>",
        "",
        "Devices online: <b>3</b>",
        "",
        "Download: <b>93.8 Mbps</b>",
        "Upload: <b>21.5 Mbps</b>",
        "Latency: <b>14.3 ms</b>",
        "",
        "Traffic used: <b>118.2 MB</b> down / <b>26.9 MB</b> up",
        "",
        f"<b>Current status:</b> {STATUS_MIDDLE}",
    ]
    assert loop.chat_actions() == ["typing"]
    assert loop.rows("metrics")[0][4:7] == ("N/A", "Example Telecom", "Berlin")


def test_detailed_report_sends_graph_with_ai_caption_and_ai_input(loop):
    loop.ai_reply = "line1<br>line2<br/>line3<br />line4"
    loop.run(9)

    method, kwargs = loop.sent()[-1]
    assert method == "sendPhoto"
    assert kwargs["data"]["caption"] == "line1\nline2\nline3\nline4"
    assert kwargs["files"]["photo"][1].startswith(b"\x89PNG")
    assert loop.chat_actions()[-3:] == ["typing", "typing", "upload_photo"]

    (system, user), = loop.ai_calls
    assert system["role"] == "system"
    assert system["content"].startswith("\nYou are a sarcastic, cynical network analyst bot.")
    assert system["content"].endswith("under 800 characters to ensure it easily fits within Telegram limits.\n")
    entry = (
        "\nNetwork speed test results:\n"
        "- Date: {ts}\n"
        "- Download: 93.80 Mbps\n"  # rounded to 1 decimal first, then shown with 2
        "- Upload: 21.50 Mbps\n"
        "- Ping: 14.33 ms\n"
        "- Client: Example Telecom\n"
        "- Server: Berlin\n"
        "- Downloaded: 118.2 MB\n"
        "- Uploaded: 26.9 MB\n"
        "- Share Link: N/A\n"
        "- Devices online: 3\n"
    )
    assert user["role"] == "user"
    stamps = [line[len("- Date: "):] for line in user["content"].split("\n") if line.startswith("- Date: ")]
    assert len(stamps) == 9
    assert user["content"] == "".join(entry.format(ts=ts) + "\n" for ts in stamps)


def test_speedtest_failure_sends_notice_writes_nothing_and_sleeps(loop):
    loop.speedtests = ["fail", "fail", "fail"]
    loop.run(1)

    (method, kwargs), = loop.sent()
    assert method == "sendMessage"
    assert kwargs["data"]["text"] == (
        "<b>Speedtest failed</b>\n"
        "The connection was probably down or resetting. Will try again next cycle."
    )
    assert loop.speedtest_calls == 3
    assert loop.nmap_calls == 0
    # Two retry delays between three attempts, then the normal loop sleep.
    assert loop.sleeps == [RETRY_DELAY, RETRY_DELAY, SLEEP_TIME]
    for table in ("metrics", "device_scans", "speedtest"):
        assert loop.rows(table) == []


def test_failed_cycle_does_not_advance_the_counter(loop):
    loop.speedtests = ["fail", "fail", "fail"]
    loop.run(10)  # 1 failed + 9 good: the 9th good one is detailed

    assert loop.kinds() == ["sendMessage"] * 9 + ["sendPhoto"]
    assert "Speedtest failed" in loop.sent()[0][1]["data"]["text"]
    assert len(loop.rows("metrics")) == 9
    assert loop.sleeps == [RETRY_DELAY, RETRY_DELAY] + [SLEEP_TIME] * 10


def test_transient_speedtest_failure_is_retried_within_the_cycle(loop):
    loop.speedtests = ["fail", "fail"]
    loop.run(1)

    assert loop.kinds() == ["sendMessage"]
    assert "Network Status Update" in loop.sent()[0][1]["data"]["text"]
    assert loop.speedtest_calls == 3
    assert loop.sleeps == [RETRY_DELAY, RETRY_DELAY, SLEEP_TIME]
    assert len(loop.rows("metrics")) == 1


def test_ai_failure_still_sends_photo_with_fallback_caption(loop):
    loop.ai_reply = RuntimeError("backend down")
    loop.run(9)

    method, kwargs = loop.sent()[-1]
    assert method == "sendPhoto"
    assert kwargs["data"]["caption"] == FALLBACK_CAPTION
    assert kwargs["files"]["photo"][1].startswith(b"\x89PNG")
    assert len(loop.rows("metrics")) == 9
    assert loop.sleeps == [SLEEP_TIME] * 9


def test_typing_indicator_failure_does_not_stop_the_cycle(loop, monkeypatch):
    real_post = requests.post

    def post(url, **kwargs):
        if url.endswith("/sendChatAction"):
            raise requests.ConnectionError("down")
        return real_post(url, **kwargs)

    monkeypatch.setattr(requests, "post", post)
    loop.run(2)

    assert loop.kinds() == ["sendMessage", "sendMessage"]
    assert len(loop.rows("metrics")) == 2
    assert loop.sleeps == [SLEEP_TIME] * 2


@pytest.mark.parametrize("download_mbps,ping,status", [
    (150, 20, STATUS_GOOD),
    (500, 1, STATUS_GOOD),
    (149.9, 20, STATUS_MIDDLE),
    (150, 20.1, STATUS_MIDDLE),
    (100, 30, STATUS_MIDDLE),
    (60, 40, STATUS_MIDDLE),
    (59.9, 10, STATUS_BAD),
    (100, 40.1, STATUS_BAD),
    (500, 41, STATUS_BAD),  # fast line but high ping is still "bad"
    (10, 100, STATUS_BAD),
])
def test_mini_report_status_thresholds(loop, download_mbps, ping, status):
    loop.speedtests = [{"download": download_mbps * 10**6, "ping": ping}]
    loop.run(1)

    (_, kwargs), = loop.sent()
    assert kwargs["data"]["text"].split("\n")[-1] == f"<b>Current status:</b> {status}"
