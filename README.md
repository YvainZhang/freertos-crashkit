# FreeRTOS CrashKit

[中文入门](README.zh-CN.md) · [Porting and API](docs/PORTING.md) · [Format v1](docs/FORMAT.md) · [Release guide](docs/RELEASING.md)

An independent, MIT-licensed crash-capture component for resource-constrained
FreeRTOS systems. It separates a bounded C encoder, CPU exception entry, OS task
registration, board-specific memory access and an offline Python reader.
Official FreeRTOS is fetched separately; no vendor SDK or kernel patch is required.

**0.1.0 is experimental.** The reference integration is validated on **single-hart
RV32 M-mode, QEMU virt, FreeRTOS V11.1.0**. Real boards and persistent storage are
not validated. This repository provides captured evidence, not automatic root
cause diagnosis or a debugger.

## Try it on your host

Requirements: C11 compiler, `ar`, Make and Python 3.9+. No Python packages required.

```sh
make verify       # static library, C/Python tests, synthetic demo, local doc links
make sanitize     # C tests under AddressSanitizer and UndefinedBehaviorSanitizer
make demo         # build/demo.bin, demo.json, demo.html
```

The host demo is explicitly **synthetic**, has no firmware identity and uses
normal-context file I/O. It does not test exception capture. Integrate the core
by compiling `src/crashkit.c` and adding `include/`; `make all` produces a host
static library as an integration example, not an embedded cross-compiled binary.

## Run actual exception tests in QEMU

Install Docker and `qemu-system-riscv32` on the host, then run from the repo root:

```sh
python3 scripts/fetch-freertos.py
docker build -f scripts/Dockerfile.rv32 -t freertos-crashkit-rv32:bookworm .
docker run --rm --user "$(id -u):$(id -g)" --network none --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 512m -v "$PWD:/work" -w /work freertos-crashkit-rv32:bookworm python3 scripts/build-rv32.py
make qemu-test
python3 tools/analyze.py evidence/qemu-rv32/1.bin --elf build/rv32/1/firmware.elf --json build/report.json --html build/report.html
```

Alternatively install the Debian cross-toolchain listed in
[third-party notices](THIRD_PARTY_NOTICES.md) and use `make rv32-build` directly.
The fetcher verifies the pinned official archive; `--archive path` supports
offline reuse. QEMU runs without a NIC. Tests check timer/ecall delegation, fault
PC/cause, original registers, bad stack pointer, nested capture abort and wrong
ELF rejection. Timeouts and arbitrary crashes fail the test. The container uses
the checkout owner's UID/GID so it can write the mounted tree without root
capabilities on Linux; keep generated files writable by that owner.

## What is included

| Area | 0.1.0 behavior |
| --- | --- |
| Core | C11, fixed buffers, explicit little-endian format, per-record and whole-dump CRC |
| Task metadata | Explicit static-task registration through public FreeRTOS APIs; bounded 16 slots |
| CPU entry | RV32IMAC+Zicsr/Zifencei, own fault stack, integer registers and four CSRs |
| Reader | Strict bounded parsing, firmware-ID comparison with ELF, JSON and escaped HTML |
| Evidence | Tests generate logs, manifests and snapshots locally; source packages omit generated data |

Fatal capture uses no heap, normal logging lock or scheduler API. RAM reads still
depend on a trusted BSP whitelist. Task metadata describes **registration time**,
not fault-time Ready/Blocked state, high-water marks or a complete task list.
No automatic backtrace, dynamic-task lifecycle tracking, assert/overflow entry,
SMP, RV64, floating/vector registers or reset/power-loss persistence is included.
Cortex-M and generic-64 format fixtures are not validated CPU ports.

CRC detects accidental damage; it does not authenticate a dump. Firmware-ID
matching relies on a trusted build/artifact mapping, not a cryptographic signature.
The source API may change in 0.x; format v1 remains explicitly versioned. See
[compatibility](docs/PORTING.md) before embedding it.

## Repository and contribution

`include/`, `src/`: core API and encoder; `ports/`: CPU/OS integration;
`examples/`: synthetic host demo and QEMU BSP; `tools/`: offline reader;
`tests/`: correctness/rejection tests; `scripts/`: build and packaging;
`docs/`: public contracts and public integration documentation.
`build/`, `third_party/` and generated `evidence/` are not source deliverables.

See [CONTRIBUTING](CONTRIBUTING.md), [SECURITY](SECURITY.md),
[changelog](CHANGELOG.md) and [license](LICENSE).
FreeRTOS and external tool licenses are described in
[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md).
