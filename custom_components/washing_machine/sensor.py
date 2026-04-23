"""Sensors for Washing Machine."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import WashingMachineCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: WashingMachineCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        TotalWashesSensor(coord),
        WashesTodaySensor(coord),
        WashesThisWeekSensor(coord),
        WashesThisMonthSensor(coord),
        CurrentCycleTimeSensor(coord),
        TimeSinceDoneSensor(coord),
        AverageCycleTimeSensor(coord),
        LastUnloadTimeSensor(coord),
        AverageUnloadTodaySensor(coord),
        AverageUnloadWeekSensor(coord),
        AverageUnloadMonthSensor(coord),
        AverageUnloadAllTimeSensor(coord),
        RemindersSentSensor(coord),
        StateSensor(coord),
    ])


class _Base(CoordinatorEntity[WashingMachineCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coord: WashingMachineCoordinator, key: str, name: str) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{coord.entry.entry_id}_{key}"
        self._attr_name = name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.coordinator.entry.entry_id)},
            "name": "Washing Machine",
            "manufacturer": "custom_components",
            "model": "washing_machine",
        }


class TotalWashesSensor(_Base):
    _attr_native_unit_of_measurement = "washes"
    _attr_icon = "mdi:washing-machine"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coord): super().__init__(coord, "total_washes", "Total Washes")

    @property
    def native_value(self) -> int:
        return self.coordinator.total_washes


class _WashesSince(_Base):
    _attr_native_unit_of_measurement = "washes"
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL

    def _since(self):
        raise NotImplementedError

    @property
    def native_value(self) -> int:
        return self.coordinator.washes_since(self._since())


class WashesTodaySensor(_WashesSince):
    def __init__(self, coord): super().__init__(coord, "washes_today", "Washes Today")
    def _since(self):
        return dt_util.as_utc(dt_util.start_of_local_day())


class WashesThisWeekSensor(_WashesSince):
    def __init__(self, coord): super().__init__(coord, "washes_this_week", "Washes This Week")
    def _since(self):
        today = dt_util.start_of_local_day()
        monday = today - timedelta(days=today.weekday())
        return dt_util.as_utc(monday)


class WashesThisMonthSensor(_WashesSince):
    def __init__(self, coord): super().__init__(coord, "washes_this_month", "Washes This Month")
    def _since(self):
        today = dt_util.start_of_local_day()
        first = today.replace(day=1)
        return dt_util.as_utc(first)


class CurrentCycleTimeSensor(_Base):
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord): super().__init__(coord, "current_cycle_time", "Current Cycle Time")

    @property
    def native_value(self) -> int:
        return int(round(self.coordinator.current_cycle_duration_min()))


class TimeSinceDoneSensor(_Base):
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coord): super().__init__(coord, "time_since_done", "Time Since Done")

    @property
    def native_value(self):
        v = self.coordinator.time_since_done_min()
        return None if v is None else int(round(v))


class AverageCycleTimeSensor(_Base):
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:chart-timeline-variant"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord): super().__init__(coord, "average_cycle_time", "Average Cycle Time")

    @property
    def native_value(self):
        v = self.coordinator.average_cycle_minutes()
        return None if v is None else int(round(v))


class LastUnloadTimeSensor(_Base):
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-sand"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord): super().__init__(coord, "last_unload_time", "Last Unload Time")

    @property
    def native_value(self):
        h = self.coordinator._state.unload_history
        if not h:
            return None
        return round(float(h[-1].get("unload_min", 0)), 1)


class _AverageUnloadBase(_Base):
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-sand"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def _since(self):
        raise NotImplementedError

    @property
    def native_value(self):
        values = self.coordinator.recent_unload_times(self._since())
        if not values:
            return None
        return round(sum(values) / len(values), 1)


class AverageUnloadTodaySensor(_AverageUnloadBase):
    def __init__(self, coord): super().__init__(coord, "average_unload_today", "Average Unload Today")
    def _since(self):
        return dt_util.utcnow() - timedelta(days=1)


class AverageUnloadWeekSensor(_AverageUnloadBase):
    def __init__(self, coord): super().__init__(coord, "average_unload_week", "Average Unload Week")
    def _since(self):
        return dt_util.utcnow() - timedelta(days=7)


class AverageUnloadMonthSensor(_AverageUnloadBase):
    def __init__(self, coord): super().__init__(coord, "average_unload_month", "Average Unload Month")
    def _since(self):
        return dt_util.utcnow() - timedelta(days=30)


class AverageUnloadAllTimeSensor(_Base):
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-sand"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord): super().__init__(coord, "average_unload_time", "Average Unload Time")

    @property
    def native_value(self):
        v = self.coordinator.average_unload_minutes_alltime()
        return None if v is None else round(v, 1)


class RemindersSentSensor(_Base):
    _attr_icon = "mdi:bell-ring"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = None

    def __init__(self, coord): super().__init__(coord, "reminders_sent", "Reminders Sent")

    @property
    def native_value(self) -> int:
        return self.coordinator.reminders_sent


class StateSensor(_Base):
    _attr_icon = "mdi:state-machine"

    def __init__(self, coord): super().__init__(coord, "state", "State")

    @property
    def native_value(self) -> str:
        return self.coordinator.state
