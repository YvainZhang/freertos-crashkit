/* SPDX-License-Identifier: MIT */
#ifndef CK_RV32_H
#define CK_RV32_H
#include <stdint.h>
/* Single-hart M-mode RV32IMAC, no floating/vector/SoC extension register capture.
 * mscratch is owned by this vector. The delegated FreeRTOS handler must not use
 * mscratch. Board-specific integration must revalidate this contract. */
void ck_rv32_install(void);
/* x0..x31, mepc, mstatus, mcause, mtval, followed by the internal fatal guard. */
extern volatile uint32_t ck_rv32_frame[37];
_Noreturn void ck_rv32_on_fault(const volatile uint32_t *frame);
_Noreturn void ck_rv32_on_nested_fault(void);
#endif
