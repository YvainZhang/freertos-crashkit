# Changelog

## 0.2.0 — experimental development candidate

- Add UART/raw-RAM import, kernel-layout task reconstruction and RV32 saved
  contexts, bounded frame-chain unwind, symbols and optional source locations.
- Add loopback GDB server, task threads, DWARF inspection, writable analysis copy,
  original RV32 virtual execution, scratch stack and ELF-only helper calls/reset.
- Add DWARF-derived object plugins for queues/waiters, semaphores/mutexes,
  event groups, streams, timers and heap_4; bounded event history and register/clock profiles.
- Capture selected application/kernel RAM and IRQ stack, with separate assert
  and real kernel stack-canary-hook cases, with separate IRQ/task context attribution
  and a real timer-ISR fault scenario.
- Raise the v1 parser/core size ceiling to 4MiB; reference dump capacity stays
  64KiB. Encoding is unchanged; 0.1 readers still reject inputs over 64KiB.
- Add actual-GDB and damaged-state acceptance plus CI configuration. Check
  GitHub Actions for the exact commit's result; a tagged Release is separate.

## 0.1.0 — initial experimental release candidate

- Original bounded C11 encoder and task registry; format v1 with explicit field
  encoding, CRCs and incomplete/complete markers.
- Public-API FreeRTOS static-task adapter; single-hart RV32 M-mode exception port
  with an independent fault stack and explicit nested-fault abort.
- QEMU virt example using pinned official FreeRTOS V11.1.0; illegal instruction,
  bad SP, load fault and nested fault checks.
- Bounded offline reader, ELF firmware-ID checks and JSON/HTML reports.
- Host library/demo, corruption tests, sanitizer checks, English integration
  contracts, Chinese quick start, CI workflow and deterministic source packaging.

This version does not include real-board validation, persistence, full task-state
enumeration, automatic stack unwinding or additional validated CPU ports.
Candidate source is public on main; host GCC/Clang and RV32 GitHub CI have passed.
The initial runner write-permission failure was fixed by running the build
container as the checkout owner's UID/GID. A version tag and Release are not yet
published; current evidence and publication state are in [RELEASING](docs/RELEASING.md).
