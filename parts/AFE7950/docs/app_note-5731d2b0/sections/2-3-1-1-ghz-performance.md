# 2.3.1 1 GHz Performance

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\LMX1204\documents\snaa360.pdf p.5 -->

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
