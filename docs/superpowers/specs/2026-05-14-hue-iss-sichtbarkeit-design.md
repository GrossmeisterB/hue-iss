# Hue ISS Sichtbarkeit — Design

**Datum:** 2026-05-14
**Status:** Approved (broad approval via "Leg los"; awaiting fine-grain redirect from user)
**Vault-Notiz:** `02 Projekte/Hue ISS Sichtbarkeit.md`

## Ziel

Lokale Web-App auf Synology (interner LAN-Zugriff via IP). Wenn die Internationale Raumstation am Wohnort visuell sichtbar wird (wie ein Stern, ohne Teleskop), löst eine wählbare Hue-Lampe einen wählbaren transienten Lichteffekt aus.

## Funktionale Anforderungen

1. **Trigger:** Lampe macht den gewählten Effekt 5 Minuten vor sichtbarem Pass und nochmal beim eigentlichen Pass-Beginn (zwei Signale).
2. **Sichtbarkeit:** Pass zählt nur als sichtbar wenn alle drei Bedingungen gleichzeitig gelten:
   - ISS-Elevation ≥ 10° über lokalem Horizont
   - ISS wird von der Sonne beleuchtet (nicht im Erdschatten)
   - Beobachter im Zwielicht oder dunkler (Sonne ≥ 6° unter Horizont)
3. **Dashboard-Konfiguration:**
   - Hue-Lampe wählbar (Dropdown aller Lampen der gepairten Bridge)
   - Lichteffekt wählbar aus 4 Presets
   - Standort einstellbar (Cascade: IP-Geo → Browser-Geo → manueller Karten-Pin)
4. **Hue-Pairing:** One-Click-Discovery + Link-Button-Flow, persistiert.

## Tech-Stack

| Schicht | Wahl | Begründung |
|---|---|---|
| Backend | Python 3.11 + Flask | Roland's eingespielter Stack (Briefingsheet, SafariRadar, crew-log) |
| Astronomy | `skyfield` | TLE-Propagation + Topozentrik + Earth-Shadow + Twilight in einer Library |
| Hue | `phue` für V1 Local API | Synchron, simpel, ausreichend für Effekt-Loops |
| Scheduler | APScheduler | In-process Jobs, kein extra Cron-Container |
| Storage | SQLite | Single-File, leicht backupbar |
| Web-UI | Server-rendered Jinja + Alpine.js CSP-Build | Roland-Pattern (Zugfrei), kein Build-Step |
| Deployment | Docker Compose auf DS220 | `/volume1/docker/hue-iss/` Layout |

## Kern-Module

### `app/iss.py` — Pass-Prediction
- Lädt ISS-TLE von Celestrak (`https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE`), Cache 6h
- `find_passes(observer_lat, observer_lon, t_from, t_to) -> list[VisiblePass]`
- Eine `VisiblePass` enthält: `rise_time`, `culminate_time`, `set_time`, `max_elevation`, `azimuth_rise`, `azimuth_set`
- Filtert intern: nur Pässe wo ALLE drei Sichtbarkeits-Bedingungen während Elevation>10° gegeben sind

### `app/hue.py` — Bridge + Lampen
- `discover_bridges() -> list[BridgeInfo]` via meethue-Cloud + mDNS-Fallback
- `pair_bridge(ip) -> username` (Link-Button-Flow)
- `list_lights(bridge_ip, username) -> list[Light]`
- `apply_effect(bridge_ip, username, light_id, effect_name)` — Snapshot-Restore-Pattern

### `app/effects.py` — 4 Presets
| Name | Logik |
|---|---|
| `soft_breathe_white` | `lselect` alert mit ct=366, 15s |
| `fast_blink_blue` | 5× (xy=blau, bri=254, sleep 200ms, off, sleep 300ms) |
| `iss_sequence` | weiss 5s → blau 5s → weiss 5s → blau 5s → weiss 5s → blau 5s, transition 1s |
| `single_flash` | `alert='select'`, single |

Vor Effekt: aktuellen State der Lampe in Memory snapshotten (`on, bri, xy, ct, sat, hue`). Nach Effekt: restoren. Wenn Lampe vor Effekt off war: am Ende wieder off.

### `app/geo.py` — Standort
- `resolve_location()` cascade: gespeicherter Wert → IP-Geo (`https://ipapi.co/json/`) → None
- Browser-Side: Geolocation API als Knopf im Dashboard (funktioniert nur unter HTTPS oder localhost)
- Karten-Override: Leaflet + OSM-Tiles, Click setzt Pin → POST → DB

