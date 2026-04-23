"""Binary sensors for Washing Machine."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity, BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, STATE_RUNNING, STATE_DONE, STATE_ERROR
from .coordinator import WashingMachineCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: WashingMachineCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ActiveSensor(coord),
        NeedsUnloadingSensor(coord),
        CycleErrorSensor(coord),
    ])


class _Base(CoordinatorEntity[WashingMachineCoordinator], BinarySensorEntity):
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


class ActiveSensor(_Base):
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:washing-machine"

    def __init__(self, coord):
        super().__init__(coord, "active", "Active")

    @property
    def is_on(self) -> bool:
        return self.coordinator.state == STATE_RUNNING


class NeedsUnloadingSensor(_Base):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:basket-unfill"

    def __init__(self, coord):
        super().__init__(coord, "needs_unloading", "Needs Unloading")

    @property
    def is_on(self) -> bool:
        return self.coordinator.state == STATE_DONE and not self.coordinator.vacation_mode


class CycleErrorSensor(_Base):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle"

    def __init__(self, coord):
        super().__init__(coord, "cycle_error", "Cycle Error")

    @property
    def is_on(self) -> bool:
        return self.coordinator.state == STATE_ERROR
