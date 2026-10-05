#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only task reconstruction, symbolication and bounded RV32 frame-chain unwind."""
import shutil
import struct
import subprocess

from elf_image import ElfImage, Memory, require

LAYOUT_NAMES = (
    'magic version pointer_bytes stack_word_bytes major minor patch current task_count tick scheduler '
    'ready list_size priorities delayed1 delayed2 suspended deleted pending tcb_size top state_item '
    'event_item priority stack name name_size stack_end list_count list_end next previous owner '
    'container item_size downward context_profile').split()


class Snapshot:
    def __init__(self, report, elf_path):
        self.report = report
        self.elf_path = str(elf_path)
        self.elf = ElfImage(elf_path)
        require(report['architecture'] == 'rv32' and report['pointer_bits'] == 32 and
                report['source_endian'] == 1, 'offline debugging requires little-endian RV32')
        require(report['firmware_id'] == self.elf.firmware_id, 'firmware identity mismatch')
        self.memory = Memory(report, self.elf)
        regs = [r for r in report['records'] if r['type'] == 1 and len(r['registers']) == 36]
        require(len(regs) == 1, 'requires one complete-shaped RV32 exception register record')
        self.registers = [int(regs[0]['registers']['x'+str(i)],16)
                          if regs[0]['registers']['x'+str(i)] is not None else None for i in range(32)]
        value = regs[0]['registers']['mepc']
        self.registers.append(int(value,16) if value is not None else None)
        self.csrs={name:int(regs[0]['registers'][name],16) if regs[0]['registers'][name] is not None else None
                   for name in ('mstatus','mepc','mcause','mtval')}
        self.diagnostics = []
        self.tasks = []
        self.system = None
        self.layout = None
        self.irq_bounds = None
        try:
            low,high=self.elf.symbol('__irq_stack_bottom'),self.elf.symbol('__stack_top')
            require(low < high <= 1 << 32 and high-low <= 256*1024,'invalid IRQ stack bounds')
            self.irq_bounds=(low,high)
        except ValueError:
            pass  # Other integrations may omit the reference board's symbols.
        sp=self.registers[2]
        self.exception_in_irq = self.irq_bounds is not None and sp is not None and self.irq_bounds[0] <= sp < self.irq_bounds[1]
        section = self.elf.section('.crashkit_layout')
        if section:
            self._layout(section['data'])
            self._tasks()
        if not self.tasks:
            self.tasks = [dict(handle=0, name='exception', state='Unknown', registers=self.registers[:],
                               stack_address=None, stack_bytes=None, context='exception', diagnostics=[],csrs=self.csrs.copy())]
        self.current = next((i+1 for i,t in enumerate(self.tasks) if t['context'] == 'exception'), 1)
        self.pristine_registers = [t['registers'][:] for t in self.tasks]
        self.pristine_csrs = [t['csrs'].copy() for t in self.tasks]

    def _layout(self, data):
        require(len(data) == len(LAYOUT_NAMES)*4, 'invalid FreeRTOS layout size')
        l = dict(zip(LAYOUT_NAMES,struct.unpack('<'+'I'*len(LAYOUT_NAMES),data)))
        require(l['magic'] == 0x314c4b43 and l['version'] == 1 and
                l['pointer_bytes'] == l['stack_word_bytes'] == 4 and
                (l['major'],l['minor'],l['patch']) == (11,1,0) and
                l['downward'] == l['context_profile'] == 1, 'unsupported kernel/context layout')
        require(0 < l['priorities'] <= 64 and 0 < l['tcb_size'] <= 4096 and
                0 < l['name_size'] <= 256 and 0 < l['list_size'] <= 256 and
                0 < l['item_size'] <= 256, 'invalid layout bounds')
        for field in ('top','priority','stack','stack_end'):
            require(l[field]+4 <= l['tcb_size'], 'TCB offset outside type')
        require(l['name']+l['name_size'] <= l['tcb_size'] and
                l['state_item']+l['item_size'] <= l['tcb_size'] and
                l['event_item']+l['item_size'] <= l['tcb_size'], 'invalid TCB fields')
        for field in ('next','previous','owner','container'):
            require(l[field]+4 <= l['item_size'], 'invalid list item offsets')
        require(l['list_end']+l['previous']+4 <= l['list_size'] and
                l['list_count']+4 <= l['list_size'], 'invalid list offsets')
        self.layout = l

    def _tasks(self):
        m, l = self.memory, self.layout
        try:
            self.system = dict(current_tcb=hex(m.u32(l['current'])), tick=m.u32(l['tick']),
                               task_count=m.u32(l['task_count']), scheduler_running=m.u32(l['scheduler']))
            require(self.system['task_count'] <= 256, 'kernel task count exceeds analysis limit')
            current = int(self.system['current_tcb'],16)
        except ValueError as error:
            self.diagnostics.append('system: '+str(error))
            return
        lists = [(l['ready']+i*l['list_size'],'Ready') for i in range(l['priorities'])]
        lists += [(l[n],state) for n,state in (('delayed1','Blocked'),('delayed2','Blocked'),
                   ('suspended','Suspended'),('deleted','Deleted')) if l[n]]
        owners = set()
        for address, state in lists:
            try:
                count = m.u32(address+l['list_count'])
                require(count <= 16, 'list count exceeds 16-task capture policy')
                end = address+l['list_end']
                item = m.u32(end+l['next'])
                previous = end
                for _ in range(count):
                    require(item != end and item % 4 == 0, 'short/unaligned task list')
                    require(m.u32(item+l['previous']) == previous and
                            m.u32(item+l['container']) == address, 'damaged task list links')
                    handle = m.u32(item+l['owner'])
                    require(handle and handle+l['state_item'] == item and handle not in owners,
                            'duplicate/invalid task owner')
                    require(len(self.tasks) < 16, 'total task count exceeds capture policy')
                    # Validate entire TCB before using selected fields.
                    m.read(handle,l['tcb_size'])
                    name = m.read(handle+l['name'],l['name_size'])
                    require(b'\0' in name, 'unterminated task name')
                    base, high = m.u32(handle+l['stack']), m.u32(handle+l['stack_end'])
                    require(base % 4 == 0 and high % 4 == 0 and base <= high and
                            high-base+4 <= 256*1024 and high+4 <= 1 << 32, 'invalid task stack range')
                    actual = 'Running' if handle == current else state
                    if actual == 'Suspended' and m.u32(handle+l['event_item']+l['container']):
                        actual = 'Blocked'  # Infinite object wait uses the suspended list.
                    separate_exception = self.exception_in_irq
                    t = dict(handle=handle, name=name.split(b'\0')[0].decode('utf-8','replace'),
                             state=actual, priority=m.u32(handle+l['priority']), stack_address=base,
                             stack_bytes=high-base+4, context='exception' if handle == current and not separate_exception else 'saved',
                             diagnostics=[], registers=[None]*33,csrs={name:None for name in self.csrs})
                    require(t['priority'] < l['priorities'], 'task priority outside configuration')
                    try:
                        if handle == current and not separate_exception:
                            t['registers'] = self.registers[:]
                            t['csrs'] = self.csrs.copy()
                            if self.registers[2] is None or not base <= self.registers[2] <= high+4:
                                t['diagnostics'].append('exception SP outside task stack; origin unknown or SP damaged')
                        else:
                            sp = m.u32(handle+l['top'])
                            require(sp % 4 == 0 and base <= sp and sp+124 <= high+4,
                                    'saved context outside task stack')
                            values = struct.unpack('<31I',m.read(sp,124))
                            regs = t['registers']
                            regs[0],regs[1],regs[2],regs[32] = 0,values[1],sp+124,values[0]
                            # Official integer port treats gp/tp as constant across tasks.
                            regs[3],regs[4] = self.registers[3],self.registers[4]
                            for reg in range(5,32): regs[reg] = values[reg-3]
                            t['csrs'].update(mstatus=values[30],mepc=values[0])
                        free = 0
                        for offset in range(0,t['stack_bytes'],256):
                            data = m.read(base+offset,min(256,t['stack_bytes']-offset))
                            n = next((i for i,b in enumerate(data) if b != 0xa5),len(data))
                            free += n
                            if n < len(data): break
                        t['stack_free_words'] = free//4
                    except ValueError as error:
                        t['diagnostics'].append(str(error))
                    self.tasks.append(t)
                    owners.add(handle)
                    previous,item = item,m.u32(item+l['next'])
                require(item == end and m.u32(end+l['previous']) == previous, 'list length/end mismatch')
            except ValueError as error:
                self.diagnostics.append(state+' list '+hex(address)+': '+str(error))
        if not any(t['handle'] == current for t in self.tasks):
            self.tasks.insert(0,dict(handle=current,name='exception (task unresolved)',state='Unknown',
                stack_address=None,stack_bytes=None,context='saved' if self.exception_in_irq else 'exception',
                diagnostics=['current task unresolved'],registers=[None]*33 if self.exception_in_irq else self.registers[:],
                csrs={name:None for name in self.csrs} if self.exception_in_irq else self.csrs.copy()))
        live = sum(t['state'] != 'Deleted' for t in self.tasks)
        if live != self.system['task_count']:
            self.diagnostics.append('task count mismatch; task view is incomplete')
        if self.exception_in_irq:
            base,end=self.irq_bounds
            self.tasks.append(dict(handle=0,name='overflow hook (ISR)' if self.report['reason']==4 else 'ISR exception',state='Exception',
                stack_address=base,stack_bytes=end-base,context='exception',diagnostics=[],registers=self.registers[:],csrs=self.csrs.copy()))
        try:
            if m.u32(l['pending']+l['list_count']):
                self.diagnostics.append('pending-ready list nonempty; scheduler transition in progress')
        except ValueError as error:
            self.diagnostics.append('pending-ready: '+str(error))

    def reset(self):
        self.memory.reset()
        for t, regs in zip(self.tasks,self.pristine_registers): t['registers'] = regs[:]
        for t, csrs in zip(self.tasks,self.pristine_csrs): t['csrs'] = csrs.copy()

    def backtrace(self, task, limit=32):
        require(1 <= limit <= 64, 'invalid frame limit')
        regs = task['registers']
        pc, fp, sp = regs[32],regs[8],regs[2]
        frames, seen = [],set()
        reason = 'frame limit reached'
        if pc is None:
            return dict(frames=[],method='rv32-frame-pointer',stopped='PC unavailable')
        for index in range(limit):
            frames.append(dict(index=index,pc=hex(pc),**self.elf.locate(pc if index==0 else max(0,pc-1))))
            if not fp:
                reason = 'frame pointer unavailable/end'; break
            if task['stack_address'] is None:
                reason = 'task stack bounds unavailable'; break
            base, end = task['stack_address'],task['stack_address']+task['stack_bytes']
            if fp in seen or fp % 4 or not base+8 <= fp <= end or sp is None or not base <= sp <= end or fp < sp:
                reason = 'invalid/cyclic frame chain'; break
            seen.add(fp)
            try:
                previous,ra = struct.unpack('<II',self.memory.read(fp-8,8))
            except ValueError as error:
                reason = str(error); break
            if not ra:
                reason = 'return address unavailable/end'; break
            if not self.elf.locate(max(0,ra-1))['function']:
                reason = 'return address outside known code'; break
            if previous and (previous <= fp or previous % 4 or not base+8 <= previous <= end):
                reason = 'previous frame outside stack/non-increasing'; break
            sp,fp,pc = fp,previous,ra
        return dict(frames=frames,method='rv32-frame-pointer',stopped=reason,
                    contract='Requires ABI frame chains; no stack-scanning guesses. Use GDB/DWARF for other builds.')

    def summary(self, addr2line=None):
        tasks=[]
        tool = addr2line or shutil.which('riscv64-unknown-elf-addr2line')
        for t in self.tasks:
            item = {k:v for k,v in t.items() if k != 'registers'}
            item['handle'] = hex(t['handle'])
            item['backtrace'] = self.backtrace(t)
            if tool:
                pcs=[hex(max(0,int(f['pc'],16)-(f['index']!=0))) for f in item['backtrace']['frames']]
                result = subprocess.run([tool,'-f','-e',self.elf_path,*pcs],capture_output=True,text=True,timeout=10)
                require(result.returncode == 0, 'addr2line failed: '+result.stderr[:256])
                lines=result.stdout.splitlines()
                require(len(lines) == 2*len(pcs), 'unexpected addr2line output')
                for i,frame in enumerate(item['backtrace']['frames']):
                    frame['source'] = lines[2*i+1]
            else:
                item['source_status'] = 'addr2line unavailable; GDB can use ELF DWARF'
            tasks.append(item)
        from objects import Objects
        return dict(system=self.system,tasks=tasks,diagnostics=self.diagnostics,objects=Objects(self).report(),
                    memory_regions=[dict(address=hex(a),bytes=len(b),source=s) for a,b,s in self.memory.regions],
                    scope='Frozen kernel view; corrupt/missing memory is explicit. No automatic root cause.')
