/* SPDX-License-Identifier: MIT */
#include "ck_rv32.h"
#if !defined(__riscv) || __riscv_xlen != 32
#error "This port requires RV32"
#endif
__attribute__((aligned(16))) volatile uint32_t ck_rv32_frame[37];
extern void ck_rv32_vector(void);
void ck_rv32_install(void) {
    __asm__ volatile("csrw mscratch, %0\ncsrw mtvec, %1" ::
                     "r"(ck_rv32_frame),"r"(ck_rv32_vector):"memory");
}
