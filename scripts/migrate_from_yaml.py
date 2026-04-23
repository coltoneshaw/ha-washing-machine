#!/usr/bin/env python3
"""One-time migration from the legacy YAML package to the washing_machine
custom integration.

Reads Home Assistant's recorder SQLite DB and reconstructs:
  - cycle_history: one entry per wash cycle completed (timestamp + duration)
  - unload_history: one entry per unload (completed/door-opened/duration)
  - total_washes: floor seeded from current total

Writes a Store JSON compatible with coordinator.PersistedState.

Usage:
  HA_HOST=10.0.5.12 HA_SSH_USER=root HA_SSH_PASS=password \\
  HA_URL=https://ha.silverhollow.xyz HA_TOKEN=<llat> \\
    ./scripts/migrate_from_yaml.py [--outlier-min 720] [--dry-run]

Flow:
  1. Use HA REST API to locate the washing_machine config_entry_id.
  2. SCP /config/home-assistant_v2.db locally (read-only copy).
  3. Query recorder tables for state history of the legacy sensors.
  4. Build the persisted-state JSON.
  5. Upload to /config/.storage/washing_machine.<entry_id>.
  6. Trigger HA restart so the integration loads with migrated history.

Non-destructive to the legacy package — that must be disabled separately.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

LEGACY_TOTAL = "sensor.washing_machine_total_washes"
LEGACY_UNLOAD = "sensor.washing_machine_last_unload_time"
LEGACY_CYCLE_TIME = "sensor.washing_machine_current_cycle_time"
LEGACY_AVG_CYCLE = "sensor.washing_machine_average_cycle_time"


def env(name: str, required: bool = True, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if required and not v:
        print(f"ERROR: {name} env var is required", file=sys.stderr)
        sys.exit(2)
    return v or ""


def ssh_cmd(base_cmd: list[str], *, user: str, host: str, password: str | None) -> list[str]:
    ssh_opts = [
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=5",
    ]
    if password:
        if not shutil.which("sshpass"):
            print("ERROR: sshpass not found — install it or use key-based auth", file=sys.stderr)
            sys.exit(2)
        return ["sshpass", "-p", password, *base_cmd, *ssh_opts]
    return [*base_cmd, *ssh_opts]


def ha_api_get(url: str, token: str, path: str) -> object:
    req = Request(f"{url}{path}", headers={"Authorization": f"Bearer {token}"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urlopen(req, context=ctx, timeout=15) as r:
        return json.loads(r.read())


def ha_api_post(url: str, token: str, path: str, body: dict | None = None) -> int:
    data = json.dumps(body or {}).encode()
    req = Request(
        f"{url}{path}", data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urlopen(req, context=ctx, timeout=15) as r:
            return r.status
    except Exception as e:
        # Restart will close the connection; that's expected
        print(f"(expected on restart) {e}")
        return 0


def find_entry_id(url: str, token: str) -> str:
    entries = ha_api_get(url, token, "/api/config/config_entries/entry")
    assert isinstance(entries, list)
    matches = [e for e in entries if e.get("domain") == "washing_machine"]
    if not matches:
        print(
            "ERROR: no washing_machine config_entry found. Add the integration via "
            "Settings → Devices & Services first, then re-run.", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print("WARN: multiple washing_machine entries found, using the first", file=sys.stderr)
    return matches[0]["entry_id"]


def fetch_db(user: str, host: str, password: str | None, dest: Path) -> None:
    remote = "/config/home-assistant_v2.db"
    # Copy to a temp location on remote first to avoid reading an actively-written WAL
    cmd_remote = (
        f"cp -a {remote} /tmp/ha_recorder_migrate.db && "
        f"sqlite3 /tmp/ha_recorder_migrate.db 'PRAGMA wal_checkpoint(TRUNCATE);' >/dev/null"
    )
    print(f"==> snapshotting recorder DB on {host}")
    subprocess.run(
        ssh_cmd(["ssh"], user=user, host=host, password=password) +
        [f"{user}@{host}", cmd_remote],
        check=True,
    )
    print(f"==> copying snapshot locally to {dest}")
    subprocess.run(
        ssh_cmd(["scp"], user=user, host=host, password=password) +
        [f"{user}@{host}:/tmp/ha_recorder_migrate.db", str(dest)],
        check=True,
    )
    subprocess.run(
        ssh_cmd(["ssh"], user=user, host=host, password=password) +
        [f"{user}@{host}", "rm -f /tmp/ha_recorder_migrate.db"],
        check=False,
    )


def query_history(db: Path, entity_id: str) -> list[tuple[float, str]]:
    """Return list of (unix_ts, state_value_string) ordered ASC."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        # Find metadata_id (modern recorder schema)
        cur.execute("SELECT metadata_id FROM states_meta WHERE entity_id = ?", (entity_id,))
        row = cur.fetchone()
        if not row:
            return []
        mid = row[0]
        cur.execute(
            "SELECT last_updated_ts, state FROM states "
            "WHERE metadata_id = ? AND state NOT IN ('unknown','unavailable','') "
            "ORDER BY last_updated_ts ASC",
            (mid,),
        )
        return [(float(ts), s) for ts, s in cur.fetchall()]
    finally:
        conn.close()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def reconstruct(
    db: Path,
    outlier_min: float,
    live_total: int | None = None,
    live_avg_cycle: float | None = None,
) -> tuple[int, list[dict], list[dict]]:
    """Return (final_total_washes, cycle_history, unload_history).

    If live_total is provided, it overrides the recorder value (recorder may
    not be tracking the total_washes sensor).
    """
    # Total washes: each increment from N to N+1 = cycle completed
    totals = query_history(db, LEGACY_TOTAL)
    cycle_times = query_history(db, LEGACY_CYCLE_TIME)
    unloads = query_history(db, LEGACY_UNLOAD)
    avgs = query_history(db, LEGACY_AVG_CYCLE)

    if live_total is not None:
        final_total = max(live_total, int(float(totals[-1][1])) if totals else 0)
    else:
        final_total = int(float(totals[-1][1])) if totals else 0
    fallback_duration = float(live_avg_cycle) if live_avg_cycle else 78.0
    if avgs:
        try:
            fallback_duration = float(avgs[-1][1])
        except (ValueError, TypeError):
            pass

    # Build cycle_history from total transitions
    cycle_history: list[dict] = []
    prev = 0
    for ts, s in totals:
        try:
            n = int(float(s))
        except (ValueError, TypeError):
            continue
        if n > prev:
            # Each step from prev -> n likely represents (n - prev) cycles,
            # but they usually come one at a time; handle the multi-increment edge case.
            duration = fallback_duration
            # Find the last cycle_time reading just before this timestamp
            preceding = [v for v_ts, v in cycle_times if v_ts <= ts]
            if preceding:
                try:
                    d = float(preceding[-1])
                    if 5 <= d <= 300:
                        duration = d
                except (ValueError, TypeError):
                    pass
            for _ in range(n - prev):
                cycle_history.append({
                    "started": iso(ts - duration * 60),
                    "completed": iso(ts),
                    "duration_min": round(duration, 1),
                })
        prev = n

    # Build unload_history from last_unload_time transitions
    unload_history: list[dict] = []
    seen_change = False
    for ts, s in unloads:
        try:
            v = float(s)
        except (ValueError, TypeError):
            continue
        # First sample may be a restore value, not a real unload — skip it.
        if not seen_change:
            seen_change = True
            continue
        if v <= 0:
            continue
        if v > outlier_min:
            # Outlier — skip (fixes the 582-min avg bug)
            continue
        # door_opened = ts, completed = ts - v minutes
        unload_history.append({
            "completed": iso(ts - v * 60),
            "door_opened": iso(ts),
            "unload_min": round(v, 1),
        })

    return final_total, cycle_history, unload_history


