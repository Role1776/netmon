import pytest

import main


def expected(timestamp, client="isp", server="srv", devices=3, status="ok"):
    return (
        "<b>Network Status Update</b>\n"
        "Here is the latest snapshot of your internet speed:\n"
        "\n"
        f"Time: <b>{timestamp}</b>\n"
        f"ISP: <b>{client}</b> | Server: <b>{server}</b>\n"
        "\n"
        f"Devices online: <b>{devices}</b>\n"
        "\n"
        "Download: <b>123.5 Mbps</b>\n"
        "Upload: <b>20.0 Mbps</b>\n"
        "Latency: <b>12.3 ms</b>\n"
        "\n"
        "Traffic used: <b>2.5 MB</b> down / <b>1.0 MB</b> up\n"
        "\n"
        f"<b>Current status:</b> {status}"
    )


@pytest.fixture
def metric(make_metric):
    return make_metric(download=123.456e6, upload=20e6, ping=12.34,
                       bytes_received=2_500_000, bytes_sent=1_000_000)


def ts(m):
    return m.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def test_plain_metric_keeps_report_format(metric):
    assert main.format_mini_report(metric, 3, "ok") == expected(ts(metric))


@pytest.mark.parametrize("name,escaped", [
    ("AT&T", "AT&amp;T"),
    ("Foo <Bar>", "Foo &lt;Bar&gt;"),
    ("<x>", "&lt;x&gt;"),
])
def test_client_and_server_names_are_html_escaped(make_metric, name, escaped):
    m = make_metric(download=123.456e6, upload=20e6, ping=12.34,
                    bytes_received=2_500_000, bytes_sent=1_000_000,
                    client=name, server=name)
    assert main.format_mini_report(m, 3, "ok") == expected(ts(m), client=escaped, server=escaped)


def test_status_text_is_not_escaped(metric):
    assert main.format_mini_report(metric, 3, "<i>x</i>") == expected(ts(metric), status="<i>x</i>")


def test_importing_main_does_not_start_bot():
    assert callable(main.main)
