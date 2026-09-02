# Trademarks

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\AFE7950\documents\sbaa637.pdf p.1 -->

Application Note

Debugging AFE7950 for Run Time and Post Bring-Up

Failure

Dhruvil Solanki and Nikhil Jain

ABSTRACT

This application note describes the systematic procedure to identify, address and resolve bugs encountered

during AFE bring-up and thereby optimize the overall efficiency and reliability of system. In the AFE bring-

up process, thorough validation is conducted through read checks and register polling at various stages of

bring-up to verify the fulfillment of prerequisites for progression. Additionally, the polling register serve as the

acknowledgment bit to indicate successful execution and making sure integrity of AFE functionality during

bring-up flow. When encountering bring-up failure, they are stem from failed read checks or poll failures.

Also, the application note describes the debugging strategy for issues seen post bring-up like SERDES/ JESD

Link instability, TX tone or RX capture problem.

Table of Contents

1 Introduction.............................................................................................................................................................................2

2 SPI Failure During Bring-Up.................................................................................................................................................. 2

2.1 Detail Regarding Chip Readouts........................................................................................................................................2

2.2 Failure and Fix for Chip Read Check.................................................................................................................................2

2.3 Poll Check for SPI Access for PLL Page........................................................................................................................... 3

2.4 Failure and Fix for the SPI Poll Check for PLL Page Access.............................................................................................3

2.5 Read Check Indicating Status of Fuse Farm Autoload...................................................................................................... 3

2.6 Failure and Fix for Autoload Read Check.......................................................................................................................... 3

3 Macro Failure Breaking the Bring-Up Flow..........................................................................................................................4

3.1 Read Check for Macro Error and Poll Check for Macro Done........................................................................................... 4

3.2 Failure and Fix for Macro Error and Poll check for Macro Done........................................................................................4

4 AFE PLL Failure......................................................................................................................................................................5

4.1 Read Check for PLL Lock.................................................................................................................................................. 5

4.2 Failure and Fix for Read Check of PLL..............................................................................................................................5

5 AFE Internal Sysref Flag Failure........................................................................................................................................... 6

5.1 Read Check Status of Sysref Flag Bit................................................................................................................................6

5.2 Failure and Fix for Read Check Status of Sysref Flag Bit..................................................................................................6

6 JESD Link Check Failure....................................................................................................................................................... 6

6.1 Multiple Read Checks Indicating Status of JESD Linkup...................................................................................................6

6.2 Failure and Fix for JESD Error...........................................................................................................................................8

7 Validating Serdes and JESD Link using CAPI......................................................................................................................9

7.1 Useful Serdes Debug CAPIs..............................................................................................................................................9

7.2 Useful JESD Debug CAPIs..............................................................................................................................................10

8 TX Chain Validation...............................................................................................................................................................11

9 RX Chain Validation.............................................................................................................................................................. 11

10 Device Health.......................................................................................................................................................................11

11 Summary..............................................................................................................................................................................11

12 References...........................................................................................................................................................................11

Trademarks

All trademarks are the property of their respective owners.

Table of Contents

SBAA637 – JUNE 2024

Debugging AFE7950 for Run Time and Post Bring-Up Failure
