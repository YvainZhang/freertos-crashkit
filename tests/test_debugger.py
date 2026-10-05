# SPDX-License-Identifier: MIT
from pathlib import Path
import struct
import sys
import unittest
from types import SimpleNamespace
import socket
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from elf_image import Memory
from gdb_server import Remote, frame, serve_connection
from registers import decode_profile
from import_dump import encode_raw, extract_log
from analyze import parse
from rv32 import CPU, CpuStop
from dwarf_types import DwarfTypes


def memory():
    return Memory({'records':[]},SimpleNamespace(segments=[],section=lambda name:None),False)


class VirtualCpuTests(unittest.TestCase):
    def setUp(self):
        self.m=memory();self.m.add(0x1000,bytes(256),'test')
        self.r=[0]*33;self.r[32]=0x1000;self.cpu=CPU(self.m,self.r)

    def operation(self,funct7,funct3,a,b):
        self.r[1],self.r[2]=a,b
        self.cpu.word((funct7<<25)|(2<<20)|(1<<15)|(funct3<<12)|(3<<7)|0x33,0x1000)
        return self.r[3]

    def test_multiply_division_edge_cases(self):
        cases=[(1,0,0xffffffff,2,0xfffffffe),(1,1,0xffffffff,0xffffffff,0),
               (1,2,0xffffffff,0xffffffff,0xffffffff),(1,3,0xffffffff,0xffffffff,0xfffffffe),
               (1,4,0x80000000,0xffffffff,0x80000000),(1,4,7,0,0xffffffff),
               (1,4,0xfffffff9,3,0xfffffffe),(1,6,0xfffffff9,3,0xffffffff),
               (1,5,0xffffffff,2,0x7fffffff),(1,7,123,0,123)]
        for f7,f3,a,b,result in cases:
            with self.subTest(f3=f3,a=a,b=b):self.assertEqual(self.operation(f7,f3,a,b),result)

    def test_register_zero_reserved_and_missing_memory(self):
        self.cpu.word(0x00100013,0x1000);self.assertEqual(self.r[0],0)
        with self.assertRaises(ValueError): self.cpu.word(0x00000003,0x1000)
        with self.assertRaises(CpuStop): self.cpu.word(0xffffffff,0x1000)
        with self.assertRaises(ValueError): self.operation(3,0,1,2)
        with self.assertRaises(ValueError): self.cpu.load(0x1001,4)

    def test_compressed_arithmetic_and_jalr(self):
        self.r[1]=7
        self.assertEqual(self.cpu.compressed(0x0085,0x1000),0x1002) # c.addi ra,1
        self.assertEqual(self.r[1],8)
        self.r[1]=0x1080
        self.assertEqual(self.cpu.compressed(0x9082,0x1000),0x1080) # c.jalr ra
        self.assertEqual(self.r[1],0x1002)

    def test_atomic_reservation_and_execution_budget(self):
        self.r[1]=0x1000;self.m.write(0x1000,(42).to_bytes(4,'little'))
        lr=(2<<27)|(1<<15)|(2<<12)|(3<<7)|0x2f
        self.cpu.word(lr,0x1080);self.assertEqual(self.r[3],42)
        self.r[2]=99
        sc=(3<<27)|(2<<20)|(1<<15)|(2<<12)|(3<<7)|0x2f
        self.cpu.word(sc,0x1080);self.assertEqual(self.r[3],0);self.assertEqual(self.m.u32(0x1000),99)
        self.cpu.word(sc,0x1080);self.assertEqual(self.r[3],1)
        self.m.write(0x1000,(0x0000006f).to_bytes(4,'little')) # jal zero,0
        with self.assertRaisesRegex(CpuStop,'budget'): self.cpu.run(20)


class ImportMemoryTests(unittest.TestCase):
    def test_equal_sized_conflicting_dwarf_layouts_are_rejected(self):
        types=DwarfTypes.__new__(DwarfTypes)
        types.named={'Queue_t':[1,2]}
        types.entries={
            1:dict(tag=0x13,attrs={0x0b:8},children=[3]),
            2:dict(tag=0x13,attrs={0x0b:8},children=[4]),
            3:dict(tag=0x0d,attrs={3:'count',0x38:0,0x49:5},children=[]),
            4:dict(tag=0x0d,attrs={3:'count',0x38:4,0x49:5},children=[]),
            5:dict(tag=0x24,attrs={0x0b:4,0x3e:7},children=[])}
        with self.assertRaisesRegex(ValueError,'ambiguous DWARF member layout'):types.member('Queue_t','count')
        types.entries[4]['attrs'][0x38]=0
        self.assertEqual(types.member('Queue_t','count'),(0,4))

    def test_raw_roundtrip_and_uart_selection(self):
        regs={**{'x'+str(i):0 for i in range(32)},'mepc':0x1000,'mstatus':0,'mcause':2,'mtval':0}
        data=encode_raw(bytes(range(256))*512,0x80000000,regs,'01'*16)
        report=parse(data);self.assertEqual(sum(r.get('captured',0) for r in report['records']),131072)
        log=b'prefix\nCK_HEX_BEGIN\n'+data.hex().encode()+b'\nCK_HEX_END\nsuffix'
        self.assertEqual(extract_log(log),data)
        with self.assertRaisesRegex(ValueError,'multiple'):extract_log(log+log)
        self.assertEqual(extract_log(log+log,1),data)
        with self.assertRaises(ValueError):extract_log(log[:-50])
        with self.assertRaises(ValueError):encode_raw(b'abc',0xffffffff,regs,'01'*16)

    def test_sparse_memory_conflicts_holes_and_reset(self):
        m=memory();m.add(0x1000,b'abcd','snapshot');m.add(0x1004,b'ef','snapshot')
        self.assertEqual(m.read(0x1002,4),b'cdef')
        with self.assertRaises(ValueError):m.add(0x1002,b'XX','snapshot')
        with self.assertRaises(ValueError):m.read(0x1002,5)
        with self.assertRaises(ValueError):m.write(0x1002,b'12345')
        self.assertFalse(m.overlay)
        m.write(0x1000,b'XX');self.assertEqual(m.read(0x1000,4),b'XXcd')
        m.reset();self.assertEqual(m.read(0x1000,4),b'abcd')


