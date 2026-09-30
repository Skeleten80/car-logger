# car-logger — Phase 2: M6 Mac Mini vehicle data logger + live dash

Read-only vehicle telemetry beside the stock ECU, now with DBC signal
decoding and a live dashboard. Three layers that compose:

- **OBD-II polling** — standard SAE J1979 PIDs (RPM, speed, coolant, throttle, fuel)
  requested on ID `0x7DF`, decoded from `0x7E8+` responses.
- **Raw CAN capture** — every frame on the bus, timestamped, into SQLite.
- **DBC decoding** (phase 2) — raw frames decoded into named physical signals
  via opendbc-format `.dbc` files (cantools), stored in the `signals` table.

Nothing here transmits except OBD-II queries in `obd2`/`both` mode. `listen` mode
is fully passive.

## Quick start (any machine, no hardware)

```bash
pip install -r requirements.txt
python tools/smoke_test.py     # phase-1: virtual bus + fake ECU, end-to-end
python tools/phase2_test.py    # phase-2: DBC decode + dash API, end-to-end
```

The phase-2 test runs the real logger for 3 s against a virtual bus (fake ECU +
background chatter + raw ENGINE_DATA frames encoded from a test DBC), then asserts
decoded signals land in SQLite **and** are served by the dash API, including the
live SSE stream.

## DBC decoding (phase 2)