def build_store(total_washes: int, cycles: list[dict], unloads: list[dict]) -> dict:
    return {
        "version": 1,
        "minor_version": 1,
        "key": "",  # filled at write time
        "data": {
            "state": "idle",
            "total_washes": total_washes,
            "current_cycle_started": None,
            "current_cycle_completed": None,
            "reminders_sent": 0,
            "vacation_mode": False,
            "pending_start_since": None,
            "pending_end_since": None,
            "last_reminder_at": None,
            "cycle_history": cycles,
            "unload_history": unloads,
        },
    }


def write_store(url: str, token: str, entry_id: str, body: dict,
                user: str, host: str, password: str | None) -> None:
    storage_key = f"washing_machine.{entry_id}"
    body["key"] = storage_key
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(body, f, indent=2)
        local_path = f.name
    remote_path = f"/config/.storage/{storage_key}"
    print(f"==> uploading store file to {remote_path}")
    subprocess.run(
        ssh_cmd(["scp"], user=user, host=host, password=password) +
        [local_path, f"{user}@{host}:{remote_path}"],
        check=True,
    )
    # Ensure owner perms are sane (HA runs as root in container)
    subprocess.run(
        ssh_cmd(["ssh"], user=user, host=host, password=password) +
        [f"{user}@{host}", f"chmod 600 {shlex.quote(remote_path)}"],
        check=False,
    )
    os.unlink(local_path)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--outlier-min", type=float, default=720.0,
                   help="drop unload values > this many minutes (default 720 = 12h)")
    p.add_argument("--dry-run", action="store_true",
                   help="print summary, don't upload or restart")
    p.add_argument("--no-restart", action="store_true",
                   help="upload store file but skip HA restart")
    args = p.parse_args()

    host = env("HA_HOST")
    user = env("HA_SSH_USER", default="root")
    password = os.environ.get("HA_SSH_PASS")
    url = env("HA_URL", default=f"https://{host}")
    token = env("HA_TOKEN")

    entry_id = find_entry_id(url, token)
    print(f"==> target config_entry_id: {entry_id}")

    # Pull live totals as fallback seed (recorder may not track total sensor)
    live_total = None
    live_avg = None
    try:
        s = ha_api_get(url, token, f"/api/states/{LEGACY_TOTAL}")
        if isinstance(s, dict) and s.get("state") not in ("unavailable", "unknown", None):
            live_total = int(float(s["state"]))
    except Exception:
        pass
    try:
        s = ha_api_get(url, token, f"/api/states/{LEGACY_AVG_CYCLE}")
        if isinstance(s, dict) and s.get("state") not in ("unavailable", "unknown", None):
            live_avg = float(s["state"])
    except Exception:
        pass
    print(f"==> live total_washes={live_total}  live avg_cycle_min={live_avg}")

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "recorder.db"
        fetch_db(user, host, password, db_path)
        print(f"==> reading history (outlier threshold: {args.outlier_min} min)")
        total, cycles, unloads = reconstruct(
            db_path, args.outlier_min, live_total=live_total, live_avg_cycle=live_avg)

    print(f"==> reconstructed: total_washes={total}  cycles={len(cycles)}  unloads={len(unloads)}")
    if cycles:
        print(f"    earliest cycle: {cycles[0]['completed']}")
        print(f"    latest cycle:   {cycles[-1]['completed']}")
    if unloads:
        mins = [u["unload_min"] for u in unloads]
        print(f"    unload min/max/avg (min): {min(mins):.1f} / {max(mins):.1f} / {sum(mins)/len(mins):.1f}")

    body = build_store(total, cycles, unloads)
    if args.dry_run:
        print("(dry-run) would upload the above to /config/.storage/washing_machine." + entry_id)
        return 0

    write_store(url, token, entry_id, body, user, host, password)

    if args.no_restart:
        print("==> skipping restart (--no-restart). Restart HA to load migrated state.")
        return 0

    print("==> restarting HA to load migrated state")
    ha_api_post(url, token, "/api/services/homeassistant/restart")
    print("==> submitted. Wait ~2-3 minutes for HA to come back, then verify sensors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
