#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Known-state and corrupt-state acceptance using real captured RV32 artifacts."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from analyze import parse
from gdb_server import Remote
from import_dump import extract_log,encode_raw
from objects import Objects
from postmortem import Snapshot
from registers import decode_profile
from rv32 import CPU,CpuStop


def check(ok,message):
    if not ok:raise RuntimeError(message)


def main():
    dump=ROOT/'evidence/qemu-rv32/1.bin';elf=ROOT/'build/rv32/1/firmware.elf'
    data=dump.read_bytes();report=parse(data);out=ROOT/'evidence/offline';out.mkdir(parents=True,exist_ok=True)
    def fresh():return Snapshot(report,elf)
    s=fresh();summary=s.summary(shutil.which('riscv64-unknown-elf-addr2line'))
    for name in ('.crashkit_debug','.crashkit_debug_rodata'):
        section=s.elf.section(name)
        check(section and section['size'],'ELF helper section missing')
        a,b=section['address'],section['address']+section['size']
        check(all(b<=start or a>=start+size for start,_,size,_ in s.elf.segments),
              'ELF helper section overlaps device PT_LOAD')
    image=ROOT/'build/rv32/1/firmware.bin'
    check(image.stat().st_size<1024*1024,'virtual helper addresses leaked into binary')
    check(not s.diagnostics and len(s.tasks)==6,'normal task view failed')
    check(all(o['status']=='captured' for o in summary['objects']),'normal object view failed')
    check(extract_log((ROOT/'evidence/qemu-rv32/1.log').read_bytes())==data,'UART import changed data')
    low=s.elf.symbol('__capture_start');high=s.elf.symbol('__capture_end')
    registers=next(r['registers'] for r in report['records'] if r['type']==1)
    raw=encode_raw(s.memory.read(low,high-low),low,registers,s.elf.firmware_id)
    check(len(Snapshot(parse(raw),elf).tasks)==6,'raw RAM import lost tasks')
    objects={o['name']:o for o in summary['objects']}
    helpers=[('ck_debug_system',(),6),('ck_debug_tasks',(),6),
             ('ck_debug_queue',(int(objects['queue']['address'],16),),2),
             ('ck_debug_semaphore',(int(objects['semaphore']['address'],16),),2),
             ('ck_debug_eventgroup',(int(objects['event']['address'],16),),5),
             ('ck_debug_streambuffer',(int(objects['stream']['address'],16),),8),
             ('ck_debug_timer',(int(objects['timer']['address'],16),),100),
             ('ck_debug_heap',(),objects['heap']['free_bytes'])]
    helper_results=[]
    for function,args,expected in helpers:
        s=fresh();output=[];cpu=CPU(s.memory,s.tasks[s.current-1]['registers'],output.append)
        value=cpu.call(s.elf.symbol(function),args)
        check(value==expected,'virtual helper result mismatch: '+function)
        helper_results.append(dict(function=function,value=value,instructions=cpu.steps,output=''.join(output)))
    # A broken list cannot produce a clean all-task claim.
    s=fresh();l=s.layout;head=l['ready']+l['list_end']
    s.memory.write(head+l['next'],head.to_bytes(4,'little'))
    s.tasks=[];s.diagnostics=[];s._tasks()
    check(s.diagnostics,'damaged task list was silently accepted')
    # Saved task SP outside the recorded stack gives unavailable registers.
    s=fresh();t=next(t for t in s.tasks if t['name']=='suspended')
    s.memory.write(t['handle']+s.layout['top'],(4).to_bytes(4,'little'))
    s.tasks=[];s.diagnostics=[];s._tasks()
    t=next(t for t in s.tasks if t['name']=='suspended')
    check(t['diagnostics'] and t['registers'][32] is None,'bad saved context was fabricated')
    # Free-list cycle is bounded and reported separately from other objects.
    s=fresh();decoder=Objects(s)
    first=decoder.scalar('BlockLink_t',s.elf.symbol('xStart'),'pxNextFreeBlock')
    offset,_=decoder.types.member('BlockLink_t','pxNextFreeBlock')
    s.memory.write(first+offset,first.to_bytes(4,'little'))
    heap=next(o for o in decoder.report() if o['name']=='heap')
    check(heap['status']=='unavailable/corrupt','heap cycle was silently accepted')
    # Missing queue memory and corrupt event CRC must stay visible.
    s=fresh();s.memory.write(s.elf.symbol('ck_example_queue'),(4).to_bytes(4,'little'))
    check(next(o for o in Objects(s).report() if o['name']=='queue')['status']=='unavailable/corrupt','bad queue accepted')
    s=fresh();address=int(objects['trace']['address'],16)+8+20
    s.memory.write(address,(s.memory.u32(address)^1).to_bytes(4,'little'))
    check(next(o for o in Objects(s).report() if o['name']=='trace')['rejected_slots']==[0],'trace CRC ignored')
    # Read-only remote and cyclic virtual code cannot mutate/run indefinitely.
    s=fresh();remote=Remote(s)
    check(remote.handle('M'+hex(low)[2:]+',1:00')=='E01' and remote.handle('c')=='E01','readonly contract failed')
    s.memory.write(0xe0000000,struct.pack('<I',0x0000006f));regs=[0]*33;regs[32]=0xe0000000
    try:CPU(s.memory,regs).run(100)
    except CpuStop as error:check('budget' in str(error),'wrong loop rejection')
    else:raise RuntimeError('virtual loop did not stop')
    profile={'version':1,'registers':[{'name':'uart_lsr','fields':[{'name':'tx_empty','mask':'0x20','shift':5}]}],
             'clocks':[{'name':'cpu','source_register':'cpu_clock_hz'},
                       {'name':'bus','parent':'cpu','divider':2},
                       {'name':'unknown','source_register':'not_captured'}]}
    hardware=decode_profile(summary['objects'],profile)
    check(hardware['registers'][0]['fields'][0]['value']==1,'UART register field decode failed')
    rates={c['name']:c['hz'] for c in hardware['clocks']}
    check(rates=={'cpu':10000000,'bus':5000000,'unknown':None},'clock profile/missing sample handling failed')
    check(hashlib.sha256(dump.read_bytes()).hexdigest()==hashlib.sha256(data).hexdigest(),'original dump changed')
    (out/'report.json').write_text(json.dumps(summary,indent=2)+'\n')
    (out/'virtual-helpers.json').write_text(json.dumps(helper_results,indent=2)+'\n')
    manifest=dict(result='PASS',snapshot_sha256=hashlib.sha256(data).hexdigest(),
                  elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
                  checks=['UART/raw import','ELF-only helper exclusion','six task contexts','ten object catalog entries','eight ELF helpers',
                          'damaged task list','bad saved SP','cyclic heap','missing queue RAM','bad trace CRC',
                          'read-only server','instruction limit','register/clock profile','original immutable'])
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('OFFLINE_PASS: tasks, objects, import, virtual helpers, corrupt-state rejection')


if __name__=='__main__':main()
