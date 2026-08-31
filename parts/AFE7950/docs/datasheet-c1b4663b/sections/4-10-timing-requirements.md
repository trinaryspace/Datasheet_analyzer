# 4.10 Timing Requirements

<!-- source: SBASA41E p.27 -->

## Unnumbered table

> **Test conditions:** Typical values at TA = +25°C, full temperature range is TA,MIN = -40°C to TJ,MAX = +110°C; TX Input Rate = 491.52MSPS, fDAC = 8847.36MSPS; fADC = 2949.12MSPS; nominal power supplies; 1 tone at -1 dBFS; DSA Attenuation =0dB; SerDes rate = 24.33Gbps; unless otherwise noted.

|  |  | MIN | NOM | MAX | UNIT |
| --- | --- | --- | --- | --- | --- |
| Timing: SYSREF+/- | Timing: SYSREF+/- | Timing: SYSREF+/- | Timing: SYSREF+/- | Timing: SYSREF+/- | Timing: SYSREF+/- |
| ts(SYSREF) | Setup Time, SYSREF+/- Valid to Rising Edge of CLK+/- |  | 50 |  | ps |
| th(SYSREF) | Hold Time, SYSREF+/- Valid after Rising Edge of CLK+/- |  | 50 |  | ps |
| Timing: Serial ports | Timing: Serial ports | Timing: Serial ports | Timing: Serial ports | Timing: Serial ports | Timing: Serial ports |
| ts(SENB) | Setup Time, SENB to Rising Edge of SCLK |  | 15 |  | ns |
| th(SENB) | Hold Time, SENB after last Rising Edge of SCLK (1) |  | 5 + tSCLK |  | ns |
| ts(SDIO) | Setup Time, SDIO valid to Rising Edge of SCLK |  | 15 |  | ns |
| th(SDIO) | Hold Time, SDIO valid after Rising Edge of SCLK |  | 5 |  | ns |
| t(SCLK)_W | Minimum SCLK period: registers write |  | 25 |  | ns |
| t(SCLK)_R | Minimum SCLK period: registers read |  | 50 |  | ns |
| td(data_out) | Minimum Data Output delay after Falling Edge of SCLK |  | 0 |  | ns |
| td(data_out) | Maximum Data Output delay after Falling Edge of SCLK |  | 15 |  | ns |
| tRESET | Minimum RESETZ Pulse Width |  | 1 |  | ms |

**Footnotes:**

- (1) SDEN\\ need to be held one more extra clock cycle with the last SCLK edge

*Machine-readable: `tables/4-10-timing-requirements-t01.csv`*
