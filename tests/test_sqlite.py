import json
import sqlite3
import uuid

import pytest

import models
import sqlite


def link(db, metric, n_devices=1):
    scan = db.add_devices([models.NetworkDevice.create(ip=f"10.0.0.{i}", latency_ms=i) for i in range(n_devices)])
    db.add_metric(metric)
    db.add_speedtest(models.SpeedTest.create(metric.id, scan))


def count(db, table):
    return db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_init_creates_tables():
    with sqlite.DB.init(":memory:") as db:
        tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"metrics", "device_scans", "speedtest"} <= tables


@pytest.mark.parametrize("path", ["", "   "])
def test_init_rejects_blank_path(path):
    with pytest.raises(ValueError):
        sqlite.DB.init(path)


def test_init_unopenable_path_raises_runtime_error(tmp_path):
    with pytest.raises(RuntimeError):
        sqlite.DB.init(str(tmp_path / "missing_dir" / "m.sql"))


def test_reopening_existing_database_keeps_data(tmp_path, make_metric):
    path = str(tmp_path / "m.sql")
    m = make_metric()
    with sqlite.DB.init(path) as db:
        db.add_metric(m)
    with sqlite.DB.init(path) as db:
        assert count(db, "metrics") == 1


def test_context_manager_closes_connection():
    with sqlite.DB.init(":memory:") as db:
        pass
    with pytest.raises(sqlite3.ProgrammingError):
        db.conn.execute("SELECT 1")


def test_metric_roundtrip(db, make_metric):
    m = make_metric(age_hours=2, share="http://x/1.png", download=123.456, ping=0)
    db.add_metric(m)
    assert db.get_metrics() == [m]


def test_add_metric_duplicate_id_raises_and_keeps_original(db, make_metric):
    m = make_metric()
    db.add_metric(m)
    with pytest.raises(RuntimeError):
        db.add_metric(m)
    assert db.get_metrics() == [m]


def test_add_devices_returns_scan_id_and_stores_ips_and_latencies_in_order(db):
    devices = [models.NetworkDevice.create(ip=ip, latency_ms=ms) for ip, ms in [("10.0.0.9", 1.5), ("10.0.0.2", 0)]]
    scan_id = db.add_devices(devices)
    assert isinstance(scan_id, uuid.UUID)
    row = db.conn.execute("SELECT id, ips, latencies FROM device_scans").fetchone()
    assert (row[0], json.loads(row[1]), json.loads(row[2])) == (str(scan_id), ["10.0.0.9", "10.0.0.2"], [1.5, 0])


def test_add_devices_accepts_empty_scan_and_ids_are_distinct(db):
    a, b = db.add_devices([]), db.add_devices([])
    assert a != b
    assert count(db, "device_scans") == 2


def test_add_speedtest_requires_existing_metric_and_scan(db, make_metric):
    m = make_metric()
    db.add_metric(m)
    with pytest.raises(RuntimeError):
        db.add_speedtest(models.SpeedTest.create(m.id, uuid.uuid4()))
    with pytest.raises(RuntimeError):
        db.add_speedtest(models.SpeedTest.create(uuid.uuid4(), db.add_devices([])))
    assert count(db, "speedtest") == 0


def test_add_speedtest_metric_can_be_linked_only_once(db, make_metric):
    m = make_metric()
    db.add_metric(m)
    db.add_speedtest(models.SpeedTest.create(m.id, db.add_devices([])))
    with pytest.raises(RuntimeError):
        db.add_speedtest(models.SpeedTest.create(m.id, db.add_devices([])))


def test_deleting_metric_cascades_to_speedtest(db, make_metric):
    link(db, make_metric())
    with db.transaction():
        db.conn.execute("DELETE FROM metrics")
    assert count(db, "speedtest") == 0


def test_get_metrics_empty_database(db):
    assert db.get_metrics() == []


def test_get_metrics_returns_oldest_first(db, make_metric):
    ms = [make_metric(age_hours=h) for h in (5, 20, 1, 10)]
    for m in ms:
        db.add_metric(m)
    assert db.get_metrics() == sorted(ms, key=lambda m: m.timestamp)


