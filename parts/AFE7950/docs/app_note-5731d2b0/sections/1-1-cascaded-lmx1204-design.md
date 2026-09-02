# 1.1 Cascaded LMX1204 Design

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\LMX1204\documents\snaa360.pdf p.2 -->

1 Introduction

When numerous devices in a system require a shared clock source, distributing the clock signal inadequately

leads to degradation in system performance. This becomes a prevalent concern for applications utilizing digital

beamforming (phased array radar, communications, ultrasound) as signal distortion increases directly as a result

of increased clock jitter. The LMX1204 is a clock distribution device designed for applications requiring minimal

added phase noise within the frequency range 300 MHz to 12.8 GHz. Although the LMX1204 is a high-speed

clock distribution device allowing for buffered, multiplied, and divided output frequency (relative to the input

frequency), this report will focus solely on the performance of this device in a buffered (1-to-1) configuration.

1.1 Cascaded LMX1204 Design

The LMX1204 creates up to four copies of an input signal, including the ability to buffer, multiply, or divide the

signal to each of the outputs. This device distributes a single low power clock signal and with minimal added

phase noise per stage. This design supports a two-level cascaded implementation creating 16 output clocks for

distribution as shown in Figure 1-1.

Figure 1-1. Simple Block Diagram of Cascaded LMX1204 Design

The purpose of this design is to show that the signal degradation caused by cascading two LMX1204 devices is

minimal. If a design requires cascading multiple LMX1204 devices, we can expect the signal integrity to be very

good, as shown in Results.

One aspect taken into consideration for this design was the board size, which was heavily determined by the

number of inputs and outputs this design requires. As shown in Figure 1-2, the design uses the Samtec Bull's

Eye Connector to ease the board size constraint created by 40 output differential pairs. All 20 outputs of a single

LMX1204 device pass through a connector that takes up only 630mm2, less than 1/4 of the equivalent PCB

footprint using typical edge mounted SMA connectors.

Figure 1-2. LMX1204 Clock Distribution Board

Introduction

Getting the Most of Your Data Converter Clocking System Using LMX1204 in

Cascaded Configuration

SNAA360 – JUNE 2022
