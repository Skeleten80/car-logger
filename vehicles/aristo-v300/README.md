# Aristo V300 (JZS161) — Vehicle Computer Install Guide

Supervisory install for Mathias's 1997–2004 Toyota Aristo V300 (2JZ-GTE VVTi,
A340E, RHD JDM). Read-only: the stock ECU keeps full control of the engine at
all times. This guide is Aristo-specific; the generic logger, dash, and vision
docs live in the parent `~/workspace/car-logger/README.md`.

**Start here:** `profile.yaml` in this folder is the source of truth for the
car's diagnostic layout. `PARTS_LIST_CAD.md` is what to buy.
`wiring-diagram.svg` is the power + data map. `GO_LIVE_CHECKLIST.md` is the
order of operations — follow it, don't freestyle.

## 0. What makes this car different

- **No CAN on the diagnostic port.** The JZS161 DLC3 speaks **ISO 9141-2
  K-Line** on pin 7 (verified: ECU pin F60-11 SIL → dash connector pin 7; only
  pins 4/7/13/16 populated). A CAN-only adapter cannot talk to this ECU —
  you need a USB ELM327-compatible adapter (OBDLink EX recommended).
- **K-Line is slow** (~10.4 kbps, ~5–10 PID reads/sec). The poll plan in
  `profile.yaml` keeps 4 PIDs on the fast loop so the dash stays live.
- **RHD**: the DLC3 is on the RIGHT side of the steering column, not the left.
- **Phone apps default to CAN** — force ISO 9141-2 (ELM327 `ATSP3`) or they'll
  fail to connect and look like a dead port.

## 1. DLC3 location

Driver footwell, right side of the steering column (RHD), above the kick panel
near the fuse box. 16-pin trapezoid connector, usually with a dust cap.
Photograph it, then confirm the pin population matches `profile.yaml`
(contacts only in 4, 7, 13, 16 — cavities 6 and 14 must be EMPTY).

If 6/14 are populated, stop: this car differs from the profile. Update
`profile.yaml` and re-run the pytest suite before continuing.

## 2. Cable routing

- **DLC3 → adapter:** plug the ELM327 straight into the DLC3. If you want it
  hidden, use the optional J1962 extension and tuck the adapter body under the
  dash trim.
- **Adapter → trunk:** run a quality USB-A→USB-C cable under the door-sill trim
  and rear seat into the trunk. Keep USB runs as short as practical; if the run
  is over ~3 m, use an active extension.
- **Power run:** battery → fuse (<30 cm from terminal) → 10 AWG red through
  the firewall grommet → along the sill (loomed, away from sharp edges and the
  exhaust) → trunk relay → inverter → UPS → Mini. 10 AWG black returns
  alongside. See `wiring-diagram.svg`.

## 3. Mounting

- Mini + UPS + inverter on a tray in the trunk, ventilated, out of direct sun.
  Foam-isolate the tray; the Mini's fan is the only moving part (SSD, no disk
  to kill).
- The Aristo's trunk is large — mount against the rear seat bulkhead so the
  load floor stays usable.

## 4. Power install

Follow `wiring-diagram.svg` exactly:

1. Disconnect battery negative first.
2. Fuse holder within 30 cm of battery positive. 30 A fuse.
3. Relay coil to an ACC-switched circuit (radio/ACC fuse tap) — key off must
   kill the inverter input.
4. Inverter chassis grounded to body. UPS plugged into inverter.
5. Mini plugged into UPS; UPS USB cable to the Mini (this is what gives macOS
   the shutdown signal).
6. Reconnect battery negative last.

## 5. Software setup

On the M6 Mini (macOS):

```bash
# 1. Python env (reuse the carlog venv pattern from the parent README)
python3 -m venv ~/.venvs/carlog && source ~/.venvs/carlog/bin/activate
pip install -r ~/workspace/car-logger/requirements.txt
pip install obd          # python-OBD: ELM327 serial driver (pyserial-based)

# 2. Find the adapter's serial port (plug it in, then:)
ls /dev/cu.usbserial* /dev/cu.usbmodem*   # note which appears

# 3. Configure — copy the example and set the Aristo profile
cp ~/workspace/car-logger/config.toml ~/workspace/car-logger/config.local.toml
```

`config.local.toml` additions for the Aristo:

```toml
[vehicle]
profile = "vehicles/aristo-v300/profile.yaml"

[obd]
# K-Line via ELM327 — NOT the CAN interface
port = "/dev/cu.usbserial-XXXX"   # from step 2
protocol = "3"                    # ELM327 ATSP3 = ISO 9141-2
baudrate = 10400
```

Then run the verification procedure from `profile.yaml`
(`diagnostics.verification_procedure`, steps 1–7) and the go-live checklist.
The parent README's `tools/smoke_test.py` exercises the generic pipeline, but
**the Aristo go-live is gated on the K-Line verification, not the smoke test.**

### Code status (honest)

The generic logger in `carlogger/` polls OBD-II over CAN (`0x7DF`) — that
path does not apply to this car. The K-Line/ELM327 poller is
**`carlogger/kline.py`** (python-OBD based, 19/19 tests passing in
`tests/test_kline.py`). It loads `pid_wishlist` and `poll_plan` from
`profile.yaml`, forces ISO 9141-2 (`ATSP3`), polls expected PIDs on the
fast (5 Hz) / slow (1 Hz) loops, probes unlikely/extended PIDs once at
startup, and writes into the same `obd2` table — so the SQLite schema,
dash, and vision layers work unchanged.

```bash
# no hardware needed: see the PID map, then bench-test the DB/dash path
python -m carlogger.kline --list-pids
python -m carlogger.kline --dry-run --duration 10

# at the car (macOS port shown; Linux is /dev/ttyUSB0)
python -m carlogger.kline --port /dev/cu.usbserial-XXXX --db ~/car-logger-data/drive.db
```

Track remaining Aristo work as issues: Toyota extended PIDs (`map_boost`,
`trans_fluid_temp`) still need Techstream identification before they can
be polled.

## 6. How profile.yaml is used

- **Humans:** the verification procedure and PID wishlist are the install
  spec. Read them before touching the car.
- **Tests:** `test_profile.py` validates the profile on every change
  (`python3 -m pytest test_profile.py`). If you learn something new about the
  car (a PID that doesn't respond, a different DLC3 location), update the YAML
  and re-run the tests — a failing test means the profile and the code
  disagree, and the car wins.
- **Code:** `carlogger/kline.py` loads `pid_wishlist` and `poll_plan` from
  this file rather than hardcoding PIDs, so one edit updates both docs
  and behavior. `--list-pids` prints the live mapping.

## 7. Fallbacks if K-Line disappoints

- **TACH wire:** the ECU's tach square wave is available at the engine-bay
  diagnostic connector (IG- terminal). A cheap USB frequency counter on that
  wire gives hardware RPM if polling is too slow for a lively tach.
- **Techstream + Mini-VCI:** the dealer-level cross-check. If python-OBD can't
  see the ECU but Techstream can, the problem is the adapter/software, not
  the car.
