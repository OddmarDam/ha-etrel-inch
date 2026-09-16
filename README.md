# Etrel INCH — Home Assistant integration

[![GitHub Release][release-shield]][release]
[![License][license-shield]](LICENSE)
[![hacs][hacs-shield]][hacs]

_Custom Home Assistant integration for the **Etrel INCH** family of EV
chargers (also sold rebadged as **Sonnen Charger**, **eMobility Power**,
and others). Local-polling Modbus TCP — no cloud, no extra hardware.
Verified on **INCH Pro G-PC1V5BY40** (22 kW, 3-phase, MID meter) running
firmware **OS 5.0 / SW 5.4 / Web 2.8.4**._

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entities](#entities)
- [Options](#options)
- [Watchdog behavior](#watchdog-behavior)
- [History &amp; long-term statistics](#history--long-term-statistics)
- [Multi-charger setup](#multi-charger-setup)
- [Troubleshooting](#troubleshooting)
- [Register map](#register-map)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Local Modbus TCP** — talks straight to the charger's port `502`. No
  Etrel cloud, no OCPP central system, no internet.
- **One device per charger.** Add the integration multiple times to
  monitor multiple chargers on the same LAN.
- **Watchdog-aware polling** — defaults to 10 s, configurable 2-60 s.
- **Complete Modbus surface area exposed.** Every register the INCH
  publishes is a Home Assistant entity:
  - Per-phase **voltage**, **current**, **active power**
  - Total **active power**, **session energy**, **session duration**
  - **Frequency**, **power factor**
  - **Vehicle-reported** max current, max power, planned energy, departure time
  - Charger **target current** (the live setpoint readback)
- **Optional, gated write controls** — current/power setpoint, pause/resume,
  stop, release-override, restart, and departure time.
- **No third-party Python dependencies**: ships with `requirements: []`
  and uses only `pymodbus` from HA core.

## How it works

The Etrel INCH exposes its full state on Modbus port `502`:

- All **runtime data** lives on **input registers** (function code `04`)
  at addresses 0-46.
- All **identity / hardware-config data** lives on **input registers**
  at addresses 990-1029.
- All **writes** go to **holding registers** (function code `16`) at
  addresses 1-13 and 1000-1004.

Per poll cycle the integration:

1. Reads regs `0-47` in one request → status, phase mode, all per-phase
   measurements, session totals, EV-reported targets, session ID.
2. Reads regs `990-1029` once at setup → serial, model, firmware, hardware
   phase config, installer-set max current.

Decoding is big-endian (byte and word), matching every published Etrel
reference. Connection drops mark entities *unavailable*; HA's
`DataUpdateCoordinator` applies exponential backoff before reconnecting.

## Installation

### Option 1: HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=keethus&repository=ha-etrel-inch&category=integration)

Or manually in HACS:

1. **HACS → Integrations → ⋮ → Custom repositories**
2. Add `https://github.com/keethus/ha-etrel-inch` with category
   **Integration**.
3. Install **Etrel INCH EV Charger** and restart Home Assistant.

### Option 2: Manual

1. Download the latest release from the
   [Releases page](https://github.com/keethus/ha-etrel-inch/releases).
2. Copy `custom_components/etrel_inch/` into your HA config's
   `custom_components/` directory.
3. Restart Home Assistant.

## Configuration

Modbus must be **enabled** on the charger first — log in to the charger's
web UI, *Settings → Modbus*, switch it on. Note the slave/unit ID (try
**`1`** first; some older firmwares ship with **`255`**).

In Home Assistant:

1. **Settings → Devices & Services → Add Integration → Etrel INCH EV Charger**.
2. Fill in:

   | Field             | Default       | Notes                                                                         |
   | ----------------- | ------------- | ----------------------------------------------------------------------------- |
   | Name              | `Etrel INCH`  | Free-form, used as the device name in HA.                                     |
   | Host / IP         | —             | Charger's LAN address. Reserve it on your DHCP server.                        |
   | Modbus TCP port   | `502`         |                                                                               |
   | Slave / Unit ID   | `1`           | Try `1`; if the connection probe times out or returns garbage, try `255`.     |
   | Poll interval (s) | `10`          | **Must** be shorter than the charger's `monitoring_interval`.                 |

3. The flow validates by reading the dynamic block (regs 0-1). If the
   charger answers, the entry is created and entities populate within ~10 s.

## Entities

Each charger becomes one HA *device*. Entities are grouped by function;
diagnostic-category entities are **disabled by default** — enable them in
the entity registry if you need them.

### Sensors (read-only)

**Live electrical:**

| Entity | Source reg | Class |
|---|---:|---|
| Charge status | `0` | ENUM (10 states + unknown) |
| Phase mode | `1` | ENUM (3-phase, 2-phase, single L1/L2/L3) |
| Vehicle max current | `2` | A, MEASUREMENT |
| Target current | `4` | A, MEASUREMENT (live setpoint readback) |
| Frequency | `6` | Hz, MEASUREMENT |
| Voltage L1 / L2 / L3 | `8` / `10` / `12` | V, MEASUREMENT |
| Current L1 / L2 / L3 | `14` / `16` / `18` | A, MEASUREMENT |
| Power L1 / L2 / L3 | `20` / `22` / `24` | kW, MEASUREMENT |
| Active power (total) | `26` | kW, MEASUREMENT |
| Power factor | `28` | %, MEASUREMENT (raw 0-1 → displayed 0-100 %) |

**Session:**

| Entity | Source reg | Class |
|---|---:|---|
| Session energy | `30` | kWh, TOTAL_INCREASING |
| Session duration | `32` | s, MEASUREMENT |
| Session departure time | `36` | TIMESTAMP |
| Session ID *(diagnostic)* | `40` | int |
| EV max power | `44` | kW, MEASUREMENT |
| EV planned energy | `46` | kWh, MEASUREMENT |

**Diagnostics (disabled by default):** `model`, `serial_number`,
`sw_version`, `hw_version`, `num_connectors`, `connector_type`,
`num_phases_hw`, `phase_rotation_l1/l2/l3`, `custom_max_current`.

> **Firmware caveat:** `session_energy` (reg 30) is reported as
> "always zero" on some firmwares (see [evcc#5346][evcc-issue]). If yours
> does the same, derive cumulative energy from `active_power` over time
> with HA's `integration` integration.

### Number entities (write — gated)

| Entity | Target reg | Range |
|---|---:|---|
| Current setpoint | `8` | 6-32 A (float32), capped by the **Max current setpoint** option |
| Power setpoint *(disabled by default)* | `11` | 1.4-22 kW (float32) |

Writing `0` to the current setpoint pauses charging. To **release** the
override and let the charger return to its previous regime, press the
*Release current setpoint* button (writes to reg `10`).

The current setpoint's upper bound comes from the **Max current setpoint**
option (see [Options](#options)) if you've set one, otherwise from the
charger's own installer-configured site max current (reg `1028`, also
exposed as the diagnostic `custom_max_current` sensor), otherwise 32A. On an
installation with a lower fuse rating than the charger's hardware max, this
keeps the slider — and any automation driving it — from ever requesting more
current than the site can safely supply.

### Switch (write — gated)

| Entity | Target reg | Notes |
|---|---:|---|
| Pause charging | `2` | Writes 1=pause, 0=resume. State derived from `charge_status` (`charger_paused`). |

### Buttons (write — gated)

| Entity | Target reg | Notes |
|---|---:|---|
| Stop charging | `1` | One-shot — ends the active session. |
| Release current setpoint *(disabled)* | `10` | Cancels current override. |
| Release power setpoint *(disabled)* | `13` | Cancels power override. |
| Restart charger *(disabled, diagnostic)* | `1004` | Soft reboot. |

### DateTime (write — gated)

| Entity | Target reg | Notes |
|---|---:|---|
| Departure time | `4` (write) / `36` (read) | int64 unix timestamp; the EV-reported planned departure. |

## Options

Per-entry: **Settings → Devices & Services → Etrel INCH EV Charger →
Configure**:

| Option              | Default | Range          | Notes                                                                                                                                              |
| ------------------- | ------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Poll interval       | 10 s    | 2 s - 60 s     | Live-reload — entry restarts when changed.                                                                                                         |
| Enable write controls | off   | —              | When on, registers the number/switch/button/datetime write entities. Off by default so a fresh install never touches the charger's command registers. |
| Max current setpoint | site max (reg `1028`), else 32 A | 6-32 A | Upper bound for the current setpoint slider. Pre-filled from the charger's own configured site max the first time you open this form — lower it if your supply fuse is rated below what the charger reports. |

## Watchdog behavior

When Modbus is enabled on the charger, two parameters control the watchdog:

- `monitoring_interval` — if no Modbus read arrives within this many
  seconds, the charger drops to `fallback_current`.
- `fallback_current` — the safe-mode amperage used after a timeout.

**Recommendations:**

- **Read-only setups:** set `monitoring_interval = 0` on the charger to
  **disable** the watchdog entirely. The integration still polls every
  `poll_interval` seconds, but a network blip won't cause the charger to
  throttle.
- **Setups using write controls:** keep the watchdog enabled and ensure
  `poll_interval < monitoring_interval` with margin (e.g.
  `monitoring_interval = 30`, `poll_interval = 10`).

## History &amp; long-term statistics

You don't need to do anything special to keep history — Home Assistant's
recorder stores it natively for every entity. For each sensor we expose:

- **Short-term history** (default 10 days, configurable in HA's recorder
  settings) — visible on each entity's detail page as a graph.
- **Long-term statistics** — kept forever for any sensor with
  `state_class=MEASUREMENT` or `TOTAL_INCREASING`. Queryable via
  *Developer tools → Statistics* and used by the Energy dashboard.

For **Energy dashboard** integration, add `session_energy` as an
*Individual device* under **Settings → Dashboards → Energy**. If your
firmware leaves reg 30 at zero, use HA's `integration` helper to integrate
`active_power` over time — same end result.

For **higher-fidelity history**, drop `poll_interval` to `2` s. The DB
grows linearly so set HA's recorder retention accordingly.

## Multi-charger setup

Run **Add Integration → Etrel INCH EV Charger** once per charger. Each
entry is bound to its serial number (read from reg 990). If your firmware
leaves the serial blank, the integration falls back to a stable
`etrel_inch_<host>_<slave>` unique_id — duplicate-prevention still works.

Naming each entry distinctly (`Garage`, `Driveway`, `Visitor`, …) keeps
their entities apart in the registry.

## Troubleshooting

**Connection succeeds but every value is 0 / "Unknown".**
This was the symptom on integration v0.1 — fixed in v0.2 by switching
reads to function code 04 (input registers). If you see it again on a
newer firmware, run `mbpoll -m tcp -a 1 -t 3 -0 -r 0 -c 50 <host>` and
share the output in an issue.

**`cannot_connect` in the config flow.**
Confirm Modbus TCP is enabled on the charger, the slave ID matches (try
1 first, then 255), and nothing else has the connection open — some
chargers permit only one Modbus TCP client at a time.

**Session energy stays at 0 while charging.**
Some firmwares zero this register. Use HA's `integration` integration to
derive session/total energy from `active_power`. The
[evcc team][evcc-issue] hit the same issue and disabled this register
in their driver.

**Sensor values look like garbage** (e.g. `voltage_l1 = 4.2e-38`).
Byte/word ordering mismatch on a non-standard firmware. Edit the
`_decode_float32` / `_decode_int64` helpers in
[modbus_client.py](custom_components/etrel_inch/modbus_client.py) — try
swapping the word order.

**Charger throttles to fallback current.**
Either your poll interval is longer than `monitoring_interval`, or the
watchdog timed out during a network glitch. Disable the watchdog
(`monitoring_interval = 0`) for read-only use, or shorten the poll
interval.

**Enable debug logs:**

```yaml
logger:
  default: warning
  logs:
    custom_components.etrel_inch: debug
    pymodbus: info
```

## Register map

Verified against the
[abauske/sonnen_charger_modbus][abauske] reference Python implementation,
the [evcc-io/evcc][evcc] Etrel driver, and the
[Etrel knowledge base][etrel-kb]. See
[`const.py`](custom_components/etrel_inch/const.py) for the source of
truth this integration uses.

For multi-connector chargers (INCH Duo), all dynamic addresses 0-46 take
a `connector_id * 100` offset for the second connector (so the second
connector's `charge_status` is at reg 100, etc.). Single-connector
chargers (INCH Pro / Home) use offset 0.

## Development

```bash
git clone https://github.com/keethus/ha-etrel-inch.git
cd ha-etrel-inch
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest          # tests (none yet — PRs welcome)
mypy            # type-check (mypy --strict)
ruff check .    # lint
ruff format .   # format
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome — especially anything
that confirms register behavior on a firmware not yet listed in the
[Register map](#register-map) section.

## License

[MIT](LICENSE) © 2026 Karlis Barbars.

This project is not affiliated with Etrel d.o.o.

---

[release-shield]: https://img.shields.io/github/v/release/keethus/ha-etrel-inch?style=flat-square
[release]: https://github.com/keethus/ha-etrel-inch/releases
[license-shield]: https://img.shields.io/github/license/keethus/ha-etrel-inch?style=flat-square
[hacs-shield]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square
[hacs]: https://github.com/hacs/integration
[abauske]: https://github.com/abauske/sonnen_charger_modbus
[evcc]: https://github.com/evcc-io/evcc/blob/master/charger/etrel.go
[evcc-issue]: https://github.com/evcc-io/evcc/issues/5346
[etrel-kb]: https://etrelchargingsolutions.atlassian.net/wiki/spaces/Home/pages/2236121092/Modbus+Communication+with+Inch+products
