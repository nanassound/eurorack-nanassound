# EuroPlatvorm Pre-Fabrication Design Review

**Project:** EuroPlatvorm (KiCad, single sheet, 4-layer PCB, 21.7 × 89.75 mm eurorack format)
**Date:** 2026-09-18
**Analyzers run:** `analyze_schematic.py`, `analyze_pcb.py --full`, `analyze_gerbers.py`, `cross_analysis.py`, `analyze_emc.py`, `analyze_thermal.py`, deep-review pass (`analysis/deep_review.json`, gate-verified 8 findings, 0 quarantined)
**Analysis run:** `analysis/2026-09-18_0008/`

## Verdict: BLOCKED — one critical fix required before fabrication

**U3 (USBLC6-2SC6) library symbol pin map contradicts the datasheet.** As drawn, the board wires the chip's D+ ESD node to the 5 V VBUS rail and leaves the chip's actual VBUS pin floating. USB will not work and 5 V lands on the ESP32-C6's non-5V-tolerant USB_D+ pad. Fix the symbol, rewire pins 4/5/6, re-route the two affected pads, re-export gerbers. Everything else on the board is fab-ready.

## Critical Findings

| Severity | Issue | Detail |
|----------|-------|--------|
| **CRITICAL** | U3 symbol pins 4/5/6 wrong | Symbol (`platvorm.kicad_sym` line 1233): pin4=NC, pin5=NC, pin6=VBUS. ST datasheet (p.1, Figure 1): pin4=I/O2, pin5=VBUS, pin6=I/O1. PCB pads confirmed: pad4 & pad5 unconnected, pad6→/VBUS. Physical chip: D+ node (I/O1, pin 6) shorted to 5 V VBUS; real VBUS pin floats → ESD steering defeated. Datasheet-verified. |
| WARNING | +3V3 dual-sourced, no isolation | U1 buck output (via L1) and U2 AMS1117 output tie directly to +3V3. Eurorack-only operation back-feeds ~2.7 V onto VBUS through the AMS1117's reverse path (unspez'd operation; PTC limits current). Raw-file verified. |
| WARNING | AMS1117 with all-MLCC output bank | Datasheet (p.4) guarantees stability with 22 µF *tantalum*; design uses 4×22 µF X5R (milliohm ESR). Usually fine in practice, outside characterized comp. Datasheet-verified. |
| WARNING | U4 module LCSC stock = 590 units | ESP32-C6-WROOM-1-N4 (C6034714) is the only low-stock line; fine for prototypes, tight for production. Extended (non-basic) part. |

## Component Summary

34 components / 25 BOM lines / 44 nets / 4 connectors. MPN coverage 100% (SS-003 pass, no DS-001/002/003 findings). Types: 4 ICs (TPS54202DDCR, AMS1117-3.3, USBLC6-2SC6, ESP32-C6-WROOM-1-N4), 1 SS34, 1 LED, 2 PTCs, 8 R, 11 C, 1 L, 2 switches, 4 connectors.

## Power Tree (raw-file verified)

```
Eurorack +12V (J1.9/10) ──F1 500mA PTC──D1 SS34──┬── U1 TPS54202 buck ──L1 10µH──┬─→ +3V3 (3.305V)
                                                  └─ C1 10µ/25V, C2 100n          │  R1 100k/R2 22k FB (VFB 0.596V)
USB-C VBUS (J2 A4B9/B4A9) ──F2 500mA PTC───────────────── U2 AMS1117-3.3 ────────┘  (3.3V)
                                                                                  C4/C5/C8/C10 4×22µF + C11 100nF
-12V (J1.1/2) → J3.3 breakout only (unused by module)
```

Both regulators feed +3V3 with no ORing (see warning). EN of U1 floats — **correct per datasheet** ("Float the EN pin to enable", p.3; internal pullup-current source, §6.3.5 p.9). Vout = 0.596 V × (1 + 100k/22k) = **3.305 V** (VFB row, p.5). BOOT–SW cap C3 100 nF as required (Table 4-1).

## LCSC Availability (jlcsearch, checked 2026-09-18)

**All 25 BOM lines in stock.** Exact-MPN matches with comfortable stock except as noted:

