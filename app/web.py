"""Flask routes: dashboard, configuration endpoints, effect-test endpoints."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo  # py3.9+
except ImportError:  # py3.8
    from backports.zoneinfo import ZoneInfo  # type: ignore

from flask import Blueprint, jsonify, render_template, request

from app import db, geo, hue
from app.effects import EFFECT_PRESETS, run_effect

log = logging.getLogger(__name__)

bp = Blueprint("web", __name__)

LOCAL_TZ = ZoneInfo("Europe/Zurich")


def _local(dt_iso: str) -> str:
    dt = datetime.fromisoformat(dt_iso).astimezone(LOCAL_TZ)
    return dt.strftime("%d.%m. %H:%M:%S")


# --------------------------------------------------------------------- dashboard

@bp.get("/")
def dashboard():
    now = datetime.now(timezone.utc)
    cfg = db.get_all_config()
    loc = geo.stored_location()

    bridge_ip = cfg.get("bridge_ip")
    bridge_user = cfg.get("bridge_user")
    lights = []
    bridge_ok = False
    if bridge_ip and bridge_user:
        try:
            lights = hue.list_lights(bridge_ip, bridge_user)
            bridge_ok = True
        except Exception as e:
            log.warning("Could not list lights: %s", e)

    upcoming = db.list_upcoming_passes(now, limit=5)
    recent = db.list_recent_passes(now, limit=5)

    upcoming_view = [_pass_view(p, now) for p in upcoming]
    recent_view = [_pass_view(p, now) for p in recent]

    return render_template(
        "dashboard.html",
        loc=loc,
        bridge_ip=bridge_ip,
        bridge_ok=bridge_ok,
        lights=lights,
        light_id=int(cfg["light_id"]) if cfg.get("light_id") else None,
        effect_name=cfg.get("effect_name") or "soft_breathe_white",
        effects=EFFECT_PRESETS,
        upcoming=upcoming_view,
        recent=recent_view,
        local_tz=str(LOCAL_TZ),
    )


def _pass_view(row, now: datetime) -> dict:
    rise = datetime.fromisoformat(row["rise_ts"])
    set_ = datetime.fromisoformat(row["set_ts"])
    delta = rise - now
    return {
        "id": row["id"],
        "rise_local": _local(row["rise_ts"]),
        "set_local": _local(row["set_ts"]),
        "max_elev": round(row["max_elevation"], 1),
        "duration": round((set_ - rise).total_seconds() / 60.0, 1),
        "az_rise": round(row["azimuth_rise"]),
        "az_set": round(row["azimuth_set"]),
        "in_seconds": int(delta.total_seconds()),
        "triggered_prewarn": bool(row["triggered_prewarn"]),
        "triggered_start": bool(row["triggered_start"]),
    }


# --------------------------------------------------------------------- bridge

@bp.post("/api/bridge/discover")
def api_discover():
    bridges = hue.discover_bridges()
    return jsonify([{"id": b.id, "ip": b.ip} for b in bridges])


@bp.post("/api/bridge/pair")
def api_pair():
    ip = (request.json or {}).get("ip")
    if not ip:
        return jsonify({"error": "ip missing"}), 400
    try:
        username = hue.pair_with_bridge(ip)
        db.set_config("bridge_ip", ip)
        db.set_config("bridge_user", username)
        db.append_event("bridge_paired", {"ip": ip})
        return jsonify({"ok": True, "ip": ip})
    except hue.PairingError as e:
        return jsonify({"error": str(e)}), 400


# --------------------------------------------------------------------- config

@bp.post("/api/config")
def api_config():
    data = request.json or {}
    if "light_id" in data and data["light_id"] is not None:
        db.set_config("light_id", str(int(data["light_id"])))
    if "effect_name" in data and data["effect_name"]:
        name = data["effect_name"]
        if name not in EFFECT_PRESETS:
            return jsonify({"error": f"unknown effect: {name}"}), 400
        db.set_config("effect_name", name)
    return jsonify({"ok": True})


@bp.post("/api/location/geocode")
def api_location_geocode():
    data = request.json or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query missing"}), 400
    loc = geo.geocode_address(query)
    if loc is None:
        return jsonify({"error": f"keine Treffer für '{query}'"}), 404
    geo.save_location(loc)
    db.append_event("location_set", {"lat": loc.lat, "lon": loc.lon, "source": "geocoded", "q": query})
    from app.scheduler import get_scheduler
    threading.Thread(target=get_scheduler().refresh_and_recompute, daemon=True).start()
    return jsonify({"lat": loc.lat, "lon": loc.lon, "label": loc.label, "source": loc.source})


@bp.post("/api/location/ip")
def api_location_ip():
    loc = geo.resolve_via_ip()
    if loc is None:
        return jsonify({"error": "IP-Geo lookup fehlgeschlagen"}), 502
    geo.save_location(loc)
    db.append_event("location_set", {"lat": loc.lat, "lon": loc.lon, "source": "ip_geo"})
    from app.scheduler import get_scheduler
    threading.Thread(target=get_scheduler().refresh_and_recompute, daemon=True).start()
    return jsonify({"lat": loc.lat, "lon": loc.lon, "label": loc.label, "source": loc.source})


@bp.post("/api/location")
def api_location():
    data = request.json or {}
    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "lat/lon missing or invalid"}), 400
    label = (data.get("label") or "").strip()
    source = (data.get("source") or "manual_pin").strip()
    if source not in {"manual_pin", "browser_geo", "ip_geo"}:
        source = "manual_pin"
    geo.save_location(geo.Location(lat=lat, lon=lon, label=label, source=source))
    db.append_event("location_set", {"lat": lat, "lon": lon, "source": source})
    from app.scheduler import get_scheduler
    threading.Thread(target=get_scheduler().refresh_and_recompute, daemon=True).start()
    return jsonify({"ok": True})


# --------------------------------------------------------------------- effect test

@bp.post("/api/effect/test")
def api_effect_test():
    data = request.json or {}
    effect_name = data.get("effect_name")
    if effect_name not in EFFECT_PRESETS:
        return jsonify({"error": f"unknown effect: {effect_name}"}), 400

    bridge_ip = db.get_config("bridge_ip")
    bridge_user = db.get_config("bridge_user")
    light_id_s = data.get("light_id") or db.get_config("light_id")
    if not (bridge_ip and bridge_user and light_id_s):
        return jsonify({"error": "bridge or light not configured"}), 400

    def _run():
        try:
            ctl = hue.BridgeLightController(bridge_ip, bridge_user)
            run_effect(ctl, int(light_id_s), effect_name)
            db.append_event("effect_test", {"effect": effect_name, "light_id": int(light_id_s)})
        except Exception as e:
            log.exception("Effect test failed: %s", e)
            db.append_event("effect_test_failed", {"effect": effect_name, "error": str(e)})

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "effect": effect_name})


# --------------------------------------------------------------------- json apis

@bp.get("/api/passes/next")
def api_next_passes():
    now = datetime.now(timezone.utc)
    rows = db.list_upcoming_passes(now, limit=10)
    return jsonify([_pass_view(r, now) for r in rows])


@bp.get("/healthz")
def healthz():
    bridge_ip = db.get_config("bridge_ip")
    bridge_user = db.get_config("bridge_user")
    bridge_ok = (
        bool(bridge_ip and bridge_user) and hue.healthcheck(bridge_ip, bridge_user)
    )
    loc = geo.stored_location()
    next_passes = db.list_upcoming_passes(datetime.now(timezone.utc), limit=1)
    return jsonify(
        {
            "status": "ok",
            "bridge": {"configured": bool(bridge_ip), "reachable": bridge_ok},
            "location": {"set": loc is not None, "label": loc.label if loc else None},
            "next_pass_in_db": next_passes[0]["rise_ts"] if next_passes else None,
        }
    )
