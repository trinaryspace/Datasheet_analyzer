# AFE7953 — datasheet corpus

> The AFE7953 is a high performance, wide bandwidth multi-channel transceiver, integrating two RF sampling transmitter chains and two RF sampling receiver chains. With operation up to 12GHz, this device enables direct RF sampling in the L, S, C and X-band frequency ranges without the need for additional frequency conversions stages. This improvement in density and flexibility enables high-channel-count, multi-mission systems.

## Key facts (verbatim from Features, p.1)

- Dual RF sampling 12GSPS transmit DACs
- Dual RF sampling 12GSPS transmit DACs
- Dual RF sampling 3GSPS receive ADCs
- Dual RF sampling 3GSPS receive ADCs
- Maximum RF signal bandwidth: 400MHz
- RF frequency range: 600MHz - 12GHz
- Digital step attenuators (DSA):
- TX: 40dB range, 0.125dB steps
- RX: 25dB range, 0.5dB steps
- Single or dual-band DUC or DDCs
- 16x NCOs per TX or RX
- Optional Internal PLL or VCO for DAC or ADC clocks or external clock at DAC or ADC sample rate
- SerDes data interface:
- JESD204B and JESD204C compatible
- 8 SerDes transceivers up to 29.5Gbps
- Subclass 1 multi-device synchronization
- Package: 17mm × 17mm FCBGA, 0.8mm pitch

## Documents

- `datasheet` SBASAN1A — 134 pages — `docs/datasheet-52d435c0/`

## How to use this corpus

- Every section file starts with `<!-- source: <doc> p.N[-M] -->` — cite those pages.
- Tables are atomic: conditions and footnotes are inline with each table;
  a machine-readable CSV twin lives next to it under `tables/`.
- Plot lookup: `dsa plots / docs/<doc>/plots.json` -> open the image file (vision).
- Answers must quote values WITH units and cite the page.

## Section map — `datasheet-52d435c0`

- **1 Features** — p.1 — `docs/datasheet-52d435c0/sections/1-features.md` (183 tok)
  Dual 12GSPS TX DAC, dual 3GSPS RX ADC, 400MHz bandwidth, 600MHz-12GHz RF, 40dB TX/25dB RX DSA, JESD204B/C, 29.5Gbps …
- **2 Applications** — p.1 — `docs/datasheet-52d435c0/sections/2-applications.md` (42 tok)
  Radar, seeker front-end, defense radio, tactical communications, wireless test applications
- **3 Description** — p.1-3 — `docs/datasheet-52d435c0/sections/3-description.md` (433 tok, 1 tables)
  AFE7953 multi-channel transceiver, RF sampling TX/RX chains, L/S/C/X-band direct sampling, 12GHz operation, 400MHz …
- **4 Specifications** — p.4-124 — `docs/datasheet-52d435c0/sections/4-specifications.md` (14 tok)
  Specifications section index
- **4.1 Absolute Maximum Ratings** — p.4 — `docs/datasheet-52d435c0/sections/4-1-absolute-maximum-ratings.md` (639 tok, 1 tables)
  Absolute maximum ratings: max RF input power, junction temperature, storage temperature
- **4.2 ESD Ratings** — p.5 — `docs/datasheet-52d435c0/sections/4-2-esd-ratings.md` (133 tok, 1 tables)
  ESD ratings and voltage parameters
- **4.3 Recommended Operating Conditions** — p.6 — `docs/datasheet-52d435c0/sections/4-3-recommended-operating-conditions.md` (241 tok, 1 tables)
  Operating conditions: ambient and junction temperature limits
- **4.4 Thermal Information AFE79xx** — p.6 — `docs/datasheet-52d435c0/sections/4-4-thermal-information-afe79xx.md` (186 tok, 1 tables)
  Thermal information: junction-to-ambient/case resistance, transient thermal impedance
- **4.5 Transmitter Electrical Characteristics** — p.7-12 — `docs/datasheet-52d435c0/sections/4-5-transmitter-electrical-characteristics.md` (5547 tok, 1 tables)
  TX DAC resolution, RF output frequency, full-scale power, 50Ω termination, attenuator range/step/phase error, gain …
- **4.6 RF ADC Electrical Characteristics** — p.13-16 — `docs/datasheet-52d435c0/sections/4-6-rf-adc-electrical-characteristics.md` (2995 tok, 1 tables)
  RX ADC resolution, RF input frequency, CW power, S11, attenuator range/step, noise spectral density, noise figure
