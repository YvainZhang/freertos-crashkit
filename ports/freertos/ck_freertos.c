/* SPDX-License-Identifier: MIT */
#include "ck_freertos.h"
int ck_freertos_track_static(struct ck_registry *r, TaskHandle_t h, const char *name,
                            StackType_t *stack, size_t words, UBaseType_t priority,
                            uint64_t generation) {
    if (!r || !h || !name || !stack || !words || words>UINT32_MAX/sizeof(StackType_t)) return CK_EINVAL;
    struct ck_task task={0};
    task.handle=(uintptr_t)h; task.generation=generation; task.stack_address=(uintptr_t)stack;
    task.stack_bytes=(uint32_t)(words*sizeof(StackType_t)); task.priority=(uint32_t)priority;
    for (unsigned i=0;i<CK_TASK_NAME_BYTES-1 && name[i];i++) task.name[i]=name[i];
    taskENTER_CRITICAL(); int rc=ck_track(r,&task); taskEXIT_CRITICAL();
    return rc;
}
int ck_freertos_untrack(struct ck_registry *r, TaskHandle_t h, uint64_t generation) {
    taskENTER_CRITICAL(); int rc=ck_untrack(r,(uintptr_t)h,generation); taskEXIT_CRITICAL();
    return rc;
}
