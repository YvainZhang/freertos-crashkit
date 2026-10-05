#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Actual GDB end-to-end acceptance, run in the tool container or Linux host."""
import argparse
import hashlib
import json
from pathlib import Path
import select
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from analyze import parse
from postmortem import Snapshot


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dump',type=Path,default=ROOT/'evidence/qemu-rv32/1.bin')
    ap.add_argument('--elf',type=Path,default=ROOT/'build/rv32/1/firmware.elf')
    args=ap.parse_args()
    gdb=shutil.which('gdb-multiarch') or shutil.which('riscv64-unknown-elf-gdb')
    if not gdb: raise SystemExit('Install gdb-multiarch or run in the RV32 tool container')
    snapshot=Snapshot(parse(args.dump.read_bytes()),args.elf)
    out=ROOT/'evidence/gdb';out.mkdir(parents=True,exist_ok=True)
    original=hashlib.sha256(args.dump.read_bytes()).hexdigest()
    server=subprocess.Popen([sys.executable,str(ROOT/'tools/gdb_server.py'),str(args.dump),
        '--elf',str(args.elf),'--port','0','--writable','--execute'],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    start=time.monotonic()
    try:
        if not select.select([server.stdout],[],[],10)[0]: raise RuntimeError('GDB server startup timed out')
        line=server.stdout.readline().strip()
        if not line.startswith('CRASHKIT_GDB_LISTEN '): raise RuntimeError('GDB server failed: '+line)
        endpoint=line.split()[1]
        commands=['set pagination off','set confirm off','set print pretty off','set remotetimeout 10',
                  'target remote '+endpoint,'info threads','thread apply all bt',
                  'thread '+str(snapshot.current),'frame 1','info locals',
                  'p/x ck_example_global','printf "CSR_MCAUSE=%#x\\n", $mcause','p pxCurrentTCB->pcTaskName',
                  'frame 0','set $sp=0xe000fff0','call ck_debug_system()',
                  'set $sp=0xe000fff0','call ck_debug_tasks()',
                  'set $sp=0xe000fff0','call ck_debug_queue(ck_example_queue)',
                  'set $sp=0xe000fff0','call ck_debug_semaphore(ck_example_semaphore)',
                  'set $sp=0xe000fff0','call ck_debug_eventgroup(ck_example_event)',
                  'set $sp=0xe000fff0','call ck_debug_streambuffer(ck_example_stream)',
                  'set $sp=0xe000fff0','call ck_debug_timer(ck_example_timer)',
                  'set $sp=0xe000fff0','call ck_debug_heap()',
                  'monitor reset','set ck_example_global=0x2468ace0','p/x ck_example_global',
                  'monitor reset','p/x ck_example_global','detach','quit']
        command=[gdb,'-q','-nx','-batch',str(args.elf)]
        for text in commands: command+=['-ex',text]
        result=subprocess.run(command,capture_output=True,text=True,timeout=45,cwd=ROOT)
        log=result.stdout+'\n'+result.stderr
        (out/'session.log').write_text(log)
        (out/'server.log').write_text(line+'\n'+server.communicate(timeout=5)[1])
        if result.returncode: raise RuntimeError('GDB failed; see evidence/gdb/session.log')
        for text in ('worker','fault','suspended','IDLE','blocked','Tmr Svc','ck_fault_middle','ck_fault_leaf',
                     'system tick=','current=fault','stack_free_words=',
                     '0x13579bdf','0x2468ace0','local = 49','CSR_MCAUSE=0x2','Analysis copy reset'):
            if text not in log: raise RuntimeError('GDB did not demonstrate: '+text+'; see session.log')
        for error in ('Cannot access memory','Attempt to ','Could not fetch','unknown type',
                      'Remote failure','Virtual execution stopped:','Rejected:'):
            if error in log: raise RuntimeError('GDB command/unwind failed: '+error+'; see session.log')
        if hashlib.sha256(args.dump.read_bytes()).hexdigest()!=original:
            raise RuntimeError('Original snapshot changed')
        manifest=dict(result='PASS',gdb=subprocess.check_output([gdb,'--version'],text=True).splitlines()[0],
                      snapshot_sha256=original,elf_sha256=hashlib.sha256(args.elf.read_bytes()).hexdigest(),
                      features=['threads','all-task backtrace','locals','global variables','machine CSRs',
                                'GDB call eight virtual helpers','analysis writes','reset','original immutable'],
                      elapsed_s=time.monotonic()-start)
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print('GDB_PASS: threads, backtraces, locals, globals, ELF helper calls, writes/reset')
    finally:
        if server.poll() is None:
            server.terminate()
            try: server.wait(timeout=5)
            except subprocess.TimeoutExpired: server.kill();server.wait()


if __name__=='__main__': main()
