# 2.3.2 3 GHz Performance

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\LMX1204\documents\snaa360.pdf p.6 -->

2.3.2 3 GHz Performance

Figure 2-4 shows the phase noise at close-in offset frequencies of a 3 GHz carrier for the SMA100B and

cascaded LMX1204 design is slightly better than the LMX1204EVM, once again indicating board layout

improvement on the cascaded LMX1204 design. The performance of all three sources is near identical out to an

offset frequency of 800 kHz, which is slightly further out than the 1-GHz carrier frequency case. Both LMX1204

devices match the SMA100B to an increased offset frequency as the SMA100B noise floor is elevated.

Offset Frequency (Hz)

dBc/Hz

101

102

103

104

105

106

107

108

109

-175

-165

-155

-145

-135

-125

-115

-105

-95

-85

SMA100B

LMX1204

Cascaded LMX1204

Figure 2-4. Phase Noise Comparison - 3 GHz

The cascaded LMX1204 design noise floor shows an average increase of 1.4 dB compared to the single

LMX1204 response at 3 GHz. Use this increase as an estimate of the noise floor degradation as additional

LMX1204 devices are cascaded. This elevation amount is important as it can be used to quickly estimate the

added phase noise for a system of N number of devices operating near 3 GHz as each additional stage should

elevate the noise floor by only 1.4 dB. Refer to Section 2.4 for a comparison in data converter performance in a

2.6 GSPS ADC application between the SMA100B and LMX1204 clock distribution board.

Results

Getting the Most of Your Data Converter Clocking System Using LMX1204 in

Cascaded Configuration

SNAA360 – JUNE 2022
