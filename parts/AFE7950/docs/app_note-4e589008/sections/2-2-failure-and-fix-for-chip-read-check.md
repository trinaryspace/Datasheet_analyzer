# 2.2 Failure and Fix for Chip Read Check

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\AFE7950\documents\sbaa637.pdf p.2 -->

1 Introduction

AFE bring-up involves a systematic and Top to Bottom configuration process. For the ease of splitting the

step in the configuration file, the bring-up file is divided into multiple steps. The section configured earlier

plays crucial role in the subsequent step of bring-up. Detail for each step mentioned below is available in

AFE79xx_ConfigurationGuide under Bring-Up Flow and Log File section.

Bring-up Flow:

rstDevice, fuseChain, mcuWakeUp, pllEfuse, pllConfig, serdesConfig, topConfig, sysConfig,

configTune, analogWrites, jesdConfig, agcConfig, miscConfig, gpioConfig, sysrefJesdLinkup, postLinkUp,

dlJesdLinkupCheck

In the AFE bring-up process, thorough validation is conducted through read checks and register polling at

various stages of bring-up. The following is the format definition of the SPI command in AFE7950 configuration

file:

SPIWrite Addr, valuetoWrite, LSB, MSB: This command is used to do SPI write for Addr in AFE and addr is up

to 15bits, value toWrite is Value to be write for mentioned LSB to MSB bits.

SPIRead Addr, LSB, MSB: This command reads the value from mention addrs for the set LSB to MSB bits.

SPIBurstWrite starting Address, [array of the value to written in the incremental address]: This command

burst writes for the AFE, starting address is mentioned and the array indicates the value to write for each

incremental address.

SPIReadCheck Addr, LSB, MSB, Expectedvalue: Read check command verifies if the readout of the register

matches the expected value. It is a onetime check. Error to read the expected value cause failure.

SPIPoll Addr, LSB, MSB, Expectedvalue: Poll check command verifies the readout of the register repeatedly

for certain set period of time until it reads the value, timeout or fails in case of readout not expected.

2 SPI Failure During Bring-Up

2.1 Detail Regarding Chip Readouts

There are three different chip identification checks for AFE. chip_type, chip_id, chip_ver. Information about what

chip readout to expect in part of bring-up generation libs and the read check command is embedded with

information about Address, bit size and readout expected.

chip_type = Indicates type of part # 0xa = AFE

chip_id = Indicates chip Id # 0x78 = AFE79xx

chip_ver = Indicates chip version

SPIReadCheck 0003,0,7,0a //Read    chip_type=0xa;     Address(0x3[7:0])

SPIReadCheck 0004,0,7,78

SPIReadCheck 0005,0,7,00 //Read    chip_id=0x78;     Address(0x4[7:0],0x5[7:0])

SPIReadCheck 0006,0,7,20 //Read    chip_ver=0x20;     Address(0x6[7:0],0x7[7:0])

2.2 Failure and Fix for Chip Read Check

1.

Chip readout as 0x0 or 0xff:

a.

We can check if SPI is working correctly. Make sure the Address length is 16, packet length is 24, packet

order as Address first, packet type as MSB first, enable state as Active low, Data latch on positive edge

for write and negative edge for read also check the physical SPI Driver connection and SPI and GPIO

Logic for AFE works at 1.8V.

b.

If all the settings are as expected, next step is to probe the SEN, SCLK, SDI, SDO and check for

waveform level and timing data to make sure proper functionality for SPI Driver and AFE.

c.

If Timing and Level of SEN, SCLK and SDI is expected and if AFE is not responding and if SDO is low.

Do HW Reset of the AFE and write SPI write for configuring 4 wire or 3 wire mode depend upon your

system need.

SPIWrite 0000,30,0,7 //Bit 4 (1: 4 Pin control; 0: 3 Pin control)

Introduction

Debugging AFE7950 for Run Time and Post Bring-Up Failure

SBAA637 – JUNE 2024
