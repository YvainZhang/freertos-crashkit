# Snapshot format v1

All integers are explicitly little endian, regardless of source CPU byte order.
No native C struct layout is serialized. Inputs are exactly the written length,
64..65536 bytes, with no extra padding.

## Header (48 bytes)

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 4 | `CKD1` complete; `CKIP` while writing |
| 4 | 2 | Version 1 |
| 6 | 2 | Header size 48 |
| 8 | 2 | Architecture: 0 generic, 1 RV32, 2 Cortex-M tag |
| 10 | 1 | Source pointer bits: 32 or 64 (RV32/Cortex-M require 32) |
| 11 | 1 | Source endian tag: 1 little, 2 big |
| 12 | 4 | Reason: 1 manual, 2 assert, 3 CPU fault, 4 stack overflow |
| 16 | 4 | Flags: 1 TRUNCATED, 2 READ_FAILED, 4 METADATA_BUSY, 8 SYNTHETIC |
| 20 | 16 | Firmware ID, all-zero means unspecified |
| 36 | 8 | Caller-defined sequence (not guaranteed unique across boots) |
| 44 | 4 | CRC32 of bytes 0..43 |

Tags/reasons do not imply implemented CPU ports or entry hooks.

## Records

Each record has a 12-byte header: type u16, flags u16, payload size u32, payload
CRC32 u32. Payloads follow with no alignment padding.

| Type | Payload |
| --- | --- |
| 1 registers | count u16, bits u16, valid mask u64, count u64 values (1..40); bits 32/64 |
| 2 memory | address u64, requested u32, captured u32, status u32, captured bytes (max 1024); status equals record flags |
| 3 task | handle/generation/stack address u64 each; stack bytes/registered priority u32 each; 16-byte name ending in NUL |
| 4 diagnostic | code u32, value u32 |

Register/task/diagnostic flags must be zero. Memory permits only TRUNCATED and
READ_FAILED; a short capture must indicate one of these. Register mask bits beyond
count and out-of-range 32-bit values are invalid. Target address ranges cannot wrap.
RV32 full register order is x0..x31, mepc, mstatus, mcause, mtval (36 values);
other shapes are reported as rN. Task records describe registration-time metadata.
Diagnostics: 1 bad/updating registry slot, 2 rejected registrations, 3 demo progress.
Unknown record types are skipped and reported; unknown flag bits are rejected.

## Footer and validation

The final 16 bytes are `END!`, total size u32, record count u32, CRC32 of all bytes
preceding the footer. CRC32 uses the IEEE reflected polynomial 0xedb88320, initial
and final XOR 0xffffffff (same as Python zlib.crc32).

The reader validates complete magic, version, all sizes/CRCs, count and known field
shapes before reporting. Incomplete snapshots are rejected, not repaired silently.
Checksum and identity are not cryptographic authentication. `--elf` additionally
requires a nonzero matching ID, and for RV32 an ELF32 RISC-V image (machine 243).
Extended ELF section numbering is unsupported. `--elf` absent means `not_checked`.
See [中文格式说明](FORMAT.md) for the corresponding local tutorial.
