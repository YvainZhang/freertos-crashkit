/* SPDX-License-Identifier: MIT */
/* Opt-in FreeRTOS V11.1.0 single-core layout and ELF-only analysis helpers.
 * Included by the official additions hook; never patch upstream tasks.c.
 * No function in this file may be called by the device application. */
#include <stddef.h>
#include <stdint.h>
#include "queue.h"
#include "semphr.h"
#include "event_groups.h"
#include "stream_buffer.h"
#include "timers.h"

#if configNUMBER_OF_CORES != 1 || configRECORD_STACK_HIGH_ADDRESS != 1
#error "CrashKit offline layout requires a single CPU and stack end addresses"
#endif

#if INCLUDE_vTaskSuspend == 1
#define CK_SUSPENDED_ADDRESS ((uint32_t)(uintptr_t)&xSuspendedTaskList)
#else
#define CK_SUSPENDED_ADDRESS 0u
#endif
#if INCLUDE_vTaskDelete == 1
#define CK_DELETED_ADDRESS ((uint32_t)(uintptr_t)&xTasksWaitingTermination)
#else
#define CK_DELETED_ADDRESS 0u
#endif

/* Explicit u32 table, version 1; addresses/offsets belong to this exact ELF.
 * The host checks the firmware identity before interpreting this table. */
__attribute__((used,section(".crashkit_layout")))
const uint32_t ck_freertos_layout[] = {
    0x314c4b43u, 1u, sizeof(void *), sizeof(StackType_t),
    tskKERNEL_VERSION_MAJOR, tskKERNEL_VERSION_MINOR, tskKERNEL_VERSION_BUILD,
    (uint32_t)(uintptr_t)&pxCurrentTCB, (uint32_t)(uintptr_t)&uxCurrentNumberOfTasks,
    (uint32_t)(uintptr_t)&xTickCount, (uint32_t)(uintptr_t)&xSchedulerRunning,
    (uint32_t)(uintptr_t)pxReadyTasksLists, sizeof(List_t), configMAX_PRIORITIES,
    (uint32_t)(uintptr_t)&xDelayedTaskList1, (uint32_t)(uintptr_t)&xDelayedTaskList2,
    CK_SUSPENDED_ADDRESS, CK_DELETED_ADDRESS, (uint32_t)(uintptr_t)&xPendingReadyList,
    sizeof(TCB_t), offsetof(TCB_t,pxTopOfStack), offsetof(TCB_t,xStateListItem),
    offsetof(TCB_t,xEventListItem), offsetof(TCB_t,uxPriority), offsetof(TCB_t,pxStack),
    offsetof(TCB_t,pcTaskName), configMAX_TASK_NAME_LEN, offsetof(TCB_t,pxEndOfStack),
    offsetof(List_t,uxNumberOfItems), offsetof(List_t,xListEnd),
    offsetof(ListItem_t,pxNext), offsetof(ListItem_t,pxPrevious),
    offsetof(ListItem_t,pvOwner), offsetof(ListItem_t,pxContainer),
    sizeof(ListItem_t), portSTACK_GROWTH == -1 ? 1u : 0u,
    1u /* Context profile: official RV32 integer port, 31 words, no extensions. */
};

#define CK_DEBUG __attribute__((used,noinline,section(".crashkit_debug")))
#define CK_DEBUG_DATA __attribute__((used,section(".crashkit_debug_rodata")))
static const char ck_sys_label[] CK_DEBUG_DATA = "system tick=";
static const char ck_tasks_label[] CK_DEBUG_DATA = " tasks=";
static const char ck_scheduler_label[] CK_DEBUG_DATA = " scheduler=";
static const char ck_current_label[] CK_DEBUG_DATA = " current=";
static const char ck_priority_label[] CK_DEBUG_DATA = " priority=";
static const char ck_stack_label[] CK_DEBUG_DATA = " stack_free_words=";
static const char ck_ready_label[] CK_DEBUG_DATA = " Ready ";
static const char ck_running_label[] CK_DEBUG_DATA = " Running ";
static const char ck_blocked_label[] CK_DEBUG_DATA = " Blocked ";
static const char ck_suspended_label[] CK_DEBUG_DATA = " Suspended ";
static const char ck_deleted_label[] CK_DEBUG_DATA = " Deleted ";
static const char ck_limit_label[] CK_DEBUG_DATA = "[task limit or damaged list]\n";

