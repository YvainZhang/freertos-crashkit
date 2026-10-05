#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Loopback GDB remote server for an immutable snapshot and an optional analysis copy."""
import argparse
import json
from pathlib import Path
import socket
import struct
import sys
import xml.sax.saxutils as xml

from analyze import parse, MAX_DUMP
from elf_image import require
from postmortem import Snapshot
from rv32 import CPU, CpuStop

ABI_NAMES = ('zero ra sp gp tp t0 t1 t2 fp s1 a0 a1 a2 a3 a4 a5 a6 a7 '
             's2 s3 s4 s5 s6 s7 s8 s9 s10 s11 t3 t4 t5 t6 pc').split()
CSR_NAMES = ('mstatus','mepc','mcause','mtval')
CSR_NUMBERS = (0x300,0x341,0x342,0x343)


def target_xml():
    regs = ''.join('<reg name="'+n+'" bitsize="32" regnum="'+str(i)+'" type="'+
                   ('code_ptr' if i == 32 else 'data_ptr' if i in (2,3,8) else 'int')+'"/>'
                   for i,n in enumerate(ABI_NAMES))
    csrs=''.join('<reg name="%s" bitsize="32" regnum="%d" type="int"/>' % (n,i+33) for i,n in enumerate(CSR_NAMES))
    return ('<?xml version="1.0"?><!DOCTYPE target SYSTEM "gdb-target.dtd">'
            '<target><architecture>riscv:rv32</architecture>'
            '<feature name="org.gnu.gdb.riscv.cpu">'+regs+'</feature>'
            '<feature name="org.gnu.gdb.riscv.csr">'+csrs+'</feature></target>')


