# Table of Contents

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\LMX1204\documents\snaa360.pdf p.1 -->

Application Note

Getting the Most of Your Data Converter Clocking System

Using LMX1204 in Cascaded Configuration

Chase Wood

Systems Engineering and Marketing

ABSTRACT

Getting the most out of a RF signal chain design partly depends on providing a low phase noise, clean clock

to the A/D converter. In this application report, phase noise data taken using the Texas Instruments’ LMX1204

clock distribution device is studied. In general, the phase noise performance of any clock distribution method,

is not only dependent upon the phase noise of the input clock source, but also the active clock signal chain

as well. In this case the LMX1204 will be studied in both single and cascaded configurations. In general, the

performance measurements confirm the operational ability of the LMX1204 device to provide as an adequate

distribution method, up to 16 channels, with minimal degradation in converter performance.

Table of Contents

1 Introduction.............................................................................................................................................................................2

1.1 Cascaded LMX1204 Design.............................................................................................................................................. 2

2 Results.....................................................................................................................................................................................3

2.1 Single Device Performance................................................................................................................................................3

2.2 Cascaded Device Performance......................................................................................................................................... 4

2.3 Detailed Results.................................................................................................................................................................5

2.4 Cascaded LMX1204 Performance With ADC32RF54..................................................................................................... 10

2.5 Cascaded LMX1204 Performance With AFE7950...........................................................................................................10

3 Summary................................................................................................................................................................................11

4 References.............................................................................................................................................................................11

List of Figures

Figure 1-1. Simple Block Diagram of Cascaded LMX1204 Design............................................................................................. 2

Figure 1-2. LMX1204 Clock Distribution Board........................................................................................................................... 2

Figure 2-1. LMX1204EVM Phase Noise Measurements.............................................................................................................3

Figure 2-2. Cascaded LMX1204 Phase Noise Measurements....................................................................................................4

Figure 2-3. Phase Noise Comparison - 1 GHz............................................................................................................................ 5

Figure 2-4. Phase Noise Comparison - 3 GHz............................................................................................................................ 6

Figure 2-5. Phase Noise Comparison - 6 GHz............................................................................................................................ 7

Figure 2-6. Phase Noise Comparison - 10 GHz.......................................................................................................................... 8

Figure 2-7. Phase Noise Comparison - 12.8 GHz....................................................................................................................... 9

Figure 2-8. ADC32RF54 - SNR vs. Clock Source vs. Frequency..............................................................................................10

Figure 2-9. AFE7950 - SNR vs Clock Source vs Frequency.....................................................................................................10

Trademarks

All trademarks are the property of their respective owners.

Table of Contents

SNAA360 – JUNE 2022

Getting the Most of Your Data Converter Clocking System Using LMX1204 in

Cascaded Configuration
