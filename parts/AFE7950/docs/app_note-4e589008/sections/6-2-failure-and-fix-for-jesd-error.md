# 6.2 Failure and Fix for JESD Error

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\AFE7950\documents\sbaa637.pdf p.8 -->

JESDC: EMB_STATE value

bits(1:0) = Lane0

bits(3:2) = Lane1

bits(5:4) = Lane2

bits(7:6) = Lane3

For stable link, the bits for each lane enabled can read as "10"

k.

SPIReadCheck 00a4,0,7,55

JESDB: FS_STATE value

bits(1:0) = Lane0

bits(3:2) = Lane1

bits(5:4) = Lane2

bits(7:6) = Lane3

For stable link, the bits for each lane enabled can read as "01"

l.

SPIReadCheck 00a6,0,7,FF

JESDB/C: ELASTIC_BUFFER_STATE value

bits(1:0) = Lane0

bits(3:2) = Lane1

bits(5:4) = Lane2

bits(7:6) = Lane3

For stable link, the bits for each lane enabled can read as "11".

Same registers are read check for second instance of JESD, that is JESD Lane4, 5, 6, 7

6.2 Failure and Fix for JESD Error

1.

If there is error in 0x118 or 0x119, this is serdes related error reg so it is important to check signal integrity of

serdes. We have CAPI to check for PRBS test pattern in SRX and read the error counter.

CAPI for SRX PRBS checker:

enableSerdesRxPrbsCheck

clearSerdesRxPrbsErrorCounter

getSerdesRxPrbsError

Also, if you want to verify the signal integrity for AFE to FPGA connection for serdes PHY layer, AFE had

CAPI to send PRBS pattern.

CAPI for STX PRBS enable:

sendserdesTxPrbs

2.

Other reg, 0x11b, 0x11c, 0x11d, 0x11e and 0x11f are JESD Lane error indicator. The error bit and the

description are self-explanatory to indicate the issue in JESD Link. The following is a list of some common

error and design for errors.

JESD204B

1.

Using Subclass 1, make sure Sysref is correctly acknowledge by both AFE and FPGA/ASIC in deterministic

fashion. Must be source synchronous with Device Clock and FPGA Ref. Clock, rising edge transition

determines LMFC alignment.

JESD Link Check Failure

Debugging AFE7950 for Run Time and Post Bring-Up Failure

SBAA637 – JUNE 2024
