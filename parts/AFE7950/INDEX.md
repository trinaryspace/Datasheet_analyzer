# AFE7950 — datasheet corpus

> The AFE7950 is a high performance, wide bandwidth multi-channel transceiver, integrating four RF sampling transmitter chains, four RF sampling receiver chains and two RF sampling feedback chains (six RF sampling ADCs total). With operation up to 12 GHz, this device enables direct RF sampling in the L, S, C and X-band frequency ranges without the need for additional frequency conversions stages. This improvement in density and flexibility enables high-channel-count, multi-mission systems.

## Key facts (verbatim from Features, p.1)

- Quad RF sampling 12GSPS transmit DACs
- Quad RF sampling 3GSPS receive ADCs
- Dual RF sampling 3GSPS feedback (auxilliary RX) ADCs
- Maximum RF signal bandwidth:
- 4TX or 2FB: 1200MHz or 2TX: 2400MHz
- RX: 1200MHz (no FB), 600MHz (with FB)
- RF frequency range:
- TX: 600MHz - 12GHz
- RX/FB: 600MHz -12GHz
- Digital step attenuators (DSA):
- TX: 40dB range, 0.125dB steps
- RX or FB: 25dB range, 0.5dB steps
- Single or dual-band DUC or DDCs for TX and RX
- 16x NCOs per TX or RX and FB
- Optional Internal PLL or VCO for DAC or ADC clocks or external clock at DAC or ADC sample rate
- SerDes data interface:
- JESD204B and JESD204C compatible
- 8 SerDes transceivers up to 29.5Gbps
- Subclass 1 multi-device synchronization
- Package: 17mm × 17mm FCBGA, 0.8mm pitch

## Documents

- `datasheet` SBASA41E — 146 pages — `docs/datasheet-c1b4663b/`

## How to use this corpus

- Read `AGENT.md` beside this file first: the retrieval protocol (both access paths, citations, the confidence rule).

## Section map — `datasheet-c1b4663b`

- **1 Features** — p.1 — `docs/datasheet-c1b4663b/sections/1-features.md` (213 tok)
  Quad 12GSPS TX DACs, quad 3GSPS RX ADCs, dual 3GSPS feedback ADCs, 600MHz-12GHz RF, 1200MHz-2400MHz bandwidth, 40dB …
- **2 Applications** — p.1 — `docs/datasheet-c1b4663b/sections/2-applications.md` (42 tok)
  Radar, seeker front end, defense radio, tactical communications infrastructure, wireless communications test …
- **3 Description** — p.1-3 — `docs/datasheet-c1b4663b/sections/3-description.md` (468 tok, 1 tables)
  AFE7950 high-performance multi-channel transceiver: 4 TX chains, 4 RX chains, 2 feedback chains, direct RF sampling …
- **4 Specifications** — p.4-133 — `docs/datasheet-c1b4663b/sections/4-specifications.md` (14 tok)
  Specifications and electrical characteristics
- **4.1 Absolute Maximum Ratings** — p.4 — `docs/datasheet-c1b4663b/sections/4-1-absolute-maximum-ratings.md` (660 tok, 1 tables)
  Absolute maximum ratings: PMAX(xRXIN+/-), junction temperature TJ, storage temperature Tstg
- **4.2 ESD Ratings** — p.5 — `docs/datasheet-c1b4663b/sections/4-2-esd-ratings.md` (136 tok, 1 tables)
  ESD ratings: V(ESD) electrostatic discharge voltage
- **4.3 Recommended Operating Conditions** — p.6 — `docs/datasheet-c1b4663b/sections/4-3-recommended-operating-conditions.md` (243 tok, 1 tables)
  Recommended operating conditions: ambient temperature TA, junction temperature TJ
- **4.4 Thermal Information** — p.6 — `docs/datasheet-c1b4663b/sections/4-4-thermal-information.md` (187 tok, 1 tables)
  Thermal information: RθJA, RθJC(top), RθJB, ΨJT, ΨJB thermal parameters
- **4.5 Transmitter Electrical Characteristics** — p.7-13 — `docs/datasheet-c1b4663b/sections/4-5-transmitter-electrical-characteristics.md` (5945 tok, 1 tables)
  TX electrical: DAC resolution, RF output frequency, max full-scale power, termination impedance, attenuator …
- **4.6 RF ADC Electrical Characteristics** — p.14-17 — `docs/datasheet-c1b4663b/sections/4-6-rf-adc-electrical-characteristics.md` (3496 tok, 1 tables)
  RX ADC electrical: ADC resolution, RF input frequency, full-scale CW power, S11 return loss, DSA range/step, noise …
