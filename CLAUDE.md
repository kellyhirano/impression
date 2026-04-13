# CLAUDE.md

## Overview

Weather display for Pimoroni Inky Impression (7-color e-paper, 600×448px) on Raspberry Pi Zero W. Subscribes to MQTT and refreshes every 15 min during active hours (6:30 AM–10:30 PM).

## Running / Deployment

```bash
# Deploy via Ansible
cd /home/hirano/dev/ansible && ./deploy.sh impression
```

## Configuration (`impression.conf`, gitignored)

```ini
[ALL]
mqtt_host = <ip>
mqtt_host_port = 1883
heartbeat_url = <uptime kuma push url>

[AWAIR]
mqtt_subs = ["location/Room1", "location/Room2"]   # local rooms
mqtt_ext_subs = ["location/Room"]                   # external rooms
```

## Architecture

Single file `weather.py`. Same pattern as `github/inky/weather.py` but adapted for the Impression display.

**Layout (600×448px):**
- Left panel (x=0–184): Outdoor temp (96pt), 1hr/24hr deltas, AQI (EPA+LRAPA), wind gust, rain, power, pool; 5-day temp chart at y=208–292 (ORANGE=past, BLUE=today, GREEN=forecast, BLACK=normals, RED=records)
- Right panel (x=185–598): All Awair rooms — each shows `initial  temp  delta  CO2  humidity%`; kitchen line with indoor temp + time
- Sparklines at y=248: pool temp (RED), outdoor temp (BLUE), power (GREEN) with hi/lo labels
- Divider at y=310
- Bottom (y=310–448): 6 forecast items + weather warnings (in red)

**7-color display:** BLACK most text, RED for alerts/warnings and high CO2 (>1000), YELLOW for moderate CO2 (600–1000).

## Key Differences from `github/inky/`

- `from inky.inky_uc8159 import Inky` — Impression display (UC8159 chip, 7 colors)
- `Inky()` takes no arguments; auto-detects hardware
- No room count limit on external Awair rooms (inky capped at 2)
- Awair lines include humidity in addition to temp/delta/CO2
- 6 forecast items instead of 4
- Config file is `impression.conf` (not `inky.conf`)

## MQTT Topics

- `weewx/sensor` — outdoor/indoor temp, wind, rain
- `purpleair/sensor` — AQI (EPA + LRAPA)
- `weathergov/forecast` — 7-day forecast (from NWS JSON API via weather.pl)
- `weathergov/warnings` — active NWS alerts for the location
- `weathergov/temptrend` — 5-day temp chart data (actual+forecast+normals+records)
- `pool/sensor` — pool temp, pump/heater/light status
- `rainforest/load` — instantaneous kW
- `awair/<location>/<room>/sensor` — indoor air quality per room (local rooms only; ext rooms not drawn)
