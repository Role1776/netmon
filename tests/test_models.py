import uuid
from typing import Any
from datetime import timedelta

import pytest

import models

VALID: dict[str, Any] = dict(download=1.5, upload=2.5, ping=3.5, share="https://x/y.png", client="isp",
             server="srv", bytes_sent=10, bytes_received=20)


def metric(**kw):
    return models.NetworkMetric.create(**(VALID | kw))


def test_metric_create_keeps_fields_and_generates_identity():
    m = metric()
    assert (m.download, m.upload, m.ping, m.share, m.client, m.server, m.bytes_sent, m.bytes_received) == (
        1.5, 2.5, 3.5, "https://x/y.png", "isp", "srv", 10, 20)
    assert isinstance(m.id, uuid.UUID)
    assert m.timestamp.utcoffset() == timedelta(0)


def test_metric_ids_are_unique():
    assert metric().id != metric().id


def test_metric_zero_values_are_valid():
    m = metric(download=0, upload=0, ping=0, bytes_sent=0, bytes_received=0)
    assert (m.download, m.upload, m.ping, m.bytes_sent, m.bytes_received) == (0, 0, 0, 0, 0)


@pytest.mark.parametrize("field", ["download", "upload", "ping", "bytes_sent", "bytes_received"])
def test_metric_negative_number_rejected(field):
    with pytest.raises(ValueError):
        metric(**{field: -1})


@pytest.mark.parametrize("field", ["client", "server"])
@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_metric_blank_text_rejected(field, value):
    with pytest.raises(ValueError):
        metric(**{field: value})


def test_metric_is_immutable():
    with pytest.raises(AttributeError):
        metric().download = 5  # type: ignore[misc]


def test_device_create_keeps_fields():
    d = models.NetworkDevice.create(ip="192.168.1.5", latency_ms=1.25)
    assert (d.ip, d.latency_ms) == ("192.168.1.5", 1.25)
    assert isinstance(d.id, uuid.UUID)
    assert d.timestamp.utcoffset() == timedelta(0)


def test_device_zero_latency_is_valid():
    assert models.NetworkDevice.create(ip="10.0.0.1", latency_ms=0).latency_ms == 0


@pytest.mark.parametrize("ip", ["", "  "])
def test_device_blank_ip_rejected(ip):
    with pytest.raises(ValueError):
        models.NetworkDevice.create(ip=ip, latency_ms=1)


def test_device_negative_latency_rejected():
    with pytest.raises(ValueError):
        models.NetworkDevice.create(ip="10.0.0.1", latency_ms=-0.01)


def test_speedtest_links_metric_and_scan():
    m, s = uuid.uuid4(), uuid.uuid4()
    st = models.SpeedTest.create(metric_id=m, device_scan_id=s)
    assert (st.metric_id, st.device_scan_id) == (m, s)
    assert st.id not in (m, s)
