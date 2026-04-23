"""Test buttons for Washing Machine notifications."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    async_add_entities([
        TestNotifyButton(coord, "test_started", "Test: Started notification",
                         lambda c: c.test_notify_started()),
        TestNotifyButton(coord, "test_done", "Test: Done notification",
                         lambda c: c.test_notify_done()),
        TestNotifyButton(coord, "test_reminder", "Test: Reminder notification",
                         lambda c: c.test_notify_reminder()),
        TestNotifyButton(coord, "test_thank_you", "Test: Thank-you notification",
                         lambda c: c.test_notify_thank_you()),
        TestNotifyButton(coord, "test_error", "Test: Error notification",
                         lambda c: c.test_notify_error()),
    ])


class TestNotifyButton(CoordinatorEntity[WashingMachineCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-ring-outline"
    _attr_entity_category = None  # show in normal device panel

    def __init__(self, coord, key: str, name: str, action) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{coord.entry.entry_id}_{key}"
        self._attr_name = name
        self._action = action

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.coordinator.entry.entry_id)},
            "name": "Washing Machine",
            "manufacturer": "custom_components",
            "model": "washing_machine",
        }

    async def async_press(self) -> None:
        self._action(self.coordinator)
