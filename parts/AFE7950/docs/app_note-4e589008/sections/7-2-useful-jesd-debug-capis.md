# 7.2 Useful JESD Debug CAPIs

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\AFE7950\documents\sbaa637.pdf p.10 -->

pollSerdesLinkStatusAllLanes: Bit wise Link Status for each lane. If Bit is 1: Lane Adapted success. If bit is 0,

lane recovery does not happen. It returns 1 even for turned off lanes. This needs to be 0xff in good case.

SetSerdesTxCursor: This function can be used to set the FFE Taps for the AFE STX. The detail for Taps is

given in configuration guide.

Solving the serdes PHY layer signal integrity problem can remove loss of signal and other serdes related error.

7.2 Useful JESD Debug CAPIs

The following CAPI can be used for JESD debug.

getJesdRxLaneErrors: This is used to check for lane error.

getJesdRxAlarms: This function can log error in complete JESD and Serdes Link.

clearJesdRxAlarms: To clear JESD alarm, as JESD Alarm reg are sticky. To read fresh error status, the

recommendation is to clear and read.

getAllLaneReady: This function reads the all lane ready counter which is the offset between the internal LMFC

boundary and the multiframe boundary (in JESD204B) or extended multi block boundary (in JESD204C) of the

last lane of arrival. This value with some offset is set in RBD.

setManualRbd: To set RBD #detail on how to set RBS is explained in another application note, (Determining

Optimal Receive Buffer Delay in JESD204B and JESD204C Receivers).

adcDacSync: This is an important function to resync AFE JESD block, there is a requirement here to leak sysref

during this function. Which is part of user define function.

The previous information can help to solve for JESD related failure during bring-up.

In previous sections, we have discussed about error or failure possible during AFE bring-up and possible cause

for the failure along with guide to resolve the bring-up error. There are few more debugging actions that come

handy post bring-up of AFE, when capturing the data for first time or in case of any failure post bring-up.

AFE79xx has many functionalities which are dynamically programmable post bring-up and to control or enable

those function, functions are made part of CAPI.

Validating Serdes and JESD Link using CAPI

Debugging AFE7950 for Run Time and Post Bring-Up Failure

SBAA637 – JUNE 2024
