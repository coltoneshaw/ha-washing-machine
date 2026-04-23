"""Washing Machine integration setup."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN
from .coordinator import WashingMachineCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]

SERVICE_SIMULATE_CYCLE = "simulate_cycle"
SERVICE_MARK_HANDLED = "mark_handled"
SERVICE_RESET_ERROR = "reset_error"
SERVICE_SET_TOTAL = "set_total_washes"


def _get_coords(hass: HomeAssistant, entry_id: str | None) -> list[WashingMachineCoordinator]:
    bucket: dict = hass.data.get(DOMAIN, {})
    if entry_id:
        coord = bucket.get(entry_id)
        return [coord] if coord else []
    return list(bucket.values())


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Washing Machine config entry."""
    coordinator = WashingMachineCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await _async_register_services(hass)
    return True


async def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SIMULATE_CYCLE):
        return

    async def simulate(call: ServiceCall) -> None:
        for c in _get_coords(hass, call.data.get("entry_id")):
            await c.async_simulate_cycle()

    async def mark_handled(call: ServiceCall) -> None:
        for c in _get_coords(hass, call.data.get("entry_id")):
            await c.async_mark_handled()

    async def reset_error(call: ServiceCall) -> None:
        for c in _get_coords(hass, call.data.get("entry_id")):
            await c.async_reset_error()

    async def set_total(call: ServiceCall) -> None:
        total = int(call.data["total"])
        for c in _get_coords(hass, call.data.get("entry_id")):
            await c.async_set_total_washes(total)

    hass.services.async_register(DOMAIN, SERVICE_SIMULATE_CYCLE, simulate,
        schema=vol.Schema({vol.Optional("entry_id"): str}))
    hass.services.async_register(DOMAIN, SERVICE_MARK_HANDLED, mark_handled,
        schema=vol.Schema({vol.Optional("entry_id"): str}))
    hass.services.async_register(DOMAIN, SERVICE_RESET_ERROR, reset_error,
        schema=vol.Schema({vol.Optional("entry_id"): str}))
    hass.services.async_register(DOMAIN, SERVICE_SET_TOTAL, set_total,
        schema=vol.Schema({
            vol.Required("total"): vol.Coerce(int),
            vol.Optional("entry_id"): str,
        }))


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: WashingMachineCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
        # If no coords left, remove services
        if not hass.data[DOMAIN]:
            for svc in (SERVICE_SIMULATE_CYCLE, SERVICE_MARK_HANDLED,
                        SERVICE_RESET_ERROR, SERVICE_SET_TOTAL):
                hass.services.async_remove(DOMAIN, svc)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry on options update."""
    await hass.config_entries.async_reload(entry.entry_id)
