/* SPDX-License-Identifier: MIT */
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H
#include <stdint.h>
void ck_example_assert(unsigned line);
#define configCPU_CLOCK_HZ 10000000u
#define configMTIME_BASE_ADDRESS 0x0200bff8u
#define configMTIMECMP_BASE_ADDRESS 0x02004000u
#define configTICK_RATE_HZ 1000u
#define configUSE_PREEMPTION 1
#define configUSE_TIME_SLICING 1
#define configMAX_PRIORITIES 4
#define configMINIMAL_STACK_SIZE 256
#define configMAX_TASK_NAME_LEN 16
#define configUSE_16_BIT_TICKS 0
#define configUSE_IDLE_HOOK 0
#define configUSE_TICK_HOOK 1
#define configUSE_MUTEXES 1
#define configUSE_COUNTING_SEMAPHORES 1
#define configUSE_TIMERS 1
#define configTIMER_TASK_PRIORITY 1
#define configTIMER_QUEUE_LENGTH 8
#define configTIMER_TASK_STACK_DEPTH 512
#define configTOTAL_HEAP_SIZE 16384
#define configSUPPORT_STATIC_ALLOCATION 1
#define configSUPPORT_DYNAMIC_ALLOCATION 1
#define configUSE_TRACE_FACILITY 1
#define configRECORD_STACK_HIGH_ADDRESS 1
#define configINCLUDE_FREERTOS_TASK_C_ADDITIONS_H 1
#define configGENERATE_RUN_TIME_STATS 0
#define configCHECK_FOR_STACK_OVERFLOW 2
#define INCLUDE_vTaskDelay 1
#define INCLUDE_vTaskDelete 1
#define INCLUDE_vTaskSuspend 1
#define INCLUDE_xTaskGetCurrentTaskHandle 1
#define INCLUDE_xSemaphoreGetMutexHolder 1
#define configASSERT(x) do { if (!(x)) ck_example_assert(__LINE__); } while (0)
#endif
