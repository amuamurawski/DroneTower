"""Config flow for DroneTower-AMU."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_EMAIL,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_PASSWORD,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DroneTowerAuthError, DroneTowerClient, DroneTowerError
from .const import (
    CONF_HISTORY_DAYS,
    CONF_INCLUDE_OVERDUE,
    CONF_INCLUDE_PLANNED,
    CONF_RADIUS,
    CONF_STORE_PHONE,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_INCLUDE_OVERDUE,
    DEFAULT_INCLUDE_PLANNED,
    DEFAULT_NAME,
    DEFAULT_RADIUS,
    DEFAULT_STORE_PHONE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_EMAIL_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
)
_PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


def _credentials_fields(email_default: str = "") -> dict[Any, Any]:
    """Email + password — the DroneTower account the app itself signs in with."""
    return {
        vol.Required(CONF_EMAIL, default=email_default): _EMAIL_SELECTOR,
        vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
    }


async def _async_validate_credentials(hass, email: str, password: str) -> str | None:
    """Try to log in. Returns an error key for the form, or None on success."""
    client = DroneTowerClient(async_get_clientsession(hass), email, password)
    try:
        await client.async_login()
    except DroneTowerAuthError as err:
        _LOGGER.debug("DroneTower rejected the credentials: %s", err)
        return "invalid_auth"
    except DroneTowerError as err:
        # Not an auth failure — surface the real reason, since the form only shows a
        # generic "cannot connect".
        _LOGGER.warning("DroneTower login could not reach the backend: %s", err)
        return "cannot_connect"
    return None


def _history_fields(history_days: int, store_phone: bool) -> dict[Any, Any]:
    """Retention and phone storage — Options only.

    Deliberately absent from first-time setup: whether to keep pilots' phone
    numbers is a considered decision, not something to tick past while adding an
    integration.
    """
    return {
        vol.Required(CONF_HISTORY_DAYS, default=history_days): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=3650, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Required(CONF_STORE_PHONE, default=store_phone): selector.BooleanSelector(),
    }


def _location_schema(
    latitude: float,
    longitude: float,
    radius: float,
    include_overdue: bool,
    include_planned: bool,
    with_name: bool = False,
    with_credentials: bool = False,
    history: dict[Any, Any] | None = None,
) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=DEFAULT_NAME)] = str
    if with_credentials:
        fields.update(_credentials_fields())
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
            **(history or {}),
        }
    )


def _options_from_input(user_input: dict[str, Any]) -> dict[str, Any]:
    location = user_input[CONF_LOCATION]
    options = {
        CONF_LATITUDE: location[CONF_LATITUDE],
        CONF_LONGITUDE: location[CONF_LONGITUDE],
        CONF_RADIUS: location.get(CONF_RADIUS, DEFAULT_RADIUS),
        CONF_INCLUDE_PLANNED: user_input[CONF_INCLUDE_PLANNED],
        CONF_INCLUDE_OVERDUE: user_input[CONF_INCLUDE_OVERDUE],
    }

    # Absent from first-time setup, so only carry them when the form offered them.
    # NumberSelector hands back a float; the retention is a whole number of days.
    if CONF_HISTORY_DAYS in user_input:
        options[CONF_HISTORY_DAYS] = int(user_input[CONF_HISTORY_DAYS])
    if CONF_STORE_PHONE in user_input:
        options[CONF_STORE_PHONE] = user_input[CONF_STORE_PHONE]

    return options


class DroneTowerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await _async_validate_credentials(
                self.hass, user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                    options=_options_from_input(user_input),
                )

        schema = _location_schema(
            self.hass.config.latitude,
            self.hass.config.longitude,
            DEFAULT_RADIUS,
            DEFAULT_INCLUDE_OVERDUE,
            DEFAULT_INCLUDE_PLANNED,
            with_name=True,
            with_credentials=True,
        )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Kick off reauth when the stored credentials stop working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None

        if user_input is not None:
            error = await _async_validate_credentials(
                self.hass, user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                _credentials_fields(entry.data.get(CONF_EMAIL, ""))
            ),
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
            history=_history_fields(
                options.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS),
                options.get(CONF_STORE_PHONE, DEFAULT_STORE_PHONE),
            ),
        )
        return self.async_show_form(step_id="init", data_schema=schema)
