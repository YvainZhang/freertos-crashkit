/* SPDX-License-Identifier: MIT */
#include "crashkit.h"
#include "ck_freertos.h"
#include "ck_rv32.h"
#include "firmware_id.h"

__attribute__((used,section(".crashkit_id"))) const uint8_t firmware_identity[16]=CK_FIRMWARE_ID;
static uint8_t dump[2048];
static struct ck_registry registry;
static volatile uint32_t progress;
static StackType_t worker_stack[512], fault_stack[512], idle_stack[256];
static StaticTask_t worker_tcb, fault_tcb, idle_tcb;
static void uart(char c) {
    volatile uint8_t *u=(volatile uint8_t *)0x10000000;
    for (unsigned i=0;i<4096;i++) if (u[5] & 0x20) {u[0]=(uint8_t)c; return;}
}
static void text(const char *s) {while (*s) uart(*s++);}
static _Noreturn void done(int pass) {
    *(volatile uint32_t *)0x100000=(pass ? 0x5555u : 0x13333u);
    for (;;) __asm__ volatile("wfi");
}
void ck_example_assert(unsigned line) {(void)line; text("UNEXPECTED_ASSERT\n"); done(0);}
void vApplicationGetIdleTaskMemory(StaticTask_t **t, StackType_t **s, configSTACK_DEPTH_TYPE *n) {
    *t=&idle_tcb; *s=idle_stack; *n=256;
}
static int read_ram(void *user, uint64_t address, uint8_t *p, size_t n) {
    (void)user;
#if CK_CASE == 4
    __asm__ volatile("lw zero, 0(zero)"); /* Deliberately trigger a nested fault. */
#endif
    /* Example whitelist is narrower than all RAM: only our known task stacks. */
    uint64_t start=(uintptr_t)fault_stack;
    if (address<start || address>start+sizeof(fault_stack) || n>start+sizeof(fault_stack)-address) return CK_EREAD;
    const volatile uint8_t *source=(const volatile uint8_t *)(uintptr_t)address;
    for (size_t i=0;i<n;i++) p[i]=source[i];
    return CK_OK;
}
_Noreturn void ck_rv32_on_fault(const volatile uint32_t *frame) {
    struct ck_writer writer; size_t size=0; uint64_t regs[36];
    struct ck_identity identity={CK_ARCH_RV32,32,1,CK_REASON_CPU_FAULT,0,{0},1};
    for (unsigned i=0;i<16;i++) identity.firmware_id[i]=firmware_identity[i];
    for (unsigned i=0;i<36;i++) regs[i]=frame[i];
    if (ck_begin(&writer,dump,sizeof(dump),&identity) || ck_registers(&writer,regs,36,32,(1ULL<<36)-1) ||
        ck_registry_capture(&writer,&registry) || ck_diagnostic(&writer,3,progress)) done(0);
    uint32_t bytes=64;
    uint64_t base=(uintptr_t)fault_stack, end=base+sizeof(fault_stack);
    if (regs[2]>=base && regs[2]<end && end-regs[2]<bytes) bytes=(uint32_t)(end-regs[2]);
    (void)ck_memory(&writer,regs[2],bytes,read_ram,NULL);
    if (ck_finish(&writer,&size)) done(0);
    text("CK_HEX_BEGIN\n");
    static const char hex[]="0123456789abcdef";
    for (size_t i=0;i<size;i++) {uart(hex[dump[i]>>4]);uart(hex[dump[i]&15]);}
    text("\nCK_HEX_END\n"); done(1);
}
_Noreturn void ck_rv32_on_nested_fault(void) {
    text("CK_NESTED_ABORT\n"); /* A complete dump is intentionally not claimed. */
    done(1);
}
static void worker(void *p) {(void)p; for (;;) {progress++; vTaskDelay(1);}}
static void fault(void *p) {
    (void)p; vTaskDelay(10);
    if (progress<2) {text("NO_SCHEDULER_PROGRESS\n"); done(0);}
#if CK_CASE == 2
    __asm__ volatile("li sp, 4\n.global ck_injected_fault\nck_injected_fault:\n.word 0xffffffff" ::: "memory");
#elif CK_CASE == 3
    __asm__ volatile(".global ck_injected_fault\nck_injected_fault:\nlw zero, 0(zero)" ::: "memory");
#else
    __asm__ volatile("li t0, 0x12345678\nli t1, 0x76543210\n.global ck_injected_fault\nck_injected_fault:\n.word 0xffffffff" ::: "t0","t1","memory");
#endif
    text("FAULT_NOT_TRIGGERED\n"); done(0);
}
int main(void) {
    ck_registry_init(&registry); ck_rv32_install();
    TaskHandle_t a=xTaskCreateStatic(worker,"worker",512,NULL,1,worker_stack,&worker_tcb);
    TaskHandle_t b=xTaskCreateStatic(fault,"fault",512,NULL,2,fault_stack,&fault_tcb);
    if (!a || !b || ck_freertos_track_static(&registry,a,"worker",worker_stack,512,1,1) ||
        ck_freertos_track_static(&registry,b,"fault",fault_stack,512,2,2)) done(0);
    text("FREERTOS_RV32_START\n"); vTaskStartScheduler(); done(0);
}
