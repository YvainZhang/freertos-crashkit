# Changelog

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
