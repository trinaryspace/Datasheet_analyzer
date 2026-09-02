# 10 Device Health

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\AFE7950\documents\sbaa637.pdf p.11 -->

8 TX Chain Validation

1.

We have CAPI dacJesdConstantTestPatternValue which can send fix I and Q value in TX Chain at the

input to NCO. A Single tone at NCO value and the tone amplitude can be controlled using the I and Q

values.

2.

This test is useful in case of checking if TX Chain is configured properly when random or improper data in

TX spectrum, In case of improper data if we enable the dacJesdConstantTestPatternValue and see tone

output is correct at NCO, we can narrow down the problem is not in TX chain but in JESD block of TX chain

or the Serdes linkup or JESD of FPGA/ASIC.

3.

We can use this test single tone for TX output power check or calibrating RX chain equivalent to a signal

generator and also program the frequency by configuring the TX NCO dynamically with in some range, To

configure NCO dynamically, we can use CAPI updateTxNco.

4.

Also, in case of any spur debug. we can easily figure out the coupling point is inside AFE or external

by changing the TX DSA using CAPI setTxDsa. If the spur level change with DSA in can be coupling

somewhere internally in Chain if spur level does not change with TX DSA or scale non-linearly it can be

external coupling or two sources with external coupling dominating.

5.

AFE CAPI Libs also has option to internally read the dbfs power with in Tx Chain, using CAPI readTxPower.

This can also be handy during debug test.

9 RX Chain Validation

In RX chain we can use a test pattern to send a ramp data from JESD to capture on FPGA, without need of

external signal generator connected to RX using CAPI adcRampTestPattern. This test pattern is useful to check

Jesd capture functionality .

We have getRxRmsPower to measure the rms power in rx chain. It can be used in debug when capture is not

working and if need to check if ADC is working fine, this function will confirm the basic functionality.

10 Device Health

CAPI to check device health, checkDeviceHealth indicates status for PLL, DAC JESD, ADC JESD, SPI, MCU,

and PAP.

11 Summary

Application note serves like a guidebook for resolving various issues seen during AFE7950 bring-up by

describing the cause of the issue and step by step approach to resolve the failures. As described, most of

the issues are dependent on external factors and can have board dependencies so it is good to inspect board

as a starting point. Depending on the nature of issue, key factor to check can be operating voltage, SPI timing,

reference clock level, sysref common mode and level, Serdes connection mapping and polarity.

Also, we have mentioned different CAPIs which can be used to analyze TX and RX related issue, post bring-up

and can be done dynamically. Implementing CAPI in FPGA or ASIC need a processor onboard. We are working

on an application note for simplifying the implementation of CAPI on FPGA platform. As CAPI has potential

advantage of giving more accessibility to AFEs operation.

12 References

1.

Texas Instruments, JESD204B Overview high speed data converter training.

2.

JEDEC Standard: JESD204C.1.

3.

Texas Instruments, Determining Optimal Receive Buffer Delay in JESD204B and JESD204C Receivers,

application note.

4.

Texas Instruments, Understanding JESD204B Subclasses and Deterministic Latency.

TX Chain Validation

SBAA637 – JUNE 2024

Debugging AFE7950 for Run Time and Post Bring-Up Failure
