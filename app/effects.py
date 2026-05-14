"""Hue light effects: 4 presets with snapshot/restore around each.

Effects are dispatched by name. Each effect receives a `LightController`
(see app/hue.py) and the light_id. Implementations are deliberately simple
and synchronous — each preset takes 1-30 seconds and is rare.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass
class LightState:
    on: bool
    bri: int
    xy: tuple[float, float] | None
    ct: int | None


class LightController(Protocol):
    def get_state(self, light_id: int) -> LightState: ...
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
    ) -> None: ...


EFFECT_PRESETS: dict[str, dict[str, str]] = {
    "soft_breathe_white": {
        "label": "🌬 Soft white breathe",
        "description": "15 s breathing effect, warm white",
    },
    "fast_blink_blue": {
        "label": "⚡ Fast blue blink",
        "description": "5× short blue blink, ~3 s",
    },
    "iss_sequence": {
        "label": "🌌 ISS sequence",
        "description": "White/blue alternation, ~30 s",
    },
    "single_flash": {
        "label": "✨ Single flash",
        "description": "One bright pulse",
    },
}

XY_BLUE = (0.15, 0.05)
XY_WHITE = (0.3127, 0.3290)


def run_effect(ctl: LightController, light_id: int, effect_name: str) -> None:
    if effect_name not in EFFECT_PRESETS:
        raise ValueError(f"Unknown effect: {effect_name}")
    snapshot = ctl.get_state(light_id)
    log.info("Effect %s on light %s (snapshot=%s)", effect_name, light_id, snapshot)
    try:
        if effect_name == "soft_breathe_white":
            _soft_breathe_white(ctl, light_id)
        elif effect_name == "fast_blink_blue":
            _fast_blink_blue(ctl, light_id)
        elif effect_name == "iss_sequence":
            _iss_sequence(ctl, light_id)
        elif effect_name == "single_flash":
            _single_flash(ctl, light_id)
    finally:
        _restore(ctl, light_id, snapshot)


def _soft_breathe_white(ctl: LightController, light_id: int) -> None:
    ctl.set_state(light_id, on=True, bri=200, ct=366, transitiontime=0)
    ctl.set_state(light_id, alert="lselect")
    time.sleep(15.5)


def _fast_blink_blue(ctl: LightController, light_id: int) -> None:
    for _ in range(5):
        ctl.set_state(light_id, on=True, bri=254, xy=XY_BLUE, transitiontime=0)
        time.sleep(0.2)
        ctl.set_state(light_id, on=False, transitiontime=0)
        time.sleep(0.3)


def _iss_sequence(ctl: LightController, light_id: int) -> None:
    palette = [XY_WHITE, XY_BLUE, XY_WHITE, XY_BLUE, XY_WHITE, XY_BLUE]
    ctl.set_state(light_id, on=True, bri=200, xy=palette[0], transitiontime=0)
    time.sleep(0.5)
    for xy in palette[1:]:
        ctl.set_state(light_id, xy=xy, bri=200, transitiontime=10)
        time.sleep(5.0)


def _single_flash(ctl: LightController, light_id: int) -> None:
    ctl.set_state(light_id, on=True, bri=254, ct=366, transitiontime=0)
    ctl.set_state(light_id, alert="select")
    time.sleep(1.2)


def _restore(ctl: LightController, light_id: int, snapshot: LightState) -> None:
    try:
        ctl.set_state(
            light_id,
            on=snapshot.on,
            bri=snapshot.bri,
            xy=snapshot.xy,
            ct=snapshot.ct,
            transitiontime=4,
            alert="none",
        )
    except Exception as e:
        log.warning("Could not restore light %s state: %s", light_id, e)