- **4.7 PLL/VCO/Clock Electrical Characteristics** — p.18-19 — `docs/datasheet-c1b4663b/sections/4-7-pll-vco-clock-electrical-characteristics.md` (1116 tok, 1 tables)
  PLL/VCO/clock electrical: VCO frequencies fVCO1-4, DAC/feedback ADC/RX ADC dividers, VCO phase noise
- **4.8 Digital Electrical Characteristics** — p.20 — `docs/datasheet-c1b4663b/sections/4-8-digital-electrical-characteristics.md` (1245 tok, 1 tables)
  Digital electrical: JESD input/output differential/common voltage, impedance, SerDes frequency, timing parameters
- **4.9 Power Supply Electrical Characteristics** — p.21-26 — `docs/datasheet-c1b4663b/sections/4-9-power-supply-electrical-characteristics.md` (9609 tok, 1 tables)
  Power supply electrical: supply currents IVDD1P8/1P2/0P9, power dissipation Pdiss
- **4.10 Timing Requirements** — p.27 — `docs/datasheet-c1b4663b/sections/4-10-timing-requirements.md` (432 tok, 1 tables)
  Timing requirements: SYSREF/SENB/SDIO setup/hold times, SCLK write/read periods
- **4.11 Switching Characteristics** — p.28 — `docs/datasheet-c1b4663b/sections/4-11-switching-characteristics.md` (685 tok, 1 tables)
  Switching characteristics: JESD latency TX/RX/feedback tJESD
- **4.12 Typical Characteristics** — p.29-133 — `docs/datasheet-c1b4663b/sections/4-12-typical-characteristics.md` (17 tok)
  Typical characteristics curves and performance plots
- **4.12.1 TX Typical Characteristics 800 MHz** — p.29-37 — `docs/datasheet-c1b4663b/sections/4-12-1-tx-typical-characteristics-800-mhz.md` (2089 tok, 43 figs)
  TX typical characteristics at 800MHz: 11796.48MSPS DAC, 491.52MSPS input, 24x interpolation, interleave mode, PLL …
- **4.12.2 TX Typical Characteristics at 1.8 GHz** — p.38-45 — `docs/datasheet-c1b4663b/sections/4-12-2-tx-typical-characteristics-at-1-8-ghz.md` (1776 tok, 34 figs)
  TX typical characteristics at 1.8GHz: 11796.48MSPS DAC, 491.52MSPS input, 24x interpolation, interleave mode, PLL …
- **4.12.3 TX Typical Characteristics at 2.6 GHz** — p.46-54 — `docs/datasheet-c1b4663b/sections/4-12-3-tx-typical-characteristics-at-2-6-ghz.md` (2068 tok, 40 figs)
  TX typical characteristics at 2.6GHz: 11796.48MSPS DAC, 491.52MSPS input, 24x interpolation, interleave mode, PLL …
- **4.12.4 TX Typical Characteristics at 3.5 GHz** — p.55-60 — `docs/datasheet-c1b4663b/sections/4-12-4-tx-typical-characteristics-at-3-5-ghz.md` (1335 tok, 31 figs)
  TX typical characteristics at 3.5GHz: 11796.48MSPS DAC, 491.52MSPS input, 24x interpolation, interleave mode, PLL …
- **4.12.5 TX Typical Characteristics at 4.9 GHz** — p.61-68 — `docs/datasheet-c1b4663b/sections/4-12-5-tx-typical-characteristics-at-4-9-ghz.md` (1798 tok, 35 figs)
  TX typical characteristics at 4.9GHz: 11796.48MSPS DAC, 491.52MSPS input, 24x interpolation, interleave mode, PLL …
- **4.12.6 TX Typical Characteristics at 8.1 GHz** — p.69-78 — `docs/datasheet-c1b4663b/sections/4-12-6-tx-typical-characteristics-at-8-1-ghz.md` (1085 tok, 45 figs)
  TX typical characteristics at 8.1GHz: 11796.48MSPS DAC, 491.52MSPS input, 24x interpolation, mixed mode, PLL fREF …
- **4.12.7 TX Typical Characteristics at 9.6 GHz** — p.79-89 — `docs/datasheet-c1b4663b/sections/4-12-7-tx-typical-characteristics-at-9-6-ghz.md` (1392 tok, 3 tables, 51 figs)
  TX typical characteristics at 9.6GHz: 4x100MHz NR output spectrum and EVM measurements
- **4.12.8 RX Typical Characteristics at 800 MHz** — p.90-96 — `docs/datasheet-c1b4663b/sections/4-12-8-rx-typical-characteristics-at-800-mhz.md` (1272 tok, 31 figs)
  RX typical at 800MHz: 2949.12GSPS ADC sampling, 491.52MSPS output (decimate 6), PLL fREF 491.52MHz, DSA 4dB
