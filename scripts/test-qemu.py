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
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from postmortem import Snapshot
from rv32 import CPU

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
case_numbers=[c['case'] for c in build['cases']]
if sorted(case_numbers)!=list(range(1,8)):raise SystemExit('Build must contain exactly seven reference cases')
for case in case_numbers:
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
        print('QEMU case 4 PASS (explicit nested abort)')
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
    label={5:'ck_assert_fault',6:'ck_overflow_fault',7:'ck_isr_fault'}.get(case,'ck_injected_fault')
    if int(regs['mepc'],16)!=symbols[label]:
        raise SystemExit('Fault PC does not match injected instruction')
    if int(regs['mcause'],16)!=(3 if case in (5,6) else 5 if case==3 else 2): raise SystemExit('Unexpected fault cause')
    if report['reason']!={5:2,6:4}.get(case,3):raise SystemExit('Unexpected capture reason')
    if case==1 and (regs['x5']!='0x12345678' or regs['x6']!='0x76543210'):
        raise SystemExit('t0/t1 were not preserved by the vector')
    if case==2 and (regs['x2']!='0x4' or not report['flags'] & 2):
        raise SystemExit('Invalid sp was not captured/degraded safely')
    memories=[r for r in report['records'] if r['type']==2]
    if case in (1,3,5,6,7) and (report['flags'] or len(memories)<2 or
                         memories[0]['captured']!=memories[0]['requested'] or not memories[0]['captured']):
        raise SystemExit('Normal stack window was not captured completely')
    tasks=[r for r in report['records'] if r['type']==3]
    if {r['name'] for r in tasks}!={'worker','fault'}: raise SystemExit('Registered tasks missing')
    progress=[r['value'] for r in report['records'] if r['type']==4 and r['code']==3]
    if len(progress)!=1 or progress[0]<2: raise SystemExit('FreeRTOS tick/context switching not demonstrated')
    (OUT/(str(case)+'.bin')).write_bytes(data)
    (OUT/(str(case)+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    snapshot=Snapshot(report,directory/'firmware.elf')
    expected_tasks={'worker','fault','suspended','blocked','Tmr Svc','IDLE'}
    if case==6:expected_tasks.add('overflow hook (ISR)')
    if case==7:expected_tasks.add('ISR exception')
    if {t['name'] for t in snapshot.tasks}!=expected_tasks or snapshot.diagnostics:
        raise SystemExit('Offline task reconstruction incomplete: '+str(snapshot.summary()))
    if snapshot.system['tick']<10 or snapshot.system['task_count']!=6:
        raise SystemExit('System state did not match the injected scenario')
    if next(t for t in snapshot.tasks if t['name']=='suspended')['state']!='Suspended':
        raise SystemExit('Suspended task state was not reconstructed')
    if next(t for t in snapshot.tasks if t['name']=='blocked')['state']!='Blocked':
        raise SystemExit('Indefinite queue wait was mistaken for explicit suspension')
    if case==6 and (next(t for t in snapshot.tasks if t['name']=='fault')['context']!='saved' or
                   next(t for t in snapshot.tasks if t['name']=='fault')['stack_free_words']!=0):
        raise SystemExit('Overflow hook context was confused with the interrupted task')
    if case==7 and (not snapshot.exception_in_irq or snapshot.tasks[snapshot.current-1]['name']!='ISR exception' or
                   any(t['context']!='saved' for t in snapshot.tasks if t['handle'])):
        raise SystemExit('Timer ISR context was confused with a task context')
    current=snapshot.tasks[snapshot.current-1]
    if case==1:
        names=[f['function'] for f in snapshot.backtrace(current)['frames']]
        if len(names)!=3 or names[0]!='ck_fault_leaf' or not names[1].startswith('ck_fault_middle') or names[2]!='fault':
            raise SystemExit('Multi-frame backtrace did not match known call path: '+str(names))
    for function in ('ck_debug_system','ck_debug_tasks'):
        snapshot.reset(); text=[]
        cpu=CPU(snapshot.memory,snapshot.tasks[snapshot.current-1]['registers'],text.append)
        value=cpu.call(snapshot.elf.symbol(function))
        content=''.join(text)
        current_name=next(t['name'] for t in snapshot.tasks if hex(t['handle'])==snapshot.system['current_tcb'])
        if value!=6 or (('current='+current_name) not in content if function=='ck_debug_system' else
                        not all(n in content for n in ('worker','fault','suspended','IDLE'))):
            raise SystemExit('ELF virtual helper failed: '+function+' '+content)
        (OUT/(str(case)+'-'+function+'.log')).write_text(content)
    snapshot.reset()
    analysis=snapshot.summary()
    if any(o['status']!='captured' for o in analysis['objects']) or len(analysis['objects'])!=10:
        raise SystemExit('Object analysis incomplete: '+str(analysis['objects']))
    objects={o['name']:o for o in analysis['objects']}
    if objects['queue']['items_hex']!=['44332211','88776655'] or objects['semaphore']['messages']!=2 or \
       objects['event']['bits']!='0x5' or objects['stream']['bytes_hex']!='63726173686b6974' or \
       objects['timer']['period_ticks']!=100 or not objects['timer']['active'] or \
       [t['name'] for t in objects['wait_queue']['waiting_to_receive']]!=['blocked'] or \
       len(objects['trace']['events'])!=3:
        raise SystemExit('Object contents did not match known injected state')
    (OUT/(str(case)+'-analysis.json')).write_text(json.dumps(analysis,indent=2)+'\n')
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
    'offline_tasks':'PASS','frame_chain':'PASS (case 1, exactly three frames)',
    'virtual_helpers':'PASS (cases 1, 2, 3, 5, 6, 7)','isr_context':'PASS (cases 6, 7)',
    'scope':'Single-hart RV32IMAC+Zicsr/Zifencei M-mode on QEMU virt. Physical hardware and persistence unverified.'},indent=2)+'\n')
print('QEMU_RV32_PASS: 4 CPU faults (including ISR) + nested abort + assert + real stack-canary hook')
