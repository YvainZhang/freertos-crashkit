/* SPDX-License-Identifier: MIT */
#include "crashkit.h"
#include <stdatomic.h>

#define RECORD_HEADER 12u
#define TASK_BYTES 48u
static void zero(uint8_t *p, size_t n) { while (n--) *p++=0; }
static void copy(uint8_t *d, const uint8_t *s, size_t n) { while (n--) *d++=*s++; }
static void put16(uint8_t *p, uint16_t v) { p[0]=(uint8_t)v; p[1]=(uint8_t)(v>>8); }
static void put32(uint8_t *p, uint32_t v) {
    for (unsigned i=0;i<4;i++) p[i]=(uint8_t)(v>>(8*i));
}
static void put64(uint8_t *p, uint64_t v) {
    for (unsigned i=0;i<8;i++) p[i]=(uint8_t)(v>>(8*i));
}
static uint32_t crc_step(uint32_t crc, const uint8_t *p, size_t n) {
    while (n--) {
        crc^=*p++;
        for (unsigned i=0;i<8;i++) crc=(crc>>1)^(0xedb88320u & (0u-(crc & 1u)));
    }
    return crc;
}
uint32_t ck_crc32(const uint8_t *p, size_t n) { return ~crc_step(~0u,p,n); }

int ck_begin(struct ck_writer *w, uint8_t *b, size_t n, const struct ck_identity *id) {
    if (!w || !b || !id || n<CK_HEADER_SIZE+CK_FOOTER_SIZE || n>CK_MAX_DUMP_BYTES ||
        (id->pointer_bits!=32 && id->pointer_bits!=64) ||
        (id->source_endian!=1 && id->source_endian!=2) || id->architecture>CK_ARCH_CORTEX_M ||
        id->reason<CK_REASON_MANUAL || id->reason>CK_REASON_STACK_OVERFLOW ||
        (id->flags & ~(uint32_t)CK_FLAG_SYNTHETIC) ||
        (id->architecture!=CK_ARCH_GENERIC && id->pointer_bits!=32)) return CK_EINVAL;
    /* Clears a stale footer too. Cost is finite and included in the budget. */
    zero(b,n);
    w->buffer=b; w->capacity=n; w->used=CK_HEADER_SIZE;
    w->records=0; w->flags=id->flags; w->state=1;
    copy(b,(const uint8_t *)"CKIP",4);
    put16(b+4,CK_FORMAT_VERSION); put16(b+6,CK_HEADER_SIZE);
    put16(b+8,id->architecture); b[10]=id->pointer_bits; b[11]=id->source_endian;
    put32(b+12,id->reason); put32(b+16,w->flags);
    copy(b+20,id->firmware_id,16); put64(b+36,id->sequence);
    return CK_OK;
}
static int reserve(struct ck_writer *w, size_t n, uint8_t **p) {
    if (!w || w->state!=1) return CK_ESTATE;
    if (n>w->capacity-w->used-CK_FOOTER_SIZE ||
        RECORD_HEADER>w->capacity-w->used-CK_FOOTER_SIZE-n) {
        w->flags|=CK_FLAG_TRUNCATED;
        return CK_ENOSPACE;
    }
    *p=w->buffer+w->used+RECORD_HEADER;
    return CK_OK;
}
static void commit(struct ck_writer *w, uint16_t type, uint16_t flags, size_t n) {
    uint8_t *h=w->buffer+w->used;
    put16(h,type); put16(h+2,flags); put32(h+4,(uint32_t)n);
    put32(h+8,ck_crc32(h+RECORD_HEADER,n));
    w->used+=RECORD_HEADER+n; w->records++;
}
int ck_registers(struct ck_writer *w, const uint64_t *values, uint16_t n,
                 uint16_t bits, uint64_t mask) {
    uint8_t *p;
    if (!values || !n || n>CK_MAX_REGISTERS || (bits!=32 && bits!=64) ||
        (mask>>n)) return CK_EINVAL;
    for (uint16_t i=0;i<n;i++) if (bits==32 && values[i]>UINT32_MAX) return CK_EINVAL;
    int rc=reserve(w,12u+8u*n,&p); if (rc) return rc;
    put16(p,n); put16(p+2,bits); put64(p+4,mask);
    for (uint16_t i=0;i<n;i++) put64(p+12+8u*i,values[i]);
    commit(w,CK_REC_REGISTERS,0,12u+8u*n); return CK_OK;
}
int ck_memory(struct ck_writer *w, uint64_t address, uint32_t requested,
              ck_read_fn read, void *user) {
    uint8_t *p; uint32_t goal=requested, captured=0; uint16_t flags=0;
    if (!requested || !read || address>UINT64_MAX-requested) return CK_EINVAL;
    if (!w || w->state!=1) return CK_ESTATE;
    if (w->buffer[10]==32 && (address>UINT32_MAX || requested-1>UINT32_MAX-address)) return CK_EINVAL;
    if (goal>CK_MAX_REGION_BYTES) goal=CK_MAX_REGION_BYTES;
    size_t available=w->capacity-w->used-CK_FOOTER_SIZE;
    if (available<=RECORD_HEADER+20u) { w->flags|=CK_FLAG_TRUNCATED; return CK_ENOSPACE; }
    if (goal>available-RECORD_HEADER-20u) goal=(uint32_t)(available-RECORD_HEADER-20u);
    if (goal<requested) flags|=CK_FLAG_TRUNCATED;
    int rc=reserve(w,20u+goal,&p); if (rc) return rc;
    while (captured<goal) {
        size_t count=goal-captured; if (count>32) count=32;
        if (read(user,address+captured,p+20+captured,count)!=CK_OK) {
            flags|=CK_FLAG_READ_FAILED; break;
        }
        captured+=(uint32_t)count;
    }
    put64(p,address); put32(p+8,requested); put32(p+12,captured); put32(p+16,flags);
    w->flags|=flags; commit(w,CK_REC_MEMORY,flags,20u+captured);
    return (flags & CK_FLAG_READ_FAILED) ? CK_EREAD : CK_OK;
}
static void encode_task(uint8_t *p, const struct ck_task *task) {
    put64(p,task->handle); put64(p+8,task->generation); put64(p+16,task->stack_address);
    put32(p+24,task->stack_bytes); put32(p+28,task->priority);
    copy(p+32,(const uint8_t *)task->name,CK_TASK_NAME_BYTES);
}
static int valid_task(const struct ck_task *t) {
    return t && t->handle && t->generation && t->stack_bytes &&
        t->stack_address<=UINT64_MAX-t->stack_bytes && t->name[CK_TASK_NAME_BYTES-1]==0;
}
int ck_task_record(struct ck_writer *w, const struct ck_task *t) {
    uint8_t *p;
    if (!valid_task(t)) return CK_EINVAL;
    if (!w || w->state!=1) return CK_ESTATE;
    if (w->buffer[10]==32 && (t->handle>UINT32_MAX || t->stack_address>UINT32_MAX ||
        t->stack_bytes-1>UINT32_MAX-t->stack_address)) return CK_EINVAL;
    int rc=reserve(w,TASK_BYTES,&p); if (rc) return rc;
    encode_task(p,t); commit(w,CK_REC_TASK,0,TASK_BYTES); return CK_OK;
}
int ck_diagnostic(struct ck_writer *w, uint32_t code, uint32_t value) {
    uint8_t *p; int rc=reserve(w,8,&p); if (rc) return rc;
    put32(p,code); put32(p+4,value); commit(w,CK_REC_DIAGNOSTIC,0,8); return CK_OK;
}
int ck_finish(struct ck_writer *w, size_t *written) {
    if (!w || !written || w->state!=1) return CK_ESTATE;
    uint8_t *b=w->buffer, *f=b+w->used;
    put32(b+16,w->flags);
    /* CRCs use final magic while the visible header remains CKIP. */
    uint32_t crc=crc_step(~0u,(const uint8_t *)"CKD1",4);
    put32(b+44,~crc_step(crc,b+4,40));
    crc=crc_step(~0u,(const uint8_t *)"CKD1",4);
    crc=~crc_step(crc,b+4,w->used-4);
    copy(f,(const uint8_t *)"END!",4); put32(f+4,(uint32_t)(w->used+CK_FOOTER_SIZE));
    put32(f+8,w->records); put32(f+12,crc);
    atomic_signal_fence(memory_order_seq_cst);
    copy(b,(const uint8_t *)"CKD1",4); /* Completion marker last. BSP handles storage barriers. */
    w->used+=CK_FOOTER_SIZE; w->state=2; *written=w->used;
    return CK_OK;
}
void ck_registry_init(struct ck_registry *r) {
    if (r) zero((uint8_t *)r,sizeof(*r));
}
int ck_track(struct ck_registry *r, const struct ck_task *t) {
    if (!r || !valid_task(t)) return CK_EINVAL;
    struct ck_task_slot *slot=NULL;
    for (unsigned i=0;i<CK_MAX_TASKS;i++) {
        if (r->slots[i].state==2 && r->slots[i].task.handle==t->handle) return CK_ESTATE;
        if (!r->slots[i].state && !slot) slot=&r->slots[i];
    }
    if (!slot) {
        if (r->dropped_registrations!=UINT32_MAX) r->dropped_registrations++;
        return CK_ENOSPACE;
    }
    slot->state=1; atomic_signal_fence(memory_order_seq_cst);
    slot->task=*t;
    uint8_t bytes[TASK_BYTES]; encode_task(bytes,t); slot->checksum=ck_crc32(bytes,TASK_BYTES);
    atomic_signal_fence(memory_order_seq_cst); slot->state=2;
    return CK_OK;
}
int ck_untrack(struct ck_registry *r, uint64_t h, uint64_t g) {
    if (!r || !h || !g) return CK_EINVAL;
    for (unsigned i=0;i<CK_MAX_TASKS;i++) {
        struct ck_task_slot *s=&r->slots[i];
        if (s->state==2 && s->task.handle==h && s->task.generation==g) {
            s->state=0; return CK_OK;
        }
    }
    return CK_ENOTFOUND;
}
int ck_registry_capture(struct ck_writer *w, const struct ck_registry *r) {
    if (!w || w->state!=1) return CK_ESTATE;
    if (!r) return CK_EINVAL;
    if (r->dropped_registrations && ck_diagnostic(w,2,r->dropped_registrations)) return CK_ENOSPACE;
    for (unsigned i=0;i<CK_MAX_TASKS;i++) {
        const struct ck_task_slot *s=&r->slots[i];
        if (!s->state) continue;
        uint8_t bytes[TASK_BYTES]; encode_task(bytes,&s->task);
        if (s->state!=2 || !valid_task(&s->task) || ck_crc32(bytes,TASK_BYTES)!=s->checksum) {
            w->flags|=CK_FLAG_METADATA_BUSY;
            if (ck_diagnostic(w,1,i)) return CK_ENOSPACE;
            continue;
        }
        int rc=ck_task_record(w,&s->task); if (rc) return rc;
    }
    return CK_OK;
}