class RemoteTests(unittest.TestCase):
    def setUp(self):
        m=memory();m.add(0x1000,b'abcdefgh','snapshot')
        self.s=SimpleNamespace(current=1,tasks=[dict(name='worker',state='Blocked',registers=[0]*33)],
                               memory=m,system=dict(tick=42))
    def test_default_is_read_only_and_missing_registers(self):
        remote=Remote(self.s)
        self.assertEqual(remote.handle('m1000,4'),'61626364')
        self.assertEqual(remote.handle('M1000,1:58'),'E01')
        self.assertEqual(remote.handle('P2=01000000'),'E01')
        self.assertEqual(remote.handle('c'),'E01')
        self.assertEqual(remote.handle('m0,4'),'E01')
        self.s.tasks[0]['registers'][10]=None
        self.assertEqual(remote.handle('pa'),'xxxxxxxx')
        self.assertEqual(remote.handle('Hg7'),'E01')
        self.assertEqual(remote.handle('qfThreadInfo'),'m1')
    def test_analysis_copy_registers_and_packet_limits(self):
        remote=Remote(self.s,writable=True)
        self.assertEqual(remote.handle('M1000,1:58'),'OK');self.assertEqual(self.s.memory.read(0x1000,1),b'X')
        self.assertEqual(remote.handle('P2=00100000'),'OK');self.assertEqual(remote.regs()[2],0x1000)
        self.assertEqual(remote.handle('m1000,1001'),'E01')
        before=remote.regs()[32]
        self.assertEqual(remote.handle('p-1'),'E01')
        self.assertEqual(remote.handle('P-1=00100000'),'E01')
        self.assertEqual(remote.regs()[32],before)
        self.assertEqual(remote.handle('qXfer:features:read:target.xml:-1,10'),'E01')
        self.s.tasks[0]['csrs']=dict(mstatus=0x1880,mepc=0x1000,mcause=2,mtval=None)
        self.assertEqual(remote.handle('p23'),'02000000')
        self.assertEqual(remote.handle('p24'),'xxxxxxxx')
        self.assertEqual(remote.handle('P23=03000000'),'OK')
        self.assertEqual(remote.handle('p23'),'03000000')
        self.assertEqual(len(remote.handle('g')),37*8)
        self.assertEqual(remote.handle('qXfer:features:read:target.xml:0,100')[:1],'m')
        self.assertEqual(remote.handle('unknown'), '')
        self.assertEqual(frame('a#b'),b'$a}\x03b#43')

    def test_transport_bad_checksum_and_fragmented_packets(self):
        server,client=socket.socketpair();client.settimeout(2)
        remote=Remote(self.s)
        worker=threading.Thread(target=serve_connection,args=(server,remote),daemon=True);worker.start()
        try:
            client.sendall(b'$?#00');self.assertEqual(client.recv(1),b'-')
            packet=frame('m1000,4')
            for byte in packet:client.sendall(bytes((byte,)))
            self.assertEqual(client.recv(1),b'+')
            result=b''
            while not (b'#' in result and len(result)>=result.index(b'#')+3):result+=client.recv(1)
            self.assertEqual(result,frame('61626364'))
            client.sendall(frame('D'))
            result=b''
            while not (b'#' in result and len(result)>=result.index(b'#')+3):result+=client.recv(1)
            self.assertEqual(result,b'+'+frame('OK'))
        finally:
            client.close();worker.join(timeout=2);server.close()
        self.assertFalse(worker.is_alive())

    def test_register_profiles_gating_unknowns_and_cycles(self):
        samples=[dict(kind='register-samples',status='captured',registers=[
            dict(name='source',width=32,value='0x989680'),dict(name='gate',width=8,value='0x0')])]
        profile=dict(version=1,clocks=[dict(name='cpu',source_register='source'),
            dict(name='off',parent='cpu',gate=dict(register='gate',mask=1)),
            dict(name='missing',source_register='absent'),dict(name='cycle',parent='cycle')])
        rates={x['name']:x['hz'] for x in decode_profile(samples,profile)['clocks']}
        self.assertEqual(rates,dict(cpu=10000000,off=0,missing=None,cycle=None))


if __name__=='__main__':unittest.main()
