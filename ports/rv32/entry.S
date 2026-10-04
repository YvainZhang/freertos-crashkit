/* SPDX-License-Identifier: MIT */
.section .text.ck_vector,"ax"
.align 2
.option norvc
.global ck_rv32_vector
.type ck_rv32_vector,@function
ck_rv32_vector:
    /* No write to interrupted sp. Preserve t1 before using it. */
    csrrw t0, mscratch, t0
    sw t1, 24(t0)
    lw t1, 144(t0)
    bnez t1, ck_nested
    csrr t1, mcause
    bltz t1, ck_delegate
    addi t1, t1, -11
    beqz t1, ck_delegate           /* FreeRTOS M-mode ecall/yield. */
    li t1, 1
    sw t1, 144(t0)
    sw x0, 0(t0)
    sw x1, 4(t0)
    sw x2, 8(t0)
    sw x3, 12(t0)
    sw x4, 16(t0)
    /* x5 is in mscratch; x6 already stored. */
    sw x7, 28(t0)
    sw x8, 32(t0)
    sw x9, 36(t0)
    sw x10, 40(t0)
    sw x11, 44(t0)
    sw x12, 48(t0)
    sw x13, 52(t0)
    sw x14, 56(t0)
    sw x15, 60(t0)
    sw x16, 64(t0)
    sw x17, 68(t0)
    sw x18, 72(t0)
    sw x19, 76(t0)
    sw x20, 80(t0)
    sw x21, 84(t0)
    sw x22, 88(t0)
    sw x23, 92(t0)
    sw x24, 96(t0)
    sw x25, 100(t0)
    sw x26, 104(t0)
    sw x27, 108(t0)
    sw x28, 112(t0)
    sw x29, 116(t0)
    sw x30, 120(t0)
    sw x31, 124(t0)
    csrr t1, mscratch
    sw t1, 20(t0)
    csrr t1, mepc
    sw t1, 128(t0)
    csrr t1, mstatus
    sw t1, 132(t0)
    csrr t1, mcause
    sw t1, 136(t0)
    csrr t1, mtval
    sw t1, 140(t0)
    csrci mstatus, 8
    csrw mscratch, t0
    la sp, ck_rv32_fault_stack_top
    mv a0, t0
    tail ck_rv32_on_fault
ck_delegate:
    lw t1, 24(t0)
    csrrw t0, mscratch, t0
    tail freertos_risc_v_trap_handler
ck_nested:
    csrci mstatus, 8
    csrw mscratch, t0
    la sp, ck_rv32_fault_stack_top
    tail ck_rv32_on_nested_fault
.size ck_rv32_vector, .-ck_rv32_vector

.section .bss.ck_fault_stack,"aw",@nobits
.align 4
.global ck_rv32_fault_stack
ck_rv32_fault_stack:
    .space 4096
.global ck_rv32_fault_stack_top
ck_rv32_fault_stack_top:
