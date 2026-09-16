"""Constants for the Etrel INCH integration.

Register map verified against the abauske/sonnen_charger_modbus reference
implementation, the evcc-io etrel.go driver, and the Etrel knowledge base.
All runtime data lives on INPUT registers (function code 04). Writes go to
HOLDING registers (function code 16). Multi-connector chargers use an offset
of (connector_index * 100) on all dynamic addresses 0-46.
"""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "etrel_inch"

# Configuration keys
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_SLAVE_ID: Final = "slave_id"
CONF_NAME: Final = "name"
CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_ENABLE_WRITES: Final = "enable_writes"
CONF_MAX_CURRENT_A: Final = "max_current_a"

# Defaults
DEFAULT_PORT: Final = 502
DEFAULT_SLAVE_ID: Final = 1
DEFAULT_POLL_INTERVAL: Final = 10
DEFAULT_NAME: Final = "Etrel INCH"
MIN_POLL_INTERVAL: Final = 2
MAX_POLL_INTERVAL: Final = 60

MANUFACTURER: Final = "Etrel"

# ===== Input registers (FC 04) — read-only runtime + identity data =====

# Dynamic block (read every poll, addresses 0..46)
REG_CHARGE_STATUS: Final = 0          # uint16, enum 1-10
REG_PHASE_MODE: Final = 1             # uint16, enum (see PHASE_MODE_MAP)
REG_VEHICLE_MAX_CURRENT: Final = 2    # float32, A
REG_TARGET_CURRENT: Final = 4         # float32, A — what charger currently allows
REG_FREQUENCY: Final = 6              # float32, Hz
REG_VOLTAGE_L1: Final = 8             # float32, V
REG_VOLTAGE_L2: Final = 10            # float32, V
REG_VOLTAGE_L3: Final = 12            # float32, V
REG_CURRENT_L1: Final = 14            # float32, A
REG_CURRENT_L2: Final = 16            # float32, A
REG_CURRENT_L3: Final = 18            # float32, A
REG_POWER_L1: Final = 20              # float32, kW
REG_POWER_L2: Final = 22              # float32, kW
REG_POWER_L3: Final = 24              # float32, kW
REG_ACTIVE_POWER: Final = 26          # float32, kW
REG_POWER_FACTOR: Final = 28          # float32, ratio
REG_SESSION_ENERGY: Final = 30        # float32, kWh (firmware-dependent — may stay 0)
REG_SESSION_DURATION: Final = 32      # int64, seconds
REG_SESSION_DEPARTURE_READ: Final = 36  # int64, unix timestamp
REG_SESSION_ID: Final = 40            # int64
REG_EV_MAX_POWER: Final = 44          # float32, kW
REG_EV_PLANNED_ENERGY: Final = 46     # float32, kWh

# Identity / config block (read once at setup, addresses 990..1029)
REG_SERIAL_NUMBER: Final = 990        # string[10]
REG_MODEL: Final = 1000               # string[10]
REG_HW_VERSION: Final = 1010          # string[5]
REG_SW_VERSION: Final = 1015          # string[5]
REG_NUM_CONNECTORS: Final = 1020      # int32
REG_CONNECTOR_TYPE: Final = 1022      # uint16 enum
REG_NUM_PHASES_HW: Final = 1023       # uint16
REG_L1_TO_PHASE: Final = 1024         # uint16
REG_L2_TO_PHASE: Final = 1025         # uint16
REG_L3_TO_PHASE: Final = 1026         # uint16
REG_CUSTOM_MAX_CURRENT: Final = 1028  # float32, A — installer-configured site limit

# ===== Holding registers (FC 03/16) — writes =====
REG_W_STOP_CHARGING: Final = 1            # bool
REG_W_PAUSE_CHARGING: Final = 2           # bool
REG_W_DEPARTURE_TIME: Final = 4           # int64, unix
REG_W_CURRENT_SETPOINT: Final = 8         # float32, A
REG_W_CANCEL_CURRENT: Final = 10          # bool — release the current override
REG_W_POWER_SETPOINT: Final = 11          # float32, kW
REG_W_CANCEL_POWER: Final = 13            # bool — release the power override
REG_W_SET_TIME: Final = 1000              # int64, unix — sync charger clock
REG_W_RESTART: Final = 1004               # bool — soft reboot

# ===== Enums =====

# Charge status (input reg 0). Values 1-10 are documented; 11+ are reserved.
CHARGE_STATUS_MAP: Final[dict[int, str]] = {
    1: "available",
    2: "waiting_for_vehicle",
    3: "waiting_to_start",
    4: "charging",
    5: "vehicle_paused",
    6: "charger_paused",
    7: "charge_ended",
    8: "error",
    9: "resuming",
    10: "unavailable",
}
CHARGE_STATUS_OPTIONS: Final = [*CHARGE_STATUS_MAP.values(), "unknown"]

# Phase mode (input reg 1) — the phase configuration the EV is using right now.
PHASE_MODE_MAP: Final[dict[int, str]] = {
    0: "three_phase",
    1: "single_l1",
    2: "single_l2",
    3: "single_l3",
    4: "unknown",
    5: "two_phase",
}
PHASE_MODE_OPTIONS: Final = list(set(PHASE_MODE_MAP.values()))

# Connector type (input reg 1022)
CONNECTOR_TYPE_MAP: Final[dict[int, str]] = {
    1: "socket_type2",
    2: "cable_type2",
}
CONNECTOR_TYPE_OPTIONS: Final = [*CONNECTOR_TYPE_MAP.values(), "unknown"]

# Bounds for the current-setpoint number entity. MAX is the INCH's hardware
# ceiling — it also bounds the user-configurable CONF_MAX_CURRENT_A option,
# which is what the entity actually uses as its live max (see number.py).
CURRENT_SETPOINT_MIN_A: Final = 6.0
CURRENT_SETPOINT_MAX_A: Final = 32.0
CURRENT_SETPOINT_STEP_A: Final = 1.0

# Bounds for the power-setpoint number entity (3-phase 32A * 230V * 3 ≈ 22 kW)
POWER_SETPOINT_MIN_KW: Final = 1.4
POWER_SETPOINT_MAX_KW: Final = 22.0
POWER_SETPOINT_STEP_KW: Final = 0.1