- **4.7 PLL/VCO/Clock Electrical Characteristics** — p.17-18 — `docs/datasheet-52d435c0/sections/4-7-pll-vco-clock-electrical-characteristics.md` (1114 tok, 1 tables)
  VCO frequencies, DAC/ADC clock dividers, VCO phase noise
- **4.8 Digital Electrical Characteristics** — p.19-20 — `docs/datasheet-52d435c0/sections/4-8-digital-electrical-characteristics.md` (1244 tok, 1 tables)
  SerDes differential voltage, common-mode voltage, impedance, data rate to 29.5Gbps, timing parameters
- **4.9 Power Supply Electrical Characteristics** — p.21-24 — `docs/datasheet-52d435c0/sections/4-9-power-supply-electrical-characteristics.md` (5308 tok, 1 tables)
  Supply currents 1.8V/1.2V/0.9V rails, power dissipation
- **4.10 Timing Requirements** — p.25 — `docs/datasheet-52d435c0/sections/4-10-timing-requirements.md` (430 tok, 1 tables)
  SYSREF, SENB, SDIO timing, setup/hold/clock period specifications
- **4.11 Switching Characteristics** — p.26 — `docs/datasheet-52d435c0/sections/4-11-switching-characteristics.md` (683 tok, 1 tables)
  JESD204 TX/RX/feedback latency
- **4.12 Typical Characteristics** — p.27-124 — `docs/datasheet-52d435c0/sections/4-12-typical-characteristics.md` (17 tok)
  Typical characteristics overview
- **4.12.1 TX Typical Characteristics 800 MHz** — p.27-35 — `docs/datasheet-52d435c0/sections/4-12-1-tx-typical-characteristics-800-mhz.md` (1974 tok, 41 figs)
  TX at 800MHz: 11.8GHz DAC, 24x interpolation, 491.52MSPS input, 1st Nyquist, PLL clock
- **4.12.2 TX Typical Characteristics at 1.8 GHz** — p.36-42 — `docs/datasheet-52d435c0/sections/4-12-2-tx-typical-characteristics-at-1-8-ghz.md` (1796 tok, 34 figs)
  TX at 1.8GHz: 11.8GHz DAC, 24x interpolation, 491.52MSPS input, 1st Nyquist, PLL clock
- **4.12.3 TX Typical Characteristics at 2.6 GHz** — p.43-50 — `docs/datasheet-52d435c0/sections/4-12-3-tx-typical-characteristics-at-2-6-ghz.md` (2083 tok, 40 figs)
  TX at 2.6GHz: 11.8GHz DAC, 24x interpolation, 491.52MSPS input, 1st Nyquist, PLL clock
- **4.12.4 TX Typical Characteristics at 3.5 GHz** — p.51-56 — `docs/datasheet-52d435c0/sections/4-12-4-tx-typical-characteristics-at-3-5-ghz.md` (1345 tok, 31 figs)
  TX at 3.5GHz: 11.8GHz DAC, 24x interpolation, 491.52MSPS input, 1st Nyquist, PLL clock
- **4.12.5 TX Typical Characteristics at 4.9 GHz** — p.57-64 — `docs/datasheet-52d435c0/sections/4-12-5-tx-typical-characteristics-at-4-9-ghz.md` (1814 tok, 35 figs)
  TX at 4.9GHz: 11.8GHz DAC, 24x interpolation, 491.52MSPS input, 1st Nyquist, PLL clock
- **4.12.6 TX Typical Characteristics at 8.1 GHz** — p.65-73 — `docs/datasheet-52d435c0/sections/4-12-6-tx-typical-characteristics-at-8-1-ghz.md` (1000 tok, 41 figs)
  TX at 8.1GHz: 11.8GHz DAC, mixed mode, 1st Nyquist, PLL clock, 100MHz NR bandwidth
- **4.12.7 TX Typical Characteristics at 9.6 GHz** — p.74-82 — `docs/datasheet-52d435c0/sections/4-12-7-tx-typical-characteristics-at-9-6-ghz.md` (1185 tok, 2 tables, 46 figs)
  TX at 9.6GHz: 4×NR 100MHz channels, output spectrum
