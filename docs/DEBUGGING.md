# Offline debugging

0.2.0 adds a post-mortem debugger for the reference single-hart RV32IMAC,
FreeRTOS V11.1.0 build. Original snapshots stay immutable; an explicitly enabled
analysis copy supports register/memory writes and bounded virtual execution.
Physical boards, other ports and SoC-specific register profiles require separate
validation. No automatic root cause diagnosis is promised.

## Capture, import and report

Build and run the reference firmware using the commands in the [README](../README.md).
It captures application/kernel `.data` and `.bss`, including task stacks and heap,
and the separate 8KiB interrupt/boot stack,
while excluding the active capture workspace and dump buffer. Immutable code comes
from the matched ELF. This is a selected RAM image, not every byte of the 16MiB
QEMU address space. The example reserves 64KiB for the dump; the core/reader limit
is 4MiB. Repeated 1024-byte records encode larger regions.

```sh
python3 tools/import_dump.py evidence/qemu-rv32/1.log --elf build/rv32/1/firmware.elf --output build/imported.bin
python3 tools/analyze.py build/imported.bin --elf build/rv32/1/firmware.elf --debug --json build/debug.json --html build/debug.html
```

Multiple UART frames need `--index N` (zero-based). A nested-abort log has no
completed frame and must be rejected. Raw RAM can be imported with
`tools/import_dump.py ram.bin --raw --base 0x80000000 --registers regs.json --elf firmware.elf --output dump.bin`.
Register JSON must contain x0..x31, mepc, mstatus, mcause and mtval as integers or
hex strings. This conversion trusts the supplied RAM/register/ELF association;
assigning the ELF's ID is not proof that an external capture came from that ELF.

With `--debug`, task reconstruction uses `.crashkit_layout`, emitted by the
official task-additions hook without modifying the kernel. It walks frozen ready,
delayed, suspended and deletion lists with link/count/owner checks and a 16-task
limit. Dynamic, idle and timer tasks are discovered as well as explicit static
tasks. An indefinite object wait in the suspended list is reported as Blocked.
Pending-ready transitions, missing memory, damaged lists and unavailable contexts
are explicit diagnostics, not a clean complete-task claim.

For task-stack exceptions, current-task registers come from the exception entry.
An SP within the ELF-declared IRQ stack creates a separate exception thread;
the interrupted task retains its saved port context. The stack-canary hook uses
this view too. Without matching stack bounds, the origin remains ambiguous rather
than being inferred from the reason alone. Other tasks use the pinned
integer port's 31-word saved context; gp/tp are assumed constant as in that port.
HWM is a bounded fill-byte scan in stack words, not proof of this crash's cause.
Python backtraces use ABI frame chains and stop on missing/corrupt bounds; build
with frame pointers. GDB uses its ELF/DWARF unwinder for other supported code.
Optional `--addr2line /path/to/target-addr2line` adds source locations; without the
tool, symbols remain available and source status is explicitly unavailable.

## GDB on the host

Start the server from the source root:

```sh
python3 tools/gdb_server.py evidence/qemu-rv32/1.bin --elf build/rv32/1/firmware.elf --port 6000
```

In another terminal, start an RV32-capable GDB with that exact ELF:

```gdb
target remote 127.0.0.1:6000
info threads
thread apply all bt
frame 1
info locals
p/x ck_example_global
p/x $mcause
p *pxCurrentTCB
monitor system
monitor tasks
monitor objects
monitor bt
detach
```

The default is read-only. For a mutable analysis copy and helper calls, add
`--writable --execute` to the server invocation:

```gdb
frame 0
set $sp = 0xe000fff0
call ck_debug_system()
set $sp = 0xe000fff0
call ck_debug_tasks()
set $sp = 0xe000fff0
call ck_debug_queue(ck_example_queue)
set $sp = 0xe000fff0
call ck_debug_heap()
monitor reset
```

