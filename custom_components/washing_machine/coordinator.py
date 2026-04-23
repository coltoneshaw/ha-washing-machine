"""Washing Machine state-machine coordinator.

Responsible for:
- Tracking power-sensor state over time to detect RUNNING <-> DONE transitions
- Tracking door-sensor state to detect unload
- Persisting counters + cycle history across restarts (HA Store)
- Dispatching notifications
- Emitting state-change events for entities to pick up
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
import logging
import random
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, State, Event
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_POWER_SENSOR, CONF_DOOR_SENSOR, CONF_NOTIFY_TARGETS,
    CONF_START_POWER_W, CONF_START_DURATION_S,
    CONF_END_POWER_W, CONF_END_DURATION_S,
    CONF_REMINDER_INTERVAL_M, CONF_REMINDER_START_HOUR, CONF_REMINDER_END_HOUR,
    CONF_ERROR_DURATION_H, CONF_DOOR_OPEN_STATE, CONF_STARTING_TOTAL,
    CONF_EXTRA_REMINDERS, CONF_EXTRA_THANK_YOU,
    DEFAULT_START_POWER_W, DEFAULT_START_DURATION_S,
    DEFAULT_END_POWER_W, DEFAULT_END_DURATION_S,
    DEFAULT_REMINDER_INTERVAL_M, DEFAULT_REMINDER_START_HOUR, DEFAULT_REMINDER_END_HOUR,
    DEFAULT_ERROR_DURATION_H, DEFAULT_DOOR_OPEN_STATE,
    DOMAIN, UPDATE_INTERVAL,
    STATE_IDLE, STATE_RUNNING, STATE_DONE, STATE_ERROR,
    CYCLE_HISTORY_DAYS, UNLOAD_HISTORY_MAX,
    NOTIFY_TAG, NOTIFY_ERROR_TAG, NOTIFY_GROUP,
    REMINDER_MESSAGES, THANK_YOU_TIERS, THANK_YOU_OVERFLOW,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


@dataclass
class CycleRecord:
    """A single completed wash cycle."""
    started: str  # ISO datetime
    completed: str  # ISO datetime
    duration_min: float

    @classmethod
    def from_dict(cls, d: dict) -> "CycleRecord":
        return cls(**d)


@dataclass
class UnloadRecord:
    """A single unload event."""
    completed: str  # ISO datetime of cycle finish
    door_opened: str  # ISO datetime of door open
    unload_min: float

    @classmethod
    def from_dict(cls, d: dict) -> "UnloadRecord":
        return cls(**d)


@dataclass
class PersistedState:
    """State that survives HA restarts."""
    state: str = STATE_IDLE
    total_washes: int = 0
    current_cycle_started: str | None = None  # ISO
    current_cycle_completed: str | None = None  # ISO (set when DONE, cleared when IDLE)
    reminders_sent: int = 0
    vacation_mode: bool = False
    # Candidate transition tracking (timestamps when condition first met)
    pending_start_since: str | None = None
    pending_end_since: str | None = None
    last_reminder_at: str | None = None
    cycle_history: list[dict] = field(default_factory=list)   # List[CycleRecord dict]
    unload_history: list[dict] = field(default_factory=list)  # List[UnloadRecord dict]


def _iso_now() -> str:
    return dt_util.utcnow().isoformat()


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return dt_util.parse_datetime(s)
    except Exception:
        return None


class WashingMachineCoordinator(DataUpdateCoordinator[PersistedState]):
    """Coordinator for the washing machine state machine."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._state = PersistedState()
        self._unsub_state: Any = None
        self._unsub_tick: Any = None

    # ------------------------------------------------------------------
    # Config accessors
    # ------------------------------------------------------------------
    @property
    def _opt(self) -> dict:
        """Current effective config (options override data)."""
        merged = dict(self.entry.data)
        merged.update(self.entry.options)
        return merged

    @property
    def power_sensor(self) -> str:
        return self._opt[CONF_POWER_SENSOR]

    @property
    def door_sensor(self) -> str:
        return self._opt[CONF_DOOR_SENSOR]

    @property
    def notify_targets(self) -> list[str]:
        return list(self._opt.get(CONF_NOTIFY_TARGETS) or [])

    @property
    def start_power_w(self) -> float:
        return float(self._opt.get(CONF_START_POWER_W, DEFAULT_START_POWER_W))

    @property
    def start_duration_s(self) -> int:
        return int(self._opt.get(CONF_START_DURATION_S, DEFAULT_START_DURATION_S))

    @property
    def end_power_w(self) -> float:
        return float(self._opt.get(CONF_END_POWER_W, DEFAULT_END_POWER_W))

    @property
    def end_duration_s(self) -> int:
        return int(self._opt.get(CONF_END_DURATION_S, DEFAULT_END_DURATION_S))

    @property
    def reminder_interval_m(self) -> int:
        return int(self._opt.get(CONF_REMINDER_INTERVAL_M, DEFAULT_REMINDER_INTERVAL_M))

    @property
    def reminder_start_hour(self) -> int:
        return int(self._opt.get(CONF_REMINDER_START_HOUR, DEFAULT_REMINDER_START_HOUR))

    @property
    def reminder_end_hour(self) -> int:
        return int(self._opt.get(CONF_REMINDER_END_HOUR, DEFAULT_REMINDER_END_HOUR))

    @property
    def error_duration_h(self) -> int:
        return int(self._opt.get(CONF_ERROR_DURATION_H, DEFAULT_ERROR_DURATION_H))

    @property
    def door_open_state(self) -> str:
        return str(self._opt.get(CONF_DOOR_OPEN_STATE, DEFAULT_DOOR_OPEN_STATE))

    # ------------------------------------------------------------------
    # Public state accessors (used by entities)
    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state.state

    @property
    def total_washes(self) -> int:
        return self._state.total_washes

    @property
    def vacation_mode(self) -> bool:
        return self._state.vacation_mode

    @property
    def current_cycle_started(self) -> datetime | None:
        return _parse_iso(self._state.current_cycle_started)

    @property
    def current_cycle_completed(self) -> datetime | None:
        return _parse_iso(self._state.current_cycle_completed)

    def washes_since(self, dt: datetime) -> int:
        """Count of completed cycles since the given datetime (UTC)."""
        count = 0
        for rec in self._state.cycle_history:
            t = _parse_iso(rec.get("completed"))
            if t and t >= dt:
                count += 1
        return count

    def recent_unload_times(self, since: datetime) -> list[float]:
        out = []
        for rec in self._state.unload_history:
            t = _parse_iso(rec.get("door_opened"))
            if t and t >= since:
                out.append(float(rec.get("unload_min", 0)))
        return out

    def current_cycle_duration_min(self) -> float:
        t = self.current_cycle_started
        if not t or self.state != STATE_RUNNING:
            return 0.0
        return (dt_util.utcnow() - t).total_seconds() / 60.0

    def time_since_done_min(self) -> float | None:
        t = self.current_cycle_completed
        if not t or self.state != STATE_DONE:
            return None
        return (dt_util.utcnow() - t).total_seconds() / 60.0

    def average_cycle_minutes(self) -> float | None:
        durations = [float(r.get("duration_min", 0)) for r in self._state.cycle_history]
        durations = [d for d in durations if d > 0]
        if not durations:
            return None
        return sum(durations) / len(durations)

    def average_unload_minutes_alltime(self) -> float | None:
        values = [float(r.get("unload_min", 0)) for r in self._state.unload_history]
        values = [v for v in values if v > 0]
        if not values:
            return None
        return sum(values) / len(values)

    @property
    def reminders_sent(self) -> int:
        return self._state.reminders_sent

    def _parse_lines(self, key: str) -> list[str]:
        raw = self._opt.get(key) or ""
        if isinstance(raw, list):
            return [str(s).strip() for s in raw if str(s).strip()]
        return [l.strip() for l in str(raw).splitlines() if l.strip()]

    @property
    def reminder_pool(self) -> list[str]:
        """Default reminders + user extras (merged, random-selected at fire time)."""
        return list(REMINDER_MESSAGES) + self._parse_lines(CONF_EXTRA_REMINDERS)

    @property
    def thank_you_tiers_all(self) -> list[tuple[int, str]]:
        """Default 1-5 tiers + user-added tiers starting at load count 6."""
        tiers = list(THANK_YOU_TIERS)
        extras = self._parse_lines(CONF_EXTRA_THANK_YOU)
        for i, msg in enumerate(extras):
            tiers.append((6 + i, msg))
        return tiers

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if stored:
            try:
                self._state = PersistedState(**stored)
            except TypeError:
                # Unknown/extra keys — filter to known fields
                known = PersistedState().__dict__.keys()
                clean = {k: v for k, v in stored.items() if k in known}
                self._state = PersistedState(**clean)
        else:
            # First run — allow pre-seeding total_washes from options
            seed = int(self._opt.get(CONF_STARTING_TOTAL) or 0)
            if seed > 0:
                self._state.total_washes = seed
                await self._store.async_save(asdict(self._state))

    async def _save(self) -> None:
        await self._store.async_save(asdict(self._state))

    async def async_shutdown(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_tick:
            self._unsub_tick()
            self._unsub_tick = None
        await self._save()

    # ------------------------------------------------------------------
    # Event wiring
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> PersistedState:
        """Called periodically by DataUpdateCoordinator AND whenever we bump it."""
        # First setup: register listeners
        if self._unsub_state is None:
            self._unsub_state = async_track_state_change_event(
                self.hass,
                [self.power_sensor, self.door_sensor],
                self._on_tracked_state,
            )
        # Always run tick logic so time-based transitions happen
        await self._tick()
        return self._state

    @callback
    def _on_tracked_state(self, event: Event) -> None:
        """Called when power or door sensor state changes — schedule tick."""
        self.hass.async_create_task(self.async_request_refresh())

    # ------------------------------------------------------------------
    # State machine tick
    # ------------------------------------------------------------------
    async def _tick(self) -> None:
        now = dt_util.utcnow()
        power = self._read_power()
        door_open = self._read_door_open()

        if self._state.state == STATE_IDLE:
            await self._tick_idle(now, power)
        elif self._state.state == STATE_RUNNING:
            await self._tick_running(now, power)
        elif self._state.state == STATE_DONE:
            await self._tick_done(now, door_open)
        elif self._state.state == STATE_ERROR:
            # ERROR state — user resolves via reset; meanwhile track for recovery
            if power is not None and power < self.end_power_w:
                # Power dropped — accept as end-of-cycle; go to IDLE (lost data)
                self._state.state = STATE_IDLE
                self._state.current_cycle_started = None
                self._state.current_cycle_completed = None
                self._state.pending_end_since = None
                await self._save()

    async def _tick_idle(self, now: datetime, power: float | None) -> None:
        """Watch for start-of-cycle."""
        if power is None:
            return
        if power >= self.start_power_w:
            # Condition met; see if sustained
            if self._state.pending_start_since is None:
                self._state.pending_start_since = now.isoformat()
            else:
                since = _parse_iso(self._state.pending_start_since)
                if since and (now - since).total_seconds() >= self.start_duration_s:
                    await self._transition_to_running(now)
        else:
            self._state.pending_start_since = None

    async def _tick_running(self, now: datetime, power: float | None) -> None:
        """Watch for end-of-cycle OR error timeout."""
        started = self.current_cycle_started
        if started is not None:
            running_for = (now - started).total_seconds()
            if running_for > self.error_duration_h * 3600:
                await self._transition_to_error(now)
                return
        if power is None:
            return
        if power <= self.end_power_w:
            if self._state.pending_end_since is None:
                self._state.pending_end_since = now.isoformat()
            else:
                since = _parse_iso(self._state.pending_end_since)
                if since and (now - since).total_seconds() >= self.end_duration_s:
                    await self._transition_to_done(now)
        else:
            self._state.pending_end_since = None

    async def _tick_done(self, now: datetime, door_open: bool | None) -> None:
        """Watch for door-open to complete unload, plus fire reminders."""
        if door_open is True:
            await self._on_door_opened(now)
            return
        # Reminder logic
        completed = self.current_cycle_completed
        if not completed:
            return
        local = dt_util.as_local(now)
        if not (self.reminder_start_hour <= local.hour < self.reminder_end_hour):
            return
        if self._state.vacation_mode:
            return
        # At least reminder_interval since last reminder (or since completion)
        last = _parse_iso(self._state.last_reminder_at) or completed
        if (now - last).total_seconds() < self.reminder_interval_m * 60:
            return
        # At least 1 hour since completion before first reminder
        if (now - completed).total_seconds() < 3600:
            return
        await self._send_reminder(now)

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------
    async def _transition_to_running(self, now: datetime) -> None:
        _LOGGER.info("Washing machine started")
        self._state.state = STATE_RUNNING
        self._state.current_cycle_started = now.isoformat()
        self._state.current_cycle_completed = None
        self._state.pending_start_since = None
        self._state.pending_end_since = None
        self._state.reminders_sent = 0
        self._state.last_reminder_at = None
        await self._save()
        self._notify(
            title="🧺 Washing Machine Started",
            message="The washing machine has started a cycle.",
            level="passive",
        )

    async def _transition_to_done(self, now: datetime) -> None:
        _LOGGER.info("Washing machine finished")
        started = self.current_cycle_started
        duration_min = 0.0
        if started:
            duration_min = (now - started).total_seconds() / 60.0
        self._state.state = STATE_DONE
        self._state.current_cycle_completed = now.isoformat()
        self._state.pending_end_since = None
        self._state.total_washes += 1
        # Record in history
        self._state.cycle_history.append({
            "started": self._state.current_cycle_started or now.isoformat(),
            "completed": now.isoformat(),
            "duration_min": round(duration_min, 1),
        })
        self._prune_history(now)
        await self._save()
        self._notify(
            title="✅ Washing Machine Done!",
            message=f"Cycle completed in {int(round(duration_min))} minutes. Your laundry is ready!",
            level="active",
        )

    async def _transition_to_error(self, now: datetime) -> None:
        _LOGGER.warning("Washing machine ERROR: cycle exceeded %sh", self.error_duration_h)
        self._state.state = STATE_ERROR
        await self._save()
        self._notify(
            title="⚠️ Washing Machine Alert",
            message=f"Cycle has been running for over {self.error_duration_h} hours. Please check the machine.",
            level="critical",
            tag=NOTIFY_ERROR_TAG,
        )

    async def _on_door_opened(self, now: datetime) -> None:
        completed = self.current_cycle_completed
        unload_min = 0.0
        if completed:
            unload_min = (now - completed).total_seconds() / 60.0
            # Sanity clamp: drop negative or >7d unloads
            if unload_min < 0 or unload_min > 10080:
                unload_min = 0.0
        if unload_min > 0:
            self._state.unload_history.append({
                "completed": completed.isoformat() if completed else now.isoformat(),
                "door_opened": now.isoformat(),
                "unload_min": round(unload_min, 1),
            })
            # Cap history
            if len(self._state.unload_history) > UNLOAD_HISTORY_MAX:
                self._state.unload_history = self._state.unload_history[-UNLOAD_HISTORY_MAX:]
        # Clear done state
        self._state.state = STATE_IDLE
        self._state.current_cycle_started = None
        self._state.current_cycle_completed = None
        self._state.reminders_sent = 0
        self._state.last_reminder_at = None
        await self._save()
        # Thank-you notification
        midnight = dt_util.start_of_local_day(dt_util.as_local(now))
        midnight_utc = dt_util.as_utc(midnight)
        loads_today = self.washes_since(midnight_utc)
        tiers = self.thank_you_tiers_all
        msg = THANK_YOU_OVERFLOW.format(n=loads_today)
        # exact match on tier threshold first; otherwise fall through to overflow
        for threshold, m in tiers:
            if loads_today == threshold:
                msg = m
                break
        avg = self.average_cycle_minutes()
        if avg:
            msg = f"{msg} (Average cycle: {int(round(avg))} min)"
        self._notify(title="👏 Thank You!", message=msg, level="passive")

    async def _send_reminder(self, now: datetime) -> None:
        pool = self.reminder_pool
        msg = random.choice(pool) if pool else random.choice(REMINDER_MESSAGES)
        self._state.reminders_sent += 1
        self._state.last_reminder_at = now.isoformat()
        await self._save()
        self._notify(title="🧺 Laundry Reminder", message=msg, level="time-sensitive")

    def _prune_history(self, now: datetime) -> None:
        cutoff = now - timedelta(days=CYCLE_HISTORY_DAYS)
        pruned = []
        for rec in self._state.cycle_history:
            t = _parse_iso(rec.get("completed"))
            if t and t >= cutoff:
                pruned.append(rec)
        self._state.cycle_history = pruned

    # ------------------------------------------------------------------
    # Sensor readers
    # ------------------------------------------------------------------
    def _read_power(self) -> float | None:
        st = self.hass.states.get(self.power_sensor)
        if st is None or st.state in ("unknown", "unavailable", None, ""):
            return None
        try:
            return float(st.state)
        except (ValueError, TypeError):
            return None

    def _read_door_open(self) -> bool | None:
        st = self.hass.states.get(self.door_sensor)
        if st is None or st.state in ("unknown", "unavailable", None, ""):
            return None
        return st.state == self.door_open_state

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def _notify(
        self,
        *,
        title: str,
        message: str,
        level: str = "passive",
        tag: str = NOTIFY_TAG,
    ) -> None:
        """Fire-and-forget notify to all configured targets."""
        targets = self.notify_targets
        if not targets:
            return
        data = {
            "title": title,
            "message": message,
            "data": {
                "push": {"interruption-level": level},
                "tag": tag,
                "group": NOTIFY_GROUP,
            },
        }
        for target in targets:
            if not target.startswith("notify."):
                _LOGGER.warning("Skipping invalid notify target: %s", target)
                continue
            service = target.split(".", 1)[1]
            self.hass.async_create_task(
                self.hass.services.async_call("notify", service, data, blocking=False)
            )

    # ------------------------------------------------------------------
    # User actions (wired up via switch/button entities or services)
    # ------------------------------------------------------------------
    async def async_set_vacation_mode(self, enabled: bool) -> None:
        self._state.vacation_mode = enabled
        await self._save()
        await self.async_request_refresh()

    async def async_mark_handled(self) -> None:
        """Force-exit DONE state without door-open (manual override)."""
        if self._state.state == STATE_DONE:
            self._state.state = STATE_IDLE
            self._state.current_cycle_started = None
            self._state.current_cycle_completed = None
            self._state.reminders_sent = 0
            self._state.last_reminder_at = None
            await self._save()
            await self.async_request_refresh()

    async def async_reset_error(self) -> None:
        if self._state.state == STATE_ERROR:
            self._state.state = STATE_IDLE
            self._state.current_cycle_started = None
            self._state.current_cycle_completed = None
            self._state.pending_start_since = None
            self._state.pending_end_since = None
            await self._save()
            await self.async_request_refresh()

    async def async_set_total_washes(self, total: int) -> None:
        """Override total_washes counter (for migration)."""
        self._state.total_washes = max(0, int(total))
        await self._save()
        await self.async_request_refresh()

    async def async_simulate_cycle(self) -> None:
        """Force-walk the state machine start → done → door-open for testing."""
        now = dt_util.utcnow()
        # Begin
        self._state.state = STATE_IDLE
        await self._transition_to_running(now)
        # Fake a 1-minute cycle
        fake_completed = now + timedelta(minutes=1)
        self._state.current_cycle_started = now.isoformat()
        self._state.state = STATE_RUNNING
        await self._transition_to_done(fake_completed)
        # Fake a 30-second unload
        fake_open = fake_completed + timedelta(seconds=30)
        await self._on_door_opened(fake_open)
