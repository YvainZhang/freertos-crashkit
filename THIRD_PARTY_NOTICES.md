# Third-party notices

The original source in this repository is MIT licensed; see [LICENSE](LICENSE).
No vendor SDK or external fault-analysis implementation is included. The project name
describes compatibility with FreeRTOS and does not imply upstream affiliation.

## FreeRTOS kernel (example dependency, not bundled)

- Source: [official FreeRTOS-Kernel V11.1.0](https://github.com/FreeRTOS/FreeRTOS-Kernel/tree/V11.1.0).
- Archive SHA-256: `0e21928b3bcc4f9bcaf7333fb1c8c0299d97e2ec9e13e3faa2c5a7ac8a3bc573`.
- License: [upstream MIT notice](https://github.com/FreeRTOS/FreeRTOS-Kernel/blob/V11.1.0/LICENSE.md),
  preserved at `third_party/FreeRTOS-Kernel-11.1.0/LICENSE.md` after fetching.
- The example links official `tasks.c`, `list.c`, `queue.c` and GCC RISC-V port
  files without modifying them. Preserve their notices when redistributing them.

## Build and test tools (not bundled)

Docker uses Debian bookworm-slim pinned by image digest. Its apt repositories are
not historical snapshots. The image installs `build-essential`, `python3`,
`gcc-riscv64-unknown-elf` and `binutils-riscv64-unknown-elf`; host QEMU comes from
the user's installation or the CI runner's `qemu-system-misc` package.

GCC/binutils/QEMU and Python carry their respective upstream licenses. The example
links libgcc compiler runtime helpers; GCC's runtime is governed by GPL with the
[GCC Runtime Library Exception](https://www.gnu.org/licenses/gcc-exception-3.1.html).
Source releases do not bundle tool binaries, container images, upstream kernel
archives or linked example ELFs. Anyone distributing compiled firmware must review
and preserve the notices of the actual linked dependencies.

Build manifests record source, compiler, flags and libgcc hashes. This is evidence
of input identity, not a promise of perpetual byte-identical toolchain rebuilds.