| Line | LCSC | Stock | Note |
|------|------|-------|------|
| U4 ESP32-C6-WROOM-1-N4 | C6034714 | **590** | ⚠ low; extended part |
| J2 TYPE-C-31-M-12 | **C165948** | 89,797 | ⚠ MPN text not indexed by jlcsearch; C165948 is the classic listing (16P right-angle receptacle) — confirm at order time |
| U1 TPS54202DDCR | C191884 | 180,809 | extended |
| U2 AMS1117-3.3 | C6186 | 2,007,447 | **basic part** |
| U3 USBLC6-2SC6 | C2687116 | 150,192 | extended |
| J1 PZ254V-12-10P | C492422 | 114,152 | |
| All passives/D1/D2/F1/F2/L1/SW | — | 23k–12.6M | exact match, ample stock |

Raw availability JSON: `analysis/2026-09-18_0008/lcsc_availability.json` (helper: `analysis/helpers/lcsc_check.py`).

## Schematic / Signal Review

- **U3 USBLC6 wiring (apart from the blocker):** UFP configuration correct — R3/R4 5.1 k on CC1/CC2, D+/D- both receptacle rows (A6/B6, A7/B7) to net, SBU NC, shield to GND. After the pin-map fix, pins 4/5/6 rewire to USB_DM/VBUS/USB_DP.
- **ESP32-C6-WROOM-1:** symbol verified pin-for-pin against datasheet Table 3-1 (p.11), incl. pin 22 NC. EN: R5 10k + C9 1 µF (15.9 Hz RC) + SW1 — satisfies "Do not leave the EN pin floating". BOOT strap GPIO9: R6 pull-up + SW2 = normal flash boot / download button. GPIO8 strap pulled up (R7). USB_D± = GPIO13/GPIO12 ✓ native USB Serial/JTAG.
- **J1 eurorack pinout:** 10/10 pins match the de-facto convention (helper `analysis/helpers/j1_pin_audit.py`); D1+F1 protect against reversed ribbon. Convention-verified (medium confidence — the bus standard has no connector datasheet).
- **LED D2:** 3.3 V → R8 1k → green LED ≈ 1.3 mA. Dim but valid power indicator.
- **RC filter R5/C9** = EN delay (correct role); C6 56 pF across R1 = buck FB feedforward, plausible (fc ≈ 28 kHz vs 500 kHz fsw).

## PCB / Gerber Review

- **Routing complete** (0 unrouted of 44 nets), 535 tracks, 85 vias, In1 = GND plane, In2 = +3V3 plane (zero signal tracks on inner layers — good stackup).
- **U4 ESP32 module:** all 29 pads on-board (nearest pad 1.64 mm inside top edge); antenna region overhangs top edge ~3 mm — recommended edge-mount antenna placement. PM-002 INFO is intentional geometry.
- **J2 USB-C:** all pads ≥1.75 mm inside bottom edge; 0.87 mm courtyard overhang = connector shell at mating edge — intentional. PM-002 ERROR dismissed.
- **C11 (0402) 0.54 mm from board edge:** pads ≥0.45 mm from edge — above the 0.3 mm JLCPCB copper-to-edge minimum. Tight but fab-legal.
- **Via-in-pad (VP-001):** U2.2 tab ×4 — these are the thermal path to the In2 plane; untented, acceptable but solder-wick risk during reflow (recommend tenting or accepting paste over-sizing). U4:10 (GPIO8) one untented via in a castellated pad — minor.
- **USB pair:** 90.3/82.6 mm — 7.6 mm intra-pair skew, mixed F/B layers. Fine for FS (12 Mbps) USB-JTAG; re-match to <2 mm if HS ever used.
- **+3V3 In2 pour = 2 islands**, stitched by 14 vias + F.Cu tracks (PS-002) — connected; minor return-path note for B.Cu signals crossing the split.
- **Fiducials: none** (FD-001). Only matters for PCBA; JLCPCB can place using panel fiducials but add 2–3 if ordering assembly. Bare-board fab unaffected.
- **Gerbers complete:** all 11 layers + PTH/NPTH drills present and aligned; B.Paste legitimately empty (J3/J4 are THT on back). Board dims 21.7 × 89.75 mm confirmed in Edge.Cuts.

## Thermal

