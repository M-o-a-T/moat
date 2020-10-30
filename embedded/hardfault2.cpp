#include "Arduino.h"

/*
----------------------------------------------------------------------
File : SEGGER_HardFaultHandler.c
Purpose : Generic SEGGER HardFault handler for Cortex-M, enables user-
          friendly analysis of hard faults in debug configurations.
-------- END-OF-HEADER ---------------------------------------------
*/
/*********************************************************************
*
* Defines
*
**********************************************************************
*/
// System Handler Control and State Register
#define SYSHND_CTRL (*(volatile unsigned int*) (0xE000ED24u))
// Memory Management Fault Status Register
#define NVIC_MFSR (*(volatile unsigned char*) (0xE000ED28u))
// Bus Fault Status Register
#define NVIC_BFSR (*(volatile unsigned char*) (0xE000ED29u))
// Usage Fault Status Register
#define NVIC_UFSR (*(volatile unsigned short*)(0xE000ED2Au))
// Hard Fault Status Register
#define NVIC_HFSR (*(volatile unsigned int*) (0xE000ED2Cu))
// Debug Fault Status Register
#define NVIC_DFSR (*(volatile unsigned int*) (0xE000ED30u))
// Bus Fault Manage Address Register
#define NVIC_BFAR (*(volatile unsigned int*) (0xE000ED38u))
// Auxiliary Fault Status Register
#define NVIC_AFSR (*(volatile unsigned int*) (0xE000ED3Cu))

#ifndef DEBUG
#define DEBUG (1)
#endif
// Should be overwritten by project settings
// in debug builds
/*********************************************************************
*
* Static data
*
**********************************************************************
*/
#if DEBUG

#undef EXTERNAL

static volatile unsigned int _Continue; // Set this variable to 1 to run further
static struct {
    struct {
        volatile unsigned int r0;
        volatile unsigned int r1;
        volatile unsigned int r2;
        volatile unsigned int r3;
        volatile unsigned int r12;
        volatile unsigned int lr;
        volatile unsigned int pc;
        union {
            volatile unsigned int byte;
            struct {
                unsigned int IPSR : 8;
                unsigned int EPSR : 19;
                unsigned int APSR : 5;
            } bits;
        } psr;
    } SavedRegs;
    //
    //
    //
    //
    //
    //
    //
    // Interrupt Program Status register (IPSR)
    // Execution Program Status register (EPSR)
    // Application Program Status register (APSR)
    // Program status register.
    union {
        volatile unsigned int byte;
        struct {
            unsigned int MEMFAULTACT : 1;
            unsigned int BUSFAULTACT : 1;
            unsigned int UnusedBits1 : 1;
            unsigned int USGFAULTACT : 1;
            unsigned int UnusedBits2 : 3;
            unsigned int SVCALLACT : 1;
            unsigned int MONITORACT : 1;
            unsigned int UnusedBits3 : 1;
            unsigned int PENDSVACT : 1;
            unsigned int SYSTICKACT : 1;
            unsigned int USGFAULTPENDED : 1;
            unsigned int MEMFAULTPENDED : 1;
            unsigned int BUSFAULTPENDED : 1;
            unsigned int SVCALLPENDED : 1;
            unsigned int MEMFAULTENA : 1;
            unsigned int BUSFAULTENA : 1;
            unsigned int USGFAULTENA : 1;
        } bits;
    } syshndctrl;
    union {
        volatile unsigned char byte;
        struct {
            unsigned char IACCVIOL : 1;
            unsigned char DACCVIOL : 1;
            unsigned char UnusedBits : 1;
            unsigned char MUNSTKERR : 1;
            unsigned char MSTKERR : 1;
            unsigned char UnusedBits2 : 2;
            unsigned char MMARVALID : 1;
        } bits;
    } mfsr;
    union {
        volatile unsigned int byte;
        struct {
            unsigned int IBUSERR : 1;
            unsigned int PRECISERR : 1;
            unsigned int IMPREISERR : 1;
            unsigned int UNSTKERR : 1;
            unsigned int STKERR : 1;
            unsigned int UnusedBits : 2;
            unsigned int BFARVALID : 1;
        } bits;
    } bfsr;
    volatile unsigned int bfar;