### `app/scheduler.py` — APScheduler-Glue
- Job 1 (alle 6h): `refresh_tle_and_recompute_passes()` → schreibt nächste 48h Pässe in DB
- Job 2 (alle 1h): `reconcile_jobs()` — stellt sicher, dass für jeden zukünftigen Pass zwei ad-hoc Jobs registriert sind (T−5min + T+0)
- Pass-Trigger-Job ruft `effects.apply_effect(...)` und loggt Pass-Event

### `app/db.py` — SQLite-Layer
Tabellen:
- `config` (key, value) — singleton settings (bridge_ip, bridge_user, light_id, effect_name, lat, lon, location_label)
- `passes` (id, rise_ts, set_ts, culminate_ts, max_elev, az_rise, az_set, triggered_prewarn, triggered_start)
- `events` (id, ts, kind, payload_json) — Audit-Trail

### `app/web.py` — Flask-Routes
- `GET /` — Dashboard
- `POST /api/bridge/discover` — sucht Bridges
- `POST /api/bridge/pair` — pairt (User muss vorher Link-Button drücken)
- `POST /api/config` — speichert Lampe/Effekt/Standort
- `POST /api/effect/test` — feuert gewählten Effekt sofort (für UX-Verifikation)
- `GET /api/passes/next` — JSON für Dashboard-Live-Update
- `GET /healthz` — Bridge erreichbar? Scheduler läuft? TLE-Alter?

### `app/app.py` — Entrypoint
- Flask + ProxyFix (Memory: Synology Reverse Proxy braucht das)
- APScheduler beim Start hochfahren, Hue-Bridge-Reconnect, TLE-Refresh-Initial

## Daten-Fluss

```
TLE-Refresh-Job (alle 6h)
  ↓
  Celestrak GP-API → SQLite
  
Pass-Predictor-Job (alle 1h)
  ↓
  skyfield Pass-Search + 3-fach Filter
  → SQLite: passes
  → APScheduler: 2 Jobs pro Pass (T−5min, T+0)

Trigger-Job (fired by scheduler)
  ↓
  read config → effects.apply(...) → SQLite: events.append
```

## Robustheit

- **TLE-Outage:** wenn Celestrak nicht erreichbar, bestehende TLE weiternutzen + warnen im Dashboard. Pass-Vorhersage degradiert nach ~3 Tagen merklich.
- **Hue-Bridge weg:** Effekt-Fail → Log, kein Crash. Health-Endpoint zeigt Bridge-Status.
- **State-Restore:** Effekt restoriert immer alten Lampen-State, auch bei Exception (try/finally).
- **Pass-Job-Drift:** Bei jedem TLE-Refresh werden Scheduler-Jobs neu berechnet, alte verworfen.
- **CSP:** strict, kein `unsafe-eval`, Alpine.js CSP-Build (Memory: Zugfrei-Pattern).
- **ProxyFix:** `x_for=1` für Synology Reverse Proxy (Memory).
- **Time-Zones:** alles in UTC speichern, nur in der UI in Europe/Zurich anzeigen.

## YAGNI — bewusst NICHT drin

- Mehrere Lampen gleichzeitig (Hue-Group-Feature reicht; eine Lampe = Gruppe falls nötig)
- Push-Notifications / Telegram-Bot
- User-Accounts / Auth (LAN-only)
- HTTPS by default (Caddy-Sidecar optional, dann wird Browser-Geo aktiv)
- Pass-Vorhersage > 48h (TLE-Drift)
- Vergangenheits-Historie >30 Tage (auto-prune)

## Deployment

- `docker-compose.yml` mit Service `hue-iss`, Image lokal gebaut
- Persistentes Volume `/volume1/docker/hue-iss-data/` für `db.sqlite` + TLE-Cache
- Port `5057` intern (Synology Reverse Proxy davor)
- ENV: `FLASK_SECRET` (Memory: kein Default), `IP_GEO_URL`, `TIMEZONE`

## Testing

- pytest-Unit für `iss.py` (vergangene Pässe gegen heavens-above-Referenzdaten)
- pytest-Unit für `effects.py` (Snapshot-Restore-Logik mit Mock-Bridge)
- pytest-Integration für `scheduler.py` (Pässe → Job-Registrierung)
- Manual: Browser-Smoke (Memory: Audit-Pflicht), `effects.test`-Button mit echter Bridge

## Implementation-Reihenfolge

1. Scaffold (deps, Dockerfile, compose, gitignore, README)
2. `app/iss.py` + Tests (verifizierbar ohne Bridge/UI)
3. `app/db.py` (config + passes)
4. `app/effects.py` mit Mock-Bridge (Tests)
5. `app/hue.py` Discovery + Pairing
6. `app/scheduler.py` Glue
7. `app/geo.py` Cascade
8. `app/web.py` + Templates + Alpine.js Dashboard
9. Docker + Compose
10. Synology-Deploy-Script
