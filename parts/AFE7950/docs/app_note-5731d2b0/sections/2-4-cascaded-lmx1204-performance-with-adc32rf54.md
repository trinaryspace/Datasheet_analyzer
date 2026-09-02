# 2.4 Cascaded LMX1204 Performance With ADC32RF54

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\LMX1204\documents\snaa360.pdf p.10 -->

2.4 Cascaded LMX1204 Performance With ADC32RF54

Figure 2-8 compares the difference in SNR (signal-to-noise ratio) using the ADC32RF54EVM evaluation module

clocked by the SMA100B and the cascaded LMX1204 design.

Frequency (MHz)

SNR (dBFS)

64.4

64.6

64.8

65

65.2

65.4

65.6

65.8

66

66.2

66.4

100

1000

2000

SMA100B

Cascaded LMX1204

Figure 2-8. ADC32RF54 - SNR vs. Clock Source vs. Frequency

Figure 2-8 above shows SNR in dBFS (decibel relative to full-scale ADC level) at numerous frequencies within

the range of 100 MHz to 2 GHz. Each of the input frequencies above is filtered using a narrow bandpass filter

to reduce the impact of higher frequency noise and harmonics throughout the capture. The sample rate is a

constant 2.6 GSPS and the SMA100B is set such that the output power matches the measured output power

level from the cascaded LMX1204 (6.17 dBm). On average, the SNR is degraded by a mere 0.15 dB.

2.5 Cascaded LMX1204 Performance With AFE7950

This section highlights the ADC SNR performance of the AFE7950EVM analog front end evaluation module

when clocked by an SMA100B versus the cascaded LMX1204 board.

Frequency (MHz)

SNR (dBFS)

60

60.4

60.8

61.2

61.6

62

62.4

62.8

63.2

63.6

64

64.4

8000

9000

10000

11000

SMA100B

Cascaded LMX1204

Figure 2-9. AFE7950 - SNR vs Clock Source vs Frequency

The AFE7950 is a 4T6R AFE containing four digital to analog converters (DAC) and six analog to digital

converters. The input clock is 11,796.48 MHz which is suitable for X-band frequency of operation.

The sample clock of the ADC of 2949.12 MHz is derived from the input clock divided by 4. The receiver operates

in a decimate by 12 mode so that the output data rate is 245.76 MSPS. The internal numerically controlled

oscillator (NCO) is set to 20 MHz below the center of each RF band so that the baseband tone falls at 20 MHz.

Figure 2-9 plots SNR performance from 8 GHz to 11 GHz in 500 MHz steps. Each input frequency is filtered

to reduce the noise and harmonics of the input source. The EVM requires a high clock drive level of around 7

to 15 dBm near 12 GHz due to on-board losses. The LMX1204 output drive is limited to roughly 1 dBm at 12

GHz. The clock output is increased with a Qorvo power amplifier (P/N: CMD158) to 16 dBm followed by a 1 dB

pad (to further improve impedance matching) to get to the optimum input level for the AFE7950EVM. The signal

generator is set such that the output power matches the measured output power of the cascaded LMX1204

Results

Getting the Most of Your Data Converter Clocking System Using LMX1204 in

Cascaded Configuration

SNAA360 – JUNE 2022
