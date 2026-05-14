"""ISS pass prediction with naked-eye visibility filter.

A pass counts as visible only when ALL three conditions hold at culmination:
1. ISS elevation above horizon >= 10°
2. ISS is illuminated by the sun (not in Earth's shadow)
3. Observer is in civil twilight or darker (sun >= 6° below horizon)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import requests
from skyfield.api import EarthSatellite, Loader, wgs84

log = logging.getLogger(__name__)

CELESTRAK_ISS_URL = (
    "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"
)
TLE_CACHE_FILENAME = "iss_tle.txt"
TLE_MAX_AGE = timedelta(hours=12)

MIN_ELEVATION_DEG = 10.0
TWILIGHT_SUN_ALT_DEG = -6.0


@dataclass(frozen=True)
class VisiblePass:
    rise_time: datetime
    culminate_time: datetime
    set_time: datetime
    max_elevation: float
    azimuth_rise: float
    azimuth_set: float

    @property
    def duration_seconds(self) -> float:
        return (self.set_time - self.rise_time).total_seconds()


@dataclass(frozen=True)
class TLE:
    name: str
    line1: str
    line2: str
    fetched_at: datetime


def _data_dir() -> Path:
    raw = os.environ.get("DATA_DIR", "data")
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read_cached_tle() -> Optional[TLE]:
    cache = _data_dir() / TLE_CACHE_FILENAME
    if not cache.exists():
        return None
    try:
        text = cache.read_text()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) < 3:
            return None
        mtime = datetime.fromtimestamp(cache.stat().st_mtime, tz=timezone.utc)
        return TLE(name=lines[0], line1=lines[1], line2=lines[2], fetched_at=mtime)
    except OSError as e:
        log.warning("Could not read TLE cache: %s", e)
        return None


def _write_tle_cache(name: str, line1: str, line2: str) -> None:
    cache = _data_dir() / TLE_CACHE_FILENAME
    cache.write_text(f"{name}\n{line1}\n{line2}\n")


def fetch_tle(force_refresh: bool = False) -> TLE:
    """Return a fresh ISS TLE. Falls back to stale cache on network error."""
    cached = _read_cached_tle()
    age = datetime.now(timezone.utc) - cached.fetched_at if cached else None
    if cached and not force_refresh and age is not None and age < TLE_MAX_AGE:
        return cached

    try:
        resp = requests.get(CELESTRAK_ISS_URL, timeout=10)
        resp.raise_for_status()
        lines = [l.strip() for l in resp.text.strip().splitlines() if l.strip()]
        if len(lines) < 3:
            raise ValueError(f"Unexpected TLE response: {resp.text[:200]!r}")
        _write_tle_cache(lines[0], lines[1], lines[2])
        return TLE(
            name=lines[0],
            line1=lines[1],
            line2=lines[2],
            fetched_at=datetime.now(timezone.utc),
        )
    except (requests.RequestException, ValueError) as e:
        if cached:
            log.warning("Celestrak fetch failed (%s), using stale TLE from %s", e, cached.fetched_at)
            return cached
        raise


def find_visible_passes(
    lat: float,
    lon: float,
    t_from_utc: datetime,
    t_to_utc: datetime,
    tle: Optional[TLE] = None,
) -> list[VisiblePass]:
    """Return visible passes within [t_from_utc, t_to_utc]."""
    if tle is None:
        tle = fetch_tle()

    loader = Loader(str(_data_dir()))
    ts = loader.timescale()
    eph = loader("de421.bsp")
    sun = eph["sun"]
    earth = eph["earth"]

    sat = EarthSatellite(tle.line1, tle.line2, tle.name, ts)
    observer_topo = wgs84.latlon(lat, lon)
    observer_geo = earth + observer_topo

    t0 = ts.from_datetime(_ensure_utc(t_from_utc))
    t1 = ts.from_datetime(_ensure_utc(t_to_utc))

    t_events, events = sat.find_events(
        observer_topo, t0, t1, altitude_degrees=MIN_ELEVATION_DEG
    )

    results: list[VisiblePass] = []
    rise_t = None
    culm_t = None
    for ti, ei in zip(t_events, events):
        if ei == 0:
            rise_t = ti
            culm_t = None
        elif ei == 1:
            culm_t = ti
        elif ei == 2:
            set_t = ti
            if rise_t is None or culm_t is None:
                rise_t = culm_t = None
                continue
            if _is_visible(sat, observer_topo, observer_geo, sun, eph, culm_t):
                diff_culm = (sat - observer_topo).at(culm_t)
                alt_culm, _, _ = diff_culm.altaz()
                az_rise = (sat - observer_topo).at(rise_t).altaz()[1].degrees
                az_set = (sat - observer_topo).at(set_t).altaz()[1].degrees
                results.append(
                    VisiblePass(
                        rise_time=rise_t.utc_datetime(),
                        culminate_time=culm_t.utc_datetime(),
                        set_time=set_t.utc_datetime(),
                        max_elevation=float(alt_culm.degrees),
                        azimuth_rise=float(az_rise),
                        azimuth_set=float(az_set),
                    )
                )
            rise_t = culm_t = None
    return results


def _is_visible(sat, observer_topo, observer_geo, sun, eph, t) -> bool:
    if not sat.at(t).is_sunlit(eph):
        return False
    sun_alt_deg = observer_geo.at(t).observe(sun).apparent().altaz()[0].degrees
    if sun_alt_deg >= TWILIGHT_SUN_ALT_DEG:
        return False
    return True


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
