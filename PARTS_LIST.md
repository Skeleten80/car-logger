# M6 Mac Mini Vehicle Computer — Parts List

Phase-1 goal: M6 Mac Mini in the trunk, read-only OBD-II/CAN logging beside the stock ECU.
All prices CAD, approximate — verify at checkout. Checked Sep 30, 2026.

## The computer

| Part | Notes | ~Price |
|---|---|---|
| Mac Mini M6, 16 GB | Base model is plenty for logging + dash + Core ML. 24 GB if you plan heavy local-LLM work. | $899 |

## CAN interface (pick one)

| Part | Notes | ~Price |
|---|---|---|
| **Budget:** DSD TECH SH-C31A (CANable 2.0 based, USB-C) | Open-hardware design, CAN FD capable. Ships with candleLight firmware (use `gs_usb`); flash slcan firmware if you want the `slcan` path. Available on Best Buy Canada marketplace. | $28 |
| **Mid:** PEAK PCAN-USB FD | Genuine article, galvanic isolation, CAN FD. macOS Apple Silicon driver via MacCAN PCBUSB (Universal binary). Now sold in a USB-C variant — ideal for the Mini. | $368 USD (~$510) |
| **Pro:** Kvaser Leaf v3 | The Leaf Light v2 (~$370 USD) is end-of-life; Kvaser's replacement is the Leaf v3 / U100 series. macOS driver via MacCAN KvaserCAN lib (has a Swift wrapper). Check kvaser.com for current v3 pricing. | ~$500+ |

Why three tiers: the $28 CANable is all phase 1 needs (OBD-II is classic CAN at 500 kbps).
Spend more only if you want isolation, vendor support, or guaranteed CAN FD later.

Links:
- PCAN-USB FD (Grid Connect, in stock): https://www.gridconnect.com/products/can-usb-fd-adapter-pcan-usb-fd?variant=8999331397668
- SH-C31A (Best Buy Canada): https://www.bestbuy.ca/en-ca/product/sh-c31a-usb-to-can-adapter-with-fd-support-based-on-canable-2-0/19688558
- Kvaser Leaf Light v2 EOL notice: https://phytools.com/products/kvaser-leaf-light-hs-v2

## Cabling (CAN side)

| Part | Notes | ~Price |
|---|---|---|
| OBD-II (J1962) to DB9 cable, ~1.5–2 m | Plugs into the car's diagnostic port, DB9 end into the adapter. Route it under trim to the trunk. | $15–25 |
| USB-C cable (if adapter is USB-A) | Short, quality cable. The SH-C31A and USB-C PCAN variant skip this. | $10–15 |

## Power (the part that matters most)

The Mini takes AC mains, and car 12 V is hostile (crank dips to ~7 V, load dumps, noise).
Architecture:

```
Battery --[30A fuse, <30cm from terminal]-- 10 AWG wire --> trunk
    --> ignition-switched 40A relay --> 300W pure-sine inverter
    --> compact UPS (USB to Mini) --> Mac Mini
```

| Part | Notes | ~Price |
|---|---|---|
| 300 W **pure sine** inverter, 12 V → 110 V | Pure sine, not modified — the Mini's PSU runs cooler and quieter on it. BESTEK 300 W pure-sine is the common pick (~$60–80 on Amazon.ca; their 500 W lists at $84.54). | ~$70 |
| APC Back-UPS BE425M (425 VA / 255 W) | Does two jobs: rides through crank dips (inverters cut out ~10 V) and gives macOS a USB HID UPS signal for clean auto-shutdown. ~$105–117 at Dell Canada / PrimeCables. | ~$115 |
| 40 A automotive relay + socket | Coil wired to an ACC-switched circuit. Kills inverter input with the key so nothing drains the battery parked. | $10 |
| Inline fuse holder + 30 A fuse | Within 30 cm of the battery positive terminal. Non-negotiable. | $10 |
| 10 AWG stranded wire, ~5–6 m, red + black | 65 W ÷ 12 V ≈ 5.5 A running, but size for the 300 W inverter's full draw (~25 A). | $15 |
| Ring terminals, loom, zip ties | | $10 |

UPS link (Dell Canada, $116.99): https://www.dell.com/en-ca/shop/apc-back-ups-425va-120v-6-nema-outlets-2-surge-battery-not-user-replaceable/apd/a9503792/power-cooling-data-center-infrastructure

### macOS power settings (do these on first boot in the car)

- System Settings → Energy → enable **"Start up automatically after a power failure"** (ignition-on boot).
- With the UPS connected over USB, the Energy settings gain a UPS tab → set **shut down after ~2 minutes on UPS power**.
- Sequence: key off → relay drops → inverter dies → UPS takes over → macOS shuts itself down cleanly. Key on → everything powers, Mini boots itself.

Budget alternative: skip the UPS and use a delay-off timer relay (~$15) that holds power 5 min
after key-off. Downside: the Mini reboots on every crank and gets hard-cut if the timer expires
mid-write. The UPS is worth it.

## Mounting / misc

| Part | Notes | ~Price |
|---|---|---|
| Trunk mounting tray + foam isolation | The Mini is SSD-only (no spinning disk); the fan is the only moving part. Keep it ventilated, out of direct sun. | $20–30 |
| Powered USB-C hub (optional) | If you add cameras / second adapter later. | $30–50 |

## Totals

- **Budget path:** $899 + $28 + $20 + $70 + $115 + $45 (power misc) + $25 (mount) ≈ **$1,200 CAD**
- **Mid path (PCAN-USB FD):** ≈ **$1,680 CAD**

## Phase-2+ shopping list (later, not now)

- Second CAN adapter (dual-bus: powertrain + body CAN simultaneously)
- USB camera(s) for Core ML vision experiments
- OBD-II Y-splitter if you want a scan tool connected at the same time
