# CarDash

The live macOS dashboard client for the car-logger dash server — phase 2 of
the vehicle-computer project. Native SwiftUI + Charts, macOS 14+, zero
third-party dependencies. Styled after the spacecraft-sim MissionOps screen:
dark theme, telemetry cards, strip charts.

## Running it

1. On the Mac, open this folder in Xcode: **File > Open > `CarDash`**
   (select the folder containing `Package.swift`).
2. Run the **CarDash** scheme with **⌘R**.
3. In the header bar, change the host field to the Mini's address, e.g.
   `http://mini.local:8080` or the hotspot IP (default is
   `http://127.0.0.1:8080`), then hit **Connect**. The host persists in
   `UserDefaults` between runs.

**The Python dash server must be running on the Mini alongside the logger**
(`python -m carlogger.dash`) — CarDash is only a client. It needs:

- `GET /api/info` — session metadata (vehicle label, loaded DBC files)
- `GET /api/live` — Server-Sent Events, one `data: <JSON>` event ~every 0.5 s
- `GET /api/history?signal=rpm&limit=600` — RPM backfill for the strip chart

## What it shows

- **Header:** app title, vehicle label (or session ID) from `/api/info`,
  connection pill (LIVE green / CONNECTING–RECONNECTING amber / OFFLINE red),
  host field + Connect/Disconnect.
- **Gauge cards:** RPM arc gauge (0–8000), speed (km/h, big number), coolant
  temperature (degC, with bar), throttle (%), fuel level (%), MAF (g/s).
  Missing readings render as "—" until the logger has seen them.
- **Strip chart:** engine-speed history from the SSE stream, backfilled on
  connect via `/api/history?signal=rpm`.
- **Decoded signals table:** live DBC-decoded signals (name, value, unit,
  message). When no DBC is loaded on the server it shows
  "No DBC loaded — raw OBD-II only".

## Behavior notes

- The SSE client reconnects with exponential backoff (1 s → 30 s cap) on
  disconnects; the pill shows RECONNECTING while it retries.
- RPM history is capped at 2400 points (~20 min at 2 Hz) and trimmed in
  halves, same as the MissionOps charts.
- Coolant bar turns red above 105 degC; fuel bar turns red below 15%.
