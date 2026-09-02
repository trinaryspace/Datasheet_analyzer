# 7 Validating Serdes and JESD Link using CAPI

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\AFE7950\documents\sbaa637.pdf p.9-10 -->

Figure 6-1. Deterministic Latency

Note

For more detail refer to Understanding JESD204B Subclasses and Deterministic Latency.

2.

Lower serdes eye margin can cause issue, Try to adjust FFE Taps from FPGA/ASIC to improve swing of

SRX on AFE.

3.

Send K28.5 pattern from FPGA and Check if the AFE SYNC PIN is responding and check if CS state is as

expected.

4.

If we see any alignment related error there is a need to adjust RBD value. RBD is a release buffer space

to buffer data for the time to adjust latency variation of lanes. See the Determining Optimal Receive Buffer

Delay in JESD204B and JESD204C Receivers, application note.

5.

After RBD is set correctly, FS state also becomes correct and link is stable at this point.

6.

Check serdes polarity. If serdes polarity is reversed, CS state can come but FS and Buff state can not come.

7.

Check if the 204B scrambler status matches for AFE and FPGA/ASIC. Either both can be enabled or both

can be disabled.

JESD204C

1.

As mentioned previously, sysref can be synchronized and applied in deterministic fashion for AFE and

FPGA/ASIC.

2.

Lower serdes eye margin can cause issue, try to adjust FFE Taps from FPGA/ASIC to improve swing of SRX

on AFE.

3.

Major source of alignment error in 204C is due to incorrect RBD size. So refer to how to set RBD application

note for same.(Determining Optimal Receive Buffer Delay in JESD204B and JESD204C Receivers).

4.

Depending on resolution of sample if 16 bits choose Extended Multiblock E = 1, if resolution is 12/24 bits

choose E=3.

5.

Choose CRC mode same for JESD receiver and transmitter.

6.

Check serdes polarity. If serdes polarity is reversed, none of the CS, Buff and FS state comes.

7 Validating Serdes and JESD Link using CAPI

7.1 Useful Serdes Debug CAPIs

Along with PRBS CAPI, below CAPI can be used to debug SERDES Linkup.

getSerdesLinkStatus: This give dynamic information about Serdes Link Status of SRX lane (status of CDR

Locked).

getSerdesRxLaneEyeMarginValue: This function gets the eye height of the receiving serder lane after

processing.

reAdaptSerDesAllLanes: This can do Logic reset and readapt all lanes.

Validating Serdes and JESD Link using CAPI

SBAA637 – JUNE 2024

Debugging AFE7950 for Run Time and Post Bring-Up Failure

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
