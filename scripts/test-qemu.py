#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('analyze',ROOT/'tools/analyze.py')
analyze=importlib.util.module_from_spec(spec);spec.loader.exec_module(analyze)
OUT=ROOT/'evidence/qemu-rv32';OUT.mkdir(parents=True,exist_ok=True)
build=json.loads((ROOT/'build/rv32/manifest.json').read_text())
for name, expected in build['source_hashes'].items():
    if name == 'toolchain/libgcc':
        continue # Recorded inside the compiler container; not installed on host.
    source=ROOT/name
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
        raise SystemExit('Build/source mismatch; rebuild reference firmware: '+name)
for case in build['cases']:
    elf=ROOT/'build/rv32'/str(case['case'])/'firmware.elf'
    if hashlib.sha256(elf.read_bytes()).hexdigest()!=case['elf_sha256']:
        raise SystemExit('ELF differs from build manifest; rebuild')
results=[]
version=subprocess.check_output(['qemu-system-riscv32','--version'],text=True)
for case in (1,2,3,4):
    directory=ROOT/'build/rv32'/str(case)
    command=['qemu-system-riscv32','-machine','virt','-cpu','rv32','-smp','1','-m','16M',
             '-bios','none','-kernel',str(directory/'firmware.elf'),'-display','none',
             '-monitor','none','-serial','stdio','-nic','none','-no-reboot']
    start=time.monotonic()
    result=subprocess.run(command,capture_output=True,timeout=15)
    (OUT/(str(case)+'.log')).write_bytes(result.stdout+result.stderr)
    if result.returncode or b'FREERTOS_RV32_START' not in result.stdout:
        raise SystemExit('QEMU failed, case '+str(case)+': '+result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))
    if case==4:
        if b'CK_NESTED_ABORT' not in result.stdout or b'CK_HEX_END' in result.stdout:
            raise SystemExit('Nested capture must abort without a completed dump')
        results.append({'case':case,'result':'PASS','expected':'nested abort; no complete dump','elapsed_s':time.monotonic()-start})
        continue
    match=re.search(rb'CK_HEX_BEGIN\r?\n([0-9a-f]+)\r?\nCK_HEX_END',result.stdout)
    if not match: raise SystemExit('No framed snapshot, case '+str(case))
    data=bytes.fromhex(match[1].decode())
    report=analyze.parse(data); elf=analyze.elf_identity(directory/'firmware.elf')
    if elf['firmware_id']!=report['firmware_id']: raise SystemExit('Firmware ID mismatch')
    report.update(elf,matching='firmware_id_matched')
    regs=report['records'][0]['registers']
    symbols={parts[2]:int(parts[0],16) for line in (directory/'symbols.txt').read_text().splitlines()
             if len(parts:=line.split())==3 and re.fullmatch('[0-9a-fA-F]+',parts[0])}
    if int(regs['mepc'],16)!=symbols['ck_injected_fault']:
        raise SystemExit('Fault PC does not match injected instruction')
    if int(regs['mcause'],16)!=(5 if case==3 else 2): raise SystemExit('Unexpected fault cause')
    if case==1 and (regs['x5']!='0x12345678' or regs['x6']!='0x76543210'):
        raise SystemExit('t0/t1 were not preserved by the vector')
    if case==2 and (regs['x2']!='0x4' or not report['flags'] & 2):
        raise SystemExit('Invalid sp was not captured/degraded safely')
    memories=[r for r in report['records'] if r['type']==2]
    if case in (1,3) and (report['flags'] or len(memories)!=1 or
                         memories[0]['captured']!=memories[0]['requested'] or not memories[0]['captured']):
        raise SystemExit('Normal stack window was not captured completely')
    tasks=[r for r in report['records'] if r['type']==3]
    if {r['name'] for r in tasks}!={'worker','fault'}: raise SystemExit('Registered tasks missing')
    progress=[r['value'] for r in report['records'] if r['type']==4 and r['code']==3]
    if len(progress)!=1 or progress[0]<2: raise SystemExit('FreeRTOS tick/context switching not demonstrated')
    (OUT/(str(case)+'.bin')).write_bytes(data)
    (OUT/(str(case)+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    results.append({'case':case,'result':'PASS','mepc':regs['mepc'],'mcause':regs['mcause'],
                    'flags':report['flags'],'progress':progress[0],
                    'snapshot_sha256':hashlib.sha256(data).hexdigest(),
                    'elf_sha256':elf['elf_sha256'],'elapsed_s':time.monotonic()-start})
    print('QEMU case '+str(case)+' PASS')
matched=subprocess.run([sys.executable,str(ROOT/'tools/analyze.py'),str(OUT/'1.bin'),
                       '--elf',str(ROOT/'build/rv32/1/firmware.elf'),
                       '--json',str(OUT/'matched-report.json'),'--html',str(OUT/'report.html')],capture_output=True,text=True)
if matched.returncode: raise SystemExit('Matched ELF CLI failed: '+matched.stderr)
wrong=subprocess.run([sys.executable,str(ROOT/'tools/analyze.py'),str(OUT/'1.bin'),
                     '--elf',str(ROOT/'build/rv32/2/firmware.elf')],capture_output=True,text=True)
if wrong.returncode!=2 or 'firmware identity mismatch' not in wrong.stderr:
    raise SystemExit('Wrong ELF must be explicitly rejected')
(OUT/'wrong-elf.log').write_text(wrong.stderr)
(OUT/'manifest.json').write_text(json.dumps({'result':'PASS','qemu':version,'build':build,
    'cases':results,'matched_elf_cli':'PASS','wrong_elf_rejection':'PASS',
    'scope':'Single-hart RV32IMAC+Zicsr/Zifencei M-mode on QEMU virt. Physical hardware and persistence unverified.'},indent=2)+'\n')
print('QEMU_RV32_PASS: 3 captured faults + 1 explicit nested abort')
