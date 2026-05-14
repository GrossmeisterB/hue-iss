"""APScheduler glue: TLE-refresh, pass-recompute, dynamic trigger jobs."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app import db, geo, iss
from app.effects import EFFECT_PRESETS, run_effect
from app.hue import BridgeLightController

log = logging.getLogger(__name__)

PREDICTION_HORIZON = timedelta(hours=48)
PREWARN_OFFSET = timedelta(minutes=5)
PASS_PURGE_KEEP_DAYS = 30


class PassScheduler:
    def __init__(self) -> None:
        self.sched = BackgroundScheduler(timezone="UTC")

    def start(self) -> None:
        self.sched.add_job(
            self.refresh_and_recompute,
            IntervalTrigger(hours=6),
            id="tle_refresh",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=10),
        )
        self.sched.add_job(
            self.reconcile_triggers,
            IntervalTrigger(minutes=10),
            id="reconcile",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        self.sched.add_job(
            self.purge_old_passes,
            IntervalTrigger(hours=24),
            id="purge",
            replace_existing=True,
        )
        self.sched.start()
        log.info("Scheduler started.")

    def shutdown(self) -> None:
        self.sched.shutdown(wait=False)

    # ------------------------------------------------------------------ jobs

    def refresh_and_recompute(self) -> None:
        log.info("Refreshing TLE + recomputing passes")
        loc = geo.stored_location()
        if loc is None:
            log.info("No location set yet; skipping pass computation.")
            return
        try:
            tle = iss.fetch_tle()
        except Exception as e:
            log.error("TLE fetch failed: %s", e)
            db.append_event("tle_fetch_failed", {"error": str(e)})
            return

        now = datetime.now(timezone.utc)
        try:
            passes = iss.find_visible_passes(
                loc.lat, loc.lon, now, now + PREDICTION_HORIZON, tle=tle
            )
        except Exception as e:
            log.error("Pass computation failed: %s", e)
            db.append_event("pass_compute_failed", {"error": str(e)})
            return

        db.delete_future_untriggered_passes()
        for p in passes:
            db.upsert_pass(
                rise_ts=p.rise_time,
                culminate_ts=p.culminate_time,
                set_ts=p.set_time,
                max_elevation=p.max_elevation,
                azimuth_rise=p.azimuth_rise,
                azimuth_set=p.azimuth_set,
            )
        log.info("Computed %s visible passes in next 48h", len(passes))
        db.append_event("passes_recomputed", {"count": len(passes)})
        self.reconcile_triggers()

    def reconcile_triggers(self) -> None:
        """Ensure each upcoming pass has its T-5 and T+0 trigger jobs."""
        now = datetime.now(timezone.utc)
        existing_job_ids = {j.id for j in self.sched.get_jobs()}
        for row in db.list_upcoming_passes(now, limit=50):
            pid = row["id"]
            rise = datetime.fromisoformat(row["rise_ts"])
            prewarn_at = rise - PREWARN_OFFSET

            prewarn_job_id = f"pass_{pid}_prewarn"
            start_job_id = f"pass_{pid}_start"

            if (
                not row["triggered_prewarn"]
                and prewarn_at > now
                and prewarn_job_id not in existing_job_ids
            ):
                self.sched.add_job(
                    self.fire_effect,
                    DateTrigger(run_date=prewarn_at),
                    args=[pid, "prewarn"],
                    id=prewarn_job_id,
                    replace_existing=True,
                )
            if (
                not row["triggered_start"]
                and rise > now
                and start_job_id not in existing_job_ids
            ):
                self.sched.add_job(
                    self.fire_effect,
                    DateTrigger(run_date=rise),
                    args=[pid, "start"],
                    id=start_job_id,
                    replace_existing=True,
                )

    def fire_effect(self, pass_id: int, kind: str) -> None:
        bridge_ip = db.get_config("bridge_ip")
        bridge_user = db.get_config("bridge_user")
        light_id_s = db.get_config("light_id")
        effect_name = db.get_config("effect_name") or "soft_breathe_white"

        if not (bridge_ip and bridge_user and light_id_s):
            log.warning("Skipping effect: bridge or light not configured.")
            db.append_event("effect_skipped", {"reason": "unconfigured", "pass_id": pass_id, "kind": kind})
            return
        if effect_name not in EFFECT_PRESETS:
            log.warning("Skipping effect: unknown preset %s", effect_name)
            return

        try:
            ctl = BridgeLightController(bridge_ip, bridge_user)
            run_effect(ctl, int(light_id_s), effect_name)
            db.mark_pass_triggered(pass_id, prewarn=(kind == "prewarn"), start=(kind == "start"))
            db.append_event(
                "effect_fired",
                {"pass_id": pass_id, "kind": kind, "effect": effect_name},
            )
        except Exception as e:
            log.exception("Effect failed: %s", e)
            db.append_event("effect_failed", {"pass_id": pass_id, "kind": kind, "error": str(e)})

    def purge_old_passes(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=PASS_PURGE_KEEP_DAYS)
        n = db.delete_passes_before(cutoff)
        if n:
            log.info("Purged %s old passes", n)


_singleton: Optional[PassScheduler] = None


def get_scheduler() -> PassScheduler:
    global _singleton
    if _singleton is None:
        _singleton = PassScheduler()
    return _singleton
