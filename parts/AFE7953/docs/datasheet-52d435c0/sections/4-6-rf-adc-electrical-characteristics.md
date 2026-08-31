# 4.6 RF ADC Electrical Characteristics

<!-- source: SBASAN1A p.13-16 -->

## Unnumbered table

> **Test conditions:** Typical values at TA = +25°C, full temperature range is TA,MIN = -40°C to TJ,MAX = +110°C; RX Output Rate = 491.52MSPS below 6GHz, 500MSPS above 6GHz, fADC = 2949.12MSPS; PLL clock mode with fREF = 491.52MHz below 6GHz input frequency and External clock mode with fCLK = 11796.48MHz above 6GHz input frequency; nominal power supplies; DSA Setting = 4dB below 6GHz and 3dB above 6GHz; SerDes rate =24.33Gbps; unless otherwise noted.

| PARAMETER | PARAMETER | TEST CONDITIONS | MIN | TYP | MAX | UNIT |
| --- | --- | --- | --- | --- | --- | --- |
| ADCRES | ADC resolution |  |  | 14 |  | bits |
| FRFin | RF input frequency range |  | 600 |  | 12000 | MHz |
| PFS_CW,min | Min Full scale input power, at device pins (1) | fIN = 830 MHz, DSA=0dB |  | -2.9 |  | dBm |
| PFS_CW,min | Min Full scale input power, at device pins (1) | fIN = 1760 MHz, DSA=0dB |  | -2.8 |  | dBm |
| PFS_CW,min | Min Full scale input power, at device pins (1) | fIN = 2610 MHz, DSA=0dB |  | -1.8 |  | dBm |
| PFS_CW,min | Min Full scale input power, at device pins (1) | fIN = 3610 MHz, DSA=0dB |  | -0.4 |  | dBm |
| PFS_CW,min | Min Full scale input power, at device pins (1) | fIN = 4910 MHz, DSA=0dB |  | 0.1 |  | dBm |
| PFS_CW,min | Min Full scale input power, at device pins (1) | fIN = 8150 MHz, DSA=0dB |  | 2.1 |  | dBm |
| PFS_CW,min | Min Full scale input power, at device pins (1) | fIN = 9610 MHz, DSA=0dB |  | 4.3 |  | dBm |
| S11 | Input Return Loss | with matching network |  | -12.0 |  | dB |
| ATTrange | DSA Attenuation range |  |  | 25.0 |  | dB |
| ATTstep | DSA Attenuation step |  |  | 0.5 |  | dB |
| ATTstep | DSA Attenuation step accuracy | Delta=Gatt(X)-Gatt(X-1), Fin=3610MHz, after calibration |  | ±0.1 |  | dB |
| ATTstep | DSA Gain Steps Phase accuracyany 8dB range | Fin=3610MHz, after calibration |  | ±0.9 |  | deg |
| ATTstep | DSA Gain Steps Phase accuracyany 8dB range | Fin=4910MHz, after calibration |  | ±1.8 |  | deg |
| NSD | Noise Density(small signal) | fIN = 830 MHz, DSA = 3dB(3) |  | -155.2 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 1760 MHz, DSA = 3dB(3) |  | -155.0 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 2610 MHz, DSA = 3dB(3) |  | -154.4 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 3610 MHz, DSA = 3dB(3) |  | -154.1 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 4910 MHz, DSA = 3dB(3) |  | -155.1 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 8150 MHz, DSA = 3dB(3) |  | -150 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 9610 MHz, DSA = 3dB(3) |  | -151 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 830 MHz, 3<=Atten<=22 |  | -156.0 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 1760 MHz, 3<=Atten<=25 |  | -155.8 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 2610 MHz, 3<=Atten<=25 |  | -155.7 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 3610 MHz, 3<=Atten<=25 |  | -155.4 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 4910 MHz, 3<=Atten<=25 |  | -155.8 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 8150 MHz, 3<=Atten<=25 |  | -152.5 |  | dBFS/Hz |
| NSD | Noise Density(small signal) | fIN = 9610 MHz, 3<=Atten<=25 |  | -152.5 |  | dBFS/Hz |
| NFmin | Noise Figure minDSA Atten=0 - 3dB | fIN = 830 MHz |  | 19.1 |  | dB |
| NFmin | Noise Figure minDSA Atten=0 - 3dB | fIN = 1760 MHz |  | 19.0 |  | dB |
| NFmin | Noise Figure minDSA Atten=0 - 3dB | fIN = 2610 MHz |  | 20.9 |  | dB |
| NFmin | Noise Figure minDSA Atten=0 - 3dB | fIN = 3610 MHz |  | 22.8 |  | dB |
| NFmin | Noise Figure minDSA Atten=0 - 3dB | fIN = 4910 MHz |  | 22.4 |  | dB |
| NFmin | Noise Figure minDSA Atten=0 - 3dB | fIN = 8150 MHz |  | 27.3 |  | dB |
| NFmin | Noise Figure minDSA Atten=0 - 3dB | fIN = 9610 MHz |  | 30 |  | dB |
| NF | Noise FigureDSA Atten=4dB | fIN = 830 MHz(4) |  | 20.0 |  | dB |
| NF | Noise FigureDSA Atten=4dB | fIN = 1760 MHz(4) |  | 20.6 |  | dB |
| NF | Noise FigureDSA Atten=4dB | fIN = 2610 MHz(4) |  | 21.9 |  | dB |
| NF | Noise FigureDSA Atten=4dB | fIN = 3610 MHz(4) |  | 23.5 |  | dB |
| NF | Noise FigureDSA Atten=4dB | fIN = 4910 MHz(4) |  | 22.3 |  | dB |
| NF | Noise FigureDSA Atten=4dB | fIN = 8150 MHz(4) |  | 27.9 |  | dB |
| NF | Noise FigureDSA Atten=4dB | fIN = 9610 MHz(4) |  | 30.7 |  | dB |
| NFmax | Noise FigureDSA Atten=20dB | fIN = 830 MHz |  | 34.7 |  | dB |
| NFmax | Noise FigureDSA Atten=20dB | fIN = 1760 MHz |  | 35.2 |  | dB |
| NFmax | Noise FigureDSA Atten=20dB | fIN = 2610 MHz |  | 36.0 |  | dB |
| NFmax | Noise FigureDSA Atten=20dB | fIN = 3610 MHz |  | 37.3 |  | dB |
| NFmax | Noise FigureDSA Atten=20dB | fIN = 4910 MHz |  | 37.6 |  | dB |
| NFmax | Noise FigureDSA Atten=20dB | fIN = 8150 MHz |  | 42.8 |  | dB |
| NFmax | Noise FigureDSA Atten=20dB | fIN = 9610 MHz |  | 45 |  | dB |
| IMD3 | 3rd order intermodulation 2 tones at at fIN ± 10MHz-7dBFS each tone | fIN = 840 MHz, 3<=Atten<=12 |  | -82.4 |  | dBc |
| IMD3 | 3rd order intermodulation 2 tones at at fIN ± 10MHz-7dBFS each tone | fIN = 1770 MHz, 3<=Atten<=12 |  | -84.1 |  | dBc |
| IMD3 | 3rd order intermodulation 2 tones at at fIN ± 10MHz-7dBFS each tone | fIN = 2610 MHz, 3<=Atten<=12 |  | -74 |  | dBc |
| IMD3 | 3rd order intermodulation 2 tones at at fIN ± 10MHz-7dBFS each tone | fIN = 3610 MHz, 3<=Atten<=12 |  | -77 |  | dBc |
| IMD3 | 3rd order intermodulation 2 tones at at fIN ± 10MHz-7dBFS each tone | fIN = 4920 MHz, 3<=Atten<=12 |  | -75.9 |  | dBc |
| IMD3 | 3rd order intermodulation 2 tones at at fIN ± 10MHz-7dBFS each tone | fIN = 8150 MHz, 3<=Atten<=12, 25MHz tone spacing |  | -55 |  | dBc |
| IMD3 | 3rd order intermodulation 2 tones at at fIN ± 10MHz-7dBFS each tone | fIN = 9610 MHz, 3<=Atten<=12, 25MHz tone spacing |  | -60 |  | dBc |
| SFDR | Spurious Free Dynamic Rangewithin output bandwidth, AIN = -3 dBFS | fIN = 830 MHz |  | 88.2 |  | dBFS |
| SFDR | Spurious Free Dynamic Rangewithin output bandwidth, AIN = -3 dBFS | fIN = 1760 MHz |  | 80.6 |  | dBFS |
| SFDR | Spurious Free Dynamic Rangewithin output bandwidth, AIN = -3 dBFS | fIN = 2610 MHz |  | 88 |  | dBFS |
| SFDR | Spurious Free Dynamic Rangewithin output bandwidth, AIN = -3 dBFS | fIN = 3610 MHz |  | 84 |  | dBFS |
| SFDR | Spurious Free Dynamic Rangewithin output bandwidth, AIN = -3 dBFS | fIN = 4910 MHz |  | 78.9 |  | dBFS |
| SFDR | Spurious Free Dynamic Rangewithin output bandwidth, AIN = -3 dBFS | fIN = 8150 MHz |  | 78 |  | dBFS |
| SFDR | Spurious Free Dynamic Rangewithin output bandwidth, AIN = -3 dBFS | fIN = 9610 MHz |  | 71 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -3 dBFS(2)(5) | fIN = 830 MHz |  | -85.5 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -3 dBFS(2)(5) | fIN = 1760 MHz |  | -90.5 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -3 dBFS(2)(5) | fIN = 2610 MHz |  | -88 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -3 dBFS(2)(5) | fIN = 3610 MHz |  | -87 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -3 dBFS(2)(5) | fIN = 4910 MHz |  | -84.2 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -3 dBFS(2)(5) | fIN = 8150 MHz |  | -70 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -3 dBFS(2)(5) | fIN = 9610 MHz |  | -70 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -3 dBFS(5) | fIN = 830 MHz |  | -80.2 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -3 dBFS(5) | fIN = 1760 MHz |  | -85.3 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -3 dBFS(5) | fIN = 2610 MHz |  | -86 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -3 dBFS(5) | fIN = 3610 MHz |  | -78 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -3 dBFS(5) | fIN = 4910 MHz |  | -75.4 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -3 dBFS(5) | fIN = 8150 MHz |  | -70 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -3 dBFS(5) | fIN = 9610 MHz |  | -70 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -3 dBFS(5) | fIN = 830 MHz |  | -88.2 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -3 dBFS(5) | fIN = 1760 MHz |  | -80.6 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -3 dBFS(5) | fIN = 2610 MHz |  | -88 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -3 dBFS(5) | fIN = 3610 MHz |  | -84 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -3 dBFS(5) | fIN = 4910 MHz |  | -81.7 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -3 dBFS(5) | fIN = 8150 MHz |  | -78 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -3 dBFS(5) | fIN = 9610 MHz |  | -71 |  | dBFS |
| SFDR | Spurious Free Dynamic RangeAIN = -13 dBFS0<=Atten<=16 | fIN = 830 MHz |  | 89.2 |  | dBFS |
| SFDR | Spurious Free Dynamic RangeAIN = -13 dBFS0<=Atten<=16 | fIN = 1760 MHz |  | 88.8 |  | dBFS |
| SFDR | Spurious Free Dynamic RangeAIN = -13 dBFS0<=Atten<=16 | fIN = 2610 MHz |  | 95 |  | dBFS |
| SFDR | Spurious Free Dynamic RangeAIN = -13 dBFS0<=Atten<=16 | fIN = 3610 MHz |  | 90 |  | dBFS |
| SFDR | Spurious Free Dynamic RangeAIN = -13 dBFS0<=Atten<=16 | fIN = 4910 MHz |  | 89.8 |  | dBFS |
| SFDR | Spurious Free Dynamic RangeAIN = -13 dBFS0<=Atten<=16 | fIN = 8150 MHz |  | 83 |  | dBFS |
| SFDR | Spurious Free Dynamic RangeAIN = -13 dBFS0<=Atten<=16 | fIN = 9610 MHz |  | 80 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 830 MHz, with board trim |  | -79.0 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 1760 MHz, with board trim |  | -101.6 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 2610 MHz, with board trim |  | -100 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 3610 MHz, with board trim |  | -101 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 4910 MHz, with board trim |  | -99.1 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 8150 MHz, with board trim |  | -107 |  | dBFS |
| HD2 | 2nd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 9610 MHz, with board trim |  | -107 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 830 MHz |  | -95.4 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 1760 MHz |  | -95.2 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 2610 MHz |  | -98 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 3610 MHz |  | -97 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 4910 MHz |  | -94 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 8150 MHz |  | -100 |  | dBFS |
| HD3 | 3rd Harmonic DistortionAIN = -13 dBFS0<=Atten<=16(5) | fIN = 9610 MHz |  | -102 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -13 dBFS0<=Atten<=16(5) | fIN = 830 MHz |  | -89.2 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -13 dBFS0<=Atten<=16(5) | fIN = 1760 MHz |  | -88.8 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -13 dBFS0<=Atten<=16(5) | fIN = 2610 MHz |  | -95 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -13 dBFS0<=Atten<=16(5) | fIN = 3610 MHz |  | -90 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -13 dBFS0<=Atten<=16(5) | fIN = 4910 MHz |  | -90 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -13 dBFS0<=Atten<=16(5) | fIN = 8150 MHz |  | -83 |  | dBFS |
| HDn, n>3 | SFDR excl. HD2 and HD3AIN = -13 dBFS0<=Atten<=16(5) | fIN = 9610 MHz |  | -80 |  | dBFS |

**Footnotes:**

- (1) The input fullscale at minimum attenuation can be reduce by adding a digital gain range to the DSA, extending the useful range of the DSA. The noise figure remains constant over the digital gain range.
- (2) NLE correction of HD2
- (3) From DSA = 3dB down to 0dB, NSD increases 1dB per DSA dB
- (4) NF increase 1dB per DSA 1dB above DSA = 3dB
- (5) DDC Bypass (TI only test mode)

*Machine-readable: `tables/4-6-rf-adc-electrical-characteristics-t01.csv`*
