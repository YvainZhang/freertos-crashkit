/* SPDX-License-Identifier: MIT */
#ifndef CK_FREERTOS_H
#define CK_FREERTOS_H
#include "crashkit.h"
#include "FreeRTOS.h"
#include "task.h"
#if configNUMBER_OF_CORES != 1
#error "CrashKit v0.1 requires a single-core freeze contract; SMP is unsupported"
#endif
/* NORMAL context only. Track static-task stack allocation explicitly. Priority
 * is registration-time metadata, not the fault-time scheduler state. This adapter
 * does not alter tasks.c or depend on private TCB field offsets. */
int ck_freertos_track_static(struct ck_registry *registry, TaskHandle_t handle,
                            const char *name, StackType_t *stack, size_t words,
                            UBaseType_t priority, uint64_t generation);
int ck_freertos_untrack(struct ck_registry *, TaskHandle_t, uint64_t generation);
#endif
