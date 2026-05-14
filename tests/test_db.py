from datetime import datetime, timedelta, timezone

from app import db


def test_init_idempotent():
    db.init_db()
    db.init_db()


def test_config_roundtrip():
    db.init_db()
    db.set_config("bridge_ip", "192.168.0.42")
    assert db.get_config("bridge_ip") == "192.168.0.42"
    db.set_config("bridge_ip", None)
    assert db.get_config("bridge_ip") is None
    assert db.get_config("missing", "default") == "default"


def test_upsert_pass_idempotent():
    db.init_db()
    rise = datetime(2026, 6, 1, 21, 0, tzinfo=timezone.utc)
    cul = rise + timedelta(minutes=3)
    set_ = rise + timedelta(minutes=6)

    pid1 = db.upsert_pass(rise, cul, set_, 42.0, 280.0, 110.0)
    pid2 = db.upsert_pass(rise, cul, set_, 45.0, 281.0, 111.0)

    assert pid1 == pid2  # same row
    upcoming = db.list_upcoming_passes(rise - timedelta(seconds=1), limit=10)
    assert len(upcoming) == 1
    assert upcoming[0]["max_elevation"] == 45.0


def test_mark_pass_triggered():
    db.init_db()
    rise = datetime(2026, 6, 2, 21, 0, tzinfo=timezone.utc)
    pid = db.upsert_pass(rise, rise + timedelta(minutes=3), rise + timedelta(minutes=6),
                         30.0, 270.0, 90.0)
    db.mark_pass_triggered(pid, prewarn=True)
    rows = db.list_upcoming_passes(rise - timedelta(seconds=1), 10)
    assert rows[0]["triggered_prewarn"] == 1
    assert rows[0]["triggered_start"] == 0


def test_delete_future_untriggered():
    db.init_db()
    base = datetime.now(timezone.utc) + timedelta(hours=1)
    pid_untouched = db.upsert_pass(base, base + timedelta(minutes=3), base + timedelta(minutes=6),
                                    20, 100, 200)
    later = base + timedelta(hours=2)
    pid_triggered = db.upsert_pass(later, later + timedelta(minutes=3), later + timedelta(minutes=6),
                                    25, 100, 200)
    db.mark_pass_triggered(pid_triggered, prewarn=True)

    db.delete_future_untriggered_passes()

    rows = db.list_upcoming_passes(datetime.now(timezone.utc), 10)
    ids = [r["id"] for r in rows]
    assert pid_untouched not in ids
    assert pid_triggered in ids


def test_event_append_and_read():
    db.init_db()
    db.append_event("test_kind", {"foo": 42})
    events = db.recent_events(10)
    assert len(events) == 1
    assert events[0]["kind"] == "test_kind"
    assert '"foo": 42' in events[0]["payload_json"]
