# Home Assistant — Washing Machine Integration

A proper Home Assistant custom component that detects washing machine cycles from a smart plug's power sensor + a door contact sensor, and tracks stats with notifications.

Replaces a 820-line YAML package that suffered from:
- Fragile `input_number`-based counters (values drifted past lifetime total)
- `utility_meter` bugs producing inflated daily/weekly counts
- False start/stop triggers from idle power draw between spin cycles
- Unload-time outliers dragging averages to unrealistic values

## Features

Entities provided:
- `binary_sensor.washing_machine_active`
- `binary_sensor.washing_machine_needs_unloading`
- `binary_sensor.washing_machine_cycle_error`
- `sensor.washing_machine_total_washes` (lifetime)
- `sensor.washing_machine_washes_today` / `_this_week` / `_this_month`
- `sensor.washing_machine_current_cycle_time`
- `sensor.washing_machine_time_since_done`
- `sensor.washing_machine_average_cycle_time`
- `sensor.washing_machine_last_unload_time`
- `sensor.washing_machine_average_unload_today` / `_week` / `_month`
- `sensor.washing_machine_state`
- `switch.washing_machine_vacation_mode`

State machine:
```
IDLE ──power > start_threshold for start_duration──> RUNNING
RUNNING ──power < end_threshold for end_duration──> DONE
RUNNING ──runs > error_duration_h──> ERROR
DONE ──door opens──> IDLE (records unload time)
```

All counters and history are persisted via HA's native `Store` API — no `input_number` hacks, no `utility_meter` race conditions. Daily/weekly/monthly counts are derived from a rolling cycle history (last 90 days), so they're always arithmetically consistent with `total_washes`.

## Install

```bash
git clone <this-repo> /tmp/ha-washing-machine
cd /tmp/ha-washing-machine
HA_HOST=10.0.5.12 HA_SSH_USER=root HA_SSH_PASS=your-ssh-pass \
  ./scripts/deploy.sh --restart
```

Then in HA: **Settings → Devices & Services → Add Integration → Washing Machine**.

Fill in:
- **Power sensor** — your smart plug's power entity (e.g. `sensor.washing_machine_outlet_power`)
- **Door sensor** — contact sensor on the washer door (e.g. `binary_sensor.washing_machine_door_sensor_contact`)
- **Door open state** — `on` if sensor reports `on` when door is open (default); flip to `off` for inverted sensors
- **Notification targets** — any `notify.*` services (e.g. `notify.mobile_app_dads_iphone`)
- **Start/end power thresholds and durations** — see tuning guide below
- **Starting total washes** — set to your previous lifetime count if migrating (one-time seed on first install only; ignored on subsequent config-entry reloads)

## Tuning

Defaults target a typical front-loader washer:
| Field | Default | Why |
|---|---|---|
| Start power | 5 W | above idle draw |
| Start duration | 30 s | avoids brief spikes |
| End power | 2 W | below running minimum |
| End duration | 600 s (10 min) | washers idle between spin cycles; too short = false finish |
| Reminder interval | 60 min | hourly reminders |
| Reminder quiet hours | 00:00–07:00 | no nag overnight |
| Error timeout | 3 h | cycle stuck too long |

If cycles are false-finishing mid-wash, increase `end_duration_s`. If reminders are firing too aggressively, widen the quiet hours.

## Deploy script

`scripts/deploy.sh` copies the `custom_components/washing_machine/` folder to the HA host via SSH.

Environment variables:
- `HA_HOST` — required (e.g. `10.0.5.12`)
- `HA_SSH_USER` — default `root`
- `HA_SSH_PASS` — SSH password (or use key auth)
- `HA_TOKEN` — long-lived access token (only needed for `--restart`)
- `HA_URL` — default `https://$HA_HOST`

Flags:
- `--restart` — reload HA core after deploy (needed for Python code changes)

## Development

```bash
# Syntax check
python3 -m py_compile custom_components/washing_machine/*.py

# Deploy without restart (fast iteration on non-entity changes)
./scripts/deploy.sh

# Deploy with restart (Python code change)
HA_TOKEN=eyJ... ./scripts/deploy.sh --restart
```

## Migrating from the YAML package

1. Install this integration; note new entity IDs are `*_2` (HA suffixes on conflict).
2. Rename old YAML-derived entities to `_legacy` (via Developer Tools → Entities), then rename new entities to the clean names.
3. Remove the `packages/washing_machine.yaml` file (or comment out its contents).
4. Remove leftover `input_datetime.washing_machine_*`, `input_number.washing_machine_*`, `input_boolean.washing_machine_*` helpers via UI.
5. Set "Starting total washes" in integration options to your previous lifetime total.

Dashboard cards referencing old entity IDs need to be updated.
