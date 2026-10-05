/* SPDX-License-Identifier: MIT */
#include "crashkit.h"
#include "ck_freertos.h"
#include "ck_rv32.h"
#include "firmware_id.h"
#include "crashkit_trace.h"
#include "queue.h"
#include "semphr.h"
#include "event_groups.h"
#include "stream_buffer.h"
#include "timers.h"

__attribute__((used,section(".crashkit_id"))) const uint8_t firmware_identity[16]=CK_FIRMWARE_ID;
__attribute__((section(".crashkit_dump"))) static uint8_t dump[65536];
extern uint8_t __capture_start[], __capture_end[];
extern uint8_t __irq_stack_bottom[], __stack_top[];
static volatile uint32_t capture_reason=CK_REASON_CPU_FAULT, capture_detail;
static struct ck_registry registry;
static volatile uint32_t progress;
static StackType_t worker_stack[512], fault_stack[512], idle_stack[256],
                   blocked_stack[512], timer_stack[512];
static StaticTask_t worker_tcb, fault_tcb, idle_tcb, blocked_tcb, timer_tcb;
volatile uint32_t ck_example_global=0x13579bdfu;
QueueHandle_t ck_example_queue, ck_example_wait_queue;
SemaphoreHandle_t ck_example_semaphore, ck_example_mutex;
EventGroupHandle_t ck_example_event;
StreamBufferHandle_t ck_example_stream;
TimerHandle_t ck_example_timer;
static StaticQueue_t queue_storage, wait_queue_storage;
static uint8_t queue_items[4*sizeof(uint32_t)], wait_items[2*sizeof(uint32_t)];
static StaticSemaphore_t semaphore_storage, mutex_storage;
static StaticEventGroup_t event_storage;
static StaticStreamBuffer_t stream_storage;
static uint8_t stream_bytes[65];
static StaticTimer_t timer_storage;
static struct ck_trace_ring trace_ring;
struct ck_trace_ring *ck_example_trace=&trace_ring;
struct ck_register_sample {char name[16];uint32_t address,value,width,source;};
struct ck_peripheral_snapshot {uint32_t tick,count;struct ck_register_sample samples[2];};
static struct ck_peripheral_snapshot peripheral_snapshot;
struct ck_peripheral_snapshot *ck_example_peripherals=&peripheral_snapshot;
struct ck_object_entry {uint32_t kind,slot;char name[16];};
__attribute__((used,section(".crashkit_objects")))
static const struct {uint32_t magic,version,count;struct ck_object_entry entries[10];} objects={
    0x314f4b43u,1,10,{
        {1,(uintptr_t)&ck_example_queue,"queue"},{1,(uintptr_t)&ck_example_wait_queue,"wait_queue"},
        {2,(uintptr_t)&ck_example_semaphore,"semaphore"},{3,(uintptr_t)&ck_example_mutex,"mutex"},
        {4,(uintptr_t)&ck_example_event,"event"},{5,(uintptr_t)&ck_example_stream,"stream"},
        {6,(uintptr_t)&ck_example_timer,"timer"},{7,0,"heap"},
        {8,(uintptr_t)&ck_example_peripherals,"registers"},{9,(uintptr_t)&ck_example_trace,"trace"}}
};
static void uart(char c) {
    volatile uint8_t *u=(volatile uint8_t *)0x10000000;
    for (unsigned i=0;i<4096;i++) if (u[5] & 0x20) {u[0]=(uint8_t)c; return;}
}
static void text(const char *s) {while (*s) uart(*s++);}
static _Noreturn void done(int pass) {
    *(volatile uint32_t *)0x100000=(pass ? 0x5555u : 0x13333u);
    for (;;) __asm__ volatile("wfi");
}
void ck_example_assert(unsigned line) {
    capture_reason=CK_REASON_ASSERT;capture_detail=line;
    __asm__ volatile(".global ck_assert_fault\nck_assert_fault:\nebreak" ::: "memory");
    done(0);
}
void vApplicationStackOverflowHook(TaskHandle_t task,char *name) {
    (void)name;capture_reason=CK_REASON_STACK_OVERFLOW;capture_detail=(uintptr_t)task;
    __asm__ volatile(".global ck_overflow_fault\nck_overflow_fault:\nebreak" ::: "memory");
    done(0);
}
void vApplicationTickHook(void) {
#if CK_CASE == 7
    if(xTaskGetTickCountFromISR()>=12) {
        __asm__ volatile(".global ck_isr_fault\nck_isr_fault:\n.word 0xffffffff" ::: "memory");
        done(0);
    }
#endif
}
void vApplicationGetIdleTaskMemory(StaticTask_t **t, StackType_t **s, configSTACK_DEPTH_TYPE *n) {
    *t=&idle_tcb; *s=idle_stack; *n=256;
}
void vApplicationGetTimerTaskMemory(StaticTask_t **t, StackType_t **s, configSTACK_DEPTH_TYPE *n) {
    *t=&timer_tcb; *s=timer_stack; *n=512;
}
static int read_ram(void *user, uint64_t address, uint8_t *p, size_t n) {
    (void)user;
#if CK_CASE == 4
    __asm__ volatile("lw zero, 0(zero)"); /* Deliberately trigger a nested fault. */
#endif
    /* Application/kernel RAM only; excludes dump and active capture workspace. */
    uint64_t start=(uintptr_t)__capture_start, end=(uintptr_t)__capture_end;
    uint64_t irq=(uintptr_t)__irq_stack_bottom,irq_end=(uintptr_t)__stack_top;
    if(!((address>=start && address<=end && n<=end-address) ||
         (address>=irq && address<=irq_end && n<=irq_end-address))) return CK_EREAD;
    const volatile uint8_t *source=(const volatile uint8_t *)(uintptr_t)address;
    for (size_t i=0;i<n;i++) p[i]=source[i];
    return CK_OK;
}
_Noreturn void ck_rv32_on_fault(const volatile uint32_t *frame) {
    struct ck_writer writer; size_t size=0; uint64_t regs[36];
    struct ck_identity identity={CK_ARCH_RV32,32,1,CK_REASON_CPU_FAULT,0,{0},1};
    identity.reason=capture_reason;
    for (unsigned i=0;i<16;i++) identity.firmware_id[i]=firmware_identity[i];
    for (unsigned i=0;i<36;i++) regs[i]=frame[i];
    if (ck_begin(&writer,dump,sizeof(dump),&identity) || ck_registers(&writer,regs,36,32,(1ULL<<36)-1) ||
        ck_registry_capture(&writer,&registry) || ck_diagnostic(&writer,3,progress)) done(0);
    if(capture_reason!=CK_REASON_CPU_FAULT) {
        if(ck_diagnostic(&writer,4,capture_reason==CK_REASON_STACK_OVERFLOW ? 1u : 0u) ||
           ck_diagnostic(&writer,5,capture_detail)) done(0);
    }
    uint32_t bytes=64;
    uint64_t base=(uintptr_t)fault_stack, end=base+sizeof(fault_stack);
    if (regs[2]>=base && regs[2]<end && end-regs[2]<bytes) bytes=(uint32_t)(end-regs[2]);
    uint64_t irq_base=(uintptr_t)__irq_stack_bottom,irq_end=(uintptr_t)__stack_top;
    if(regs[2]>=irq_base && regs[2]<irq_end && irq_end-regs[2]<bytes) bytes=(uint32_t)(irq_end-regs[2]);
    (void)ck_memory(&writer,regs[2],bytes,read_ram,NULL);
    /* Keep each read bounded, but save all application/kernel data for host
     * task/list analysis. Stack-window bytes duplicate identical frozen RAM. */
    for(uintptr_t p=(uintptr_t)__capture_start;p<(uintptr_t)__capture_end;) {
        uint32_t n=(uint32_t)((uintptr_t)__capture_end-p);
        if(n>CK_MAX_REGION_BYTES) n=CK_MAX_REGION_BYTES;
        int rc=ck_memory(&writer,p,n,read_ram,NULL);
        if(rc==CK_ENOSPACE) break;
        if(rc!=CK_OK) break;
        p+=n;
    }
    for(uintptr_t p=(uintptr_t)__irq_stack_bottom;p<(uintptr_t)__stack_top;p+=CK_MAX_REGION_BYTES)
        if(ck_memory(&writer,p,CK_MAX_REGION_BYTES,read_ram,NULL)!=CK_OK) break;
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
static void blocked(void *p) {(void)p;uint32_t value;for(;;) (void)xQueueReceive(ck_example_wait_queue,&value,portMAX_DELAY);}
static void timer_callback(TimerHandle_t timer) {(void)timer;}
__attribute__((noinline)) static void ck_fault_leaf(void) {
#if CK_CASE == 2
    __asm__ volatile("li sp, 4\n.global ck_injected_fault\nck_injected_fault:\n.word 0xffffffff" ::: "memory");
#elif CK_CASE == 3
    __asm__ volatile(".global ck_injected_fault\nck_injected_fault:\nlw zero, 0(zero)" ::: "memory");
#else
    __asm__ volatile("li t0, 0x12345678\nli t1, 0x76543210\n.global ck_injected_fault\nck_injected_fault:\n.word 0xffffffff" ::: "t0","t1","memory");
#endif
    text("FAULT_NOT_TRIGGERED\n"); done(0);
}
__attribute__((noinline)) static void ck_fault_middle(unsigned token) {
    volatile unsigned local=token+7;
    void (*volatile target)(void)=ck_fault_leaf;
    target(); ck_example_global=local;
}
__attribute__((used,noinline)) static void fault(void *p) {
    (void)p; vTaskDelay(10);
    if (progress<2) {text("NO_SCHEDULER_PROGRESS\n"); done(0);}
    taskENTER_CRITICAL();
    peripheral_snapshot.tick=(uint32_t)xTaskGetTickCount(); peripheral_snapshot.count=2;
    struct ck_register_sample clock={"cpu_clock_hz",0,configCPU_CLOCK_HZ,32,1};
    struct ck_register_sample serial={"uart_lsr",0x10000005,*(volatile uint8_t *)0x10000005,8,2};
    peripheral_snapshot.samples[0]=clock;peripheral_snapshot.samples[1]=serial;
    (void)ck_trace_write(&trace_ring,peripheral_snapshot.tick,3,progress);
    taskEXIT_CRITICAL();
#if CK_CASE == 5
    configASSERT(ck_example_global==0);
#elif CK_CASE == 6
    fault_stack[0]=0; /* Break the real FreeRTOS stack canary; SP remains valid. */
    taskYIELD();     /* Kernel switch check invokes the real overflow hook. */
#endif
#if CK_CASE == 7
    for(;;) vTaskDelay(1); /* Let the real timer IRQ enter the tick hook. */
#endif
    ck_fault_middle(42);
    /* Keep a real ABI return path in the fixture so task-root RA=0 terminates
     * GDB/DWARF unwinding, instead of a compiler-elided noreturn RA rule. */
    while(ck_example_global) vTaskDelay(1);
}
__attribute__((naked)) static void fault_entry(void *p __attribute__((unused))) {
    __asm__ volatile("li s0,0\nli ra,0\ntail fault");
}
int main(void) {
    if(ck_example_global!=0x13579bdfu) done(0);
    ck_registry_init(&registry); ck_rv32_install();
    TaskHandle_t a=xTaskCreateStatic(worker,"worker",512,NULL,1,worker_stack,&worker_tcb);
    ck_trace_init(&trace_ring);
    ck_example_queue=xQueueCreateStatic(4,sizeof(uint32_t),queue_items,&queue_storage);
    ck_example_wait_queue=xQueueCreateStatic(2,sizeof(uint32_t),wait_items,&wait_queue_storage);
    ck_example_semaphore=xSemaphoreCreateCountingStatic(3,2,&semaphore_storage);
    ck_example_mutex=xSemaphoreCreateMutexStatic(&mutex_storage);
    ck_example_event=xEventGroupCreateStatic(&event_storage);
    ck_example_stream=xStreamBufferCreateStatic(64,1,stream_bytes,&stream_storage);
    ck_example_timer=xTimerCreateStatic("periodic",100,pdTRUE,NULL,timer_callback,&timer_storage);
    if(!ck_example_queue || !ck_example_wait_queue || !ck_example_semaphore || !ck_example_mutex ||
       !ck_example_event || !ck_example_stream || !ck_example_timer) done(0);
    uint32_t first=0x11223344u,second=0x55667788u;
    if(xQueueSend(ck_example_queue,&first,0)!=pdPASS || xQueueSend(ck_example_queue,&second,0)!=pdPASS) done(0);
    (void)ck_trace_write(&trace_ring,0,1,first);(void)ck_trace_write(&trace_ring,0,2,second);
    (void)xEventGroupSetBits(ck_example_event,5);
    const char stream_data[]="crashkit";
    if(xStreamBufferSend(ck_example_stream,stream_data,8,0)!=8) done(0);
    void *allocation=pvPortMalloc(128);if(!allocation) done(0);
    vPortFree(allocation);
    if(xTimerStart(ck_example_timer,0)!=pdPASS) done(0);
    TaskHandle_t b=xTaskCreateStatic(fault_entry,"fault",512,NULL,2,fault_stack,&fault_tcb);
    TaskHandle_t c=NULL;
    if(xTaskCreate(worker,"suspended",256,NULL,1,&c)!=pdPASS || !c) done(0);
    vTaskSuspend(c);
    if(!xTaskCreateStatic(blocked,"blocked",512,NULL,1,blocked_stack,&blocked_tcb)) done(0);
    if (!a || !b || ck_freertos_track_static(&registry,a,"worker",worker_stack,512,1,1) ||
        ck_freertos_track_static(&registry,b,"fault",fault_stack,512,2,2)) done(0);
    text("FREERTOS_RV32_START\n"); vTaskStartScheduler(); done(0);
}
