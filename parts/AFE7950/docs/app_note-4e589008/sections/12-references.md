# 12 References

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\AFE7950\documents\sbaa637.pdf p.11-12 -->

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

IMPORTANT NOTICE AND DISCLAIMER

TI PROVIDES TECHNICAL AND RELIABILITY DATA (INCLUDING DATA SHEETS), DESIGN RESOURCES (INCLUDING REFERENCE

DESIGNS), APPLICATION OR OTHER DESIGN ADVICE, WEB TOOLS, SAFETY INFORMATION, AND OTHER RESOURCES “AS IS”

AND WITH ALL FAULTS, AND DISCLAIMS ALL WARRANTIES, EXPRESS AND IMPLIED, INCLUDING WITHOUT LIMITATION ANY

IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE OR NON-INFRINGEMENT OF THIRD

PARTY INTELLECTUAL PROPERTY RIGHTS.

These resources are intended for skilled developers designing with TI products. You are solely responsible for (1) selecting the appropriate

TI products for your application, (2) designing, validating and testing your application, and (3) ensuring your application meets applicable

standards, and any other safety, security, regulatory or other requirements.

These resources are subject to change without notice. TI grants you permission to use these resources only for development of an

application that uses the TI products described in the resource. Other reproduction and display of these resources is prohibited. No license

is granted to any other TI intellectual property right or to any third party intellectual property right. TI disclaims responsibility for, and you

will fully indemnify TI and its representatives against, any claims, damages, costs, losses, and liabilities arising out of your use of these

resources.

TI’s products are provided subject to TI’s Terms of Sale or other applicable terms available either on ti.com or provided in conjunction with

such TI products. TI’s provision of these resources does not expand or otherwise alter TI’s applicable warranties or warranty disclaimers for

TI products.

TI objects to and rejects any additional or different terms you may have proposed. IMPORTANT NOTICE

Mailing Address: Texas Instruments, Post Office Box 655303, Dallas, Texas 75265
