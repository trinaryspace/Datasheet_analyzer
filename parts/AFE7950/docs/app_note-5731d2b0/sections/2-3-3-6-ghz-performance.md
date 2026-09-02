# 2.3.3 6 GHz Performance

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\LMX1204\documents\snaa360.pdf p.7 -->

2.3.3 6 GHz Performance

Figure 2-5 shows phase noise at offset frequencies is quite similar for all sources out to an offset frequency

of 800 kHz, which is similar to the 3 GHz carrier frequency measurements. Again, a noise floor discrepancy

appears between the LMX1204EVM measurement and the cascaded LMX1204 design measurement. This

elevated noise floor is caused by the additive thermal noise of the second LMX1204 stage.

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

-180

-170

-160

-150

-140

-130

-120

-110

-100

-90

-80

SMA100B

LMX1204

Cascaded LMX1204

Figure 2-5. Phase Noise Comparison - 6 GHz

The difference between the two LMX1204 device noise floors is 2.2 dB on average. Use this to estimate the

noise floor of a system with N stages of cascaded LMX1204 devices near 6 GHz.

Results

SNAA360 – JUNE 2022

Getting the Most of Your Data Converter Clocking System Using LMX1204 in

Cascaded Configuration
