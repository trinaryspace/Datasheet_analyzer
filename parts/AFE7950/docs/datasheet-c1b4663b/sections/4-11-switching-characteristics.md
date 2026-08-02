# 4.11 Switching Characteristics

<!-- source: SBASA41E p.28 -->

## Table 1

> **Test conditions:** Typical values at TA = +25°C, full temperature range is TA,MIN = -40°C to TJ,MAX = +110°C; TX Input Rate = 491.52MSPS, fDAC = 8847.36MSPS; fADC = 2949.12MSPS; nominal power supplies; 1 tone at -1 dBFS; DSA Attenuation =0dB; SerDes rate = 24.33Gbps; unless otherwise noted.

| PARAMETER | PARAMETER | TEST CONDITIONS | MIN | TYP | MAX | UNIT |
| --- | --- | --- | --- | --- | --- | --- |
| TX Channel Latency | TX Channel Latency | TX Channel Latency | TX Channel Latency | TX Channel Latency | TX Channel Latency | TX Channel Latency |
|  | SerDes Receiver Analog Delay | Full rate |  | 2.8 |  | ns |
| tJESDTX | JESD to TX output Latency | LMFSHd=2-8-8-1, 368.64 MSPS input rate, 24x Interpolation, Serdes rate = 16.22Gbps (JESD204C) |  | 152 |  | interface clock cycles(1) |
| tJESDTX | JESD to TX output Latency | LMFSHd=8-16-4-1, 491.52 MSPS 24x Interpolation, Serdes rate = 16.22Gbps (JESD204C) |  | 176 |  | interface clock cycles(1) |
| tJESDTX | JESD to TX output Latency | LMFSHd=4-16-8-1, 245.76 MSPS 48x Interpolation, Serdes rate = 16.22Gbps (JESD204C) |  | 124 |  | interface clock cycles(1) |
| tJESDTX | JESD to TX output Latency | LMFSHd=2-16-16-1, 122.88 MSPS 96x Interpolation, Serdes rate = 16.22Gbps (JESD204C) |  | 97 |  | interface clock cycles(1) |
| RX Channel Latency | RX Channel Latency | RX Channel Latency | RX Channel Latency | RX Channel Latency | RX Channel Latency | RX Channel Latency |
|  | SerDes Transmitter Analog Delay |  |  | 3.6 |  | ns |
| tJESDRX | RX input to JESD output Latency | LMFS=2-16-16-1, 122.88 MSPS, 24x Decimation, Serdes rate = 16.22Gbps (JESD204C) |  | 92 |  | interface clock cycles(1) |
| tJESDRX | RX input to JESD output Latency | LMFS=4-16-8-1, 245.76 MSPS, 12x Decimation, Serdes rate = 16.22Gbps (JESD204C) |  | 108 |  | interface clock cycles(1) |
| tJESDRX | RX input to JESD output Latency | LMFS=4-8-4-1, 491.52 MSPS, 6x Decimation, Serdes rate = 16.22Gbps (JESD204C) |  | 153 |  | interface clock cycles(1) |
| FB Channel Latency | FB Channel Latency | FB Channel Latency | FB Channel Latency | FB Channel Latency | FB Channel Latency | FB Channel Latency |
|  | SerDes Transmitter Analog Delay |  |  | 3.6 |  | ns |
| tJESDFB | FB input to JESD output Latency | LMFS=1-2-8-1, 368.64 MSPS, 8x Decimation |  | 151 |  | interface clock cycles(1) |
| tJESDFB | FB input to JESD output Latency | LMFS=2-4-4-1, 491.52 MSPS, 6x Decimation |  | 177 |  | interface clock cycles(1) |

**Footnotes:**

- (1) Interface clock cycles is the period of the digital interface sample rate, e.g. 1GSPS = 1ns.

*Machine-readable: `tables/4-11-switching-characteristics-t01.csv`*
