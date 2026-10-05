#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Strict offline reader for CrashKit v1. No target code is executed."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import struct
import subprocess
import zlib

MAX_DUMP = 4194304

def crc(data):
    return zlib.crc32(data) & 0xffffffff

def require(ok, message):
    if not ok:
        raise ValueError(message)

def parse(data):
    require(64 <= len(data) <= MAX_DUMP, 'invalid dump size')
    require(data[:4] == b'CKD1', 'snapshot is incomplete or magic is invalid')
    version, header = struct.unpack_from('<HH', data, 4)
    require(version == 1 and header == 48, 'unsupported format/header')
    require(crc(data[:44]) == struct.unpack_from('<I', data, 44)[0], 'header CRC mismatch')
    arch, bits, endian, reason, flags = struct.unpack_from('<HBBII', data, 8)
    require(arch in (0, 1, 2) and bits in (32, 64) and endian in (1, 2), 'invalid target profile')
    require(arch == 0 or bits == 32, 'architecture/pointer width mismatch')
    require(reason in (1, 2, 3, 4) and flags & ~15 == 0, 'invalid reason/flags')
    footer = len(data) - 16
    magic, total, count, checksum = struct.unpack_from('<4sIII', data, footer)
    require(magic == b'END!' and total == len(data), 'footer/size mismatch')
    require(crc(data[:footer]) == checksum, 'snapshot CRC mismatch')
    result = {'format': version, 'architecture': {0:'generic', 1:'rv32', 2:'cortex-m'}[arch],
              'pointer_bits': bits, 'source_endian': endian, 'reason': reason,
              'flags': flags, 'synthetic': bool(flags & 8), 'firmware_id': data[20:36].hex(),
              'sequence': struct.unpack_from('<Q', data, 36)[0],
              'matching': 'not_checked', 'records': [],
              'scope': 'Captured facts only; task metadata is registration-time metadata. No automatic root cause or backtrace.'}
    offset = 48
    while offset < footer:
        require(footer-offset >= 12, 'truncated record header')
        kind, rf, size, check = struct.unpack_from('<HHII', data, offset)
        require(size <= footer-offset-12 and rf & ~15 == 0, 'invalid record size/flags')
        payload = data[offset+12:offset+12+size]
        require(crc(payload) == check, 'record CRC mismatch')
        rec = {'type': kind, 'flags': rf}
        if kind == 1:
            require(size >= 12 and rf == 0, 'invalid register record')
            n, width, mask = struct.unpack_from('<HHQ', payload)
            require(0 < n <= 40 and width in (32, 64) and size == 12+8*n and mask >> n == 0,
                    'invalid register shape')
            values = struct.unpack_from('<'+'Q'*n, payload, 12)
            require(width == 64 or all(v <= 0xffffffff for v in values), 'register overflow')
            names = ['x'+str(i) for i in range(32)]+['mepc','mstatus','mcause','mtval'] if arch == 1 and n == 36 else ['r'+str(i) for i in range(n)]
            rec.update(register_bits=width, registers={name:hex(v) if mask & (1 << i) else None for i, (name, v) in enumerate(zip(names, values))})
        elif kind == 2:
            require(size >= 20, 'invalid memory record')
            address, requested, captured, status = struct.unpack_from('<QIII', payload)
            require(requested > 0 and captured <= min(requested, 1024) and size == 20+captured and status == rf,
                    'invalid memory shape')
            require(address < 1 << bits and requested <= (1 << bits)-address, 'memory address overflow')
            require(rf & ~3 == 0 and (captured == requested or rf & 3), 'invalid memory status')
            rec.update(address=hex(address), requested=requested, captured=captured, bytes_hex=payload[20:].hex())
        elif kind == 3:
            require(size == 48 and rf == 0, 'invalid task record')
            handle, generation, address, stack_bytes, priority, name = struct.unpack('<QQQII16s', payload)
            require(handle > 0 and generation > 0 and stack_bytes > 0 and name[-1] == 0,
                    'invalid task metadata')
            require(handle < 1 << bits and address < 1 << bits and stack_bytes <= (1 << bits)-address,
                    'task address overflow')
            rec.update(handle=hex(handle), generation=generation, stack_address=hex(address),
                       stack_bytes=stack_bytes, registered_priority=priority,
                       name=name.split(b'\0',1)[0].decode('utf-8','replace'))
        elif kind == 4:
            require(size == 8 and rf == 0, 'invalid diagnostic')
            rec.update(zip(('code','value'), struct.unpack('<II',payload)))
        else:
            rec.update(unknown=True, payload_size=size)
        result['records'].append(rec)
        offset += 12+size
    require(offset == footer and len(result['records']) == count, 'record count mismatch')
    return result

