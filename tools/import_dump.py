#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Import framed UART snapshots or raw RAM plus explicit RV32 registers and ELF."""
import argparse
from pathlib import Path
import re
import struct
import zlib

from analyze import MAX_DUMP, parse
from elf_image import ElfImage, require


def encode_raw(data, address, registers, firmware_id):
    require(data and len(data) <= MAX_DUMP-131072 and 0 <= address < 1 << 32 and
            len(data) <= (1 << 32)-address,'raw RAM exceeds snapshot/range limit')
    names=['x'+str(i) for i in range(32)]+['mepc','mstatus','mcause','mtval']
    require(isinstance(registers,dict) and set(registers) == set(names),'requires x0..x31,mepc,mstatus,mcause,mtval')
    values=[int(registers[n],0) if isinstance(registers[n],str) else registers[n] for n in names]
    require(all(type(v) is int and 0 <= v <= 0xffffffff for v in values) and values[0] == 0,
            'invalid RV32 register value')
    records=[]
    def record(kind,payload):
        records.append(struct.pack('<HHII',kind,0,len(payload),zlib.crc32(payload))+payload)
    record(1,struct.pack('<HHQ',36,32,(1 << 36)-1)+struct.pack('<36Q',*values))
    for offset in range(0,len(data),1024):
        chunk=data[offset:offset+1024]
        record(2,struct.pack('<QIII',address+offset,len(chunk),len(chunk),0)+chunk)
    header=struct.pack('<4sHHHBBII16sQ',b'CKD1',1,48,1,32,1,3,0,bytes.fromhex(firmware_id),1)
    header+=struct.pack('<I',zlib.crc32(header))
    output=header+b''.join(records)
    output+=struct.pack('<4sIII',b'END!',len(output)+16,len(records),zlib.crc32(output))
    require(len(output) <= MAX_DUMP,'encoded snapshot exceeds size limit')
    parse(output)
    return output


def extract_log(data,index=None):
    require(len(data) <= 2*MAX_DUMP+1024*1024,'UART log too large')
    matches=list(re.finditer(rb'CK_HEX_BEGIN\r?\n([0-9a-fA-F]+)\r?\nCK_HEX_END',data))
    require(matches,'no complete framed snapshot in UART log')
    require(index is not None or len(matches) == 1,'multiple snapshots; choose --index (zero-based)')
    index=0 if index is None else index
    require(0 <= index < len(matches),'snapshot index outside log')
    hexdata=matches[index][1]
    require(len(hexdata) % 2 == 0 and len(hexdata) <= 2*MAX_DUMP,'invalid snapshot hex length')
    result=bytes.fromhex(hexdata.decode())
    parse(result)
    return result


def main():
    import json
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path); ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--index',type=int); ap.add_argument('--elf',type=Path)
    ap.add_argument('--raw',action='store_true'); ap.add_argument('--base',type=lambda s:int(s,0))
    ap.add_argument('--registers',type=Path)
    args=ap.parse_args()
    try:
        require(args.source.resolve() != args.output.resolve(),'cannot overwrite original source')
        require(args.source.stat().st_size <= 2*MAX_DUMP+1024*1024,'input too large')
        if args.raw:
            require(args.elf and args.registers and args.base is not None,'raw input needs --elf, --registers and --base')
            require(args.registers.stat().st_size <= 65536,'register JSON too large')
            elf=ElfImage(args.elf)
            result=encode_raw(args.source.read_bytes(),args.base,
                              json.loads(args.registers.read_text()),elf.firmware_id)
        else:
            require(args.base is None and not args.registers,'raw options require --raw')
            result=extract_log(args.source.read_bytes(),args.index)
            if args.elf:
                require(parse(result)['firmware_id'] == ElfImage(args.elf).firmware_id,'firmware identity mismatch')
        args.output.write_bytes(result)
        print('IMPORTED '+str(len(result))+' bytes -> '+str(args.output))
    except (ValueError,OSError) as error:
        ap.exit(2,'Rejected: '+str(error)+'\n')


if __name__ == '__main__': main()
