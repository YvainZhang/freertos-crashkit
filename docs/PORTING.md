# Porting and public API

## Compatibility policy

0.1.0 supports source integration of the C11 core; it makes no binary ABI promise.
Public structs are caller-owned: initialize through the API and do not mutate writer
internals. A 0.x minor release may change source APIs with a changelog entry; patch
releases should not intentionally break them. Snapshot format v1 is independent
of the library version: incompatible encoding requires a new format version.
Unknown v1 record types are reported without interpreting their payload.

| Configuration | Validation |
| --- | --- |
| Host core/reader, generic 32/64 fields, endian tags | Unit tests; no CPU exception port implied |
| Single-hart RV32IMAC+Zicsr/Zifencei, ILP32, M-mode, QEMU virt, FreeRTOS V11.1.0 | Four injected fault cases |
| Physical RV32 SoC, reset/power-loss storage | Not validated |
| Cortex-M, RV64, SMP, FPU/vector state, other FreeRTOS versions | Not supported/validated in 0.1.0 |

## Integrating the core

Compile `src/crashkit.c` with `include/` using a C11 compiler. No FreeRTOS headers
are needed by the core. Inspect generated code for compiler-supplied helpers and
stack use; an optimization can lower loops to libc calls. The reference embedded
build uses `-ffreestanding -fno-builtin` and explicitly accounts for libgcc.

Allocate the writer, dump buffer and registry before any fault. Keep them in RAM
accessible after the supported fault. Buffers are 64..65536 bytes. Reserve capacity
for the 48-byte header, 16-byte footer and each record's 12-byte header. `ck_begin`
clears the entire buffer, so clearing and CRC work belong in the time budget.

| API | Contract |
| --- | --- |
| `ck_begin` | Start one snapshot with target profile, reason, flags, 16-byte build ID and caller sequence; initial flags may only be SYNTHETIC |
| `ck_registers` | 1..40 values encoded as u64, width 32/64, validity mask with no bits beyond count |
| `ck_memory` | Positive non-wrapping target range; at most 1024 bytes/record and 32 bytes/read callback |
| `ck_task_record` | Nonzero handle/generation/stack size, valid target range, name[15]=0; registration-time fields |
| `ck_diagnostic` | Fixed u32 code/value pair; custom codes should be documented by the integration |
| `ck_finish` | Finalize once and return exact written length; later appends/finish fail with ESTATE |
| `ck_track` / `ck_untrack` | Normal-context, externally serialized registry updates; handle+generation prevents stale deletion |
| `ck_registry_capture` | Fatal-context capture on a frozen single CPU; fixed 16 slots, checks state and metadata CRC |

Return values are `CK_OK`, `CK_EINVAL`, `CK_ENOSPACE`, `CK_ESTATE`, `CK_EREAD` and
`CK_ENOTFOUND`; consult the declaration for numeric values. Read failure can still
commit a partial memory record and set READ_FAILED. Capacity clipping can return
OK with TRUNCATED; inspect flags and captured/requested, not just the return code.
ENOSPACE leaves the footer reserved; if the writer remains active, finish the
degraded snapshot. Invalid input is a programming/configuration error to resolve.
Buffers, source arrays and registry memory must be valid and non-overlapping with
the destination being written; arbitrary caller memory corruption is outside the API.

## CPU entry and FreeRTOS adapter

Use the reference `ports/rv32/entry.S` only after reviewing your trap ownership.
It owns mtvec and mscratch. Save interrupted integer registers before C and before
using the interrupted stack; synchronous fatal exceptions use a dedicated 4KiB
stack. Interrupts and M-mode ecall delegate to the official FreeRTOS handler.
The delegated handler must not use mscratch. Nested capture calls the integration's
`ck_rv32_on_nested_fault` and cannot emit a completed snapshot. Fatal callbacks are
`_Noreturn`; reset/halt policy belongs to the BSP.

For the FreeRTOS adapter compile `ports/freertos/ck_freertos.c` with official kernel
headers. Enable static tasks and single-core operation. Initialize the registry;
after creating each static task, call `ck_freertos_track_static` before its first
execution (for example before starting the scheduler). Preserve the stack's full
allocation range and a nonzero generation. Untrack in normal context **before**
deleting/reusing task resources. Do not use these critical-section APIs in a fault
or ISR. Dynamic tasks, idle task enumeration and automatic priority/name updates
are intentionally not implemented.

## BSP and artifact identity

The reader callback must validate each whole address range against known readable
RAM, reject wraparound/MMIO and return finitely. Whitelisted damaged RAM can still
fault: the nested-abort path must remain usable. Output has a finite byte/time
budget; never call normal printf/logger/heap/scheduler services from fatal capture.
The QEMU BSP uses bounded polling UART and a test finisher. It does not prove
durability, device timing, watchdog behavior or recovery across a reset.

Use a trusted build pipeline to put the same nonzero 16-byte firmware ID in the
snapshot identity and one ELF `.crashkit_id` section. The example hashes source,
compiler, flags, case and libgcc into the ID and retains the ELF mapping. All-zero
means unspecified (host demo), so it cannot establish an ELF match. Supply the
original ELF to `tools/analyze.py --elf`; without it the report says `not_checked`.
CRC/ID equality are not authentication. Store exactly `written` bytes: trailing
buffer padding is rejected. A compiler completion fence is not a storage barrier.

Real-board acceptance must independently test exception
entry, corrupted SP, timing/budget, nested fault and storage/reset behavior.
