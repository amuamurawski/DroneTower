"""Tests for the config and options flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType

from custom_components.dronetower_amu.api import DroneTowerAuthError, DroneTowerError
from custom_components.dronetower_amu.const import (
    CONF_INCLUDE_OVERDUE,
    CONF_INCLUDE_PLANNED,
    CONF_RADIUS,
    DOMAIN,
)

CREDENTIALS = {CONF_EMAIL: "pilot@example.com", CONF_PASSWORD: "secret"}


@pytest.fixture
def mock_flow_client():
    with patch(
        "custom_components.dronetower_amu.config_flow.DroneTowerClient",
        autospec=True,
    ) as client_class:
        client_class.return_value.async_login = AsyncMock()
        yield client_class.return_value


async def test_user_flow_creates_entry(hass, mock_flow_client, mock_client):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Dom",
            **CREDENTIALS,
            "location": {"latitude": 52.1, "longitude": 21.2, "radius": 3000},
            CONF_INCLUDE_PLANNED: True,
            CONF_INCLUDE_OVERDUE: False,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dom"
    assert result["data"] == {"name": "Dom", **CREDENTIALS}
    assert result["options"] == {
        "latitude": 52.1,
        "longitude": 21.2,
        CONF_RADIUS: 3000,
        CONF_INCLUDE_PLANNED: True,
        CONF_INCLUDE_OVERDUE: False,
    }
    mock_flow_client.async_login.assert_awaited_once()


async def test_user_flow_handles_unreachable_backend(hass, mock_flow_client):
    mock_flow_client.async_login.side_effect = DroneTowerError("boom")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Dom",
            **CREDENTIALS,
            "location": {"latitude": 52.1, "longitude": 21.2, "radius": 3000},
            CONF_INCLUDE_PLANNED: True,
            CONF_INCLUDE_OVERDUE: False,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_handles_bad_credentials(hass, mock_flow_client):
    mock_flow_client.async_login.side_effect = DroneTowerAuthError("nope")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Dom",
            **CREDENTIALS,
            "location": {"latitude": 52.1, "longitude": 21.2, "radius": 3000},
            CONF_INCLUDE_PLANNED: True,
            CONF_INCLUDE_OVERDUE: False,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_flow_updates_password(
    hass, config_entry, mock_flow_client, mock_client
):
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": config_entry.entry_id,
        },
        data=config_entry.data,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_EMAIL: "pilot@example.com", CONF_PASSWORD: "new-secret"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "new-secret"


async def test_options_flow_updates_radius(hass, config_entry, mock_client):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "location": {"latitude": 50.0, "longitude": 19.0, "radius": 12000},
            CONF_INCLUDE_PLANNED: False,
            CONF_INCLUDE_OVERDUE: True,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_RADIUS] == 12000
    assert config_entry.options["latitude"] == 50.0
    assert config_entry.options[CONF_INCLUDE_OVERDUE] is True
