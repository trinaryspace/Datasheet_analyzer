<!-- dsa:staleness -->
> ⚠ Revision not checked: this corpus is built from SBASAN1A and has not been confirmed against upstream. Run `dsa check-revisions --part AFE7953` before relying on it for a design decision.
<!-- /dsa:staleness -->

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

- Read `AGENT.md` beside this file first: the retrieval protocol (both access paths, citations, the confidence rule).

## Section map — `datasheet-52d435c0`

- **1 Features** — p.1 — `docs/datasheet-52d435c0/sections/1-features.md` (183 tok)
  Dual RF sampling 12GSPS transmit DACs
- **2 Applications** — p.1 — `docs/datasheet-52d435c0/sections/2-applications.md` (42 tok)
  (no content)
- **3 Description** — p.1-3 — `docs/datasheet-52d435c0/sections/3-description.md` (433 tok, 1 tables)
  The AFE7953 is a high performance, wide bandwidth multi-channel transceiver, integrating two RF sampling transmitter …
- **4 Specifications** — p.4-124 — `docs/datasheet-52d435c0/sections/4-specifications.md` (14 tok)
  (no content)
- **4.1 Absolute Maximum Ratings** — p.4 — `docs/datasheet-52d435c0/sections/4-1-absolute-maximum-ratings.md` (641 tok, 1 tables)
  Parameters: PMAX(xRXIN+/-), TJ, Tstg.
- **4.2 ESD Ratings** — p.5 — `docs/datasheet-52d435c0/sections/4-2-esd-ratings.md` (136 tok, 1 tables)
  Parameters: V(ESD).
- **4.3 Recommended Operating Conditions** — p.6 — `docs/datasheet-52d435c0/sections/4-3-recommended-operating-conditions.md` (243 tok, 1 tables)
  Parameters: TA, TJ.
- **4.4 Thermal Information AFE79xx** — p.6 — `docs/datasheet-52d435c0/sections/4-4-thermal-information-afe79xx.md` (189 tok, 1 tables)
  Parameters: RθJA, RθJC(top), RθJB, ΨJT, ΨJB.
- **4.5 Transmitter Electrical Characteristics** — p.7-12 — `docs/datasheet-52d435c0/sections/4-5-transmitter-electrical-characteristics.md` (5549 tok, 1 tables)
  Parameters: DACRES, fRFout, Pmax_FS, RTERM, ATTrange, ATTstep, ATTphase-err, Gflat.
- **4.6 RF ADC Electrical Characteristics** — p.13-16 — `docs/datasheet-52d435c0/sections/4-6-rf-adc-electrical-characteristics.md` (2997 tok, 1 tables)
  Parameters: ADCRES, FRFin, PFS_CW,min, S11, ATTrange, ATTstep, NSD, NFmin.
- **4.7 PLL/VCO/Clock Electrical Characteristics** — p.17-18 — `docs/datasheet-52d435c0/sections/4-7-pll-vco-clock-electrical-characteristics.md` (1116 tok, 1 tables)
  Parameters: fVCO1, fVCO2, fVCO3, fVCO4, DIVDAC, DIVFBADC, DIVRXADC, PNVCO.
- **4.8 Digital Electrical Characteristics** — p.19-20 — `docs/datasheet-52d435c0/sections/4-8-digital-electrical-characteristics.md` (1246 tok, 1 tables)
  Parameters: VSRDIFF, VSRCOM, ZSRdiff, FSerDes, TJ, VSTDIFF, VSTCOM, ZSTdiff.
- **4.9 Power Supply Electrical Characteristics** — p.21-24 — `docs/datasheet-52d435c0/sections/4-9-power-supply-electrical-characteristics.md` (5310 tok, 1 tables)
  Parameters: IVDD1P8, IVDD1P2, IVDD0P9, Pdiss.
- **4.10 Timing Requirements** — p.25 — `docs/datasheet-52d435c0/sections/4-10-timing-requirements.md` (432 tok, 1 tables)
  Parameters: ts(SYSREF), th(SYSREF), ts(SENB), th(SENB), ts(SDIO), th(SDIO), t(SCLK)_W, t(SCLK)_R.
- **4.11 Switching Characteristics** — p.26 — `docs/datasheet-52d435c0/sections/4-11-switching-characteristics.md` (685 tok, 1 tables)
  Parameters: tJESDTX, tJESDRX, tJESDFB.
- **4.12 Typical Characteristics** — p.27-124 — `docs/datasheet-52d435c0/sections/4-12-typical-characteristics.md` (17 tok)
  (no content)
- **4.12.1 TX Typical Characteristics 800 MHz** — p.27-35 — `docs/datasheet-52d435c0/sections/4-12-1-tx-typical-characteristics-800-mhz.md` (1974 tok, 41 figs)
  Typical values at TA = +25°C with nominal supplies. 41 plots.
- **4.12.2 TX Typical Characteristics at 1.8 GHz** — p.36-42 — `docs/datasheet-52d435c0/sections/4-12-2-tx-typical-characteristics-at-1-8-ghz.md` (1796 tok, 34 figs)
  Typical values at TA = +25°C with nominal supplies. 34 plots.
- **4.12.3 TX Typical Characteristics at 2.6 GHz** — p.43-50 — `docs/datasheet-52d435c0/sections/4-12-3-tx-typical-characteristics-at-2-6-ghz.md` (2083 tok, 40 figs)
  Typical values at TA = +25°C with nominal supplies. 40 plots.