def test_get_metrics_includes_unlinked_metrics(db, make_metric):
    m = make_metric()
    db.add_metric(m)
    assert db.get_metrics() == [m]


@pytest.mark.parametrize("age,kept", [(0, True), (23.9, True), (24.1, False), (48, False)])
def test_get_metrics_24h_window(db, make_metric, age, kept):
    m = make_metric(age_hours=age)
    db.add_metric(m)
    assert db.get_metrics() == ([m] if kept else [])


def test_get_metrics_caps_at_48_most_recent(db, make_metric):
    ms = [make_metric(age_hours=23.5 - i * 0.4) for i in range(50)]
    for m in ms:
        db.add_metric(m)
    assert db.get_metrics() == ms[2:]


def test_get_metrics_covers_full_24h_at_30_minute_cadence(db, make_metric):
    ms = [make_metric(age_hours=i / 2 + 0.1) for i in range(48)]
    for m in ms:
        db.add_metric(m)
    assert db.get_metrics() == ms[::-1]


def test_counts_empty_database(db):
    assert db.get_metrics_with_device_counts() == ([], [])


def test_counts_pair_each_metric_with_its_scan_size_oldest_first(db, make_metric):
    old, new = make_metric(age_hours=3), make_metric(age_hours=1)
    link(db, new, n_devices=5)
    link(db, old, n_devices=2)
    assert db.get_metrics_with_device_counts() == ([old, new], [2, 5])


def test_counts_empty_scan_counts_zero(db, make_metric):
    m = make_metric()
    link(db, m, n_devices=0)
    assert db.get_metrics_with_device_counts() == ([m], [0])


def test_counts_skip_metrics_without_speedtest_link(db, make_metric):
    linked = make_metric(age_hours=2)
    link(db, linked, n_devices=3)
    db.add_metric(make_metric(age_hours=1))
    assert db.get_metrics_with_device_counts() == ([linked], [3])


@pytest.mark.parametrize("age,kept", [(23.9, True), (24.1, False)])
def test_counts_24h_window(db, make_metric, age, kept):
    m = make_metric(age_hours=age)
    link(db, m, n_devices=4)
    assert db.get_metrics_with_device_counts() == (([m], [4]) if kept else ([], []))


def test_counts_cap_at_48_most_recent(db, make_metric):
    ms = [make_metric(age_hours=23.5 - i * 0.4) for i in range(50)]
    for i, m in enumerate(ms):
        link(db, m, n_devices=i % 3)
    metrics, counts = db.get_metrics_with_device_counts()
    assert metrics == ms[2:]
    assert counts == [i % 3 for i in range(2, 50)]


def test_failed_statement_rolls_back_whole_transaction(db, make_metric):
    m = make_metric()
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.add_metric(m)
            db.add_metric(m)
    assert count(db, "metrics") == 0


def test_non_database_error_rolls_back_and_propagates(db, make_metric):
    with pytest.raises(KeyError):
        with db.transaction():
            db.add_metric(make_metric())
            raise KeyError("boom")
    assert count(db, "metrics") == 0


def test_nested_transactions_commit_together(db, make_metric):
    with db.transaction():
        db.add_metric(make_metric(age_hours=1))
        with db.transaction():
            db.add_metric(make_metric(age_hours=2))
    assert count(db, "metrics") == 2


def test_inner_failure_rolls_back_outer_writes(db, make_metric):
    m = make_metric()
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.add_metric(make_metric(age_hours=2))
            with db.transaction():
                db.add_metric(m)
                db.add_metric(m)
    assert count(db, "metrics") == 0


def test_database_usable_after_failed_transaction(db, make_metric):
    m = make_metric()
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.add_metric(m)
            db.add_metric(m)
    db.add_metric(m)
    assert db.get_metrics() == [m]


def test_committed_writes_survive_a_later_rollback(db, make_metric):
    kept = make_metric(age_hours=2)
    db.add_metric(kept)
    with pytest.raises(KeyError):
        with db.transaction():
            db.add_metric(make_metric(age_hours=1))
            raise KeyError
    assert db.get_metrics() == [kept]
