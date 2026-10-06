# Coil + injector sub-harness — JZS161 Aristo V300 (2JZ-GTE VVTi)

A from-scratch replacement for the coil and injector section of the engine
harness: one removable sub-harness from a bulkhead disconnect to the coils
and injectors. Target: eliminate 29-year-old wiring as a variable.

> **Correction (Oct 6, 2026):** the VVTi 2JZ-GTE uses **3 wasted-spark coil
> packs** (Denso 90919-02216; ECU drives IGT1 = coils 1+6, IGT2 = 2+5,
> IGT3 = 3+4) plus an external igniter module — *not* 6 individual COP
> coils. This matters: all three packs share one +B power feed, so a single
> bad joint (like the repaired power clip) starves the entire ignition.

## 1. Architecture

```
                          ┌─────────────────────────────────┐
                          │  FACTORY (untouched)              │
                          │  EFI relay + fuse ──► +B (key ON) │
                          │  ECU ──► IGT1/2/3, INJ1..6, IGF   │
                          │  igniter module (stays on mount)  │
                          └──────────────┬──────────────────┘
                                         │  ← cut & repin here
                          ┌──────────────┴──────────────────┐
                          │  BULKHEAD (new, serviceable)    │
                          │  Deutsch DT 12-way (injectors)   │
                          │  Deutsch DT  8-way (coils)       │
                          └──────┬───────────────┬──────────┘
                    ┌────────────┘               └────────────┐
              COIL BRANCH                              INJECTOR BRANCH
        3 × coil-pack connectors                  6 × injector connectors
        (2-pin Denso)                             (2-pin Denso top-slot)
```

- **Coil branch:** per pack — Pin A: +B (switched 12V, EFI relay circuit;
  factory wire is black with a thin white stripe — confirmed on this car
  Oct 6, 2026);
  Pin B: trigger return to the igniter. **Verify pin assignment on your car**
  (key ON: +B reads ~12V; other pin shows continuity to the igniter
  connector with igniter unplugged).
- **Injector branch:** per injector — Pin 1: +B (common switched 12V, same
  black/white factory feed);
  Pin 2: ECU-switched ground (individual per cylinder, #10–#60). **Verify:**
  +B reads ~12V key ON; signal pin shows continuity to the ECU injector
  pins with the ECU unplugged (or use a noid light with engine running).
- **Grounds:** dedicated 16 AWG from the bulkhead area to a cylinder-head
  bolt and to the chassis star point. Do not rely on mounting bolts alone.
- The igniter module, EFI relay/fuse, and ECU connectors stay factory —
  only the wire *between* them is renewed.

## 2. Wire schedule (1:1 through the bulkhead — most serviceable)

| # | From | To | Function | Gauge (TXL) | Suggested color |
|---|------|----|----------|-------------|-----------------|
| 1–3 | Bulkhead A 1–3 | Coil packs 1–3, pin A | +B (switched 12V) | 18 AWG | red |
| 4–6 | Bulkhead A 4–6 | Coil packs 1–3, pin B | trigger → igniter | 20 AWG | white / white-black / white-red |
| 7 | Bulkhead A 7 | head bolt ring terminal | ground | 16 AWG | black |
| 8 | Bulkhead A 8 | — | **spare** | 20 AWG | — |
| 9–14 | Bulkhead B 1–6 | Injectors 1–6, pin 1 | +B (switched 12V) | 18 AWG | red |
| 15–20 | Bulkhead B 7–12 | Injectors 1–6, pin 2 | ECU injector drive | 20 AWG | yellow, green, blue, orange, violet, grey |

Total: 20 conductors. (Alternative: common the six injector +B feeds on the
engine side to save pins — 1:1 is recommended for per-cylinder diagnosis.)

## 3. Parts

- **Wire:** TXL thin-wall automotive wire — 16 AWG (~3 m), 18 AWG (~15 m),
  20 AWG (~25 m). TXL, not generic hookup wire (heat + oil resistant).
- **Coil connectors:** 3× 2-pin Denso coil-pack pigtails — Wiring Specialties
  "2JZ Coilpack Connector" (pigtail or housing+terminals), or Toyota
  90980-11246 housings. **Match to your packs before ordering.**
- **Injector connectors:** 6× Denso top-slot 2-pin pigtails (Toyota
  90980-11153 housing / Sumitomo 6189-0060, 2.3 mm terminals). Verify
  top-slot keying against your injectors.
- **Bulkhead:** 1× Deutsch DT 12-way + 1× Deutsch DT 8-way (housings, pins,
  seals, locking wedges).
- **Terminations:** open-barrel crimper + correct terminals; adhesive-lined
  heat shrink for any splice to factory wire; braided sleeving or DR-25 for
  looming; ring terminals for grounds.
- **Rule:** crimp new pins into new housings wherever possible. Solder +
  adhesive shrink only where joining to existing factory wire.

## 4. Build order

1. **Template first.** With the old harness still in place, lay string along
   the routing (bulkhead location → each coil/injector, with service loops).
   Measure twice; add 10% and build on the bench.
2. Crimp all terminals, assemble connectors, continuity-check every wire
   end-to-end (< 1 Ω) *before* looming.
3. Loom, keeping the coil branch and injector branch separable.
4. Install: mount bulkhead, route, connect. Do **not** cut the factory
   harness until the new one is built and bench-verified.

## 5. Verification (before first start — non-negotiable)

1. Battery disconnected: continuity every wire, end to end (< 1 Ω).
2. Isolation: no continuity between adjacent bulkhead pins; no signal wire
   shorted to ground or +B.
3. Battery connected, key ON (engine off): +B pins read battery voltage;
   grounds read < 0.5 Ω to battery negative.
4. Start, idle 5 min: recheck +B at the coil connectors (~13.8–14.4 V),
   voltage drop across the whole new feed (< 0.2 V).
5. Road test through the previously bad RPM bands.

## 6. Honest unknowns (verify on YOUR car, not from this doc)

- Coil-pack connector pinout (which pin is +B) — meter it, don't assume.
- Injector connector pinout — meter it.
- ECU pin numbering: the published 2JZ-GTE VVTi pinout floating around is
  from the Supra JZA80; your Aristo's automatic-transmission ECU may differ
  in connector layout. Identify wires by function (12V key-ON / continuity
  to ECU pins), never by assumed colors.
- IGF (igniter feedback to ECU): left on the factory igniter wiring in this
  plan; if you extend it, keep it twisted/shielded as factory.

## 7. Cost sanity check

Wire + connectors + sleeving + crimper (if you don't own one): roughly
$120–200 CAD in parts. A shelf replacement engine harness (e.g. Wiring
Specialties) runs several times that — this sub-harness is the
cost-effective middle ground, and it targets the exact circuit your
symptoms implicate.
