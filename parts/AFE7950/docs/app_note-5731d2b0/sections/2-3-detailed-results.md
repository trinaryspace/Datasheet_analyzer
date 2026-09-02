# 2.3 Detailed Results

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\LMX1204\documents\snaa360.pdf p.5-9 -->

2.3 Detailed Results

This section highlights performance at each of the individually tested frequencies and compares the results

alongside the SMA100B clock source. Device performance is captured at the frequencies: 1 GHz, 3 GHz, 6

GHz, 10 GHz, and 12.8 GHz. For the following measurements, please note:

•

All LMX1204 devices are from the same production lot.

•

The output power for the SMA100B measurement matches the cascaded LMX1204 design output level.

•

All LMX1204 devices have the output power set to maximum level (unless mentioned otherwise).

2.3.1 1 GHz Performance

The LMX1204EVM has slightly elevated phase noise compared to both the cascaded LMX1204 design and

SMA100B as shown in Figure 2-3. As the cascaded LMX1204 design matches the SMA100B at low frequency

offsets (< 100 Hz), the inconsistency at those low frequency offsets is likely due to PCB layout related

differences.

Figure 2-3. Phase Noise Comparison - 1 GHz

All three sources match to around the 400-kHz offset frequency range before diverging. At this point, the

SMA100B begins to drop beneath the -160 dc/Hz noise floor shown by the LMX1204 devices. There is minimal

separation between the single and dual stage LMX1204 configurations, indicating the added phase noise by the

second LMX1204 is negligible at 1 GHz.

Results

SNAA360 – JUNE 2022

Getting the Most of Your Data Converter Clocking System Using LMX1204 in

Cascaded Configuration

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

2.3.4 10 GHz Performance

Figure 2-6 shows a 10 GHz carrier frequency. The performance of all three sources is near identical out to an

offset frequency of 1 MHz, which is slightly further than the previous carrier frequencies. An average difference

measures as 0.7 dB between the LMX1204EVM and the cascaded LMX1204 design. Refer to Section 2.5 for a

comparison of performance in a high frequency application.

Figure 2-6. Phase Noise Comparison - 10 GHz

Results

Getting the Most of Your Data Converter Clocking System Using LMX1204 in

Cascaded Configuration

SNAA360 – JUNE 2022

2.3.5 12.8 GHz Performance

Figure 2-7 shows the phase noise is similar out to an offset frequency of 2.5 MHz, at which point the LMX1204

devices' measured phase noise begins to converge. The phase noise of the cascaded LMX1204 design follows

what is measured on the LMX1204EVM up to an offset frequency of 100 MHz, at which point the cascaded

design follows the variation produced by the SMA100B at an elevated noise floor.

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

-165

-155

-145

-135

-125

-115

-105

-95

-85

-75

SMA100B

LMX1204

Cascaded LMX1204

Figure 2-7. Phase Noise Comparison - 12.8 GHz

The average difference measured beyond 2.5 MHz comes out as 0.4 dB, which predicts the amount of added

phase noise generated by any additional cascaded LMX1204 devices in a system operating near 12.8 GHz.

Refer to Section 2.5 for a comparison in high-speed converter performance.

Results

SNAA360 – JUNE 2022

Getting the Most of Your Data Converter Clocking System Using LMX1204 in

Cascaded Configuration
