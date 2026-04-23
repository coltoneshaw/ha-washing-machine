"""Config + Options flow for Washing Machine integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
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
)


def _notify_service_options(hass) -> list[str]:
    """Return all currently-registered notify.* service names as 'notify.xxx'."""
    try:
        services = hass.services.async_services().get("notify", {}) or {}
    except Exception:  # hass may be None in some contexts
        services = {}
    return sorted(f"notify.{name}" for name in services.keys())


def _base_schema(defaults: dict | None = None, notify_options: list[str] | None = None) -> vol.Schema:
    d = defaults or {}
    notify_opts = notify_options or []
    return vol.Schema({
        vol.Required(CONF_POWER_SENSOR,
                     default=d.get(CONF_POWER_SENSOR)):
            selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
        vol.Required(CONF_DOOR_SENSOR,
                     default=d.get(CONF_DOOR_SENSOR)):
            selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
        vol.Optional(CONF_NOTIFY_TARGETS,
                     default=d.get(CONF_NOTIFY_TARGETS, [])):
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=notify_opts,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        vol.Required(CONF_START_POWER_W,
                     default=d.get(CONF_START_POWER_W, DEFAULT_START_POWER_W)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.1, max=100, step=0.1, mode="box",
                                              unit_of_measurement="W")
            ),
        vol.Required(CONF_START_DURATION_S,
                     default=d.get(CONF_START_DURATION_S, DEFAULT_START_DURATION_S)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=600, step=1, mode="box",
                                              unit_of_measurement="s")
            ),
        vol.Required(CONF_END_POWER_W,
                     default=d.get(CONF_END_POWER_W, DEFAULT_END_POWER_W)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.1, max=100, step=0.1, mode="box",
                                              unit_of_measurement="W")
            ),
        vol.Required(CONF_END_DURATION_S,
                     default=d.get(CONF_END_DURATION_S, DEFAULT_END_DURATION_S)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=3600, step=10, mode="box",
                                              unit_of_measurement="s")
            ),
        vol.Required(CONF_REMINDER_INTERVAL_M,
                     default=d.get(CONF_REMINDER_INTERVAL_M, DEFAULT_REMINDER_INTERVAL_M)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=720, step=5, mode="box",
                                              unit_of_measurement="min")
            ),
        vol.Required(CONF_REMINDER_START_HOUR,
                     default=d.get(CONF_REMINDER_START_HOUR, DEFAULT_REMINDER_START_HOUR)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=24, step=1, mode="box")
            ),
        vol.Required(CONF_REMINDER_END_HOUR,
                     default=d.get(CONF_REMINDER_END_HOUR, DEFAULT_REMINDER_END_HOUR)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=24, step=1, mode="box")
            ),
        vol.Required(CONF_ERROR_DURATION_H,
                     default=d.get(CONF_ERROR_DURATION_H, DEFAULT_ERROR_DURATION_H)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=24, step=1, mode="box",
                                              unit_of_measurement="h")
            ),
        vol.Required(CONF_DOOR_OPEN_STATE,
                     default=d.get(CONF_DOOR_OPEN_STATE, DEFAULT_DOOR_OPEN_STATE)):
            selector.SelectSelector(
                selector.SelectSelectorConfig(options=["on", "off"])
            ),
        vol.Optional(CONF_STARTING_TOTAL,
                     default=d.get(CONF_STARTING_TOTAL, 0)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=1000000, step=1, mode="box")
            ),
        vol.Optional(CONF_EXTRA_REMINDERS,
                     default=d.get(CONF_EXTRA_REMINDERS, "")):
            selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
        vol.Optional(CONF_EXTRA_THANK_YOU,
                     default=d.get(CONF_EXTRA_THANK_YOU, "")):
            selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
    })


class WashingMachineConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Washing Machine config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            # one entry per unique power sensor
            await self.async_set_unique_id(user_input[CONF_POWER_SENSOR])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Washing Machine",
                data=user_input,
            )
        return self.async_show_form(
            step_id="user",
            data_schema=_base_schema(notify_options=_notify_service_options(self.hass)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> "WashingMachineOptionsFlow":
        return WashingMachineOptionsFlow(entry)


class WashingMachineOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        merged = dict(self.entry.data)
        merged.update(self.entry.options)
        return self.async_show_form(
            step_id="init",
            data_schema=_base_schema(
                defaults=merged,
                notify_options=_notify_service_options(self.hass),
            ),
        )
