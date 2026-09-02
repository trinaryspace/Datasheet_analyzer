# 4.1 Read Check for PLL Lock

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\AFE7950\documents\sbaa637.pdf p.5 -->

happen, we can read below writes to get more insight on error and for more detail can check TRM document

and parallelly check for point 1.

SPIWrite 0018,20,0,7

SPIRead 00f1,0,7    //Read    MACRO_ERROR_OPCODE=0x0;

SPIRead 00f0,4,4    //Read    MACRO_ERROR_IN_OPCODE=0x0;

SPIRead 00f0,5,5    //Read    MACRO_ERROR_OPCODE_NOT_ALLOWED=0x0;

SPIRead 00f0,6,6    //Read    MACRO_ERROR_IN_OPERAND=0x0;

SPIRead 00f0,7,7    //Read    MACRO_ERROR_IN_EXECUTION=0x0;

SPIRead 00f3,0,7    //Read    MACRO_ERROR_EXTENDED_CODE=0x0;

SPIRead 00f2,0,7    //Read    MACRO_ERROR_EXTENDED_CODE=0x0;

SPIRead 00f4,0,7    //Read    MACRO_ERROR_EXTENDED_CODE=0x0;

SPIRead 00f5,0,7    //Read    MACRO_ERROR_EXTENDED_CODE=0x0;

SPIWrite 0018,00,0,7

6.

Effective execution of the for 0x78 macro opcode, hinges on precise implementation of SPI Burst writes.

4 AFE PLL Failure

4.1 Read Check for PLL Lock

PLL Lock status is read to check if device main PLL is locked and is stable.

SPIReadCheck 0066,4,4,10    //Lock

SPIReadCheck 0066,6,6,00    //Lock Lost Sticky

We monitor two specific bits, Bit[4] signifies current Lock status of PLL, while Bit[6] indicates whether PLL lost

lock after being lock for first time. This bit indicates instability in PLL after the first time it has locked.

Table 4-1. Reference Clock Electrical Characteristics

fPFD

PFD frequency

100

500

MHz

FREF

Input Clock

frequency

0.1

12

GHz

VSS

Input Clock level

0.6

1.8

VPPdiff

Coupling

AC Coupling

Only

REFCLK input

impedance

Parallel resistance

100

Ω

Parallel capacitance

0.5

pF

4.2 Failure and Fix for Read Check of PLL

The main source of error for PLL read check failure is if the reference clock is not proper. Check if the reference

clock is of correct frequency and power level is as expected range at pin also check for the common mode

forced from device is around 1.2V. Also, check for phase noise of reference clock in case of Bit 6 is high along

with if PLL 1.8V is stable.

AFE PLL Failure

SBAA637 – JUNE 2024

Debugging AFE7950 for Run Time and Post Bring-Up Failure
