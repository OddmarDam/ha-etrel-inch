"""Config and options flows for the Etrel INCH integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .const import (
    CONF_ENABLE_WRITES,
    CONF_HOST,
    CONF_MAX_CURRENT_A,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONF_SLAVE_ID,
    CURRENT_SETPOINT_MAX_A,
    CURRENT_SETPOINT_MIN_A,
    DEFAULT_NAME,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SLAVE_ID,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from .modbus_client import EtrelModbusClient, EtrelModbusError

_LOGGER = logging.getLogger(__name__)


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Required(CONF_HOST, default=d.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=d.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                int, vol.Range(min=1, max=65535)
            ),
            vol.Required(CONF_SLAVE_ID, default=d.get(CONF_SLAVE_ID, DEFAULT_SLAVE_ID)): vol.All(
                int, vol.Range(min=1, max=247)
            ),
            vol.Required(
                CONF_POLL_INTERVAL, default=d.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ): vol.All(int, vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL)),
        }
    )


async def _validate(hass, data: dict[str, Any]) -> str:
    """Connect, verify the charger answers, and return a unique_id.

    Validation reads the dynamic block at regs 0-1 (status + phases) — those
    are populated on every INCH regardless of commissioning. The identity
    block at 990 is unreliable across firmwares, so we read it best-effort:
    use the serial if present, otherwise synthesize a host-based unique_id.
    """
    client = EtrelModbusClient(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        slave_id=data[CONF_SLAVE_ID],
    )
    try:
        await client.connect()
        await client.probe_connectivity()
        info = await client.read_device_info()
    finally:
        await client.close()

    if info.serial_number:
        return info.serial_number
    # Fallback: stable, human-readable, unique per host+slave on the LAN.
    return f"etrel_inch_{data[CONF_HOST]}_{data[CONF_SLAVE_ID]}"


class EtrelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Etrel INCH."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                serial = await _validate(self.hass, user_input)
            except EtrelModbusError as err:
                _LOGGER.warning("Etrel INCH validation failed: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating Etrel INCH")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured(updates=user_input)
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                    options={CONF_ENABLE_WRITES: False},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return EtrelOptionsFlow(entry)


class EtrelOptionsFlow(OptionsFlow):
    """Allow editing poll interval and the (placeholder) write feature flag."""

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_poll = self.entry.options.get(
            CONF_POLL_INTERVAL,
            self.entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )
        current_writes = self.entry.options.get(CONF_ENABLE_WRITES, False)
        current_max_current = self.entry.options.get(CONF_MAX_CURRENT_A, self._default_max_current())

        schema = vol.Schema(
            {
                vol.Required(CONF_POLL_INTERVAL, default=current_poll): vol.All(
                    int, vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL)
                ),
                vol.Required(CONF_ENABLE_WRITES, default=current_writes): bool,
                vol.Required(CONF_MAX_CURRENT_A, default=current_max_current): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=CURRENT_SETPOINT_MIN_A, max=CURRENT_SETPOINT_MAX_A),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    def _default_max_current(self) -> float:
        """Seed the max-current field from the charger's own reported site max.

        Falls back to the hardware ceiling if the coordinator isn't up yet or
        the charger hasn't reported a site max (reg 1028 left at 0).
        """
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)
        site_max = getattr(getattr(coordinator, "device_info", None), "custom_max_current_a", 0)
        return site_max if site_max and site_max > 0 else CURRENT_SETPOINT_MAX_A