- **4.12.4 TX Typical Characteristics at 3.5 GHz** — p.51-56 — `docs/datasheet-52d435c0/sections/4-12-4-tx-typical-characteristics-at-3-5-ghz.md` (1345 tok, 31 figs)
  Typical values at TA = +25°C with nominal supplies. 31 plots.
- **4.12.5 TX Typical Characteristics at 4.9 GHz** — p.57-64 — `docs/datasheet-52d435c0/sections/4-12-5-tx-typical-characteristics-at-4-9-ghz.md` (1814 tok, 35 figs)
  Typical values at TA = +25°C with nominal supplies. 35 plots.
- **4.12.6 TX Typical Characteristics at 8.1 GHz** — p.65-73 — `docs/datasheet-52d435c0/sections/4-12-6-tx-typical-characteristics-at-8-1-ghz.md` (1000 tok, 41 figs)
  Typical values at TA = +25°C with nominal supplies. 41 plots.
- **4.12.7 TX Typical Characteristics at 9.6 GHz** — p.74-82 — `docs/datasheet-52d435c0/sections/4-12-7-tx-typical-characteristics-at-9-6-ghz.md` (1187 tok, 2 tables, 46 figs)
  Figure 4-274 TX 4xNR100 MHz Output Spectrum at 9.61 GHz 46 plots.
- **4.12.8 RX Typical Characteristics at 800 MHz** — p.83-88 — `docs/datasheet-52d435c0/sections/4-12-8-rx-typical-characteristics-at-800-mhz.md` (1273 tok, 31 figs)
  Typical values at TA = +25°C, ADC Sampling Rate = 2949.12 GHz. 31 plots.
- **4.12.9 RX Typical Characteristics at 1.75-1.9 GHz** — p.89-94 — `docs/datasheet-52d435c0/sections/4-12-9-rx-typical-characteristics-at-1-75-1-9-ghz.md` (1267 tok, 30 figs)
  Typical values at TA = +25°C, ADC Sampling Rate = 2949.12 GHz. 30 plots.
- **4.12.10 RX Typical Characteristics at 3.5 GHz** — p.95-99 — `docs/datasheet-52d435c0/sections/4-12-10-rx-typical-characteristics-at-3-5-ghz.md` (1115 tok, 27 figs)
  Typical values at TA = +25°C, ADC Sampling Rate = 2949.12 GHz. 27 plots.
- **4.12.11 RX Typical Characteristics at 2.6 GHz** — p.100-103 — `docs/datasheet-52d435c0/sections/4-12-11-rx-typical-characteristics-at-2-6-ghz.md` (779 tok, 20 figs)
  Typical values at TA = +25°C, ADC Sampling Rate = 2949.12 GHz. 20 plots.
- **4.12.12 RX Typical Characteristics at 4.9 GHz** — p.104-108 — `docs/datasheet-52d435c0/sections/4-12-12-rx-typical-characteristics-at-4-9-ghz.md` (1191 tok, 29 figs)
  Typical values at TA = +25°C, ADC Sampling Rate = 2949.12 GHz. 29 plots.
- **4.12.13 RX Typical Characteristics at 8.1 GHz** — p.109-113 — `docs/datasheet-52d435c0/sections/4-12-13-rx-typical-characteristics-at-8-1-ghz.md` (617 tok, 28 figs)
  Typical values at TA = +25°C, ADC Sampling Rate = 2949.12 GHz. 28 plots.
- **4.12.14 RX Typical Characteristics at 9.6 GHz** — p.114-118 — `docs/datasheet-52d435c0/sections/4-12-14-rx-typical-characteristics-at-9-6-ghz.md` (571 tok, 28 figs)
  Typical values at TA = +25°C, ADC Sampling Rate = 2949.12 GHz. 28 plots.
- **4.12.15 PLL and Clock Typical Characteristics** — p.119-124 — `docs/datasheet-52d435c0/sections/4-12-15-pll-and-clock-typical-characteristics.md` (1311 tok, 31 figs)
  31 plots.
- **5 Device and Documentation Support** — p.125 — `docs/datasheet-52d435c0/sections/5-device-and-documentation-support.md` (18 tok)
  (no content)
- **5.1 Receiving Notification of Documentation Updates** — p.125 — `docs/datasheet-52d435c0/sections/5-1-receiving-notification-of-documentation-updates.md` (95 tok)
  To receive notification of documentation updates, navigate to the device product folder on ti.com.
- **5.2 Support Resources** — p.125 — `docs/datasheet-52d435c0/sections/5-2-support-resources.md` (112 tok)
  TI E2E™ support forums are an engineer's go-to source for fast, verified answers and design help — straight from the …
- **5.3 Trademarks** — p.125 — `docs/datasheet-52d435c0/sections/5-3-trademarks.md` (40 tok)
  TI E2E™ is a trademark of Texas Instruments.
- **5.4 Electrostatic Discharge Caution** — p.125 — `docs/datasheet-52d435c0/sections/5-4-electrostatic-discharge-caution.md` (18 tok)
  (no content)
- **5.5 Glossary** — p.125 — `docs/datasheet-52d435c0/sections/5-5-glossary.md` (33 tok)
  This glossary lists and explains terms, acronyms, and definitions.
- **6 Revision History** — p.125 — `docs/datasheet-52d435c0/sections/6-revision-history.md` (86 tok)
  Changes from May 24, 2023 to May 1, 2025 (from Revision * (May 2023) to Revision A (May 2025))
- **7 Mechanical, Packaging, and Orderable Information** — p.125 — `docs/datasheet-52d435c0/sections/7-mechanical-packaging-and-orderable-information.md` (101 tok)
  The following pages include mechanical, packaging, and orderable information.