Always select frame 0 before changing machine registers. The scratch stack is
64KiB at 0xe0000000; align SP to 16 bytes. ELF-only `.crashkit_debug*` functions
live at 0xf0000000 and are excluded from device PT_LOAD segments and binary output.
They must never be called on hardware. Dependencies used by these helpers may
still contribute ordinary device code; the section exclusion alone is not a
zero-total-overhead claim. Check map, program headers and the generated binary.
The linker/GDB may warn that these two allocated sections are outside load
segments; this is intentional for the reference analysis-only ELF sections.

The original RV32 interpreter supports integer, compressed, multiply/divide and
single-CPU atomic analysis operations, a small CSR subset and a dedicated character
ECALL. It is not a hardware simulator: F/V, MMIO, interrupts, privileged return and
unknown instructions fail explicitly. Limits are two million instructions per
resume, 64KiB console output and a bounded write overlay. `monitor call symbol [args]`
is an alternative to GDB `call`; it prepares the scratch stack and reports the
return value. `monitor reset` restores RAM/registers and clears breakpoints.
Execution can modify the analysis heap/lists, so reset before interpreting a new
result against the original crash.

## Object and register plugins

`.crashkit_objects` is an opt-in ELF catalog of kind, pointer-slot address and
16-byte name. Kinds 1..9 are queue, semaphore, mutex, event group, stream buffer,
timer, heap_4, cached register samples and application event trace. The reference
catalog and memory layouts are in [main.c](../examples/qemu-rv32/main.c).
Kernel object offsets come from the matched ELF's DWARF, not hard-coded private
TCB/queue offsets. The bounded type reader accepts common DWARF2..5 forms;
split/indexed/compressed debug information and unsupported forms are unavailable.

Reports include queue FIFO bytes/waiters, semaphore counts, mutex owner, event
bits/waiters, stream contents/waiters, timer period/expiry/active state, and heap_4
free blocks/totals. Damaged objects degrade individually. Event-trace slots have
commit state and CRC, sequence/tick/tag/value, an overwrite count and rejected-slot
list. Producers must be externally serialized; ticks/tags are application-defined.

Register samples are collected in normal context by the BSP. The example records
configured CPU frequency and sampled UART LSR, never inventing live peripheral
state from uncaptured RAM. `--register-profile profile.json` adds field decoding
and a parent/mux/divider/gate clock tree to `--debug`. For example:

```json
{"version":1,"registers":[{"name":"uart_lsr","fields":[{"name":"tx_empty","mask":"0x20","shift":5}]}],"clocks":[{"name":"cpu","source_register":"cpu_clock_hz"},{"name":"bus","parent":"cpu","divider":2}]}
```

Profiles must come from the board's real register definitions and include the
required cached samples. Missing inputs produce unknown rates. Derived clock
rates are not measurements. No vendor clock/UART decoder is bundled or validated.

## Reproducible acceptance

After a fresh RV32 build and `make qemu-test`, run in the independent tool image:

```sh
docker run --rm --user "$(id -u):$(id -g)" --network none --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 512m -v "$PWD:/work" -w /work freertos-crashkit-rv32:bookworm python3 scripts/test-debug.py
```

The seven QEMU scenarios cover task/ISR CPU faults, a damaged SP, nested abort,
an assertion, and a real kernel stack-canary check invoking its overflow hook.
This executes actual GDB, checks threads/backtraces/locals/globals/CSRs/helper calls,
writes/reset/original hashes, eight ELF helpers, raw/UART imports and corrupt
task/heap/queue/trace rejection. Generated manifests/logs are in
`evidence/qemu-rv32/`, `evidence/offline/` and `evidence/gdb/`; no customer dumps
or generated ELF files belong in Git or source packages.

Protocol references: [GDB packets](https://sourceware.org/gdb/current/onlinedocs/gdb.html/Packets.html),
[RISC-V target descriptions](https://sourceware.org/gdb/current/onlinedocs/gdb.html/RISC_002dV-Features.html),
[RISC-V ABI](https://riscv-non-isa.github.io/riscv-elf-psabi-doc/),
[ISA specification](https://docs.riscv.org/reference/isa/unpriv/unpriv-index.html).
