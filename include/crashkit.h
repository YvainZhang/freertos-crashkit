/* SPDX-License-Identifier: MIT */
#ifndef CRASHKIT_H
#define CRASHKIT_H
#include <stddef.h>
#include <stdint.h>

#define CK_VERSION_MAJOR 0u
#define CK_VERSION_MINOR 2u
#define CK_VERSION_PATCH 0u
#define CK_VERSION_STRING "0.2.0"
#define CK_FORMAT_VERSION 1u
#define CK_HEADER_SIZE 48u
#define CK_FOOTER_SIZE 16u
#define CK_MAX_DUMP_BYTES 4194304u
#define CK_MAX_REGISTERS 40u
#define CK_MAX_REGION_BYTES 1024u
#define CK_MAX_TASKS 16u
#define CK_TASK_NAME_BYTES 16u

enum ck_error { CK_OK=0, CK_EINVAL=-1, CK_ENOSPACE=-2, CK_ESTATE=-3,
                CK_EREAD=-4, CK_ENOTFOUND=-5 };
enum ck_arch { CK_ARCH_GENERIC=0, CK_ARCH_RV32=1, CK_ARCH_CORTEX_M=2 };
enum ck_reason { CK_REASON_MANUAL=1, CK_REASON_ASSERT=2,
                 CK_REASON_CPU_FAULT=3, CK_REASON_STACK_OVERFLOW=4 };
enum ck_record_type { CK_REC_REGISTERS=1, CK_REC_MEMORY=2,
                      CK_REC_TASK=3, CK_REC_DIAGNOSTIC=4 };
enum ck_flag { CK_FLAG_TRUNCATED=1, CK_FLAG_READ_FAILED=2,
               CK_FLAG_METADATA_BUSY=4, CK_FLAG_SYNTHETIC=8 };

struct ck_identity {
    uint16_t architecture;
    uint8_t pointer_bits; /* 32 or 64; source endian: 1=little, 2=big. */
    uint8_t source_endian;
    uint32_t reason;
    uint32_t flags;
    uint8_t firmware_id[16]; /* Exact identity emitted by the build pipeline. */
    uint64_t sequence;
};
struct ck_writer {
    uint8_t *buffer;
    size_t capacity, used;
    uint32_t records, flags;
    uint8_t state;
};
struct ck_task {
    uint64_t handle, generation, stack_address;
    uint32_t stack_bytes, priority;
    char name[CK_TASK_NAME_BYTES];
};
struct ck_task_slot {
    volatile uint32_t state; /* 0=empty, 1=updating, 2=committed. */
    uint32_t checksum;
    struct ck_task task;
};
struct ck_registry {
    struct ck_task_slot slots[CK_MAX_TASKS];
    uint32_t dropped_registrations;
};

/* Readers must fail finitely; whitelist validation is the caller's duty.
 * A reader cannot turn arbitrary MMIO/broken RAM into a safe access. */
typedef int (*ck_read_fn)(void *user, uint64_t address, uint8_t *dst, size_t count);

uint32_t ck_crc32(const uint8_t *data, size_t size);
int ck_begin(struct ck_writer *, uint8_t *, size_t, const struct ck_identity *);
int ck_registers(struct ck_writer *, const uint64_t *, uint16_t count,
                 uint16_t register_bits, uint64_t valid_mask);
int ck_memory(struct ck_writer *, uint64_t address, uint32_t requested,
              ck_read_fn, void *user);
int ck_task_record(struct ck_writer *, const struct ck_task *);
int ck_diagnostic(struct ck_writer *, uint32_t code, uint32_t value);
int ck_finish(struct ck_writer *, size_t *written);

/* Normal-context registry updates must be externally serialized. Fatal capture
 * requires a frozen SINGLE CPU. No locks, heap, scheduler calls or traversal of
 * FreeRTOS private lists take place here. Metadata describes registration time. */
void ck_registry_init(struct ck_registry *);
int ck_track(struct ck_registry *, const struct ck_task *);
int ck_untrack(struct ck_registry *, uint64_t handle, uint64_t generation);
int ck_registry_capture(struct ck_writer *, const struct ck_registry *);
#endif
