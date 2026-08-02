# 4.7 PLL/VCO/Clock Electrical Characteristics

<!-- source: SBASA41E p.18-19 -->

## Table 1

> **Test conditions:** Typical values at TA = +25°C, full temperature range is TA,MIN = -40°C to TJ,MAX = +110°C; Reference clock input frequency 491.52MHz (unless otherwise noted), fDAC = fVCO, fOUT = fDAC/4, normalized to fVCO.

| PARAMETER | PARAMETER | TEST CONDITIONS | MIN | TYP | MAX | UNIT |
| --- | --- | --- | --- | --- | --- | --- |
| fVCO1 | VCO1 min frequency |  |  |  | 7.2 | GHz |
| fVCO1 | VCO1 max frequency |  | 7.68 |  |  | GHz |
| fVCO2 | VCO2 min frequency |  |  |  | 8.8 | GHz |
| fVCO2 | VCO2 max frequency |  | 9.1 |  |  | GHz |
| fVCO3 | VCO3 min frequency |  |  |  | 9.7 | GHz |
| fVCO3 | VCO3 max frequency |  | 10.24 |  |  | GHz |
| fVCO4 | VCO4 min frequency |  |  |  | 11.6 | GHz |
| fVCO4 | VCO4 max frequency |  | 12.08 |  |  | GHz |
| DIVDAC | DAC sample rate divider |  |  | 1, 2 or 3 |  |  |
| DIVFBADC | ADC sample rate divider from DAC sample rate |  |  | 1, 2, 3, 4, 6 or 8 |  |  |
| DIVRXADC | ADC sample rate divider |  |  | 1, 2, 3, 4, 6 or 8 |  |  |
| PNVCO | Closed Loop Phase Noise FPLL = 11.79848 GHz FREF=491.52MHz | 600kHz |  | -113 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL = 11.79848 GHz FREF=491.52MHz | 800kHz |  | -116 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL = 11.79848 GHz FREF=491.52MHz | 1MHz |  | -119 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL = 11.79848 GHz FREF=491.52MHz | 1.8MHz |  | -125 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL = 11.79848 GHz FREF=491.52MHz | 5MHz |  | -133 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL = 11.79848 GHz FREF=491.52MHz | 50MHz |  | –141 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL=8.84736 GHz FREF=491.52MHz | 600kHz |  | -114 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL=8.84736 GHz FREF=491.52MHz | 800kHz |  | –118 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL=8.84736 GHz FREF=491.52MHz | 1MHz |  | –120 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL=8.84736 GHz FREF=491.52MHz | 1.8MHz |  | –127 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL=8.84736 GHz FREF=491.52MHz | 5MHz |  | –135 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL=8.84736 GHz FREF=491.52MHz | 50MHz |  | –142 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL= 9.8403 GHz FREF=491.52MHz | 600kHz |  | –113 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL= 9.8403 GHz FREF=491.52MHz | 800kHz |  | –116 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL= 9.8403 GHz FREF=491.52MHz | 1MHz |  | –119 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL= 9.8403 GHz FREF=491.52MHz | 1.8MHz |  | –125 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL= 9.8403 GHz FREF=491.52MHz | 5MHz |  | –134 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL= 9.8403 GHz FREF=491.52MHz | 50MHz |  | –140 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL= 7.86432GHz FREF=491.52MHz | 600kHz |  | –116 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL= 7.86432GHz FREF=491.52MHz | 800kHz |  | –119 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL= 7.86432GHz FREF=491.52MHz | 1MHz |  | –122 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL= 7.86432GHz FREF=491.52MHz | 1.8MHz |  | –127 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL= 7.86432GHz FREF=491.52MHz | 5MHz |  | –136 |  | dBc/Hz |
| PNVCO | Closed Loop Phase Noise FPLL= 7.86432GHz FREF=491.52MHz | 50MHz |  | –143 |  | dBc/Hz |
| Frms | Clock PLL integrated phase error(1) | fPLL=11.79848 GHz, [1KHz, 100MHz] |  | -43.4 |  | dBc/Hz |
| Frms | Clock PLL integrated phase error(1) | fPLL=8.8536 GHz, [1KHz, 100MHz] |  | -47.6 |  | dBc/Hz |
| Frms | Clock PLL integrated phase error(1) | fPLL=9.8304 GHz, [1KHz, 100MHz] |  | -46.2 |  | dBc/Hz |
| fPFD | PFD frequency |  | 100 |  | 500 | MHz |
| PNpll_flat | Normalized PLL flat Noise | fVCO = 11796.48MHz |  | –226.5 |  | dBc/Hz |
| FREF | Input Clock frequency |  | 0.1 |  | 12 | GHz |
| VSS | Input Clock level |  | 0.6 |  | 1.8 | Vppdiff |
| Coupling |  |  |  | AC Coupling Only |  |  |
|  | REFCLK input impedance(2) | Parallel resistance |  | 100 |  | Ω |
|  | REFCLK input impedance(2) | Parallel capacitance |  | 0.5 |  | pF |

**Footnotes:**

- (1) Single Sideband, not including the reference clock contribution
- (2) Refer to S11 data available from TI for impedance vs frequency

*Machine-readable: `tables/4-7-pll-vco-clock-electrical-characteristics-t01.csv`*
