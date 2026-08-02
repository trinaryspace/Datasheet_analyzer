# 4.8 Digital Electrical Characteristics

<!-- source: SBASA41E p.20 -->

## Table 1

> **Test conditions:** Typical values at TA = +25°C, full temperature range is TA,MIN = -40°C to TJ,MAX = +110°C (unless otherwise noted)

| PARAMETER | PARAMETER | TEST CONDITIONS | MIN | TYP | MAX | UNIT |
| --- | --- | --- | --- | --- | --- | --- |
| CML SerDes Inputs [8:1]SRX+/- | CML SerDes Inputs [8:1]SRX+/- | CML SerDes Inputs [8:1]SRX+/- | CML SerDes Inputs [8:1]SRX+/- | CML SerDes Inputs [8:1]SRX+/- | CML SerDes Inputs [8:1]SRX+/- | CML SerDes Inputs [8:1]SRX+/- |
| VSRDIFF | SerDes Receiver Input Amplitude | differential | 100 |  | 1200 | mVpp |
| VSRCOM | SerDes Input Common Mode |  | 0.4 | 0.5 | 0.6 | V |
| ZSRdiff | SerDes Internal Differential Termination(1) |  |  | 100 |  | Ω |
| FSerDes | SerDes Bit Rate | Full rate mode | 19 |  | 29.5 | Gbps |
| FSerDes | SerDes Bit Rate | Half rate mode | 9.5 |  | 16.25 | Gbps |
| FSerDes | SerDes Bit Rate | Quarter rate mode | 4.75 |  | 8.125 | Gbps |
|  | Insertion Loss Tolerance(2) | Serdes supply = 1.8V |  | 25 |  | dB |
| TJ | Total Jitter Tolerance |  |  |  | 0.42 | UI |
| CML SerDes Outputs [8:1]STX+/- | CML SerDes Outputs [8:1]STX+/- | CML SerDes Outputs [8:1]STX+/- | CML SerDes Outputs [8:1]STX+/- | CML SerDes Outputs [8:1]STX+/- | CML SerDes Outputs [8:1]STX+/- | CML SerDes Outputs [8:1]STX+/- |
| VSTDIFF | SerDes Transmitter Output Amplitude | differential | 500 |  | 1000 | mVpp |
| VSTCOM | SerDes Output Common Mode |  | 0.4 | 0.45 | 0.55 | V |
| ZSTdiff | SerDes Output Impedance |  |  | 100 |  | Ω |
| TRF | Output rise and fall time | 20-80% | 8 |  |  | ps |
| TEQS | Equalization range |  |  |  | 7 | dB |
| TTJ | Output total jitter |  |  |  | 0.21 | UI |
| CMOS I/O: GPIO{B/C/D/E}x, SPICLK, SPISDIO, SPISDO, SPISEN, RESETZ, BISTB0, BISTB1 | CMOS I/O: GPIO{B/C/D/E}x, SPICLK, SPISDIO, SPISDO, SPISEN, RESETZ, BISTB0, BISTB1 | CMOS I/O: GPIO{B/C/D/E}x, SPICLK, SPISDIO, SPISDO, SPISEN, RESETZ, BISTB0, BISTB1 | CMOS I/O: GPIO{B/C/D/E}x, SPICLK, SPISDIO, SPISDO, SPISEN, RESETZ, BISTB0, BISTB1 | CMOS I/O: GPIO{B/C/D/E}x, SPICLK, SPISDIO, SPISDO, SPISEN, RESETZ, BISTB0, BISTB1 | CMOS I/O: GPIO{B/C/D/E}x, SPICLK, SPISDIO, SPISDO, SPISEN, RESETZ, BISTB0, BISTB1 | CMOS I/O: GPIO{B/C/D/E}x, SPICLK, SPISDIO, SPISDO, SPISEN, RESETZ, BISTB0, BISTB1 |
| VIH | High-Level Input Voltage |  | 0.6×VDD1P8GPIO |  |  | V |
| VIL | Low-Level Input Voltage |  |  |  | 0.4×VDD1P8GPIO | V |
| IIH | High-Level Input Current |  | –250 |  | 250 | µA |
| IIL | Low-Level Input Current |  | –250 |  | 250 | µA |
| CL | CMOS input capacitance |  |  | 2 |  | pF |
| VOH | High-Level Ouput Voltage |  | VDD1P8GPIO–0.2 |  |  | V |
| VOL | Low-Level Output Voltage |  |  |  | 0.2 | V |
| Differential Inputs: SYSREF+/- Mode A | Differential Inputs: SYSREF+/- Mode A | Differential Inputs: SYSREF+/- Mode A | Differential Inputs: SYSREF+/- Mode A | Differential Inputs: SYSREF+/- Mode A | Differential Inputs: SYSREF+/- Mode A | Differential Inputs: SYSREF+/- Mode A |
| ClockMODE |  |  |  | PLL Clock Mode Only |  |  |
| FSYSREFMAX | SYSREF Input Frequency Maximum |  |  | 40 |  | MHz |
| VSWINGSRMAX | SYSREF Input Swing Maximum |  |  | 1.8 |  | Vppdiff(3) |
| VSWINGSRMIN | SYSREF Input Swing Minimum | fREF < 500MHz |  | 0.3 |  | Vppdiff(3) |
| VSWINGSRMIN | SYSREF Input Swing Minimum | fREF > 500MHz |  | 0.6 |  | Vppdiff(3) |
| VCOMSRMAX | SYSREF Input Common Mode Voltage Maximum |  |  | 0.8 |  | V |
| VCOMSRMIN | SYSREF Input Common Mode Voltage Minimum |  |  | 0.6 |  | V |
| ZT | Input termination | differential |  | 100 (1) |  | Ω |
| CL | Input capacitance | Each pin to GND |  | 0.5 |  | pF |
| LVDS Inputs: 0SYNCIN+/- and 1SYNCIN+/- | LVDS Inputs: 0SYNCIN+/- and 1SYNCIN+/- | LVDS Inputs: 0SYNCIN+/- and 1SYNCIN+/- | LVDS Inputs: 0SYNCIN+/- and 1SYNCIN+/- | LVDS Inputs: 0SYNCIN+/- and 1SYNCIN+/- | LVDS Inputs: 0SYNCIN+/- and 1SYNCIN+/- | LVDS Inputs: 0SYNCIN+/- and 1SYNCIN+/- |
| VICOM | Input Common Voltage |  |  | 1.2 |  | V |
| VID | Differential Input Voltage swing |  |  | 450 |  | Vppdiff(3) |
| ZT | Input termination | differential |  | 100 |  | Ω |
| LVDS Outputs: 0SYNCOUT+/- and 1SYNCOUT+/- | LVDS Outputs: 0SYNCOUT+/- and 1SYNCOUT+/- | LVDS Outputs: 0SYNCOUT+/- and 1SYNCOUT+/- | LVDS Outputs: 0SYNCOUT+/- and 1SYNCOUT+/- | LVDS Outputs: 0SYNCOUT+/- and 1SYNCOUT+/- | LVDS Outputs: 0SYNCOUT+/- and 1SYNCOUT+/- | LVDS Outputs: 0SYNCOUT+/- and 1SYNCOUT+/- |
| VOCOM | Output Common Voltage |  |  | 1.2 |  | V |
| VOD | Differential Output Voltage swing |  |  | 500 |  | Vppdiff(3) |
| ZT | Internal Termination |  |  | 100 |  | Ω |

**Footnotes:**

- (1) SYSREF termination is programmable between 100Ω, 150Ω and 300Ω
- (2) Loss tolerance is bump to bump from STX to SRX
- (3) Vppdiff is the difference between the maximum differential voltage (positive value) and minimum differential voltage (negative value).

*Machine-readable: `tables/4-8-digital-electrical-characteristics-t01.csv`*
