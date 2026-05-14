"""Location resolution: stored config → IP-geo → None.

Browser-Geolocation and map-pin overrides arrive via dashboard POST; this
module covers the server-side resolution and the IP-geo bootstrap.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import requests

from app import db

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    label: str
    source: str  # "stored" | "ip_geo" | "browser_geo" | "manual_pin"


def stored_location() -> Optional[Location]:
    lat_s = db.get_config("location_lat")
    lon_s = db.get_config("location_lon")
    if lat_s is None or lon_s is None:
        return None
    try:
        return Location(
            lat=float(lat_s),
            lon=float(lon_s),
            label=db.get_config("location_label") or "",
            source=db.get_config("location_source") or "stored",
        )
    except ValueError:
        log.warning("Stored location has non-numeric coords; ignoring")
        return None


def save_location(loc: Location) -> None:
    db.set_config("location_lat", str(loc.lat))
    db.set_config("location_lon", str(loc.lon))
    db.set_config("location_label", loc.label)
    db.set_config("location_source", loc.source)


def resolve_via_ip(timeout: float = 5.0) -> Optional[Location]:
    url = os.environ.get("IP_GEO_URL", "https://ipapi.co/json/")
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        lat = data.get("latitude")
        lon = data.get("longitude")
        if lat is None or lon is None:
            return None
        label_parts = [
            data.get("city"),
            data.get("region"),
            data.get("country_name") or data.get("country"),
        ]
        label = ", ".join([p for p in label_parts if p]) or "IP-Geo"
        return Location(lat=float(lat), lon=float(lon), label=label, source="ip_geo")
    except (requests.RequestException, ValueError) as e:
        log.warning("IP-geo lookup failed: %s", e)
        return None


def resolve() -> Optional[Location]:
    stored = stored_location()
    if stored is not None:
        return stored
    ip = resolve_via_ip()
    if ip is not None:
        save_location(ip)
        return ip
    return None


def geocode_address(query: str, timeout: float = 8.0) -> Optional[Location]:
    """Forward-geocode a free-text address via Nominatim/OSM."""
    if not query.strip():
        return None
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "addressdetails": 1},
            headers={"User-Agent": "hue-iss/0.1 (private LAN dashboard)"},
            timeout=timeout,
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None
        r = results[0]
        return Location(
            lat=float(r["lat"]),
            lon=float(r["lon"]),
            label=r.get("display_name", query)[:120],
            source="geocoded",
        )
    except (requests.RequestException, ValueError, KeyError) as e:
        log.warning("Geocoding failed for %r: %s", query, e)
        return None
