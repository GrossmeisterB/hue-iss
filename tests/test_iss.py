from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import iss


SAMPLE_TLE = """ISS (ZARYA)
1 25544U 98067A   26134.45833333  .00012345  00000+0  22000-3 0  9990
2 25544  51.6420 123.4567 0001234  90.1234 270.1234 15.49000000999990
"""


def test_read_write_tle_cache(tmp_data_dir):
    cache = Path(tmp_data_dir) / iss.TLE_CACHE_FILENAME
    cache.write_text(SAMPLE_TLE)
    tle = iss._read_cached_tle()
    assert tle is not None
    assert tle.name == "ISS (ZARYA)"
    assert tle.line1.startswith("1 25544U")
    assert tle.line2.startswith("2 25544")


def test_read_cached_tle_returns_none_when_missing(tmp_data_dir):
    assert iss._read_cached_tle() is None


def test_fetch_tle_uses_cache_within_ttl(tmp_data_dir, monkeypatch):
    cache = Path(tmp_data_dir) / iss.TLE_CACHE_FILENAME
    cache.write_text(SAMPLE_TLE)

    called = {"count": 0}

    def fake_get(*a, **k):
        called["count"] += 1
        raise AssertionError("network should not be called")

    monkeypatch.setattr(iss.requests, "get", fake_get)
    tle = iss.fetch_tle()
    assert tle.name == "ISS (ZARYA)"
    assert called["count"] == 0


def test_ensure_utc_handles_naive_and_aware():
    naive = datetime(2026, 5, 14, 12, 0)
    aware = iss._ensure_utc(naive)
    assert aware.tzinfo == timezone.utc

    other = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    same = iss._ensure_utc(other)
    assert same == other
