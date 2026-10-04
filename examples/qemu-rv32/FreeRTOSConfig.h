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
#define configUSE_TICK_HOOK 0
#define configUSE_MUTEXES 0
#define configUSE_TIMERS 0
#define configSUPPORT_STATIC_ALLOCATION 1
#define configSUPPORT_DYNAMIC_ALLOCATION 0
#define configUSE_TRACE_FACILITY 0
#define configGENERATE_RUN_TIME_STATS 0
#define configCHECK_FOR_STACK_OVERFLOW 0
#define INCLUDE_vTaskDelay 1
#define INCLUDE_vTaskDelete 1
#define configASSERT(x) do { if (!(x)) ck_example_assert(__LINE__); } while (0)
#endif
