#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded ELF32 RV32 image and sparse captured-memory view. Standard library only."""
import bisect
from pathlib import Path
import struct


def require(ok, message):
    if not ok:
        raise ValueError(message)


class ElfImage:
    def __init__(self, path):
        p = Path(path)
        require(p.stat().st_size <= 32 * 1024 * 1024, 'ELF exceeds input limit')
        self.data = p.read_bytes()
        d = self.data
        require(len(d) >= 52 and d[:7] == b'\x7fELF\x01\x01\x01', 'requires little-endian ELF32')
        require(struct.unpack_from('<HH', d, 16) == (2, 243), 'requires executable RV32 ELF')
        self.entry, phoff, shoff = struct.unpack_from('<III', d, 24)
        phsize, phnum, shsize, shnum, strings = struct.unpack_from('<HHHHH', d, 42)
        require(0 < shnum <= 4096 and strings < shnum and shsize >= 40 and
                shoff + shnum * shsize <= len(d), 'invalid ELF sections')
        require(phnum <= 256 and (not phnum or phsize >= 32) and
                phoff + phnum * phsize <= len(d), 'invalid ELF segments')
        self.sections = []
        raw = [struct.unpack_from('<10I', d, shoff + i * shsize) for i in range(shnum)]
        names = self._slice(raw[strings][4], raw[strings][5])
        for s in raw:
            name = self._string(names, s[0])
            require(s[3] + s[5] <= 1 << 32, 'ELF section address overflow')
            payload = b'' if s[1] == 8 else self._slice(s[4], s[5])
            self.sections.append(dict(name=name, type=s[1], flags=s[2], address=s[3],
                                      size=s[5], link=s[6], entsize=s[9], data=payload))
        ids = [s['data'] for s in self.sections if s['name'] == '.crashkit_id']
        require(len(ids) == 1 and len(ids[0]) == 16 and any(ids[0]), 'missing/invalid firmware identity')
        self.firmware_id = ids[0].hex()
        self.segments = []
        for i in range(phnum):
            kind, off, addr, _, size, total, flags, _ = struct.unpack_from('<8I', d, phoff+i*phsize)
            if kind != 1:
                continue
            require(size <= total and addr + total <= 1 << 32, 'invalid load segment')
            data = self._slice(off, size)
            self.segments.append((addr, data, total, flags))
        self.symbols = {}
        self.functions = []
        for s in self.sections:
            if s['type'] not in (2, 11):
                continue
            require(s['entsize'] == 16 and s['size'] % 16 == 0 and s['size']//16 <= 65536 and
                    s['link'] < len(self.sections), 'invalid ELF symbols')
            names = self.sections[s['link']]['data']
            for offset in range(0, s['size'], 16):
                n, addr, size, info, _, index = struct.unpack_from('<IIIBBH', s['data'], offset)
                name = self._string(names, n)
                if not name or not index:
                    continue
                symbol = dict(name=name, address=addr, size=size, kind=info & 15)
                if name in self.symbols and (self.symbols[name] is None or self.symbols[name]['address'] != addr):
                    # Ambiguous local symbols must not silently select a different TU.
                    self.symbols[name] = None
                else:
                    self.symbols[name] = symbol
                if info & 15 == 2 and size:
                    require(addr + size <= 1 << 32, 'symbol overflow')
                    self.functions.append(symbol)
        self.functions.sort(key=lambda s: s['address'])
        self._starts = [s['address'] for s in self.functions]

    def _slice(self, offset, size):
        require(offset <= len(self.data) and size <= len(self.data)-offset, 'ELF range outside file')
        return self.data[offset:offset+size]

    @staticmethod
    def _string(data, offset):
        require(offset < len(data), 'ELF string offset outside table')
        end = data.find(b'\0', offset)
        require(end >= 0 and end-offset <= 4096, 'invalid ELF string')
        return data[offset:end].decode('utf-8', 'replace')

    def section(self, name):
        result = [s for s in self.sections if s['name'] == name]
        require(len(result) <= 1, 'duplicate ELF section: '+name)
        return result[0] if result else None

    def symbol(self, name):
        require(name in self.symbols and self.symbols[name] is not None, 'missing/ambiguous ELF symbol: '+name)
        return self.symbols[name]['address']

    def locate(self, pc):
        i = bisect.bisect_right(self._starts, pc)-1
        if i >= 0 and pc < self.functions[i]['address']+self.functions[i]['size']:
            s = self.functions[i]
            return dict(function=s['name'], offset=pc-s['address'])
        return dict(function=None, offset=None)


class Memory:
    """Original captured bytes are immutable. Writes go to a bounded analysis overlay."""
    def __init__(self, report, elf, scratch=True):
        self.regions = []
        self.overlay = {}
        self.written = 0
        for rec in report['records']:
            if rec['type'] == 2 and rec['captured']:
                self.add(int(rec['address'], 16), bytes.fromhex(rec['bytes_hex']), 'snapshot')
        # Only immutable, file-backed ELF segments supplement captured RAM.
        # Never fabricate writable .data or missing .bss from the ELF.
        for addr, data, _, flags in elf.segments:
            if not flags & 2 and data:
                self.add(addr, data, 'elf')
        for name in ('.crashkit_debug', '.crashkit_debug_rodata'):
            s = elf.section(name)
            if s:
                require(0xf0000000 <= s['address'] < 0xf0040000 and s['size'] <= 0xf0040000-s['address'],
                        'analysis section outside reserved virtual space')
                self.add(s['address'], s['data'], 'elf-helper')
        if scratch:
            self.add(0xe0000000, bytes(65536), 'scratch')
        self.regions.sort(key=lambda x: x[0])

    def add(self, address, data, source):
        require(0 <= address < 1 << 32 and len(data) <= (1 << 32)-address and
                len(data) <= 4*1024*1024, 'invalid memory region')
        if not data:
            return
        for start, previous, _ in self.regions:
            a, b = max(address, start), min(address+len(data), start+len(previous))
            if a < b:
                require(data[a-address:b-address] == previous[a-start:b-start],
                        'conflicting captured/ELF memory regions')
        require(len(self.regions) < 4096, 'too many memory regions')
        self.regions.append((address, data, source))

    def read(self, address, size):
        require(0 <= address < 1 << 32 and 0 <= size <= 65536 and size <= (1 << 32)-address,
                'invalid memory request')
        result = bytearray()
        while len(result) < size:
            at = address+len(result)
            region = next((r for r in self.regions if r[0] <= at < r[0]+len(r[1])), None)
            require(region is not None, 'memory not captured: '+hex(at))
            n = min(size-len(result), region[0]+len(region[1])-at)
            result.extend(region[1][at-region[0]:at-region[0]+n])
        for i in range(size):
            if address+i in self.overlay:
                result[i] = self.overlay[address+i]
        return bytes(result)

    def write(self, address, data):
        self.read(address, len(data))  # Validate the whole request before mutation.
        require(len(self.overlay)+len(data) <= 2*1024*1024, 'analysis write budget exceeded')
        self.overlay.update((address+i, value) for i, value in enumerate(data))
        self.written += len(data)

    def u32(self, address):
        return int.from_bytes(self.read(address, 4), 'little')

    def reset(self):
        self.overlay.clear()
        self.written = 0
