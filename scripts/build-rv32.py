#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, str(ROOT/'scripts/fetch-freertos.py')], check=True)
KERNEL=ROOT/'third_party/FreeRTOS-Kernel-11.1.0'
PORT=KERNEL/'portable/GCC/RISC-V'
BUILD=ROOT/'build/rv32'; BUILD.mkdir(parents=True,exist_ok=True)
CC='riscv64-unknown-elf-gcc'
version=subprocess.check_output([CC,'--version'],text=True)
libgcc=Path(subprocess.check_output([CC,'-march=rv32imac','-mabi=ilp32','-print-libgcc-file-name'],text=True).strip())
sources=[ROOT/'src/crashkit.c',ROOT/'src/crashkit_trace.c',ROOT/'ports/freertos/ck_freertos.c',ROOT/'ports/rv32/ck_rv32.c',
         ROOT/'ports/rv32/entry.S',ROOT/'examples/qemu-rv32/start.S',ROOT/'examples/qemu-rv32/main.c',
         ROOT/'examples/qemu-rv32/minilibc.c',KERNEL/'tasks.c',KERNEL/'list.c',KERNEL/'queue.c',
         KERNEL/'event_groups.c',KERNEL/'stream_buffer.c',KERNEL/'timers.c',KERNEL/'portable/MemMang/heap_4.c',
         PORT/'port.c',PORT/'portASM.S']
flags=['-march=rv32imac_zicsr_zifencei','-mabi=ilp32','-mcmodel=medany','-msmall-data-limit=0','-std=c11',
       '-Os','-g3','-gdwarf-4','-fno-omit-frame-pointer','-fno-optimize-sibling-calls',
       '-ffreestanding','-fno-builtin','-ffunction-sections','-fdata-sections',
       '-fstack-usage','-Wall','-Wextra','-Werror']
includes=[ROOT/'include',ROOT/'ports/freertos',ROOT/'ports/rv32',ROOT/'examples/qemu-rv32',
          ROOT/'examples/qemu-rv32/minilibc',KERNEL/'include',PORT,
          PORT/'chip_specific_extensions/RISCV_MTIME_CLINT_no_extensions']
inputs={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for name in ('src','include','ports','examples','scripts') for p in sorted((ROOT/name).rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts}
inputs['third_party/freertos-V11.1.0.tar.gz']=hashlib.sha256((ROOT/'third_party/freertos-V11.1.0.tar.gz').read_bytes()).hexdigest()
inputs['toolchain/libgcc']=hashlib.sha256(libgcc.read_bytes()).hexdigest()
inputs.update({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(KERNEL.rglob('*')) if p.is_file() and p.suffix in ('.c','.h','.S')})
manifest={'compiler':version,'flags':flags,'kernel_version':'V11.1.0','source_hashes':inputs,
          'libgcc_sha256':hashlib.sha256(libgcc.read_bytes()).hexdigest(),'cases':[]}
for case in (1,2,3,4,5,6,7):
    out=BUILD/str(case); out.mkdir(exist_ok=True)
    firmware_id=hashlib.sha256(json.dumps([inputs,version,flags,case],sort_keys=True).encode()).digest()[:16]
    (out/'firmware_id.h').write_text('#define CK_FIRMWARE_ID {'+','.join(str(b) for b in firmware_id)+'}\n')
    objects=[]
    for i,source in enumerate(sources):
        obj=out/(str(i)+'-'+source.stem+'.o'); objects.append(obj)
        command=[CC,*flags,'-DCK_CASE='+str(case),'-I'+str(out)]
        command+=['-I'+str(p) for p in includes]
        subprocess.run([*command,'-c',str(source),'-o',str(obj)],check=True)
    elf=out/'firmware.elf'
    subprocess.run([CC,'-march=rv32imac_zicsr_zifencei','-mabi=ilp32','-mcmodel=medany','-nostdlib',
                    '-Wl,--gc-sections','-Wl,-Map='+str(out/'firmware.map'),
                    '-T',str(ROOT/'examples/qemu-rv32/link.ld'),*[str(p) for p in objects],
                    str(libgcc),'-o',str(elf)],check=True)
    symbols=subprocess.check_output(['riscv64-unknown-elf-nm','-n',str(elf)],text=True)
    (out/'symbols.txt').write_text(symbols)
    size=subprocess.check_output(['riscv64-unknown-elf-size',str(elf)],text=True)
    (out/'size.txt').write_text(size)
    disassembly=subprocess.check_output(['riscv64-unknown-elf-objdump','-d',str(elf)],text=True)
    (out/'disassembly.txt').write_text(disassembly)
    image=out/'firmware.bin'
    subprocess.run(['riscv64-unknown-elf-objcopy','-O','binary',
                    '--remove-section=.crashkit_debug','--remove-section=.crashkit_debug_rodata',
                    str(elf),str(image)],check=True)
    if image.stat().st_size>1024*1024: raise SystemExit('ELF-only code leaked into firmware image')
    manifest['cases'].append({'case':case,'firmware_id':firmware_id.hex(),
         'elf_sha256':hashlib.sha256(elf.read_bytes()).hexdigest(),'size':size.strip()})
    print('Built case '+str(case)+': '+firmware_id.hex())
(BUILD/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