- **4.12.8 RX Typical Characteristics at 800 MHz** — p.83-88 — `docs/datasheet-52d435c0/sections/4-12-8-rx-typical-characteristics-at-800-mhz.md` (1273 tok, 31 figs)
  RX at 800MHz: 2.95GHz ADC sampling, 491.52MSPS output, 6× decimation, PLL clock
- **4.12.9 RX Typical Characteristics at 1.75-1.9 GHz** — p.89-94 — `docs/datasheet-52d435c0/sections/4-12-9-rx-typical-characteristics-at-1-75-1-9-ghz.md` (1267 tok, 30 figs)
  RX at 1.75-1.9GHz: 2.95GHz ADC sampling, 491.52MSPS output, 6× decimation, PLL clock
- **4.12.10 RX Typical Characteristics at 3.5 GHz** — p.95-99 — `docs/datasheet-52d435c0/sections/4-12-10-rx-typical-characteristics-at-3-5-ghz.md` (1115 tok, 27 figs)
  RX at 3.5GHz: 2.95GHz ADC sampling, 491.52MSPS output, 6× decimation, PLL clock
- **4.12.11 RX Typical Characteristics at 2.6 GHz** — p.100-103 — `docs/datasheet-52d435c0/sections/4-12-11-rx-typical-characteristics-at-2-6-ghz.md` (779 tok, 20 figs)
  RX at 2.6GHz: 2.95GHz ADC sampling, 491.52MSPS output, 6× decimation, PLL clock
- **4.12.12 RX Typical Characteristics at 4.9 GHz** — p.104-108 — `docs/datasheet-52d435c0/sections/4-12-12-rx-typical-characteristics-at-4-9-ghz.md` (1191 tok, 29 figs)
  RX at 4.9GHz: 2.95GHz ADC sampling, 491.52MSPS output, 6× decimation, PLL clock
- **4.12.13 RX Typical Characteristics at 8.1 GHz** — p.109-113 — `docs/datasheet-52d435c0/sections/4-12-13-rx-typical-characteristics-at-8-1-ghz.md` (617 tok, 28 figs)
  RX at 8.1GHz: 2.95GHz ADC sampling, 491.52MSPS output, 6× decimation, external clock, 8.1GHz matched
- **4.12.14 RX Typical Characteristics at 9.6 GHz** — p.114-118 — `docs/datasheet-52d435c0/sections/4-12-14-rx-typical-characteristics-at-9-6-ghz.md` (571 tok, 28 figs)
  RX at 9.6GHz: 2.95GHz ADC sampling, 1.47GSPS output, 2× decimation, external clock, 9.6GHz matched
- **4.12.15 PLL and Clock Typical Characteristics** — p.119-124 — `docs/datasheet-52d435c0/sections/4-12-15-pll-and-clock-typical-characteristics.md` (1311 tok, 31 figs)
  PLL, VCO, clock typical characteristics at TA=25°C
- **5 Device and Documentation Support** — p.125 — `docs/datasheet-52d435c0/sections/5-device-and-documentation-support.md` (18 tok)
  Device support and documentation
- **5.1 Receiving Notification of Documentation Updates** — p.125 — `docs/datasheet-52d435c0/sections/5-1-receiving-notification-of-documentation-updates.md` (95 tok)
  Documentation update notifications via ti.com product page
- **5.2 Support Resources** — p.125 — `docs/datasheet-52d435c0/sections/5-2-support-resources.md` (112 tok)
  TI E2E support forums for technical assistance
- **5.3 Trademarks** — p.125 — `docs/datasheet-52d435c0/sections/5-3-trademarks.md` (40 tok)
  Trademark information
- **5.4 Electrostatic Discharge Caution** — p.125 — `docs/datasheet-52d435c0/sections/5-4-electrostatic-discharge-caution.md` (18 tok)
  ESD caution notice
- **5.5 Glossary** — p.125 — `docs/datasheet-52d435c0/sections/5-5-glossary.md` (33 tok)
  Glossary of terms and acronyms
- **6 Revision History** — p.125 — `docs/datasheet-52d435c0/sections/6-revision-history.md` (86 tok)
  Revision history: changes from May 2023 to May 2025
- **7 Mechanical, Packaging, and Orderable Information** — p.125 — `docs/datasheet-52d435c0/sections/7-mechanical-packaging-and-orderable-information.md` (101 tok)
  Mechanical, packaging, orderable information