- **4.12.9 RX Typical Characteristics at 1.75 GHz – 1.9 GHz** — p.97-102 — `docs/datasheet-c1b4663b/sections/4-12-9-rx-typical-characteristics-at-1-75-ghz-1-9-ghz.md` (1266 tok, 30 figs)
  RX typical at 1.75-1.9GHz: 2949.12GSPS ADC sampling, 491.52MSPS output (decimate 6), PLL fREF 491.52MHz, DSA 4dB
- **4.12.10 RX Typical Characteristics at 2.6 GHz** — p.103-108 — `docs/datasheet-c1b4663b/sections/4-12-10-rx-typical-characteristics-at-2-6-ghz.md` (1315 tok, 34 figs)
  RX typical at 2.6GHz: 2949.12GSPS ADC sampling, 491.52MSPS output (decimate 6), PLL fREF 491.52MHz, DSA 4dB
- **4.12.11 RX Typical Characteristics at 3.5 GHz** — p.109-113 — `docs/datasheet-c1b4663b/sections/4-12-11-rx-typical-characteristics-at-3-5-ghz.md` (1113 tok, 27 figs)
  RX typical at 3.5GHz: 2949.12GSPS ADC sampling, 491.52MSPS output (decimate 6), PLL fREF 491.52MHz, DSA 4dB
- **4.12.12 RX Typical Characteristics at 4.9 GHz** — p.114-119 — `docs/datasheet-c1b4663b/sections/4-12-12-rx-typical-characteristics-at-4-9-ghz.md` (1191 tok, 29 figs)
  RX typical at 4.9GHz: 2949.12GSPS ADC sampling, 491.52MSPS output (decimate 6), PLL fREF 491.52MHz, DSA 4dB
- **4.12.13 RX Typical Characteristics at 8.1GHz** — p.120-123 — `docs/datasheet-c1b4663b/sections/4-12-13-rx-typical-characteristics-at-8-1ghz.md` (589 tok, 27 figs)
  RX typical at 8.1GHz: 2949.12GSPS ADC, 1474.56MSPS output (decimate 2), external clock 11796.48MHz, DSA 3dB
- **4.12.14 RX Typical Characteristics at 9.6 GHz** — p.124-128 — `docs/datasheet-c1b4663b/sections/4-12-14-rx-typical-characteristics-at-9-6-ghz.md` (539 tok, 26 figs)
  RX typical at 9.6GHz: 2949.12GSPS ADC, 1474.56MSPS output (decimate 2), external clock 11796.48MHz, DSA 3dB
- **4.12.15 PLL and Clock Typical Characteristics** — p.129-133 — `docs/datasheet-c1b4663b/sections/4-12-15-pll-and-clock-typical-characteristics.md` (1317 tok, 31 figs)
  PLL and clock typical characteristics: phase noise measurements at TX output, fREF 491.52MHz
- **5 Revision History** — p.134-135 — `docs/datasheet-c1b4663b/sections/5-revision-history.md` (1032 tok)
  Revision history documenting changes from prior versions
- **6 Device and Documentation Support** — p.136 — `docs/datasheet-c1b4663b/sections/6-device-and-documentation-support.md` (18 tok)
  Device and documentation support resources
- **6.1 Receiving Notification of Documentation Updates** — p.136 — `docs/datasheet-c1b4663b/sections/6-1-receiving-notification-of-documentation-updates.md` (95 tok)
  Notification of documentation updates via ti.com product folder subscriptions
- **6.2 Support Resources** — p.136 — `docs/datasheet-c1b4663b/sections/6-2-support-resources.md` (112 tok)
  TI E2E support forums for technical questions and design assistance
- **6.3 Trademarks** — p.136 — `docs/datasheet-c1b4663b/sections/6-3-trademarks.md` (40 tok)
  Trademark information and ownership
- **6.4 Electrostatic Discharge Caution** — p.136 — `docs/datasheet-c1b4663b/sections/6-4-electrostatic-discharge-caution.md` (18 tok)
  ESD caution and handling guidelines
- **6.5 Glossary** — p.136 — `docs/datasheet-c1b4663b/sections/6-5-glossary.md` (33 tok)
  Glossary of terms, acronyms, and definitions
- **7 Mechanical, Packaging, and Orderable Information** — p.136 — `docs/datasheet-c1b4663b/sections/7-mechanical-packaging-and-orderable-information.md` (101 tok)
  Mechanical, packaging, and orderable information for device variants
