/* SPDX-License-Identifier: MIT */
#include "crashkit.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint8_t output[4096], ram[128];
static struct ck_registry registry;
static struct ck_identity identity={CK_ARCH_RV32,32,1,CK_REASON_MANUAL,CK_FLAG_SYNTHETIC,{1,2,3},1};
struct source { unsigned calls; int fail; };
static int read_memory(void *u, uint64_t address, uint8_t *p, size_t n) {
    struct source *s=u; s->calls++;
    if (s->fail && s->calls==2) return CK_EREAD;
    if (address<0x80000000 || address-0x80000000>sizeof(ram) || n>sizeof(ram)-(address-0x80000000)) return CK_EREAD;
    memcpy(p,ram+(address-0x80000000),n); return CK_OK;
}
static void save(const char *name, const uint8_t *p, size_t n) {
    char path[128]; snprintf(path,sizeof(path),"build/%s.bin",name);
    FILE *f=fopen(path,"wb"); assert(f); assert(fwrite(p,1,n,f)==n); assert(fclose(f)==0);
}
int main(void) {
    struct ck_writer w; size_t n; struct source s={0};
    for (unsigned i=0;i<sizeof(ram);i++) ram[i]=(uint8_t)i;
    assert(ck_crc32((const uint8_t *)"123456789",9)==0xcbf43926u);
    assert(ck_begin(&w,output,63,&identity)==CK_EINVAL);
    assert(ck_begin(&w,output,sizeof(output),&identity)==CK_OK);
    assert(ck_finish(&w,&n)==CK_OK && n==64);
    assert(ck_finish(&w,&n)==CK_ESTATE); save("empty",output,n);
    assert(ck_begin(&w,output,sizeof(output),&identity)==CK_OK);
    uint64_t regs[]={0,0x80000010,0x80004000,0x80000044};
    assert(ck_registers(&w,regs,4,32,15)==CK_OK);
    assert(ck_registers(&w,regs,4,32,16)==CK_EINVAL);
    assert(ck_memory(&w,UINT64_MAX-1,4,read_memory,&s)==CK_EINVAL);
    assert(ck_memory(&w,UINT32_MAX-1,4,read_memory,&s)==CK_EINVAL);
    ck_registry_init(&registry);
    struct ck_task task={0x80005000,1,0x80000000,128,2,"wifi_worker"};
    assert(ck_track(&registry,&task)==CK_OK);
    assert(ck_track(&registry,&task)==CK_ESTATE);
    assert(ck_untrack(&registry,task.handle,2)==CK_ENOTFOUND);
    assert(ck_registry_capture(&w,&registry)==CK_OK);
    assert(ck_memory(&w,0x80000000,128,read_memory,&s)==CK_OK && s.calls==4);
    assert(ck_finish(&w,&n)==CK_OK); save("valid",output,n);
    assert(ck_begin(&w,output,sizeof(output),&identity)==CK_OK);
    registry.slots[0].task.stack_bytes^=1; /* Simulated corrupt metadata. */
    assert(ck_registry_capture(&w,&registry)==CK_OK);
    s.calls=0; s.fail=1;
    assert(ck_memory(&w,0x80000000,128,read_memory,&s)==CK_EREAD && s.calls==2);
    assert(ck_finish(&w,&n)==CK_OK); save("degraded",output,n);
    assert(w.flags==(CK_FLAG_SYNTHETIC|CK_FLAG_METADATA_BUSY|CK_FLAG_READ_FAILED));
    ck_registry_init(&registry);
    for (unsigned i=0;i<CK_MAX_TASKS;i++) {task.handle=i+1; assert(ck_track(&registry,&task)==CK_OK);}
    task.handle=99; assert(ck_track(&registry,&task)==CK_ENOSPACE && registry.dropped_registrations==1);
    assert(ck_untrack(&registry,1,1)==CK_OK); task.generation=2; task.handle=1;
    assert(ck_track(&registry,&task)==CK_OK); assert(ck_untrack(&registry,1,1)==CK_ENOTFOUND);
    assert(ck_untrack(&registry,1,2)==CK_OK);
    registry.slots[1].state=1;
    assert(ck_begin(&w,output,sizeof(output),&identity)==CK_OK);
    assert(ck_registry_capture(&w,&registry)==CK_OK && (w.flags & CK_FLAG_METADATA_BUSY));
    assert(ck_finish(&w,&n)==CK_OK); save("registry",output,n);
    assert(ck_begin(&w,output,120,&identity)==CK_OK);
    s.fail=0; s.calls=0;
    assert(ck_memory(&w,0x80000000,128,read_memory,&s)==CK_OK && s.calls==1);
    assert(ck_diagnostic(&w,9,9)==CK_ENOSPACE);
    assert(ck_finish(&w,&n)==CK_OK && n==120 && (w.flags & CK_FLAG_TRUNCATED)); save("bounded",output,n);
    assert(ck_begin(&w,output,sizeof(output),&identity)==CK_OK);
    assert(ck_memory(&w,0x80000000,128,read_memory,&s)==CK_OK); /* No finish: must reject. */
    save("interrupted",output,w.used);
    identity.architecture=CK_ARCH_GENERIC; identity.pointer_bits=64; identity.source_endian=2;
    assert(ck_begin(&w,output,sizeof(output),&identity)==CK_OK);
    task.handle=0x100000001ULL; task.stack_address=0x100000100ULL;
    assert(ck_task_record(&w,&task)==CK_OK);
    regs[1]=0x123456789abcdef0ULL;
    assert(ck_registers(&w,regs,4,64,15)==CK_OK);
    assert(ck_finish(&w,&n)==CK_OK); save("generic64",output,n);
    printf("CORE_PASS writer=%zu registry=%zu max_dump=%u\n",sizeof(w),sizeof(registry),CK_MAX_DUMP_BYTES);
    return 0;
}