TS-002 (U2 Tj=115 °C) and TS-004 (no thermal vias) are **false premises**: U2's input is VBUS (5 V), not 12 V. Recomputed: 0.65 W peak (Wi-Fi TX 382 mA), 0.85 W sustained max (F2 500 mA bound) vs 1.2 W SOT-223 rating — Tj ≈ 60–75 °C worst case; the 4 tab vias to the +3V3 plane exist (see VP-001). U1 buck: 60 °C, 65 °C margin. No thermal blocker.

## EMC

Score 38.5/100 driven largely by findings triaged below. Real residual items: SW-001 buck 500 kHz harmonics in the 30–88 MHz band conducted onto the +12V bus (eurorack case: could couple into analog neighbors — a small input ferrite/π-filter would help if that shows up in practice); PD-001 +3V3 PDN anti-resonance (model-level note; 4×22 µF + module caps is reasonable for this load); 21+ RP-001 layer-transition stitching warnings are generic for a 2-signal-layer board with solid planes — low priority at FS speeds.

## False Positives / Reviewer Overrides

| Finding | Disposition |
|---------|-------------|
| PP-001 U1.VIN no DC path (ERROR) | **False positive** — VIN fed through F1 + D1 (SS34); diode edge not traversed by the BFS |
| PU-001 U1 EN missing pull-up | **False positive** — datasheet: float EN to enable (internal pullup current source) |
| TS-002 / TS-004 U2 thermal | **False premise** — input is 5 V VBUS not 12 V; recomputed 0.65 W peak; tab vias exist |
| SU-001 adjacent signal layers F/In1 | **False positive** — In1/In2 carry zero tracks; both are dedicated planes |
| GP-001 /-12V reference gap (ERROR) | **False positive** — DC power net routed to J3.3, not a signal; loop-antenna logic N/A |
| GR-004 paste 49% of copper flashes | **False positive** — copper count includes 85 via pads + 10 THT; paste (121) ≥ SMD pads on F.Cu (112) |
| GR-002 layer width variance 2.5 mm | **Benign** — copper stops short of edge clearance vs outline; B.Silkscreen art extent is 90.18 mm vs 89.75 mm board height → ~0.4 mm of sketch art clips at the edge (cosmetic) |
| PM-002 J2/U4 courtyard overhang | **Intentional** — edge-mount USB-C shell; ESP32 antenna overhang (pads all on-board) |
| TE-001 0% test points | Accepted — hand-debug hobby module; GPIOs all on J3/J4 headers |
| UC-001 VBUS no decoupling at J2 | Soft-dismiss — C7 10 µF on VBUS net (placement distance heuristic) |

## BOM / Sourcing Notes

- C4/C5/C8/C10 value field says "22uF 10V" but MPN CL21A226MQQNNNE = **6.3 V** part (fine at 3.3 V; fix the value string to avoid ordering confusion).
- F2 = 500 mA PTC on USB VBUS: bounds LDO sustained current; OK for ESP32-C6 peaks.
- VBUS uses nine 0.2 mm segments after F2 — passes IPC for <0.5 A with modest rise; widen to 0.3 mm if you touch the layout anyway.

## Not Performed / Review Limits

- **SPICE simulation not run** — no ngspice/LTspice/Xyce installed on this machine.
- **Formal lifecycle audit not run** — `analyze_schematic.py --lifecycle` needs distributor keys (none set); LCSC stock/availability for all 25 lines checked instead (all active, in stock). No NRND/EOL data queried.
- **J1 pinout convention-verified only** (de-facto standard; no authoritative datasheet table exists for the bus pinout) — medium confidence; red-stripe silkscreen check recommended at assembly.
- No prior review/delta exists (first review; analysis manifest has only this run's hashes).

## Verification Basis

Datasheet-verified: U3 pinout (ST USBLC6-2 p.1), U1 EN/VFB/BOOT (TI TPS54202 p.3/5/9), U2 stability & 1.2 W rating (AMS1117 p.3/4), U4 pin table + EN note (Espressif p.11). Raw-file verified: all nets above, PCB pad→net map for U3/J1/J2/U4, board outline vs pad extents, track layer distribution, paste/copper counts. Analyzer-derived: LCSC stock figures, EMC scoring, remaining statistics. Datasheets cached in `datasheets/`.
