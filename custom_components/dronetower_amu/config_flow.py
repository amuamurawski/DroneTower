"""Config flow for DroneTower-AMU."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LOCATION, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DroneTowerClient, DroneTowerError
from .const import (
    CONF_INCLUDE_OVERDUE,
    CONF_INCLUDE_PLANNED,
    CONF_RADIUS,
    DEFAULT_INCLUDE_OVERDUE,
    DEFAULT_INCLUDE_PLANNED,
    DEFAULT_NAME,
    DEFAULT_RADIUS,
    DOMAIN,
)


def _location_schema(
    latitude: float,
    longitude: float,
    radius: float,
    include_overdue: bool,
    include_planned: bool,
    with_name: bool = False,
) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=DEFAULT_NAME)] = str
    return vol.Schema(
        {
            **fields,
            vol.Required(
                CONF_LOCATION,
                default={
                    CONF_LATITUDE: latitude,
                    CONF_LONGITUDE: longitude,
                    CONF_RADIUS: radius,
                },
            ): selector.LocationSelector(
                selector.LocationSelectorConfig(radius=True, icon="mdi:quadcopter")
            ),
            vol.Required(
                CONF_INCLUDE_PLANNED, default=include_planned
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_INCLUDE_OVERDUE, default=include_overdue
            ): selector.BooleanSelector(),
        }
    )


def _options_from_input(user_input: dict[str, Any]) -> dict[str, Any]:
    location = user_input[CONF_LOCATION]
    return {
        CONF_LATITUDE: location[CONF_LATITUDE],
        CONF_LONGITUDE: location[CONF_LONGITUDE],
        CONF_RADIUS: location.get(CONF_RADIUS, DEFAULT_RADIUS),
        CONF_INCLUDE_PLANNED: user_input[CONF_INCLUDE_PLANNED],
        CONF_INCLUDE_OVERDUE: user_input[CONF_INCLUDE_OVERDUE],
    }


class DroneTowerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            client = DroneTowerClient(async_get_clientsession(self.hass))
            try:
                await client.async_get_checkins()
            except DroneTowerError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_NAME: user_input[CONF_NAME]},
                    options=_options_from_input(user_input),
                )

        schema = _location_schema(
            self.hass.config.latitude,
            self.hass.config.longitude,
            DEFAULT_RADIUS,
            DEFAULT_INCLUDE_OVERDUE,
            DEFAULT_INCLUDE_PLANNED,
            with_name=True,
        )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DroneTowerOptionsFlow:
        return DroneTowerOptionsFlow()


class DroneTowerOptionsFlow(OptionsFlow):
    """Let the user move the monitored point or retune the filters."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=_options_from_input(user_input))

        options = self.config_entry.options
        schema = _location_schema(
            options[CONF_LATITUDE],
            options[CONF_LONGITUDE],
            options.get(CONF_RADIUS, DEFAULT_RADIUS),
            options.get(CONF_INCLUDE_OVERDUE, DEFAULT_INCLUDE_OVERDUE),
            options.get(CONF_INCLUDE_PLANNED, DEFAULT_INCLUDE_PLANNED),
        )
        return self.async_show_form(step_id="init", data_schema=schema)
