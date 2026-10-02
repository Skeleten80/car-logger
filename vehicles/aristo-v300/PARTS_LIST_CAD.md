# Aristo V300 Vehicle Computer — Parts List (CAD)

One important change from the generic `car-logger` parts list: **this car does
not speak CAN on its diagnostic port.** The JZS161's DLC3 carries ISO 9141-2
K-Line on pin 7 (see `profile.yaml`), so the CAN adapters in the parent list
(CANable, PCAN-USB, Kvaser) *cannot* talk to the engine ECU. The vehicle
interface below is swapped for a K-Line-capable adapter. Everything else
(power chain, Mini, mounting) is unchanged.

Prices in CAD. New prices checked **Oct 2, 2026**; carried-over power parts
last checked **Sep 30, 2026** (marked ↩). Verify at checkout — prices move.

Ownership: Mathias does **not** yet own the M6 Mac Mini (planned purchase —
marked TO-BUY). Everything else is also to-buy unless noted.

## Vehicle interface (the Aristo-specific part — pick one)

| Part | Notes | ~Price |
|---|---|---|
| **Recommended: OBDLink EX (USB)** | STN chipset, speaks ISO 9141-2 K-Line plus all OBD-II protocols. USB = no pairing dance, ideal for a headless Mini. python-OBD talks to it over serial on macOS with no extra driver. | ~$95 (US$69.95 on Amazon.com — ships from US) |
| **Budget: generic ELM327 USB v1.5** | Must have a genuine ELM327 chip and FTDI USB-serial (avoid the $12 clones — they lie about the chip version and fail K-Line init). Search Amazon.ca for "ELM327 USB FTDI". | ~$25–40 |

Link (verified via search index Oct 2, 2026 — Amazon blocks automated page
fetches, confirmed the listing exists at this URL):
- OBDLink EX: https://www.amazon.com/dp/B081VQVD3F/ref=cm_sw_r_cso_fm_apin_dp_PPM35EV279V9E6QCKBD0?badgeInsights=insights

Why not the CAN adapters: a CAN-only interface physically cannot do K-Line
signaling. Keep the CANable on the shelf as a fallback *only* if verification
ever finds CAN on pins 6/14 (profile says it won't).

## The computer

| Part | Notes | ~Price |
|---|---|---|
| Mac Mini M6, 16 GB — **TO-BUY** | Base model is plenty for logging + dash + Core ML vision. | $899 ↩ |

## Power (unchanged from parent architecture — the part that matters most)

Battery → 30 A fuse (<30 cm from terminal) → 10 AWG → ignition-switched 40 A
relay → 300 W pure-sine inverter → APC BE425M UPS → Mac Mini.

| Part | Notes | ~Price |
|---|---|---|
| 300 W **pure sine** inverter, 12 V → 110 V | Pure sine, not modified — Mini's PSU runs cooler/quieter. BESTEK 300 W pure-sine is the common pick. | ~$70 ↩ |
| APC Back-UPS BE425M (425 VA / 255 W) | Rides through crank dips; USB HID signal gives macOS clean auto-shutdown. | ~$117 ↩ |
| 40 A automotive relay + socket | Coil on an ACC-switched circuit — kills inverter input with the key, zero parked drain. | $10 ↩ |
| Inline fuse holder + 30 A fuse | Within 30 cm of battery positive. Non-negotiable. | $10 ↩ |
| 10 AWG stranded wire, ~5–6 m red + black | Sized for the inverter's full ~25 A draw, not just the Mini's ~5.5 A running. | $15 ↩ |
| Ring terminals, loom, zip ties | | $10 ↩ |

Link (carried from Sep 30 verification):
- APC BE425M, Dell Canada ($116.99): https://www.dell.com/en-ca/shop/apc-back-ups-425va-120v-6-nema-outlets-2-surge-battery-not-user-replaceable/apd/a9503792/power-cooling-data-center-infrastructure

macOS power settings (on first boot in the car): Energy → "Start up automatically
after a power failure" ON; UPS tab → shut down after ~2 min on UPS power.
Key-off sequence: relay drops → inverter dies → UPS holds → macOS shuts down
cleanly. Key-on: everything powers, Mini boots itself.

## Cabling / install extras

| Part | Notes | ~Price |
|---|---|---|
| J1962 OBD-II extension cable, ~1.5 m (optional) | Only if you want the ELM327 body tucked under trim with a clean run to the trunk — otherwise plug it straight into the DLC3. | ~$20 |
| USB-A to USB-C cable, short | If the adapter is USB-A (OBDLink EX is). Quality cable, minimal length. | $10–15 |
| Trunk mounting tray + foam isolation | Ventilated, out of direct sun. Mini is SSD-only; the fan is the only moving part. | $20–30 ↩ |

## Verification tools (buy once, use for every car)

| Part | Notes | ~Price |
|---|---|---|
| Toyota Techstream + Mini-VCI cable | The independent cross-check for the verification procedure: confirms what the ECU actually exposes (extended PIDs, DTCs) regardless of what any ELM327 reports. Search Amazon.ca for "Mini VCI Techstream". | ~$30–40 |

## Later phases (not now)

- GPS puck (USB) for speed/position overlay — ~$40–50
- USB dashcam for phase-3 vision — the parent README covers this
- Second ELM327 if you ever want a scan tool connected simultaneously (or a J1962 Y-splitter)

## Totals

- **Budget path** (generic ELM327 USB): $899 + $32 + $70 + $117 + $45 (power misc) + $25 (mount) + $12 (cables) ≈ **$1,200 CAD**
- **Recommended path** (OBDLink EX): ≈ **$1,265 CAD**
- Verification tools add ~$35 either way.

↩ = price carried from the Sep 30, 2026 check in the parent `PARTS_LIST.md`;
re-verify at checkout.
