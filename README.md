# FreeRTOS CrashKit

[中文入门](README.zh-CN.md) · [Porting and API](docs/PORTING.md) · [Format v1](docs/FORMAT.md) · [Offline debugging](docs/DEBUGGING.md) · [Release guide](docs/RELEASING.md)

An independent, MIT-licensed crash-capture and post-mortem debugging toolkit for
FreeRTOS. It separates a bounded C encoder, CPU entry, OS/BSP integration, frozen
kernel/object analysis, a GDB remote server and a bounded RV32 analysis interpreter.
Official FreeRTOS is fetched separately; no vendor SDK or kernel patch is required.

**0.2.0 is an experimental development candidate.** The reference integration
targets **single-hart RV32 M-mode, QEMU virt, FreeRTOS V11.1.0**. Check
[GitHub Actions](https://github.com/YvainZhang/freertos-crashkit/actions) for the
exact commit's CI results; source publication does not imply a tagged Release.
Real boards and persistent storage are not validated. Reports expose evidence and
missing data; they do not diagnose root cause automatically.

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
python3 tools/analyze.py evidence/qemu-rv32/1.bin --elf build/rv32/1/firmware.elf --debug --json build/report.json --html build/report.html
docker run --rm --user "$(id -u):$(id -g)" --network none --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 512m -v "$PWD:/work" -w /work freertos-crashkit-rv32:bookworm python3 scripts/test-debug.py
```

Alternatively install the Debian cross-toolchain listed in
[third-party notices](THIRD_PARTY_NOTICES.md) and use `make rv32-build` directly.
The fetcher verifies the pinned official archive; `--archive path` supports
offline reuse. QEMU runs without a NIC. Tests check timer/ecall delegation, fault
PC/cause, original registers, bad stack pointer, timer-ISR context, nested abort, assert and the real
kernel stack-canary hook, wrong ELF rejection, frozen task/object analysis and ELF
helper execution. Actual GDB tests exercise task backtraces, locals, globals,
function calls and analysis reset. Timeouts and arbitrary crashes fail. The container uses
the checkout owner's UID/GID so it can write the mounted tree without root
capabilities on Linux; keep generated files writable by that owner.

## What is included

| Area | 0.2.0 behavior |
| --- | --- |
| Core | C11, fixed buffers, explicit little-endian format, per-record and whole-dump CRC |
| Task metadata | Public-API registry plus bounded host-side kernel task discovery via matching ELF layout |
| CPU entry | RV32IMAC+Zicsr/Zifencei, own fault stack, integer registers and four CSRs |
| Reader | UART/raw import, strict parsing, firmware-ID check, symbols/source locations, frame-chain reports |
| Objects | Tasks/HWM, queues/waiters, semaphores/mutexes, events, streams, timers, heap_4, event history |
| Debugger | Loopback GDB threads/registers/memory, DWARF backtraces/locals, optional writable analysis copy |
| Virtual execution | RV32 integer/compressed/M/atomic helper execution, scratch stack, explicit budgets/failures |
| Hardware extension | Cached register fields and board-supplied clock profiles; QEMU sample only |
| Evidence | Tests generate logs, manifests and snapshots locally; source packages omit generated data |

Fatal capture uses no heap, normal logging lock or scheduler API. RAM reads depend
on a trusted BSP whitelist. Type-3 task records remain **registration-time** data;
the optional offline view reconstructs frozen kernel state separately. Its private
layout/context compatibility is explicit. The sample includes static/dynamic,
idle, timer and blocked tasks. Missing/corrupt structures are not a complete view.
Python unwind needs frame chains; GDB/DWARF has its own optimization/information
limits. SMP, RV64, F/V, other validated CPU ports, SoC-specific clock profiles and
reset/power-loss persistence are not included. See [debugging contracts](docs/DEBUGGING.md).

CRC detects accidental damage; it does not authenticate a dump. Firmware-ID
matching relies on a trusted build/artifact mapping, not a cryptographic signature.
The source API may change in 0.x; format v1 remains explicitly versioned. See
[compatibility](docs/PORTING.md) before embedding it.

## Repository and contribution

`include/`, `src/`: core API and encoder; `ports/`: CPU/OS integration;
`examples/`: synthetic host demo and QEMU BSP; `tools/`: offline reader;
`tests/`: correctness/rejection tests; `scripts/`: build, GDB acceptance and packaging;
`docs/`: public API, format and release contracts.
`build/`, `third_party/` and generated `evidence/` are not source deliverables.

See [CONTRIBUTING](CONTRIBUTING.md), [SECURITY](SECURITY.md),
[changelog](CHANGELOG.md) and [license](LICENSE).
FreeRTOS and external tool licenses are described in
[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md).