    union {
        volatile unsigned short byte;
        struct {
            unsigned short UNDEFINSTR : 1;
            unsigned short INVSTATE : 1;
            unsigned short INVPC : 1;
            unsigned short NOCP : 1;
            unsigned short UnusedBits : 4;
            unsigned short UNALIGNED : 1;
            unsigned short DIVBYZERO : 1;
            // Read as 1 if SVC exception is active
        } bits;
    } ufsr;
    //
    union {
        volatile unsigned int byte;
        struct {
            unsigned int UnusedBits : 1;
            unsigned int VECTBL : 1;
            unsigned int UnusedBits2 : 28;
            unsigned int FORCED : 1;
            unsigned int DEBUGEVT : 1;
        } bits;
    } hfsr; // Hard Fault Status Register (0xE000ED2C)
    union {
        volatile unsigned int byte;
        struct {
            unsigned int HALTED : 1;
            unsigned int BKPT : 1;
            unsigned int DWTTRAP : 1;
            unsigned int VCATCH : 1;
            unsigned int EXTERNAL : 1;
        } bits;
    } dfsr;
    volatile unsigned int afsr; // Auxiliary Fault Status Register
} HardFaultRegs;
#endif
/*********************************************************************
*
* Global functions
*
**********************************************************************
*/
/*********************************************************************
*
* HardFaultHandler()
*
* Function description
*
Generic hardfault handler
*/
extern "C" {
void HardFaultHandler(unsigned int* pStack);
}

void HardFaultHandler(unsigned int* pStack) {
    //
    // In case we received a hard fault because of a breakpoint instruction, we return.
    // This may happen when using semihosting for printf outputs and no debugger
    // is connected, i.e. when running a "Debug" configuration in release mode.
    //
    if (NVIC_HFSR & (1uL << 31)) {
        NVIC_HFSR |= (1uL << 31); // Reset Hard Fault status
        *(pStack + 6u) += 2u; // PC is located on stack at SP + 24 bytes;
        // increment PC by 2 to skip break instruction.
        return; // Return to interrupted application
    }
#if DEBUG
    //
    // Read NVIC registers
    //
    HardFaultRegs.syshndctrl.byte = SYSHND_CTRL; // System Handler Control and State Register
    HardFaultRegs.mfsr.byte = NVIC_MFSR; // Memory Fault Status Register
    HardFaultRegs.bfsr.byte = NVIC_BFSR; // Bus Fault Status Register
    HardFaultRegs.bfar = NVIC_BFAR; // Bus Fault Manage Address Register
    HardFaultRegs.ufsr.byte = NVIC_UFSR; // Usage Fault Status Register
    HardFaultRegs.hfsr.byte = NVIC_HFSR; // Hard Fault Status Register
    HardFaultRegs.dfsr.byte = NVIC_DFSR; // Debug Fault Status Register
    HardFaultRegs.afsr = NVIC_AFSR; // Auxiliary Fault Status Register
    //
    //
    HardFaultRegs.SavedRegs.r0 = pStack[0]; // Register R0
    HardFaultRegs.SavedRegs.r1 = pStack[1]; // Register R1
    HardFaultRegs.SavedRegs.r2 = pStack[2]; // Register R2
    HardFaultRegs.SavedRegs.r3 = pStack[3]; // Register R3
    HardFaultRegs.SavedRegs.r12 = pStack[4]; // Register R12
    HardFaultRegs.SavedRegs.lr = pStack[5]; // Link register LR
    HardFaultRegs.SavedRegs.pc = pStack[6]; // Program counter PC
    HardFaultRegs.SavedRegs.psr.byte = pStack[7]; // Program status word PSR
    //
    Serial.print("\nHF PC=x");
    Serial.print(HardFaultRegs.SavedRegs.pc, HEX);
    Serial.println(" -- HALT"); Serial.flush();
    // Halt execution
    // To step out of the HardFaultHandler, change the variable value to != 0.
    //
    _Continue = 0u;
    while (_Continue == 0u) {
    }
#else
    //
    // If this module is included in a release configuration,
    // simply stay in the HardFault handler
    //
    (void)pStack;
    do {
    } while (1);
#endif
}
/*************************** End of file ****************************/
