# Security and trust boundaries

0.1.0 is experimental and has no security certification or guaranteed response
time. The reader handles bounded local inputs, not an Internet-facing service.
Run unfamiliar dumps and ELFs with least privilege; never run target code to
inspect a snapshot. CRC and firmware IDs do not authenticate attacker-controlled
inputs. Memory captures can contain credentials and customer data.

## Reporting

After a remote repository is created, use its private vulnerability-reporting
channel if the maintainer enables one. Until such a channel exists, open a public
issue requesting private contact **without exploit details, secrets or production
dumps**. No contact address or active disclosure channel is claimed by this local
release candidate. Provide a minimal synthetic reproducer privately when contact
is established. Ordinary non-sensitive correctness bugs can be public issues.

## Embedded integration

The BSP must supply finite RAM reads and a bounded output/abort path. It must
reject MMIO, invalid ranges and unsupported memory states before dereferencing.
A whitelist is not a guarantee that damaged RAM remains readable. The RV32 port
owns mtvec/mscratch and assumes a frozen single hart; SMP and concurrent writes
are unsupported. UART output in QEMU is a test backend, not reset-safe storage.

Retain original ELF/build mapping privately where necessary. Strip secrets before
sharing reports and prefer the repository's generated fault cases as reproductions.
