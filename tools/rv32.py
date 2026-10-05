#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded RV32IMAC analysis interpreter; no peripherals, interrupts or target I/O.
Unknown/reserved instructions and uncaptured memory fail explicitly. Not a SoC emulator.
"""
from elf_image import require

MASK = 0xffffffff


def signed(value, bits=32):
    value &= (1 << bits)-1
    return value-(1 << bits) if value & (1 << (bits-1)) else value


class CpuStop(ValueError):
    pass


class CPU:
    def __init__(self, memory, registers, output=None):
        require(len(registers) == 33, 'requires x0..x31 and pc')
        self.memory, self.regs = memory, registers
        self.output = output or (lambda text: None)
        self.steps = 0
        self.output_size = 0
        self.reservation = None
        self.csrs = {0x300:0,0x340:0,0x341:0,0x342:0,0x343:0}

    def reg(self, n):
        if n == 0: return 0
        require(self.regs[n] is not None, 'register unavailable: x'+str(n))
        return self.regs[n]

    def put(self, n, value):
        if n: self.regs[n] = value & MASK

    def load(self, address, n, extend=False):
        address &= MASK
        require(address % n == 0, 'misaligned analysis load')
        value = int.from_bytes(self.memory.read(address,n),'little')
        return signed(value,n*8) if extend else value

    def store(self, address, value, n):
        address &= MASK
        require(address % n == 0, 'misaligned analysis store')
        self.memory.write(address,(value & ((1 << (8*n))-1)).to_bytes(n,'little'))
        self.reservation = None

    def step(self):
        pc = self.regs[32]
        require(pc is not None and pc % 2 == 0, 'invalid/unavailable PC')
        h = self.load(pc,2)
        self.steps += 1
        if h & 3 != 3:
            next_pc = self.compressed(h,pc)
        else:
            instruction = int.from_bytes(self.memory.read(pc,4),'little')
            next_pc = self.word(instruction,pc)
        self.regs[0] = 0
        self.regs[32] = next_pc & MASK

    def word(self, i, pc):
        op,rd,f3,r1,r2,f7 = i&127,(i>>7)&31,(i>>12)&7,(i>>15)&31,(i>>20)&31,i>>25
        next_pc = pc+4
        imm = signed(i>>20,12)
        if op == 0x37: self.put(rd,i&0xfffff000)
        elif op == 0x17: self.put(rd,pc+(i&0xfffff000))
        elif op == 0x6f:
            n=((i>>31)<<20)|(((i>>12)&255)<<12)|(((i>>20)&1)<<11)|(((i>>21)&1023)<<1)
            self.put(rd,next_pc); next_pc=pc+signed(n,21)
        elif op == 0x67:
            require(f3 == 0, 'reserved JALR')
            target=(self.reg(r1)+imm)&~1; self.put(rd,next_pc); next_pc=target
        elif op == 0x63:
            n=((i>>31)<<12)|(((i>>7)&1)<<11)|(((i>>25)&63)<<5)|(((i>>8)&15)<<1)
            a,b=self.reg(r1),self.reg(r2)
            choices={0:a==b,1:a!=b,4:signed(a)<signed(b),5:signed(a)>=signed(b),6:a<b,7:a>=b}
            require(f3 in choices,'reserved branch')
            if choices[f3]: next_pc=pc+signed(n,13)
        elif op == 0x03:
            sizes={0:(1,True),1:(2,True),2:(4,False),4:(1,False),5:(2,False)}
            require(f3 in sizes, 'reserved load')
            n,se=sizes[f3]; self.put(rd,self.load(self.reg(r1)+imm,n,se))
        elif op == 0x23:
            n=signed(((i>>25)<<5)|((i>>7)&31),12)
            require(f3 in (0,1,2),'reserved store')
            self.store(self.reg(r1)+n,self.reg(r2),1 << f3)
        elif op == 0x13:
            a=self.reg(r1)
            if f3 == 0: value=a+imm
            elif f3 == 2: value=int(signed(a)<imm)
            elif f3 == 3: value=int(a<(imm&MASK))
            elif f3 == 4: value=a^(imm&MASK)
            elif f3 == 6: value=a|(imm&MASK)
            elif f3 == 7: value=a&(imm&MASK)
            elif f3 == 1:
                require(f7 == 0,'reserved SLLI'); value=a<<r2
            else:
                require(f7 in (0,32),'reserved shift immediate')
                value=(signed(a) if f7 == 32 else a)>>r2
            self.put(rd,value)
        elif op == 0x33:
            a,b=self.reg(r1),self.reg(r2)
            if f7 == 1:
                if f3 == 0: value=a*b
                elif f3 == 1: value=(signed(a)*signed(b))>>32
                elif f3 == 2: value=(signed(a)*b)>>32
                elif f3 == 3: value=(a*b)>>32
                else:
                    sa,sb=(signed(a),signed(b)) if f3 in (4,6) else (a,b)
                    quotient=-1 if sb == 0 else (abs(sa)//abs(sb))*(-1 if (sa<0)!=(sb<0) else 1)
                    value=quotient if f3 in (4,5) else (sa if sb == 0 else sa-quotient*sb)
            else:
                require(f7 == 0 or (f7 == 32 and f3 in (0,5)), 'reserved integer operation')
                values={0:a-b if f7==32 else a+b,1:a<<(b&31),2:int(signed(a)<signed(b)),
                        3:int(a<b),4:a^b,5:(signed(a) if f7==32 else a)>>(b&31),6:a|b,7:a&b}
                value=values[f3]
            self.put(rd,value)
        elif op == 0x0f:
            require(f3 in (0,1),'unsupported fence')  # Serialized host-memory model.
        elif op == 0x2f:
            require(f3 == 2,'only word atomics supported')
            address=self.reg(r1); fun=(i>>27)&31; value=self.load(address,4); b=self.reg(r2)
            if fun == 2:
                require(r2 == 0,'reserved LR'); self.reservation=address; self.put(rd,value)
            elif fun == 3:
                success=self.reservation == address
                if success: self.store(address,b,4)
                self.reservation=None; self.put(rd,0 if success else 1)
            else:
                operations={0:value+b,1:b,4:value^b,8:value|b,12:value&b,
                            16:min(signed(value),signed(b)),20:max(signed(value),signed(b)),
                            24:min(value,b),28:max(value,b)}
                require(fun in operations,'reserved atomic')
                self.store(address,operations[fun],4); self.put(rd,value)
        elif op == 0x73:
            if i == 0x73:
                require(self.reg(17) == 0x434b, 'unsupported ECALL (no device services)')
                require(self.output_size < 65536,'virtual output budget exhausted')
                self.output_size += 1
                self.output(chr(self.reg(10)&255))
            elif i == 0x00100073: raise CpuStop('breakpoint')
            elif f3 in (1,2,3,5,6,7):
                csr=i>>20
                if csr in (0xc00,0xc02):
                    old=self.steps
                    require(f3 in (2,3,6,7) and r1 == 0,'read-only analysis counter')
                else:
                    require(csr in self.csrs,'unsupported CSR '+hex(csr))
                    old=self.csrs[csr]; source=r1 if f3 >= 5 else self.reg(r1)
                    require(old is not None,'analysis CSR unavailable '+hex(csr))
                    if f3 in (1,5): self.csrs[csr]=source
                    elif r1: self.csrs[csr]=(old|source) if f3 in (2,6) else (old&~source)
                self.put(rd,old)
            else: raise CpuStop('unsupported privileged instruction')
        else: raise CpuStop('unsupported/illegal instruction '+hex(i)+' at '+hex(pc))
        return next_pc

    def compressed(self, h, pc):
        q,f = h&3,h>>13
        rd,r2=(h>>7)&31,(h>>2)&31
        a,b=8+((h>>7)&7),8+((h>>2)&7)
        n=signed(((h>>12)&1)*32+((h>>2)&31),6)
        next_pc=pc+2
        if q == 0:
            if f == 0:
                imm=(((h>>7)&15)<<6)|(((h>>11)&3)<<4)|(((h>>5)&1)<<3)|(((h>>6)&1)<<2)
                require(imm != 0,'reserved C.ADDI4SPN'); self.put(b,self.reg(2)+imm)
            elif f in (2,6):
                imm=(((h>>10)&7)<<3)|(((h>>6)&1)<<2)|(((h>>5)&1)<<6)
                if f == 2: self.put(b,self.load(self.reg(a)+imm,4))
                else: self.store(self.reg(a)+imm,self.reg(b),4)
            else: raise CpuStop('unsupported compressed load/store')
        elif q == 1:
            if f == 0: self.put(rd,self.reg(rd)+n)
            elif f in (1,5):
                imm=(((h>>12)&1)<<11)|(((h>>11)&1)<<4)|(((h>>9)&3)<<8)|(((h>>8)&1)<<10)|(((h>>7)&1)<<6)|(((h>>6)&1)<<7)|(((h>>3)&7)<<1)|(((h>>2)&1)<<5)
                if f == 1: self.put(1,next_pc)
                next_pc=pc+signed(imm,12)
            elif f == 2: self.put(rd,n)
            elif f == 3:
                if rd == 2:
                    imm=(((h>>12)&1)<<9)|(((h>>6)&1)<<4)|(((h>>5)&1)<<6)|(((h>>3)&3)<<7)|(((h>>2)&1)<<5)
                    require(imm != 0,'reserved C.ADDI16SP'); self.put(2,self.reg(2)+signed(imm,10))
                else:
                    require(rd != 0 and n != 0,'reserved C.LUI'); self.put(rd,n<<12)
            elif f == 4:
                mode=(h>>10)&3
                if mode < 2:
                    require(not h&0x1000,'RV64 compressed shift unsupported')
                    self.put(a,(signed(self.reg(a)) if mode==1 else self.reg(a))>>((h>>2)&31))
                elif mode == 2: self.put(a,self.reg(a)&(n&MASK))
                else:
                    require(not h&0x1000,'RV64 compressed arithmetic unsupported')
                    x,y=self.reg(a),self.reg(b)
                    self.put(a,(x-y,x^y,x|y,x&y)[(h>>5)&3])
            elif f in (6,7):
                imm=(((h>>12)&1)<<8)|(((h>>10)&3)<<3)|(((h>>5)&3)<<6)|(((h>>3)&3)<<1)|(((h>>2)&1)<<5)
                if (self.reg(a)==0) == (f==6): next_pc=pc+signed(imm,9)
        elif q == 2:
            if f == 0:
                require(not h&0x1000,'RV64 compressed shift unsupported'); self.put(rd,self.reg(rd)<<((h>>2)&31))
            elif f == 2:
                require(rd != 0,'reserved C.LWSP')
                imm=(((h>>12)&1)<<5)|(((h>>4)&7)<<2)|(((h>>2)&3)<<6)
                self.put(rd,self.load(self.reg(2)+imm,4))
            elif f == 4:
                if not h&0x1000:
                    if r2: self.put(rd,self.reg(r2))
                    else:
                        require(rd != 0,'reserved C.JR'); next_pc=self.reg(rd)&~1
                elif r2: self.put(rd,self.reg(rd)+self.reg(r2))
                elif rd:
                    target=self.reg(rd)&~1; self.put(1,next_pc); next_pc=target
                else: raise CpuStop('breakpoint')
            elif f == 6:
                imm=(((h>>9)&15)<<2)|(((h>>7)&3)<<6)
                self.store(self.reg(2)+imm,self.reg(r2),4)
            else: raise CpuStop('unsupported compressed instruction')
        else: raise CpuStop('invalid instruction length')
        return next_pc

    def run(self, limit=2000000, breakpoints=(), single=False):
        require(0 < limit <= 2000000,'invalid execution budget')
        for index in range(limit):
            if self.regs[32] in breakpoints and not single:
                return 'breakpoint'
            self.step()
            if single: return 'step'
        raise CpuStop('instruction budget exhausted')

    def call(self, address, arguments=(), limit=2000000):
        require(len(arguments) <= 8, 'at most eight register arguments')
        self.regs[1],self.regs[2],self.regs[32] = 0xe000fffc,0xe000fff0,address
        for i,value in enumerate(arguments): self.put(10+i,value)
        self.run(limit,{0xe000fffc})
        return self.reg(10)