static CK_DEBUG void ck_debug_char(unsigned c) {
    register unsigned a0 __asm__("a0")=c;
    register unsigned a7 __asm__("a7")=0x434bu;
    __asm__ volatile("ecall" : "+r"(a0) : "r"(a7) : "memory");
}
static CK_DEBUG void ck_debug_text(const char *s) {
    for (unsigned i=0;i<128 && s[i];i++) ck_debug_char((unsigned char)s[i]);
}
static CK_DEBUG void ck_debug_number(uint32_t n) {
    char digits[10]; unsigned count=0;
    do { digits[count++]=(char)('0'+n%10u); n/=10u; } while(n && count<10);
    while(count) ck_debug_char((unsigned)digits[--count]);
}
CK_DEBUG unsigned ck_debug_system(void) {
    ck_debug_text(ck_sys_label); ck_debug_number((uint32_t)xTickCount);
    ck_debug_text(ck_tasks_label); ck_debug_number((uint32_t)uxCurrentNumberOfTasks);
    ck_debug_text(ck_scheduler_label); ck_debug_number((uint32_t)xSchedulerRunning);
    ck_debug_text(ck_current_label);
    if(pxCurrentTCB) ck_debug_text(pxCurrentTCB->pcTaskName);
    ck_debug_char('\n'); return (unsigned)uxCurrentNumberOfTasks;
}
static CK_DEBUG unsigned ck_debug_list(List_t *list, const char *state, unsigned budget) {
    ListItem_t *end=(ListItem_t *)&list->xListEnd, *item=list->xListEnd.pxNext;
    unsigned seen=0;
    while(item!=end && seen<budget) {
        TCB_t *t=(TCB_t *)item->pvOwner;
        const char *actual=state;
        if(state==ck_suspended_label && t->xEventListItem.pxContainer) actual=ck_blocked_label;
        ck_debug_text(t->pcTaskName); ck_debug_text(t==pxCurrentTCB ? ck_running_label : actual);
        ck_debug_text(ck_priority_label); ck_debug_number((uint32_t)t->uxPriority);
        ck_debug_text(ck_stack_label);
        unsigned words=0;
        const uint8_t *p=(const uint8_t *)t->pxStack;
        uintptr_t stop=(uintptr_t)t->pxEndOfStack+sizeof(StackType_t);
        /* Host execution only, bounded scan; missing RAM aborts explicitly. */
        while((uintptr_t)p<stop && words<65536u && *p==tskSTACK_FILL_BYTE) {p++; words++;}
        ck_debug_number(words/sizeof(StackType_t)); ck_debug_char('\n');
        item=item->pxNext; seen++;
    }
    if(item!=end) ck_debug_text(ck_limit_label);
    return seen;
}
CK_DEBUG unsigned ck_debug_tasks(void) {
    unsigned count=0;
    for(unsigned i=0;i<configMAX_PRIORITIES && count<16;i++)
        count+=ck_debug_list(&pxReadyTasksLists[i],ck_ready_label,16-count);
    if(count<16) count+=ck_debug_list(&xDelayedTaskList1,ck_blocked_label,16-count);
    if(count<16) count+=ck_debug_list(&xDelayedTaskList2,ck_blocked_label,16-count);
#if INCLUDE_vTaskSuspend == 1
    if(count<16) count+=ck_debug_list(&xSuspendedTaskList,ck_suspended_label,16-count);
#endif
#if INCLUDE_vTaskDelete == 1
    if(count<16) count+=ck_debug_list(&xTasksWaitingTermination,ck_deleted_label,16-count);
#endif
    return count;
}

static const char ck_count_label[] CK_DEBUG_DATA = " count=";
static const char ck_spaces_label[] CK_DEBUG_DATA = " spaces=";
static const char ck_bits_label[] CK_DEBUG_DATA = " bits=";
static const char ck_period_label[] CK_DEBUG_DATA = " period=";
static const char ck_expiry_label[] CK_DEBUG_DATA = " expiry=";
static const char ck_heap_label[] CK_DEBUG_DATA = "heap free=";
static const char ck_min_label[] CK_DEBUG_DATA = " minimum=";
static const char ck_blocks_label[] CK_DEBUG_DATA = " blocks=";
CK_DEBUG unsigned ck_debug_queue(QueueHandle_t q) {
    unsigned n=(unsigned)uxQueueMessagesWaiting(q);
    ck_debug_text(ck_count_label); ck_debug_number(n);
    ck_debug_text(ck_spaces_label); ck_debug_number((unsigned)uxQueueSpacesAvailable(q));
    ck_debug_char('\n'); return n;
}
CK_DEBUG unsigned ck_debug_semaphore(SemaphoreHandle_t q) {return ck_debug_queue(q);}
CK_DEBUG unsigned ck_debug_eventgroup(EventGroupHandle_t g) {
    unsigned bits=(unsigned)xEventGroupGetBitsFromISR(g);
    ck_debug_text(ck_bits_label); ck_debug_number(bits); ck_debug_char('\n');return bits;
}
CK_DEBUG unsigned ck_debug_streambuffer(StreamBufferHandle_t s) {
    unsigned n=(unsigned)xStreamBufferBytesAvailable(s);
    ck_debug_text(ck_count_label); ck_debug_number(n);
    ck_debug_text(ck_spaces_label); ck_debug_number((unsigned)xStreamBufferSpacesAvailable(s));
    ck_debug_char('\n');return n;
}
CK_DEBUG unsigned ck_debug_timer(TimerHandle_t t) {
    unsigned period=(unsigned)xTimerGetPeriod(t);
    ck_debug_text(pcTimerGetName(t)); ck_debug_text(ck_period_label); ck_debug_number(period);
    ck_debug_text(ck_expiry_label); ck_debug_number((unsigned)xTimerGetExpiryTime(t));
    ck_debug_char('\n'); return period;
}
CK_DEBUG unsigned ck_debug_heap(void) {
    HeapStats_t stats; vPortGetHeapStats(&stats);
    ck_debug_text(ck_heap_label); ck_debug_number((uint32_t)stats.xAvailableHeapSpaceInBytes);
    ck_debug_text(ck_min_label); ck_debug_number((uint32_t)stats.xMinimumEverFreeBytesRemaining);
    ck_debug_text(ck_blocks_label); ck_debug_number((uint32_t)stats.xNumberOfFreeBlocks);
    ck_debug_char('\n'); return (unsigned)stats.xAvailableHeapSpaceInBytes;
}