def elf_identity(path):
    """Read a bounded ELF section table; extended section numbering is unsupported."""
    p = Path(path)
    require(p.stat().st_size <= 32*1024*1024, 'ELF exceeds input limit')
    data = p.read_bytes()
    require(len(data) >= 64 and data[:4] == b'\x7fELF' and data[4] in (1, 2) and data[5] in (1, 2), 'invalid ELF')
    endian = '<' if data[5] == 1 else '>'
    if data[4] == 1:
        off = struct.unpack_from(endian+'I',data,32)[0]
        entry, n, strings = struct.unpack_from(endian+'HHH',data,46)
        fmt = endian+'IIIIIIIIII'; need = 40
    else:
        off = struct.unpack_from(endian+'Q',data,40)[0]
        entry, n, strings = struct.unpack_from(endian+'HHH',data,58)
        fmt = endian+'IIQQQQIIQQ'; need = 64
    require(0 < n <= 4096 and strings < n and entry >= need and off+n*entry <= len(data), 'invalid/unsupported ELF section table')
    sections = [struct.unpack_from(fmt,data,off+i*entry) for i in range(n)]
    sh = sections[strings]
    require(sh[4]+sh[5] <= len(data), 'invalid ELF string table')
    names = data[sh[4]:sh[4]+sh[5]]
    identities = []
    for sh in sections:
        require(sh[0] < len(names), 'invalid ELF section name')
        end = names.find(b'\0',sh[0]); require(end >= 0, 'unterminated section name')
        if names[sh[0]:end] == b'.crashkit_id':
            require(sh[1] != 8 and sh[5] == 16 and sh[4]+16 <= len(data), 'invalid firmware ID section')
            identities.append(data[sh[4]:sh[4]+16].hex())
    require(len(identities) == 1, 'ELF must contain one .crashkit_id section')
    return {'firmware_id':identities[0], 'elf_sha256':hashlib.sha256(data).hexdigest(),
            'elf_class':data[4], 'elf_machine':struct.unpack_from(endian+'H',data,18)[0]}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('dump', type=Path)
    ap.add_argument('--elf', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--html', type=Path)
    ap.add_argument('--debug', action='store_true', help='reconstruct tasks and frame chains with matched RV32 ELF')
    ap.add_argument('--addr2line', help='optional target addr2line executable for source locations')
    ap.add_argument('--register-profile', type=Path, help='board register/clock JSON profile (requires --debug)')
    args = ap.parse_args()
    try:
        require(not args.addr2line or args.debug, '--addr2line requires --debug')
        require(args.dump.stat().st_size <= MAX_DUMP, 'dump exceeds input limit')
        result = parse(args.dump.read_bytes())
        if args.elf:
            require(result['firmware_id'] != '00'*16, 'firmware identity is unspecified')
            identity = elf_identity(args.elf)
            require(identity['firmware_id'] == result['firmware_id'], 'firmware identity mismatch')
            if result['architecture'] == 'rv32':
                require(identity['elf_class'] == 1 and identity['elf_machine'] == 243, 'ELF target mismatch')
            result.update(identity, matching='firmware_id_matched')
        if args.debug:
            require(args.elf is not None, '--debug requires --elf')
            from postmortem import Snapshot
            result['analysis'] = Snapshot(result,args.elf).summary(args.addr2line)
            result['scope'] = 'Snapshot records plus separately reconstructed kernel/object evidence; no automatic root cause.'
        if args.register_profile:
            require(args.debug and args.register_profile.stat().st_size <= 65536,'register profile requires --debug and <=64KiB')
            from registers import decode_profile
            result['analysis']['hardware'] = decode_profile(result['analysis']['objects'],json.loads(args.register_profile.read_text()))
        text = json.dumps(result, ensure_ascii=False, indent=2)+'\n'
        if args.json: args.json.write_text(text,encoding='utf-8')
        if args.html:
            args.html.write_text('<!doctype html><meta charset="utf-8"><title>CrashKit report</title>'
                                 '<h1>CrashKit evidence report</h1><pre>'+html.escape(text)+'</pre>',encoding='utf-8')
        if not args.json: print(text,end='')
    except (ValueError, OSError, struct.error, subprocess.TimeoutExpired) as error:
        ap.exit(2, 'Rejected: '+str(error)+'\n')

if __name__ == '__main__':
    main()
