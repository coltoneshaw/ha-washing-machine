"""Pytest fixtures + minimal HA mocks for testing the coordinator.

We don't install Home Assistant — we stub the symbols coordinator.py uses.
This keeps the test suite fast and self-contained.
"""
from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Stub the `homeassistant` module tree before coordinator.py imports it.
# ---------------------------------------------------------------------------
def _make_ha_stubs():
    ha = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    helpers_event = types.ModuleType("homeassistant.helpers.event")
    helpers_storage = types.ModuleType("homeassistant.helpers.storage")
    helpers_update = types.ModuleType("homeassistant.helpers.update_coordinator")
    config_entries = types.ModuleType("homeassistant.config_entries")
    util = types.ModuleType("homeassistant.util")
    util_dt = types.ModuleType("homeassistant.util.dt")
    ha_const = types.ModuleType("homeassistant.const")

    class _Platform:
        BINARY_SENSOR = "binary_sensor"
        BUTTON = "button"
        SENSOR = "sensor"
        SWITCH = "switch"
    ha_const.Platform = _Platform

    class _UnitOfTime:
        MINUTES = "min"
        SECONDS = "s"
        HOURS = "h"
    ha_const.UnitOfTime = _UnitOfTime

    # homeassistant.core
    def _callback(fn):
        return fn

    class _HomeAssistant:
        def __init__(self):
            self._states: dict[str, Any] = {}
            self.services = SimpleNamespace(async_call=AsyncMock(return_value=None))

        @property
        def states(self):
            parent = self

            class _States:
                def get(_self, entity_id):
                    return parent._states.get(entity_id)

            return _States()

        def set_state(self, entity_id: str, state: str):
            self._states[entity_id] = SimpleNamespace(state=state, entity_id=entity_id)

        def async_create_task(self, coro):
            # Return an already-completed future by scheduling the coro
            return asyncio.ensure_future(coro)

    class _State:
        def __init__(self, state):
            self.state = state

    class _Event:
        pass

    class _ServiceCall:
        def __init__(self, data=None):
            self.data = data or {}

    core.callback = _callback
    core.HomeAssistant = _HomeAssistant
    core.State = _State
    core.Event = _Event
    core.ServiceCall = _ServiceCall

    # helpers.event — we bypass real tracking; tests drive ticks manually
    def _async_track_state_change_event(hass, entity_ids, cb):
        def _unsub():
            return None
        return _unsub

    def _async_track_time_interval(hass, cb, interval):
        def _unsub():
            return None
        return _unsub

    helpers_event.async_track_state_change_event = _async_track_state_change_event
    helpers_event.async_track_time_interval = _async_track_time_interval

    # helpers.storage — in-memory store
    class _Store:
        _memory: dict[str, Any] = {}

        def __init__(self, hass, version, key):
            self._key = key

        async def async_load(self):
            return type(self)._memory.get(self._key)

        async def async_save(self, data):
            type(self)._memory[self._key] = data

    helpers_storage.Store = _Store

    # helpers.update_coordinator — provide a trivial base class
    class _DataUpdateCoordinator:
        def __init__(self, hass, logger, *, name, update_interval):
            self.hass = hass
            self.name = name
            self.update_interval = update_interval
            self.data = None

        def __class_getitem__(cls, item):
            return cls

        async def async_config_entry_first_refresh(self):
            self.data = await self._async_update_data()

        async def async_request_refresh(self):
            self.data = await self._async_update_data()

    helpers_update.DataUpdateCoordinator = _DataUpdateCoordinator
    helpers_update.CoordinatorEntity = object  # not used by coordinator

    # config_entries
    class _ConfigEntry:
        def __init__(self, entry_id: str, data: dict, options: dict | None = None):
            self.entry_id = entry_id
            self.data = data
            self.options = options or {}

        def add_update_listener(self, cb):
            def _unsub(): return None
            return _unsub

        def async_on_unload(self, fn):
            pass

    config_entries.ConfigEntry = _ConfigEntry

    # util.dt — static "now" for determinism
    class _DtUtil:
        _fixed_utc: datetime | None = None

        @classmethod
        def utcnow(cls) -> datetime:
            return cls._fixed_utc or datetime.now(timezone.utc)

        @staticmethod
        def parse_datetime(s: str) -> datetime | None:
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None

        @staticmethod
        def as_local(dt_: datetime) -> datetime:
            return dt_.astimezone()  # system local tz — tests shouldn't rely on hour

        @staticmethod
        def as_utc(dt_: datetime) -> datetime:
            return dt_.astimezone(timezone.utc)

        @staticmethod
        def start_of_local_day(dt_: datetime | None = None) -> datetime:
            if dt_ is None:
                dt_ = datetime.now()
            return dt_.replace(hour=0, minute=0, second=0, microsecond=0)

    util_dt.utcnow = _DtUtil.utcnow
    util_dt.parse_datetime = _DtUtil.parse_datetime
    util_dt.as_local = _DtUtil.as_local
    util_dt.as_utc = _DtUtil.as_utc
    util_dt.start_of_local_day = _DtUtil.start_of_local_day
    util_dt._fixed_utc_holder = _DtUtil  # tests can set via this

    # Register in sys.modules
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.event"] = helpers_event
    sys.modules["homeassistant.helpers.storage"] = helpers_storage
    sys.modules["homeassistant.helpers.update_coordinator"] = helpers_update
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = util_dt
    sys.modules["homeassistant.const"] = ha_const
    # Platforms we don't use from HA directly (binary_sensor/sensor/switch base classes)
    # get stub modules so our platform files don't fail on import. We never instantiate
    # those entities in tests — coordinator is the unit under test.
    for mod_name in (
        "homeassistant.components",
        "homeassistant.components.binary_sensor",
        "homeassistant.components.sensor",
        "homeassistant.components.switch",
        "homeassistant.helpers.entity_platform",
    ):
        m = types.ModuleType(mod_name)
        sys.modules[mod_name] = m
    # Minimum classes we need
    sys.modules["homeassistant.components.binary_sensor"].BinarySensorEntity = object
    sys.modules["homeassistant.components.binary_sensor"].BinarySensorDeviceClass = SimpleNamespace(
        RUNNING="running", PROBLEM="problem",
    )
    sys.modules["homeassistant.components.sensor"].SensorEntity = object
    sys.modules["homeassistant.components.sensor"].SensorDeviceClass = SimpleNamespace()
    sys.modules["homeassistant.components.sensor"].SensorStateClass = SimpleNamespace(
        TOTAL_INCREASING="total_increasing", TOTAL="total", MEASUREMENT="measurement",
    )
    sys.modules["homeassistant.components.switch"].SwitchEntity = object
    sys.modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = object
    m = types.ModuleType("homeassistant.components.button")
    m.ButtonEntity = object
    sys.modules["homeassistant.components.button"] = m


