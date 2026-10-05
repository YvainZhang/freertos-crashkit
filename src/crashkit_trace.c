/* SPDX-License-Identifier: MIT */
#include "crashkit_trace.h"
#include "crashkit.h"
#include <stdatomic.h>
void ck_trace_init(struct ck_trace_ring *ring) {
    if(!ring) return;
    ring->magic=0x31544b43u; ring->sequence=0;
    for(unsigned i=0;i<CK_TRACE_SLOTS;i++) ring->entries[i].state=0;
}
int ck_trace_write(struct ck_trace_ring *ring,uint32_t tick,uint32_t tag,uint32_t value) {
    if(!ring || ring->magic!=0x31544b43u || ring->sequence==UINT32_MAX) return CK_EINVAL;
    uint32_t sequence=ring->sequence+1;
    struct ck_trace_entry *e=&ring->entries[(sequence-1)%CK_TRACE_SLOTS];
    e->state=1; atomic_signal_fence(memory_order_seq_cst);
    e->sequence=sequence; e->tick=tick; e->tag=tag; e->value=value;
    /* Table profile is explicitly RV32 little endian in the reference port. */
    e->crc=ck_crc32((const uint8_t *)&e->sequence,16);
    atomic_signal_fence(memory_order_seq_cst); e->state=2;
    ring->sequence=sequence; return CK_OK;
}
