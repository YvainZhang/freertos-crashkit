/* SPDX-License-Identifier: MIT */
#ifndef CRASHKIT_TRACE_H
#define CRASHKIT_TRACE_H
#include <stdint.h>
#define CK_TRACE_SLOTS 16u
struct ck_trace_entry { volatile uint32_t state; uint32_t sequence, tick, tag, value, crc; };
struct ck_trace_ring { uint32_t magic, sequence; struct ck_trace_entry entries[CK_TRACE_SLOTS]; };
/* Normal-context only; caller serializes producers. No allocator or OS calls.
 * tick is caller supplied, not an elapsed wall-clock time. */
void ck_trace_init(struct ck_trace_ring *);
int ck_trace_write(struct ck_trace_ring *,uint32_t tick,uint32_t tag,uint32_t value);
#endif