class Remote:
    def __init__(self, snapshot, writable=False, execute=False, limit=2000000):
        require(not execute or writable, 'execution requires an analysis copy (--writable)')
        require(0 < limit <= 2000000,'invalid instruction limit')
        self.snapshot,self.writable,self.execute,self.limit = snapshot,writable,execute,limit
        self.selected = self.running = snapshot.current
        self.breakpoints = set()
        self.no_ack = False
        self.closed = False
        self.output = []
        self.output_size = 0
        self.cpus = {}

    def regs(self):
        return self.snapshot.tasks[self.selected-1]['registers']

    def values(self):
        csrs=self.snapshot.tasks[self.selected-1].get('csrs',{})
        if self.selected in self.cpus:
            values=[self.cpus[self.selected].csrs.get(n) for n in CSR_NUMBERS]
        else:values=[csrs.get(n) for n in CSR_NAMES]
        return self.regs()+values

    def write_register(self,n,value):
        if n<33:
            if n:self.regs()[n]=value
        else:
            name=CSR_NAMES[n-33]
            self.snapshot.tasks[self.selected-1].setdefault('csrs',{})[name]=value
            if self.selected in self.cpus:self.cpus[self.selected].csrs[CSR_NUMBERS[n-33]]=value

    def stop(self, signal=5):
        return 'T%02xthread:%x;' % (signal,self.selected)

    def emit(self, text):
        require(self.output_size+len(text) <= 65536,'console output limit exceeded')
        self.output.append(text)
        self.output_size += len(text)

    @staticmethod
    def encode(value):
        return 'xxxxxxxx' if value is None else struct.pack('<I',value).hex()

    @staticmethod
    def number(text):
        require(0 < len(text) <= 8 and all(c in '0123456789abcdefABCDEF' for c in text),
                'invalid protocol integer')
        return int(text,16)

    def _thread(self, text):
        if text in ('-1','0'): return self.selected
        value=self.number(text)
        require(1 <= value <= len(self.snapshot.tasks),'unknown thread')
        return value

    def _xfer(self, text, data):
        data=data.encode('ascii','xmlcharrefreplace').decode('ascii')
        offset,length=text.rsplit(':',1)[1].split(',')
        offset,length=self.number(offset),self.number(length)
        require(0 < length <= 4096,'invalid XML transfer length')
        return ('m' if offset+length < len(data) else 'l')+data[offset:offset+length]

    def monitor(self, command):
        command=command.strip()
        if command == 'reset':
            self.snapshot.reset(); self.cpus.clear(); self.breakpoints.clear()
            self.selected=self.running=self.snapshot.current
            self.emit('Analysis copy reset; original snapshot unchanged.\n')
        elif command in ('system','tasks','bt','objects'):
            if command == 'system': data=self.snapshot.system
            elif command == 'tasks': data=[{k:v for k,v in t.items() if k != 'registers'} for t in self.snapshot.tasks]
            elif command == 'bt': data=self.snapshot.backtrace(self.snapshot.tasks[self.selected-1])
            else:
                from objects import Objects
                data=Objects(self.snapshot).report()
            self.emit(json.dumps(data,indent=2)+'\n')
        elif command.startswith('call '):
            require(self.execute,'virtual execution disabled')
            words=command.split(); require(2 <= len(words) <= 10,'usage: monitor call symbol [integer args]')
            cpu=self.cpu()
            value=cpu.call(self.snapshot.elf.symbol(words[1]),[int(x,0) for x in words[2:]],self.limit)
            self.emit('\nreturn='+hex(value)+' instructions='+str(cpu.steps)+'\n')
        elif command == 'help':
            self.emit('monitor system | tasks | objects | bt | reset | call symbol [args]\n'
                      'Writes/execution affect only the analysis copy; missing RAM is never synthesized.\n')
        else: raise ValueError('unknown monitor command')

    def cpu(self):
        if self.selected not in self.cpus:
            self.cpus[self.selected]=CPU(self.snapshot.memory,self.regs(),self.emit)
            csrs=self.snapshot.tasks[self.selected-1].get('csrs',{})
            for name,number in zip(CSR_NAMES,CSR_NUMBERS):self.cpus[self.selected].csrs[number]=csrs.get(name)
        return self.cpus[self.selected]

    def handle(self, packet):
        self.output=[]
        self.output_size=0
        try:
            return self._handle(packet)
        except (ValueError,IndexError,OverflowError,struct.error) as error:
            if self.output_size > 65000:
                self.output=[];self.output_size=0
            self.emit('Rejected: '+str(error)+'\n')
            return 'E01'

    def _handle(self, p):
        if p == '?': return self.stop()
        if p.startswith('qSupported'):
            return 'PacketSize=4000;qXfer:features:read+;qXfer:threads:read+;QStartNoAckMode+;swbreak+'
        if p == 'QStartNoAckMode': self.no_ack=True; return 'OK'
        if p.startswith('qXfer:features:read:target.xml:'): return self._xfer(p,target_xml())
        if p.startswith('qXfer:threads:read::'):
            data='<threads>'+''.join('<thread id="%x" core="0" name="%s"/>' %
                 (i+1,xml.escape(t['name'],{'"':'&quot;'})) for i,t in enumerate(self.snapshot.tasks))+'</threads>'
            return self._xfer(p,data)
        if p == 'qfThreadInfo': return 'm'+','.join('%x' % (i+1) for i in range(len(self.snapshot.tasks)))
        if p == 'qsThreadInfo': return 'l'
        if p.startswith('qThreadExtraInfo,'):
            t=self.snapshot.tasks[self._thread(p.split(',')[1])-1]
            return (t['name']+' '+t['state']).encode().hex()
        if p == 'qC': return 'QC%x' % self.selected
        if p in ('qAttached','qAttached:1'): return '1'
        if p.startswith('H'):
            thread=self._thread(p[2:]); require(p[1] in ('c','g'),'invalid thread selector')
            if p[1] == 'g': self.selected=thread
            else: self.running=thread
            return 'OK'
        if p.startswith('T'): self._thread(p[1:]); return 'OK'
        if p == 'g': return ''.join(self.encode(v) for v in self.values())
        if p.startswith('p'):
            n=self.number(p[1:]); require(n < 37,'unknown register'); return self.encode(self.values()[n])
        if p.startswith(('G','P')):
            require(self.writable,'read-only snapshot; enable --writable for an analysis copy')
            if p[0] == 'G':
                require(len(p[1:]) == 37*8,'invalid register block')
                values=[]
                for i in range(37):
                    h=p[1+8*i:1+8*(i+1)]
                    values.append(None if h == 'xxxxxxxx' else int.from_bytes(bytes.fromhex(h),'little'))
                for i,value in enumerate(values):self.write_register(i,value)
                self.regs()[0]=0
            else:
                n,value=p[1:].split('='); n=self.number(n)
                require(n < 37 and len(value) == 8,'invalid register write')
                v=int.from_bytes(bytes.fromhex(value),'little')
                self.write_register(n,v)
            return 'OK'
        if p.startswith('m'):
            a,n=p[1:].split(','); n=self.number(n); require(n <= 4096,'memory packet too large')
            return self.snapshot.memory.read(self.number(a),n).hex()
        if p.startswith('M'):
            require(self.writable,'read-only snapshot')
            request,data=p[1:].split(':'); a,n=request.split(','); data=bytes.fromhex(data)
            require(len(data) == self.number(n) and len(data) <= 4096,'invalid memory write')
            self.snapshot.memory.write(self.number(a),data); return 'OK'
        if p.startswith(('Z0,','z0,','Z1,','z1,')):
            _,a,n=p.split(','); address=self.number(a)
            require(self.execute and self.number(n) in (2,4),'breakpoints require virtual execution')
            self.snapshot.memory.read(address,self.number(n))
            if p[0] == 'Z':
                require(len(self.breakpoints) < 128,'breakpoint limit'); self.breakpoints.add(address)
            else: self.breakpoints.discard(address)
            return 'OK'
        if p == 'vCont?': return 'vCont;c;s' if self.execute else ''
        if p.startswith(('c','s','vCont;')):
            require(self.execute,'virtual execution disabled')
            if p.startswith('vCont;'):
                action=p.split(';')[1]; operation,_,thread=action.partition(':')
                require(operation in ('c','s') and p.count(';') == 1,'unsupported resume action')
                if thread: self.selected=self._thread(thread)
            else:
                operation=p[0]
                if len(p)>1: self.regs()[32]=self.number(p[1:])
            try:
                self.cpu().run(self.limit,self.breakpoints,single=operation=='s')
                return self.stop()
            except ValueError as error:
                self.emit('Virtual execution stopped: '+str(error)+'\n')
                return self.stop(5 if isinstance(error,CpuStop) and str(error)=='breakpoint' else 11)
        if p.startswith('qRcmd,'):
            command=bytes.fromhex(p.split(',')[1]).decode('ascii'); require(len(command)<=512,'monitor too long')
            self.monitor(command); return 'OK'
        if p.startswith('D'): self.closed=True; return 'OK'
        if p in ('k','vKill;1'): self.closed=True; return 'OK'
        return ''  # Standard reply for unsupported optional packets.


