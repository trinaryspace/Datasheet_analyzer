# 6 JESD Link Check Failure

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\AFE7950\documents\sbaa637.pdf p.6-8 -->

5 AFE Internal Sysref Flag Failure

5.1 Read Check Status of Sysref Flag Bit

We have internal clock and sysref flag status to check if the device has registered the pin sysref.

SPIReadCheck 012c,3,3,08    // jesd_clk_rx1

SPIReadCheck 0130,3,3,08    // monitor_jesd_sysref_rx1

5.2 Failure and Fix for Read Check Status of Sysref Flag Bit

Failure in read check sysref status points towards improper pin sysref. Make sure sysref frequency and level

are in expected range. If using pulse sysref mode is selected, common mode voltage must be supplied through

external driver along with swing limits. In case of continuous sysref mode is selected, AC coupling capacitor can

be used and device can force common mode internally for sysref pins around 0.7V.

Table 5-1. Sysref Electrical Characteristics

Differential Inputs: ±Mode A

FSYSREFMAX

SYSREF Input Frequency Maximum

1

GHz

VSWINGSRMAX

SYSREF Input SWING Maximum

1.8

VPPdiff

VSWINGSRMIN

SYSREF Input SWING Minimum

fREF < 500MHz

0.3

VPPdiff

fREF > 500MHz

0.6

VPPdiff

VCOMSRMAX

SYSREF Input Common Mode Voltage Maximum

0.8

V

VCOMSRMIN

SYSREF Input Common Mode Voltage Minimum

0.6

V

ZT

Input Termination

Differential

100

Ω

CL

Input Capacitance

Each pin to GD

500

pF

6 JESD Link Check Failure

6.1 Multiple Read Checks Indicating Status of JESD Linkup

1.

JESD linkup is done at the end of AFE bring-up. We have multiple check points for JESD linkup status of

AFE. During the bring-up flow serdes is already linked during the AFE bring-up. Do make sure the FPGA/

ASIC STX is transmitting some data so that the CDR of AFE SRX can adapt and achieve serdes linkup

between AFE and FPGA/ASIC.

During JESD Linkup we check for Serdes and JESD linkup and error status. Below is list read check done

during bring-up.

a.

SPIReadCheck 0118,0,7,00 #Below is the definition of error indicated for 0x118

[3:0] = TIED to 0

[4] = JESD shorttest alarm

[5] = TIED to 0

[6] = serdesab_pll_loss_of_lock

[7] = serdescd_pll_loss_of_lock

b.

SPIReadCheck 0119,0,7,00

[0] = SRX1 LOS indicator

[1] = SRX2 LOS indicator

[2] = SRX3 LOS indicator

[3] = SRX4 LOS indicator

[4] = SRX1 Serdes-FIFO error

[5] = SRX2 Serdes-FIFO error

AFE Internal Sysref Flag Failure

Debugging AFE7950 for Run Time and Post Bring-Up Failure

SBAA637 – JUNE 2024

[6] = SRX3 Serdes-FIFO error

[7] = SRX4 Serdes-FIFO error

c.

SPIReadCheck 011a,0,7,00

TIED to 0

d.

SPIReadCheck 011b,0,7,00

[3:0] = TIED to 0

[4] = JESDB: Lane0 Frame-Sync error (Ctrl-K in middle of data) JESDC: Lane0 Fixed ones error

[5] = JESDB: Lane1 Frame-Sync error (Ctrl-K in middle of data) JESDC: Lane1 Fixed ones error

[6] = JESDB: Lane2 Frame-Sync error (Ctrl-K in middle of data) JESDC: Lane2 Fixed ones error

[7] = JESDB: Lane3 Frame-Sync error (Ctrl-K in middle of data) JESDC: Lane3 Fixed ones error

e.

SPIReadCheck 011c,0,7,00

Below is lane error for JESD 204B protocol for lane 0:

bit7 = JESDB: multiframe alignment error

bit6 = JESDB: frame alignment error

bit5 = JESDB: link configuration error

bit4 = JESDB: elastic buffer overflow (bad RBD value)

bit3 = JESDB: elastic buffer match error. The first non-/K/ does not match 'match_ctrl' and 'match_data'

programmed values

bit2 = JESDB: code synchronization error

bit1 = JESDB: 8b/10b not-in-table code error

bit0 = JESDB: 8b/10b disparity error

If we use JESD 204C protocol, below is the lane error mapped to for lane 0:

bit7 = JESDC: EoEMB alignment error

bit6 = JESDC: EoMB alignment error

bit5 = JESDC: cmd-data in crc mode not matching with spi register bits

bit4 = JESDC: elastic buffer overflow (bad RBD value)

bit3 = JESDC: TIED to 0. bit2 = JESDC: extended multiblock alignment error

bit1 = JESDC: sync-header invalid error ('11' or '00' received in expected sync header location)

bit0 = JESDC: sync-header CRC error

f.

SPIReadCheck 011e,0,7,00

Same as above lane error mapping for JESD lane 1

g.

SPIReadCheck 011d,0,7,00

Same as above lane error mapping for JESD lane 2

h.

SPIReadCheck 011c,0,7,00

Same as above lane error mapping for JESD lane 2

i.

SPIReadCheck 00ee,0,3,0f

JESDB: comma_align_lock_lane[0:3]monitor_flag

JESDC: sync_header_align_lock_lane[0:3]monitor_flag

j.

SPIReadCheck 00a2,0,7,aa

JESDB: CS_STATE value

JESD Link Check Failure

SBAA637 – JUNE 2024

Debugging AFE7950 for Run Time and Post Bring-Up Failure

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
