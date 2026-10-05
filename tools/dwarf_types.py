#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded DWARF2..5 type/member reader. Unsupported forms fail, never guess offsets."""
import struct
from elf_image import require


class Cursor:
    def __init__(self,data,offset=0,end=None):
        self.data,self.offset,self.end=data,offset,len(data) if end is None else end
    def bytes(self,n):
        require(0 <= n <= self.end-self.offset,'truncated DWARF')
        value=self.data[self.offset:self.offset+n];self.offset+=n;return value
    def uint(self,n): return int.from_bytes(self.bytes(n),'little')
    def leb(self,signed=False):
        value=shift=0
        for _ in range(10):
            byte=self.uint(1);value|=(byte&127)<<shift;shift+=7
            if not byte&128:
                return value-(1 << shift) if signed and byte&64 else value
        raise ValueError('oversized DWARF LEB128')
    def string(self):
        end=self.data.find(b'\0',self.offset,self.end)
        require(end >= 0 and end-self.offset <= 4096,'invalid DWARF string')
        value=self.bytes(end-self.offset+1)
        return value[:-1].decode('utf-8','replace')


class DwarfTypes:
    def __init__(self,elf):
        self.entries={};self.named={};self.abbrevs={}
        info=elf.section('.debug_info');abbrev=elf.section('.debug_abbrev');strings=elf.section('.debug_str')
        require(info and abbrev,'ELF has no DWARF type information')
        self.abbrev=abbrev['data'];self.strings=strings['data'] if strings else b''
        line_strings=elf.section('.debug_line_str')
        self.line_strings=line_strings['data'] if line_strings else b''
        c=Cursor(info['data'])
        while c.offset<c.end:
            start=c.offset;length=c.uint(4)
            require(7 <= length <= c.end-c.offset,'invalid DWARF compilation unit')
            end=c.offset+length;version=c.uint(2)
            require(2 <= version <= 5,'unsupported DWARF version')
            if version == 5:
                unit_type,width=c.uint(1),c.uint(1)
                offset=c.uint(4)
                if unit_type not in (1,3):
                    c.offset=end;continue  # No layout claims from split/type units.
                table=self.abbreviation(offset)
            else:
                table=self.abbreviation(c.uint(4));width=c.uint(1)
            require(width == 4,'requires RV32 DWARF addresses')
            parents=[]
            while c.offset<end:
                offset=c.offset;code=c.leb()
                if not code:
                    require(parents,'unbalanced DWARF children');parents.pop();continue
                require(code in table,'unknown DWARF abbreviation')
                tag,children,fields=table[code]
                attrs={key:(implicit if form==0x21 else self.value(c,form,start,width))
                       for key,form,implicit in fields}
                require(c.offset<=end and len(self.entries)<100000,'DWARF DIE budget/range exceeded')
                node=dict(tag=tag,attrs=attrs,children=[])
                self.entries[offset]=node
                if parents: self.entries[parents[-1]]['children'].append(offset)
                if 3 in attrs: self.named.setdefault(attrs[3],[]).append(offset)
                if children:
                    require(len(parents)<64,'DWARF nesting limit');parents.append(offset)
            require(not parents,'unclosed DWARF child tree')

    def abbreviation(self,offset):
        if offset in self.abbrevs: return self.abbrevs[offset]
        c=Cursor(self.abbrev,offset);table={}
        for _ in range(65536):
            code=c.leb()
            if not code:
                self.abbrevs[offset]=table;return table
            require(code not in table,'duplicate DWARF abbreviation')
            tag,children=c.leb(),c.uint(1);require(children in (0,1),'invalid DWARF children flag')
            fields=[]
            for _ in range(256):
                key,form=c.leb(),c.leb()
                if key == form == 0: break
                require(key and form,'invalid DWARF attribute')
                fields.append((key,form,c.leb(True) if form==0x21 else None))
            else: raise ValueError('DWARF attribute limit')
            table[code]=(tag,children,fields)
        raise ValueError('DWARF abbreviation limit')

    def value(self,c,form,start,width,depth=0):
        require(depth<16,'DWARF indirect form depth exceeded')
        if form in (1,): return c.uint(width)
        if form in (5,6,7,11,12): return c.uint({5:2,6:4,7:8,11:1,12:1}[form])
        if form == 8: return c.string()
        if form == 13: return c.leb(True)
        if form == 15: return c.leb()
        if form == 14:
            offset=c.uint(4);return Cursor(self.strings,offset).string()
        if form in (17,18,19,20): return start+c.uint({17:1,18:2,19:4,20:8}[form])
        if form == 21: return start+c.leb()
        if form in (16,23): return c.uint(4)
        if form == 25: return 1
        if form in (3,4,9,10,24):
            n=c.uint({3:2,4:4,10:1}[form]) if form in (3,4,10) else c.leb()
            require(n<=65536,'DWARF block limit');return c.bytes(n)
        if form == 22: return self.value(c,c.leb(),start,width,depth+1)
        if form == 32: return c.uint(8)
        if form == 30: return c.bytes(16)
        if form == 31: return Cursor(self.line_strings,c.uint(4)).string()
        raise ValueError('unsupported DWARF form '+hex(form))

    def resolve(self,offset):
        seen=set()
        while True:
            require(offset in self.entries and offset not in seen,'missing/cyclic DWARF type')
            seen.add(offset);node=self.entries[offset]
            if node['tag'] not in (0x16,0x26,0x35,0x37): return node
            require(0x49 in node['attrs'],'incomplete DWARF alias');offset=node['attrs'][0x49]

    def type(self,name):
        require(name in self.named,'missing DWARF type: '+name)
        candidates=[]
        for offset in self.named[name]:
            node=self.resolve(offset)
            if node['tag'] in (0x13,0x17) and 0x0b in node['attrs']: candidates.append(node)
        require(candidates,'incomplete DWARF type: '+name)
        sizes={node['attrs'][0x0b] for node in candidates}
        require(len(sizes)==1,'ambiguous DWARF type size: '+name)
        def shape(node,seen=()):
            require(id(node) not in seen and len(seen)<16,'cyclic/deep DWARF member layout')
            attrs=node['attrs']
            header=(node['tag'],attrs.get(0x0b),attrs.get(0x3e))
            if node['tag'] not in (0x13,0x17):return header
            members=[]
            for offset in node['children']:
                member=self.entries[offset]
                if member['tag']!=0x0d:continue
                a=member['attrs'];require(0x49 in a,'incomplete member type')
                members.append((a.get(3),a.get(0x38,0),a.get(0x0d),a.get(0x6b),
                                shape(self.resolve(a[0x49]),seen+(id(node),))))
            return header+tuple(members)
        require(len({shape(node) for node in candidates})==1,'ambiguous DWARF member layout: '+name)
        return candidates[0]

    def member(self,name,path):
        node=self.type(name);offset=0
        for part in path.split('.'):
            matches=[self.entries[i] for i in node['children'] if self.entries[i]['tag']==0x0d and
                     self.entries[i]['attrs'].get(3)==part]
            require(len(matches)==1,'missing/ambiguous DWARF member: '+name+'.'+path)
            attrs=matches[0]['attrs'];location=attrs.get(0x38,0)
            if isinstance(location,bytes):
                require(location and location[0]==0x23,'unsupported member location expression')
                expression=Cursor(location,1);location=expression.leb()
                require(expression.offset==expression.end,'unsupported member expression suffix')
            require(type(location) is int and 0 <= location < 65536 and not (0x0d in attrs or 0x6b in attrs),
                    'unsupported bit-field/offset')
            offset+=location;node=self.resolve(attrs[0x49])
        size=node['attrs'].get(0x0b,4 if node['tag']==0x0f else None)
        require(type(size) is int and 0 < size <= 65536,'unknown member size')
        require(offset+size <= self.type(name)['attrs'][0x0b],'member outside containing type')
        return offset,size

    def scalar(self,memory,name,address,path):
        offset,size=self.member(name,path)
        require(size in (1,2,4,8),'member is not an integer/pointer scalar')
        return int.from_bytes(memory.read(address+offset,size),'little')