_make_ha_stubs()


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------
import pathlib, sys as _sys
_sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "custom_components"))

from washing_machine import const as C  # noqa: E402
from washing_machine.coordinator import WashingMachineCoordinator  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.helpers.storage import Store  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset the in-memory store between tests."""
    Store._memory = {}
    dt_util._fixed_utc_holder._fixed_utc = None
    yield


@pytest.fixture
def hass():
    return HomeAssistant()


@pytest.fixture
def clock():
    """Return a helper that sets the fake 'now'."""
    holder = dt_util._fixed_utc_holder

    class _Clock:
        t: datetime

        def __init__(self):
            self.t = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
            holder._fixed_utc = self.t

        def advance(self, **kwargs):
            self.t = self.t + timedelta(**kwargs)
            holder._fixed_utc = self.t
            return self.t

        def set(self, dt_: datetime):
            self.t = dt_
            holder._fixed_utc = self.t

    return _Clock()


@pytest.fixture
def entry():
    return ConfigEntry(
        entry_id="test_entry",
        data={
            C.CONF_POWER_SENSOR: "sensor.wm_power",
            C.CONF_DOOR_SENSOR: "binary_sensor.wm_door",
            C.CONF_NOTIFY_TARGETS: ["notify.test"],
            C.CONF_START_POWER_W: 5.0,
            C.CONF_START_DURATION_S: 30,
            C.CONF_END_POWER_W: 2.0,
            C.CONF_END_DURATION_S: 600,
            C.CONF_REMINDER_INTERVAL_M: 60,
            C.CONF_REMINDER_START_HOUR: 0,   # always "daytime" for tests
            C.CONF_REMINDER_END_HOUR: 24,
            C.CONF_ERROR_DURATION_H: 3,
            C.CONF_DOOR_OPEN_STATE: "on",
            C.CONF_STARTING_TOTAL: 0,
        },
    )


@pytest.fixture
async def coord(hass, entry, clock):
    c = WashingMachineCoordinator(hass, entry)
    await c.async_load()
    # Set initial sensor states so _tick doesn't crash
    hass.set_state(entry.data[C.CONF_POWER_SENSOR], "0.5")
    hass.set_state(entry.data[C.CONF_DOOR_SENSOR], "off")
    return c
