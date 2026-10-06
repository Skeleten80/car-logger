# toyota-diag

Free, open-source K-Line diagnostic tooling for 1990s–2000s JDM Toyotas
(e.g. 1997 Toyota Aristo JZS161, 2JZ-GTE VVTi) — cars whose ECUs ignore
generic OBD-II scanners.

## Honest status: v0.1 is a discovery instrument

Toyota's K-Line protocol for these cars is only *partially* documented by
the enthusiast community. v0.1 does not pretend to decode it. Instead it:

1. Probes the diagnostic port with every init sequence the community knows
   (ISO 9141-2, KWP2000 slow/fast init, Toyota extended mode `$21`, bus monitor),
2. Logs **every byte** exchanged to a timestamped JSONL file,
3. Decodes whatever *generic* OBD-II the ECU happens to speak (RPM, speed,
   coolant, DTCs…),
4. Captures Toyota-proprietary responses **raw** so decoding tables can be
   built from real logs.

**v0.1 is deliberately read-only.** It never sends code-clear, actuator-test,
or reprogramming commands. It cannot brick your ECU.

## Hardware

- Any ELM327-compatible adapter (USB recommended; Bluetooth/Wi-Fi also work
  if they expose a serial port).
- **Get a v1.5 clone, not v2.1.** The v2.1 clones are notorious for broken
  firmware that lies about supported AT commands. (~$15–25.)
- The car's DLC3 port: K-Line is pin 7. Ignition ON; engine can be off for
  codes, running for live data.

## Install

```bash
cd car-logger/toyota-diag
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Usage

```bash
# find the adapter's serial port
.venv/bin/toyota-diag ports

# probe everything, log to probe-<timestamp>.jsonl
.venv/bin/toyota-diag --help
.venv/bin/toyota-diag probe --port /dev/ttyUSB0

# probe only one attempt
.venv/bin/toyota-diag probe --port /dev/ttyUSB0 --attempt iso9141_5baud

# best-effort decode of a saved log
.venv/bin/toyota-diag decode-log probe-20261006-120000.jsonl
```

Probe attempts:

| attempt | what it tries |
|---|---|
| `iso9141_5baud` | ISO 9141-2, 5-baud init + generic OBD-II |
| `kwp2000_5baud` | KWP2000, 5-baud init + generic OBD-II |
| `kwp2000_fastinit` | KWP2000, fast init + generic OBD-II |
| `toyota_mode21` *(experimental)* | Toyota extended mode `$21` over K-Line |
| `bus_monitor` *(experimental)* | `ATMA`: capture any ECU chatter for 5 s |

The `probe` command prints a per-attempt hit summary (`answered/sent`).
**Send the `.jsonl` log back for analysis** — real Toyota responses in it
are what v0.2 decoders get built from.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

All hardware access is behind an injectable serial factory; the suite runs
with zero hardware attached.

## Roadmap

- **v0.2** — decode tables for Toyota `$21` responses, built from real probe logs
- **v0.3** — live-data polling loop (RPM / MAP / temps) + CSV logging
- **v0.4** — DTC read/clear as explicit, confirmed user actions (never automatic)

## Protocol notes

- Physical layer: ISO 9141-2, 10.4 kbaud, K-Line on DLC3 pin 7.
- Init: 5-baud init to address `$33` (ELM327 protocol 3) or KWP2000
  variants (protocols 4/5). The ELM327 handles the timing.
- Generic payloads use standard SAE J1979 mode `$01`/`$03`/`$09` framing.
- Toyota extended diagnostics (mode `$21`) use proprietary PID layouts;
  v0.1 captures them raw.

## License

MIT.