def frame(payload):
    raw=payload.encode('utf-8')
    escaped=bytearray()
    for b in raw:
        if b in b'$#}*': escaped.extend((125,b^32))
        else: escaped.append(b)
    return b'$'+escaped+b'#'+('%02x' % (sum(escaped)&255)).encode()


def serve_connection(connection, remote):
    connection.settimeout(600)
    last=b''
    def send(text):
        nonlocal last
        last=frame(text); connection.sendall(last)
    while not remote.closed:
        start=connection.recv(1)
        if not start: break
        if start == b'-':
            if last: connection.sendall(last)
            continue
        if start == b'\x03': send(remote.stop(2)); continue
        if start != b'$': continue
        data=bytearray()
        while True:
            b=connection.recv(1)
            if not b: return
            if b == b'#': break
            data.extend(b)
            require(len(data) <= 16384,'packet exceeds limit')
        check=bytearray()
        while len(check)<2:
            b=connection.recv(2-len(check))
            if not b: return
            check.extend(b)
        try: valid=int(check,16)==sum(data)&255
        except ValueError: valid=False
        if not valid:
            if not remote.no_ack: connection.sendall(b'-')
            continue
        old_no_ack=remote.no_ack
        if not old_no_ack: connection.sendall(b'+')
        decoded=bytearray(); escaped=False
        for b in data:
            if escaped: decoded.append(b^32); escaped=False
            elif b==125: escaped=True
            else: decoded.append(b)
        if escaped: send('E01'); continue
        try: packet=decoded.decode('ascii')
        except UnicodeDecodeError: send(''); continue
        reply=remote.handle(packet)
        # Console packets are legal while executing/monitoring, not in response
        # to register/memory/XML requests (GDB would mistake them for the reply).
        if packet.startswith(('qRcmd,','c','s','vCont;')):
            for text in remote.output:
                for off in range(0,len(text),1024): send('O'+text[off:off+1024].encode().hex())
        elif remote.output:
            print('Protocol '+packet[:128]+': '+''.join(remote.output).strip(),file=sys.stderr,flush=True)
        send(reply)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('dump',type=Path); ap.add_argument('--elf',required=True,type=Path)
    ap.add_argument('--port',type=int,default=6000)
    ap.add_argument('--writable',action='store_true'); ap.add_argument('--execute',action='store_true')
    ap.add_argument('--instruction-limit',type=int,default=2000000)
    args=ap.parse_args()
    try:
        require(0 <= args.port <= 65535,'invalid port')
        require(args.dump.stat().st_size <= MAX_DUMP,'snapshot exceeds input limit')
        snapshot=Snapshot(parse(args.dump.read_bytes()),args.elf)
        remote=Remote(snapshot,args.writable,args.execute,args.instruction_limit)
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            server.bind(('127.0.0.1',args.port)); server.listen(1)
            print('CRASHKIT_GDB_LISTEN 127.0.0.1:'+str(server.getsockname()[1]),flush=True)
            connection,_=server.accept()
            with connection: serve_connection(connection,remote)
    except (ValueError,OSError) as error:
        ap.exit(2,'Rejected: '+str(error)+'\n')
    except KeyboardInterrupt:
        pass


if __name__ == '__main__': main()
