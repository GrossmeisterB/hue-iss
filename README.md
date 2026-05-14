# hue-iss

Local web app for Synology that triggers a Philips Hue lamp effect whenever the International Space Station becomes visible (as a star, naked-eye) from your home.

## Was die App macht

Berechnet jeden sichtbaren ISS-Pass an deinem Wohnort und lässt eine wählbare Hue-Lampe 5 Minuten vor und beim Pass-Start einen wählbaren Lichteffekt ausführen.

**„Sichtbar"** = alle drei gleichzeitig:
- ISS-Elevation ≥ 10° über Horizont
- ISS von Sonne beleuchtet (nicht im Erdschatten)
- Beobachter im Zwielicht oder dunkler

## Effekt-Presets

| Name | Effekt |
|---|---|
| Sanftes Pulsieren weiss | 15s breathe, warmweiss |
| Schneller Blink blau | 5× kurzer Blau-Blink |
| ISS-Sequenz | weiss↔blau, 30s |
| Single Flash | 1× kurzer Hell-Puls |

## Setup

### Lokal (Mac)

```bash
cd ~/Developer/hue-iss
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # FLASK_SECRET setzen
python -m app.app
```

Dashboard: <http://localhost:5057>

### Synology

```bash
ssh rolandbieg@192.168.0.12
cd /volume1/docker/hue-iss
cp .env.example .env  # FLASK_SECRET setzen
sudo docker compose up -d --build
```

Dashboard: `http://192.168.0.12:5057`

## Hue-Pairing

1. Dashboard → „Bridge suchen"
2. Link-Button auf der Bridge drücken
3. „Pairing bestätigen" klicken (innerhalb 30s)
4. Lampe + Effekt wählen → speichern

## Standort

Auto-Detection via IP-Geolocation auf ersten Aufruf. Override:
- Browser-Geolocation-Knopf (nur unter HTTPS)
- Karten-Pin verschieben
- Adresse eingeben

## Architektur

Siehe [`docs/superpowers/specs/2026-05-14-hue-iss-sichtbarkeit-design.md`](docs/superpowers/specs/2026-05-14-hue-iss-sichtbarkeit-design.md).

## Tests

```bash
pytest
```
