"""Switches for Washing Machine."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WashingMachineCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: WashingMachineCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VacationModeSwitch(coord)])


class VacationModeSwitch(CoordinatorEntity[WashingMachineCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:beach"

    def __init__(self, coord: WashingMachineCoordinator) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{coord.entry.entry_id}_vacation_mode"
        self._attr_name = "Vacation Mode"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.coordinator.entry.entry_id)},
            "name": "Washing Machine",
            "manufacturer": "custom_components",
            "model": "washing_machine",
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.vacation_mode

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_vacation_mode(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_vacation_mode(False)
