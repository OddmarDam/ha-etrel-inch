"""Number platform — current setpoint (A) and power setpoint (kW).

Both write to verified holding registers (FC 16) using float32 encoding:
- current_setpoint: addr 8, A, range 6-32
- power_setpoint:   addr 11, kW, range 1.4-22

Gated behind CONF_ENABLE_WRITES until the user opts in.
"""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENABLE_WRITES,
    CONF_MAX_CURRENT_A,
    CURRENT_SETPOINT_MAX_A,
    CURRENT_SETPOINT_MIN_A,
    CURRENT_SETPOINT_STEP_A,
    DOMAIN,
    POWER_SETPOINT_MAX_KW,
    POWER_SETPOINT_MIN_KW,
    POWER_SETPOINT_STEP_KW,
    REG_W_CURRENT_SETPOINT,
    REG_W_POWER_SETPOINT,
)
from .coordinator import EtrelCoordinator
from .modbus_client import EtrelModbusError
from .sensor import build_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if not entry.options.get(CONF_ENABLE_WRITES, False):
        return
    coordinator: EtrelCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EtrelCurrentSetpointNumber(coordinator),
            EtrelPowerSetpointNumber(coordinator),
        ]
    )


class _EtrelNumberBase(CoordinatorEntity[EtrelCoordinator], NumberEntity):
    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: EtrelCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_info.serial_number}_{key}"
        self._attr_device_info = build_device_info(coordinator)
        self._last_value: float | None = None

    @property
    def native_value(self) -> float | None:
        return self._last_value


class EtrelCurrentSetpointNumber(_EtrelNumberBase):
    _attr_translation_key = "current_setpoint"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = CURRENT_SETPOINT_MIN_A
    _attr_native_step = CURRENT_SETPOINT_STEP_A

    def __init__(self, coordinator: EtrelCoordinator) -> None:
        super().__init__(coordinator, "current_setpoint")
        # Upper bound, in priority order: the user's explicit max_current_a
        # option (set on the options card, pre-filled from the site max
        # below) > the charger's own installer-configured site max (reg
        # 1028) > the INCH's 32A hardware ceiling. Installations on a
        # lower-rated fuse than the charger's hardware max would otherwise
        # have no way to keep this slider (or an automation driving it) from
        # requesting more current than the site can safely supply.
        configured_max = coordinator.entry.options.get(CONF_MAX_CURRENT_A)
        if configured_max is not None:
            self._attr_native_max_value = min(float(configured_max), CURRENT_SETPOINT_MAX_A)
        else:
            site_max = coordinator.device_info.custom_max_current_a
            self._attr_native_max_value = (
                min(CURRENT_SETPOINT_MAX_A, site_max) if site_max > 0 else CURRENT_SETPOINT_MAX_A
            )
        # Initial reflection: prefer target_current from the coordinator if non-zero.
        data = coordinator.data or {}
        target = data.get("target_current_a")
        if isinstance(target, (int, float)) and target > 0:
            self._last_value = float(target)

    async def async_set_native_value(self, value: float) -> None:
        amps = max(CURRENT_SETPOINT_MIN_A, min(self._attr_native_max_value, float(value)))
        try:
            await self.coordinator.client.write_current_setpoint(
                address=REG_W_CURRENT_SETPOINT,
                amps=amps,
            )
        except EtrelModbusError as err:
            _LOGGER.error("Failed to write current setpoint: %s", err)
            raise
        self._last_value = amps
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class EtrelPowerSetpointNumber(_EtrelNumberBase):
    _attr_translation_key = "power_setpoint"
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_native_min_value = POWER_SETPOINT_MIN_KW
    _attr_native_max_value = POWER_SETPOINT_MAX_KW
    _attr_native_step = POWER_SETPOINT_STEP_KW
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: EtrelCoordinator) -> None:
        super().__init__(coordinator, "power_setpoint")

    async def async_set_native_value(self, value: float) -> None:
        kw = max(POWER_SETPOINT_MIN_KW, min(POWER_SETPOINT_MAX_KW, float(value)))
        try:
            await self.coordinator.client.write_power_setpoint(
                address=REG_W_POWER_SETPOINT,
                kw=kw,
            )
        except EtrelModbusError as err:
            _LOGGER.error("Failed to write power setpoint: %s", err)
            raise
        self._last_value = kw
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
