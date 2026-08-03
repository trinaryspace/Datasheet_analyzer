# 4.12.15 PLL and Clock Typical Characteristics

<!-- source: SBASAN1A p.119-124 -->

## Figures

- **Figure 4-468 Phase Noise vs Offset Frequency for PLL and External Clock at 12 GHz** — measured at TX output, normalized to 12 GHz by 20 x log10(12GHz/FOUT)
- **Figure 4-470 Phase Noise for 12-GHz VCO vs Offset Frequency and Temperature at fOUT = 1910 MHz** — PLL enabled, fVCO = 11796.48 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-472 Phase Noise for 12-GHz VCO vs Offset Frequency and fOUT at –40°C** — PLL enabled, fVCO = 11796.48 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-474 Phase Noise for 12-GHz VCO vs Offset Frequency and CP Setting at fOUT = 2.6 GHz** — PLL enabled, fVCO = 11796.48 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-476 Phase Noise for 12-GHz VCO at 600 kHz Offset vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 11796.48 MHz, measured at TX output
- **Figure 4-478 Phase Noise for 12-GHz VCO at 1-MHz Offset vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 11796.48 MHz, measured at TX output
- **Figure 4-480 Phase Noise for 12-GHz VCO at 5-MHz Offset vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 11796.48 MHz, measured at TX output
- **Figure 4-482 Phase Noise for 10-GHz VCO vs Offset Frequency and Temperature at fOUT = 1910 MHz** — PLL enabled, fVCO = 9830.4 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-484 Phase Noise for 10-GHz VCO vs Offset Frequency and fOUT at –40°C** — PLL enabled, fVCO = 9830.4 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-486 Integrated Phase Noise for 10-GHz VCO vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 9830.4 MHz, 1-kHz to 100-MHz, single-sided integration bandwidth, measured at TX output
- **Figure 4-488 Phase Noise for 10-GHz VCO at 800 kHz vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 9830.4 MHz, measured at TX output
- **Figure 4-490 Phase Noise for 10-GHz VCO at 1.8 MHz vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 9830.4 MHz, measured at TX output
- **Figure 4-492 Phase Noise for 10-GHz VCO at 50 MHz vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 9830.4 MHz, measured at TX output
- **Figure 4-494 Phase Noise for 9-GHz VCO vs Offset Frequency and fOUT at 25°C** — PLL enabled, fVCO = 8847.36 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-496 Phase Noise for 9-GHz VCO vs Offset Frequency and fOUT at 110°C** — PLL enabled, fVCO = 8847.36 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-498 Phase Noise for 8-GHz VCO vs Offset Frequency and Temperature at fOUT = 1910 MHz** — PLL enabled, fVCO = 7864.32 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-469 Phase Noise vs Offset Frequency and fVCO at fOUT = 2610 MHz** — PLL enabled, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-471 Phase Noise for 12-GHz VCO vs Offset Frequency and fOUT at 25°C** — PLL enabled, fVCO = 11796.48 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-473 Phase Noise for 12-GHz VCO vs Offset Frequency and fOUT at 110°C** — PLL enabled, fVCO = 11796.48 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-475 Integrated Phase Noise for 12-GHz VCO vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 11796.48 MHz, 1-kHz to 100-MHz, single-sided integration bandwidth, measured at TX output
- **Figure 4-477 Phase Noise for 12-GHz VCO at 800-kHz Offset vs Temperature and fREF at fOUT = 2.6 GHz** — A. PLL enabled, fVCO = 11796.48 MHz, measured at TX output
- **Figure 4-479 Phase Noise for 12-GHz VCO at 1.8-MHz Offset vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 11796.48 MHz, measured at TX output
- **Figure 4-481 Phase Noise for 12-GHz VCO at 50-MHz Offset vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 11796.48 MHz, measured at TX output
- **Figure 4-483 Phase Noise for 10-GHz VCO vs Offset Frequency and fOUT at 25°C** — PLL enabled, fVCO = 9830.4 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-485 Phase Noise for 10-GHz VCO vs Offset Frequency and fOUT at 110°C** — PLL enabled, fVCO = 9830.4 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-487 Phase Noise for 10-GHz VCO at 600 kHz vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 9830.4 MHz, measured at TX output
- **Figure 4-489 Phase Noise for 10-GHz VCO at 1 MHz vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 9830.4 MHz, measured at TX output
- **Figure 4-491 Phase Noise for 10-GHz VCO at 5 MHz vs Temperature and fREF at fOUT = 2.6 GHz** — PLL enabled, fVCO = 9830.4 MHz, measured at TX output
- **Figure 4-493 Phase Noise for 9-GHz VCO vs Offset Frequency and Temperature at fOUT = 1910 MHz** — PLL enabled, fVCO = 8847.36 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-495 Phase Noise for 9-GHz VCO vs Offset Frequency and fOUT at –40°C** — PLL enabled, fVCO = 8847.36 MHz, fREF = 491.52 MSPS, measured at TX output
- **Figure 4-497 Phase Noise for 9-GHz VCO vs Temperature Over Offset Frequency at fOUT = 2.6 GHz** — PLL enabled, fVCO = 8847.36 MHz, fREF = 491.52 MSPS, minimum LPF BW, measured at TX output
