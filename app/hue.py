"""Philips Hue Bridge discovery, pairing, and light control.

V1 Local API (works on all bridges, no rate limits at our scale).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from app.effects import LightState

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BridgeInfo:
    id: str
    ip: str


@dataclass(frozen=True)
class HueLight:
    id: int
    name: str
    type: str
    reachable: bool


# --------------------------------------------------------------------- discovery

def discover_bridges(timeout: float = 5.0) -> list[BridgeInfo]:
    """Find all Hue bridges on the local network via meethue cloud discovery."""
    try:
        resp = requests.get("https://discovery.meethue.com/", timeout=timeout)
        resp.raise_for_status()
        return [
            BridgeInfo(id=b.get("id", ""), ip=b["internalipaddress"])
            for b in resp.json()
            if b.get("internalipaddress")
        ]
    except requests.RequestException as e:
        log.warning("Bridge discovery via meethue cloud failed: %s", e)
        return []


# --------------------------------------------------------------------- pairing

class PairingError(Exception):
    pass


def pair_with_bridge(ip: str, devicetype: str = "hue-iss#dashboard") -> str:
    """Press the link button on the bridge, then call this. Returns username."""
    try:
        resp = requests.post(
            f"http://{ip}/api",
            json={"devicetype": devicetype},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            entry = data[0]
            if "success" in entry:
                return entry["success"]["username"]
            if "error" in entry:
                msg = entry["error"].get("description", "unknown error")
                raise PairingError(msg)
        raise PairingError(f"Unexpected pairing response: {data!r}")
    except requests.RequestException as e:
        raise PairingError(f"Could not reach bridge at {ip}: {e}") from e


# --------------------------------------------------------------------- lights

def list_lights(ip: str, username: str) -> list[HueLight]:
    resp = requests.get(f"http://{ip}/api/{username}/lights", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list) and data and "error" in data[0]:
        raise PairingError(data[0]["error"].get("description", "auth error"))
    result: list[HueLight] = []
    for light_id_str, info in data.items():
        state = info.get("state", {})
        result.append(
            HueLight(
                id=int(light_id_str),
                name=info.get("name", f"Light {light_id_str}"),
                type=info.get("type", ""),
                reachable=bool(state.get("reachable", False)),
            )
        )
    return result


# --------------------------------------------------------------------- controller

class BridgeLightController:
    """Implements the LightController Protocol from app/effects.py."""

    def __init__(self, ip: str, username: str, session: requests.Session | None = None) -> None:
        self.ip = ip
        self.username = username
        self.session = session or requests.Session()

    def _url(self, light_id: int, suffix: str = "") -> str:
        return f"http://{self.ip}/api/{self.username}/lights/{light_id}{suffix}"

    def get_state(self, light_id: int) -> LightState:
        resp = self.session.get(self._url(light_id), timeout=5)
        resp.raise_for_status()
        data = resp.json()
        state = data.get("state", {})
        xy = state.get("xy")
        return LightState(
            on=bool(state.get("on", False)),
            bri=int(state.get("bri", 254)),
            xy=(float(xy[0]), float(xy[1])) if xy else None,
            ct=int(state["ct"]) if "ct" in state else None,
        )

    def set_state(
        self,
        light_id: int,
        *,
        on: bool | None = None,
        bri: int | None = None,
        xy: tuple[float, float] | None = None,
        ct: int | None = None,
        transitiontime: int | None = None,
        alert: str | None = None,
    ) -> None:
        body: dict[str, Any] = {}
        if on is not None:
            body["on"] = on
        if bri is not None:
            body["bri"] = max(1, min(254, int(bri)))
        if xy is not None:
            body["xy"] = [float(xy[0]), float(xy[1])]
        if ct is not None:
            body["ct"] = max(153, min(500, int(ct)))
        if transitiontime is not None:
            body["transitiontime"] = max(0, int(transitiontime))
        if alert is not None:
            body["alert"] = alert
        if not body:
            return
        resp = self.session.put(self._url(light_id, "/state"), json=body, timeout=5)
        resp.raise_for_status()


def healthcheck(ip: str, username: str) -> bool:
    try:
        resp = requests.get(f"http://{ip}/api/{username}/config", timeout=5)
        resp.raise_for_status()
        return "bridgeid" in resp.json()
    except (requests.RequestException, ValueError):
        return False