1. Get a DBC for the car. The community collection is
   [opendbc](https://github.com/commaai/opendbc) — on the Mini:
   ```bash
   git clone --depth 1 --filter=blob:none --sparse https://github.com/commaai/opendbc.git
   cd opendbc && git sparse-checkout set opendbc
   ```
2. In `config.local.toml`:
   ```toml
   [decode]
   dbc_path = "~/opendbc/opendbc"   # or one specific <make>_<model>_<year>.dbc
   vehicle = "2021 Toyota RAV4"
   ```
3. Run the logger as usual — matching frames are decoded in real time into the
   `signals(session_id, ts, message, signal, value, unit)` table. With `dbc_path`
   empty, decoding is off and everything else works unchanged.

Decoding is best-effort per frame: unknown IDs and undecodable payloads are
skipped silently, never crash the logger.

## Live dash (phase 2)

```bash
python -m carlogger.dash        # alongside the logger (separate process)
```

Serves on `0.0.0.0:8080` (config `[dash]`):

- `/` — **web dash**: RPM arc gauge, speed, coolant, throttle, fuel, MAF,
  RPM history sparkline, and a live table of decoded CAN signals. Zero build
  step, works from any phone/laptop browser on the car's Wi-Fi hotspot.
- `/api/latest`, `/api/live` (SSE ~2 Hz), `/api/history?signal=&limit=`,
  `/api/info` — JSON API the web dash and the native app share.

The dash only reads the SQLite file, so it can run on the same Mini or any
machine with the DB file.

### Native app: CarDash (`CarDash/`)

SwiftUI macOS app (macOS 14+, Xcode on the iMac or Mini) in the MissionOps
visual style: gauge cards, RPM strip chart, decoded-signal table, connection
status pill. Open `CarDash/Package.swift` in Xcode, ⌘R, and point it at the
Mini (`http://mini.local:8080` or the hotspot IP). It consumes the same
`/api/live` SSE stream as the web dash — no extra server work needed.

## Dashcam perception (phase 3)

`python -m carlogger.vision` (separate process; set `[vision] enabled = true`
first) captures frames from a USB dashcam — or a video file for testing —
runs YOLOv8n object detection, and logs every detection to the
`vision_events` table on the same wall clock as the CAN data, so video and
bus traffic correlate after a drive ("what did the camera see when the
bus did X?").

### One runtime, both machines

The model is ONNX, executed by onnxruntime. The execution providers come
from config, so the *same* file runs:

- on the M6 Mini with `["CoreMLExecutionProvider", "CPUExecutionProvider"]`
  — the CoreML EP dispatches eligible ops to the **Neural Engine**;
- on a Linux dev box with `["CPUExecutionProvider"]`.

Verify ANE usage on the Mini with
`sudo powermetrics --samplers ane_power -n 1` while the vision process
runs — ANE power reads above zero under load.

### Model export (once per machine, or copy the file over)

```bash
pip install -r requirements-export.txt   # ultralytics + torch, export only
python tools/export_models.py            # -> models/yolov8n.onnx (~12 MB, NMS baked in)
python tools/phase3_test.py              # end-to-end: real photo, real detections
```

### What gets logged

`vision_events(session_id, ts, label, confidence, x1, y1, x2, y2,
snapshot_path, interesting)` — one row per detection above
`conf_threshold`. Frames flagged *interesting* — a person at high
confidence, a large close vehicle, or any detection during hard braking
(fused from OBD-II speed in the same DB) — save an annotated JPEG to
`~/car-logger-data/snapshots/`. The dash shows the latest detections per
label plus the newest snapshot (`/snapshots/<name>`).

Correlated query — interesting moments with the speed at the time:

```sql
SELECT datetime(v.ts,'unixepoch','localtime') t, v.label, v.confidence,
       (SELECT value FROM obd2 WHERE name='speed' AND ts <= v.ts
        ORDER BY ts DESC LIMIT 1) AS speed_kph
FROM vision_events v WHERE v.interesting ORDER BY v.ts DESC LIMIT 20;
```

### Power and thermal notes

- `target_fps = 4` by default: plenty for a driving log, easy on thermals in
  a hot car. YOLOv8n on the M6 ANE is capable of far more — raise it for
  denser coverage.
- A USB dashcam adds ~2.5 W to the power budget — noise next to the Mini
  on the 300 W inverter.

### What's next (phase 3b)

Driver monitoring — in-cabin camera plus face/eye tracking via Apple's
Vision framework — is the second half of phase 3. Like CarDash, that's
Swift/Xcode work for the iMac.

## On the M6 Mini (with a USB-CAN adapter)

1. **Adapter driver** (macOS has no SocketCAN; each vendor needs its backend):
   - PCAN-USB → install MacCAN [PCBUSB](https://mac-can.github.io/drivers/libPCBUSB.html) (Universal binary, Apple Silicon OK), then `python-can` uses `interface="pcan", channel="PCAN_USBBUS1"`.
   - Kvaser Leaf → install MacCAN [KvaserCAN](https://mac-can.github.io/drivers/KvaserCAN/), then `interface="kvaser", channel=0`.
   - CANable (candleLight firmware) → no driver; `pip install "python-can[gs_usb]" pyusb`, then `interface="gs_usb", channel=0`.
   - CANable (slcan firmware) → no driver; `interface="slcan", channel="/dev/cu.usbmodemXXXX"`.
2. Copy `config.toml` → `config.local.toml`, set your `interface`/`channel`/`bitrate`.
   Most cars: 500000 baud, 11-bit IDs. Some use 250000 — if you see nothing, try that.
3. Plug the OBD-II→DB9 cable into the car's diagnostic port (key on, engine can be off
   for a first test — the ECU answers OBD-II with just ignition).
4. `python -m carlogger.logger --duration 60` for a one-minute capture, or run
   indefinitely and stop with Ctrl-C.

## Auto-start on boot (launchd)

```bash
mkdir -p ~/car-logger-data
cp com.skeleten80.carlogger.plist ~/Library/LaunchAgents/
# edit paths inside the plist first (python path, config path, username)
launchctl load ~/Library/LaunchAgents/com.skeleten80.carlogger.plist
```

Pair with the power setup in `PARTS_LIST.md`: macOS "start up automatically after
power failure" + UPS shutdown on power loss = key-on logging, key-off clean stop.
The logger traps SIGTERM so launchd shutdowns always flush the DB.

## Data layout

SQLite at `~/car-logger-data/drive.db` (configurable):

- `sessions(id, started_at, note)` — one row per run
- `raw_frames(session_id, ts, arb_id, is_extended, dlc, data_hex)` — every frame
- `obd2(session_id, ts, pid, name, value, unit)` — decoded samples
- `signals(session_id, ts, message, signal, value, unit)` — DBC-decoded signals (phase 2)

Query example:

```sql
SELECT datetime(ts,'unixepoch','localtime') t, name, value, unit
FROM obd2 WHERE pid = 12 ORDER BY ts DESC LIMIT 20;   -- recent RPM
```
```sql
SELECT datetime(ts,'unixepoch','localtime') t, signal, value, unit
FROM signals WHERE message = 'ENGINE_DATA'
ORDER BY ts DESC LIMIT 20;                            -- decoded DBC signals
```

## Roadmap

- Phase 1: OBD-II + raw capture → SQLite. ✅
- Phase 2: DBC decoding (opendbc) + live dash (web + SwiftUI CarDash). ✅
- Phase 3: dashcam perception (YOLOv8n via onnxruntime; Neural Engine on the
  Mini through the CoreML execution provider) + live vision in the dash. ✅
  Driver monitoring (in-cabin, Vision framework) queued as phase 3b.
- Phase 4: supervised CAN transmit experiments (bench first, road much later).
