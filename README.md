# impression

Weather display for the Pimoroni Inky Impression (7-color 600x448 e-paper) running on a Raspberry Pi Zero W.

The app subscribes to MQTT topics for weather, AQI, power, pool, and Awair data, then refreshes the display every 15 minutes during active hours (6:30 AM to 10:30 PM).

## Files

- `weather.py` - main display app
- `impression.conf.example` - example runtime config
- `apt.txt` - OS packages required on the Pi
- `requirements.txt` - Python dependencies
- `etc/systemd/system/impression-weather.service` - example systemd unit

## Configuration

Create `impression.conf`:

```ini
[ALL]
mqtt_host = <broker ip>
mqtt_host_port = 1883
heartbeat_url = <uptime kuma push url>

[AWAIR]
mqtt_subs = ["location/Room1", "location/Room2"]
mqtt_ext_subs = ["location/Room3"]
```

## MQTT Topics

- `weewx/sensor`
- `purpleair/sensor`
- `weathergov/forecast`
- `weathergov/warnings`
- `weathergov/temptrend`
- `pool/sensor`
- `rainforest/load`
- `awair/<location>/<room>/sensor`

## Deploy

This repo is deployed from the Ansible workspace:

```bash
cd /home/hirano/dev/ansible
./deploy.sh impression
```
