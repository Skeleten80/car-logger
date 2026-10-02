# Aristo V300 — Go-Live Verification Checklist

Do these in order. Each phase gates the next: **do not skip ahead.** Check off
each item as you complete it; anything that fails stops the line until it's
resolved.

## Phase A — Bench (kitchen table, no car)

- [ ] All parts from `PARTS_LIST_CAD.md` on hand; adapter is ELM327-compatible
      (STN or genuine ELM327 v1.5 + FTDI — no $12 clones).
- [ ] `python3 -m pytest test_profile.py` passes in `vehicles/aristo-v300/`.
- [ ] python-OBD installed in the carlog venv; `import obd` works on the Mini.
- [ ] Adapter appears as `/dev/cu.usbserial*` (or `cu.usbmodem*`) when plugged
      into the Mini. Note the exact port name for `config.local.toml`.
- [x] K-Line poller exists (`carlogger/kline.py`) and has a `--dry-run`
      virtual mode — `python -m carlogger.kline --dry-run --duration 10`
      exercises the DB/dash path with no hardware. 19/19 tests pass
      (`tests/test_kline.py`). Do not go to the car without running it.
- [ ] Inverter + UPS bench test: plug into wall power, confirm the Mini sees
      the UPS over USB (Energy settings gains a UPS tab).

## Phase B — Parked (car in driveway, key ON, engine OFF first)

- [ ] **Read-only safety check:** confirm nothing in the install can transmit
      on any vehicle bus. The ELM327 only sends Mode 01/03 diagnostic requests
      (normal OBD polling). No CAN adapter connected to the car.
- [ ] Power install per `wiring-diagram.svg`: fuse <30 cm from battery
      terminal, relay coil on ACC circuit, grounds to bare metal.
- [ ] Key ON, engine OFF: relay clicks, inverter powers, UPS takes load, Mini
      boots itself (macOS "start up after power failure" enabled).
- [ ] DLC3 found (RHD: right of steering column), photographed; pin population
      matches profile (contacts ONLY in 4, 7, 13, 16; 6/14 empty).
- [ ] Multimeter: pin 16 → pin 4 reads battery voltage; pin 4 → chassis ≈ 0 Ω.
- [ ] Adapter plugged into DLC3. Phone app (Torque/OBD Fusion) with protocol
      forced to ISO 9141-2 connects and reads RPM (= 0) and coolant temp.
      - If it fails here, try the Techstream + Mini-VCI cross-check before
        concluding the port is dead (clone ELM327s fail K-Line init).

## Phase C — Parked, engine running

- [ ] K-Line poller connects via the Mini
      (`python -m carlogger.kline --port /dev/cu.usbserial-XXXX`); fast-loop
      PIDs (RPM, speed, throttle, load) stream at ~5 Hz; slow loop at ~1 Hz.
- [ ] Dash (`python -m carlogger.dash`) shows live gauges on your phone over
      the car's hotspot.
- [ ] Rev the engine in neutral: RPM on the dash tracks the cluster tach with
      no visible lag or dropouts for 60 seconds.
- [ ] Mode 03 DTC read returns a valid response (empty is fine). **Do not
      clear codes** unless diagnosing a known fault.
- [ ] PID sweep: record which wishlist PIDs respond; update `profile.yaml`
      (set `location_confidence: high`, fill in results) and re-run pytest.

## Phase D — Road test (quiet streets first)

- [ ] Logger running, dash on phone mounted where it doesn't distract.
- [ ] 10-minute mixed drive: verify speed/RPM/throttle track reality, no
      dropouts over bumps (loose DLC3 connection shows up here).
- [ ] **Sequential turbo check:** one smooth pull through 4000 rpm in 2nd/3rd —
      confirm the log shows the transition cleanly (this is also your first
      real data: RPM + MAP + throttle together).
- [ ] Key OFF: relay drops → inverter dies → UPS holds → macOS shuts down
      cleanly within ~2 minutes. Confirm no parked drain (relay open = zero
      draw).
- [ ] Pull the DB and spot-check: `SELECT COUNT(*), MIN(ts), MAX(ts) FROM obd2`
      covers the whole drive with no gaps > 5 s.

## Phase E — Sign-off

- [ ] `profile.yaml` updated with everything learned; pytest green.
- [ ] Any deviations from this checklist written into the README.
- [ ] Copy of the first real drive DB archived (`~/car-logger-data/`).

**If anything behaves unexpectedly at any phase:** stop, note what happened,
and check it against `profile.yaml`'s notes before changing hardware. The car
is always right; the paperwork catches up.
