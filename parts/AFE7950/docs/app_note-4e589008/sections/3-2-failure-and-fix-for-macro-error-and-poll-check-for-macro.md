# 3.2 Failure and Fix for Macro Error and Poll check for Macro Done

<!-- source: C:\Users\afpim\Repos\datasheet_analyzer\parts\AFE7950\documents\sbaa637.pdf p.4 -->

3 Macro Failure Breaking the Bring-Up Flow

3.1 Read Check for Macro Error and Poll Check for Macro Done

1.

The device is configured through SPI using a combination of direct register reads/writes for simple

configurations, and register writes to initiate macros. Macro commands abstract out the internal device

configuration sequence to a simple set of configurations and simplify the host interaction. The commands

reduce complex configurations into simple writes, avoid computation complexity on the host side and provide

simple status information in response. Macro command is used at multiple places in bring-up.

2.

Macro Opcode: Operation code which informs AFE the operation to be performed. For differential operations

of AFE, different Macro opcode is defined.

Macro Operand: Operand are values or expressions that is used to perform an operation in AFE.

3.

The first SPIPoll, Poll for Bit 0 from Address 0xf0 which indicates if Macro/MCU is ready for a next operation.

If the Poll fails, the MCU is still not ready for new operation and if we run a new macro operation the MCU

can fail to execute.

4.

Later if Macro ready passes, operand and opcode are loaded.

5.

After that Macro Done status is polled #SPIPoll 00f0,2,2,04. This is to check if macro operation is complete.

6.

After that read check for 0xf0 bit 3 is read to check if macro operation was executed error free or had error.

7.

Bring-up can break if any of the this check fail. The following discusses if macro error and failure happen

how to figure out the error and resolve the issue.

Sample Code

SPIPoll 00f0,0,0,01            //MACRO_READY

SPIWrite 00a3,00,0,7    //MACRO_OPERAND_REG

SPIWrite 00a2,00,0,7    //MACRO_OPERAND_REG

SPIWrite 00a1,00,0,7    //MACRO_OPERAND_REG

SPIWrite 00a0,02,0,7    //MACRO_OPERAND_REG

SPIWrite 0193,01,0,7    //MACRO_OPCODE=0x1;

WAIT 0.001

SPIRead 00f0,2,2    //Read    MACRO_DONE=0x1;

SPIPoll 00f0,2,2,04

SPIReadCheck 00f0,3,3,00    //Read    MACRO_ERROR=0x0;

SPIRead 00f1,0,7    //Read    MACRO_ERROR_OPCODE=0x0;

SPIRead 00f0,4,4    //Read    MACRO_ERROR_IN_OPCODE=0x0;

SPIRead 00f0,5,5    //Read    MACRO_ERROR_OPCODE_NOT_ALLOWED=0x0;

SPIRead 00f0,6,6    //Read    MACRO_ERROR_IN_OPERAND=0x0;

SPIRead 00f0,7,7    //Read    MACRO_ERROR_IN_EXECUTION=0x0;

SPIRead 00f3,0,7    //Read    MACRO_ERROR_EXTENDED_CODE=0x0;

SPIRead 00f2,0,7    //Read    MACRO_ERROR_EXTENDED_CODE=0x0;

3.2 Failure and Fix for Macro Error and Poll check for Macro Done

1.

Macro operation are sensitive to AFE power nets (0.925V, 1.2V and 1.8V). First make sure all voltages are

within range and also the current limit for each rail is sufficient up to 3A. It is observed that if the current

sourcing is not sufficient then there could be a voltage dip and could result in Macro failure.

2.

For some macro operation to be successful, Sysref functionality needs to beokay. It is important to check if

Sysref level is reaching device pin as per data sheet specification range and frequency.

3.

When failure is in (SPIPoll 00f0,0,0,01) that is, Macro Ready fails means that the macro is still busy and not

able to take up new operation. Once the issue is located to which section of macro ready is failing. Some

delay (WAIT 1) can be added before the failing macro ready command and checked. In case if the failure still

exists check for point 1.

4.

When failure is in (SPIPoll 00f0,2,2,04) that is, Macro Done is failing means the macro is still working on

current operation. Once the issue is located to which section of macro done is failing. Some delay (WAIT 1)

can be added before the failing macro done command and checked, in case if the failure still exists check for

point 1.

5.

Now if the failure is in (SPIReadCheck 00f0,3,3,00) then it means there has happened a macro error during

the current macro operation. We have readout register which gives more detail on what type of error has

Macro Failure Breaking the Bring-Up Flow

Debugging AFE7950 for Run Time and Post Bring-Up Failure

SBAA637 – JUNE 2024
