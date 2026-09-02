# 5.2 Failure and Fix for Read Check Status of Sysref Flag Bit

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\AFE7950\documents\sbaa637.pdf p.6 -->

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
