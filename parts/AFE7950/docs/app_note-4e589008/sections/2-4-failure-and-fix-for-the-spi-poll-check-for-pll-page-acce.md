# 2.4 Failure and Fix for the SPI Poll Check for PLL Page Access

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\AFE7950\documents\sbaa637.pdf p.3 -->

d.

Check for device input voltage levels and check for device reset state current level.

2.

Incorrect LSB readout: Check for the above-mentioned SPI setting and check the timing of the SDO, SCLK

and SEN. For debug purpose we can call any of the chip readout separately and Probe the SPI Pins. SEN

need to be held one more extra clock cycle with the last SCLK edge.

3.

Before moving forward with the AFE bring-up process, it is important to verify the implementation of SPI

Burst write. This is essential because SPI Burst write is utilized in various aspects of the AFE bring-up,

and any issue with the implementation can potentially lead to macro error later on. There is certain macro

operation which involves loading and verifying the success of burst write operation. To verify we can use a fix

bus write sequence and read the register sequentially. SPIBurstWrite 0010, [01,02,03,04,05,06,07,08,09,0A]

then, read SPI address from 0x10 to 0x19 and confirm if readout is as expected. Later set all address back

to zero.

2.3 Poll Check for SPI Access for PLL Page

When in AFE bring up if we try to write or read in PLL Page, the device needs to internally request SPI access

for PLL Page and SPIPoll 0171,0,0,01 is the Poll check to get information about if SPI has got the access to PLL

page.

2.4 Failure and Fix for the SPI Poll Check for PLL Page Access

Check for voltage on the AFE power nets (0.925V, 1.2V and 1.8V) are in expected range as per data sheet

recommendation.

2.5 Read Check Indicating Status of Fuse Farm Autoload

EFuse auto load is done and checked for any autoload error.

Fuse Farm autoload read check is to verify the fuse are loaded correctly.

SPIReadCheck 0150,0,3,0f //Read    obs_func_spi_chain_autoload_done=0xf;

SPIReadCheck 0150,4,7,00 //Read    obs_func_spi_chain_autoload_error=0x0;

SPIReadCheck 0160,0,3,0f //Read    obs_func_spi_chain_autoload_done=0xf;

SPIReadCheck 0160,4,7,00 //Read    obs_func_spi_chain_autoload_error=0x0;

2.6 Failure and Fix for Autoload Read Check

The most common reason for failure of autoload read check is if reference clock is not reaching the device.

Autoload operation work on clock which is derived after dividing reference clock inside AFE. So, it is important to

check if the reference clock is reaching the AFE pin with in expected voltage range also check if 1.2V common

mode is present at reference clock AFE side pin (common mode is forced internally).

Check for voltage on the AFE power nets (0.925V, 1.2V and 1.8V) are in expected range as per data sheet

recommendation.

SPI Failure During Bring-Up

SBAA637 – JUNE 2024

Debugging AFE7950 for Run Time and Post Bring-Up Failure
