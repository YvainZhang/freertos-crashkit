#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Versioned object catalog, DWARF-derived FreeRTOS fields, trace/register plugins."""
import struct
import zlib
from dwarf_types import DwarfTypes
from elf_image import require

KINDS={1:'queue',2:'semaphore',3:'mutex',4:'event-group',5:'stream-buffer',6:'timer',
       7:'heap-4',8:'register-samples',9:'event-trace'}


def cstring(memory,address,limit=128):
    data=bytearray()
    for i in range(limit):
        b=memory.read(address+i,1)[0]
        if not b: return data.decode('utf-8','replace')
        data.append(b)
    raise ValueError('string exceeds analysis limit')


class Objects:
    def __init__(self,snapshot):
        self.s=snapshot;self.m=snapshot.memory;self.elf=snapshot.elf
        self.types=None

    def scalar(self,name,address,path):
        if self.types is None: self.types=DwarfTypes(self.elf)
        return self.types.scalar(self.m,name,address,path)

    def waiters(self,type_name,address,path):
        if self.types is None: self.types=DwarfTypes(self.elf)
        offset,size=self.types.member(type_name,path)
        l=self.s.layout;require(l and size==l['list_size'],'unavailable list layout')
        base=address+offset;end=base+l['list_end'];count=self.m.u32(base+l['list_count'])
        require(count<=16,'waiting-task limit exceeded')
        item=self.m.u32(end+l['next']);previous=end;result=[];seen=set()
        for _ in range(count):
            require(item!=end and item not in seen and self.m.u32(item+l['previous'])==previous and
                    self.m.u32(item+l['container'])==base,'damaged object wait list')
            seen.add(item);owner=self.m.u32(item+l['owner'])
            task=next((t for t in self.s.tasks if t['handle']==owner),None)
            require(owner and owner+l['event_item']==item,'invalid waiting task owner')
            result.append(dict(handle=hex(owner),name=task['name'] if task else None))
            previous,item=item,self.m.u32(item+l['next'])
        require(item==end and self.m.u32(end+l['previous'])==previous,'wait-list length mismatch')
        return result

    def decode(self,kind,address):
        if kind in (1,2,3):
            get=lambda field:self.scalar('Queue_t',address,field)
            count,length,size=get('uxMessagesWaiting'),get('uxLength'),get('uxItemSize')
            require(0<length<=4096 and count<=length and size<=1024,'invalid queue dimensions')
            result=dict(messages=count,length=length,item_bytes=size,
                        waiting_to_send=self.waiters('Queue_t',address,'xTasksWaitingToSend'),
                        waiting_to_receive=self.waiters('Queue_t',address,'xTasksWaitingToReceive'))
            if kind==3:
                require(size==0 and get('pcHead')==0,'catalog mutex does not have mutex layout')
                result['owner']=hex(get('u.xSemaphore.xMutexHolder'))
                result['recursive_count']=get('u.xSemaphore.uxRecursiveCallCount')
            elif kind==2: require(size==0,'semaphore item size is nonzero')
            elif size:
                base=get('pcHead');last=get('u.xQueue.pcReadFrom')
                require(base and length*size<=65536 and base<=last<base+length*size and
                        (last-base)%size==0,'invalid queue ring pointers')
                items=[]
                for i in range(min(count,16,4096//size)):
                    pointer=base+((last-base+(i+1)*size)%(length*size))
                    items.append(self.m.read(pointer,size).hex())
                result.update(items_hex=items,items_truncated=len(items)<count)
            return result
        if kind==4:
            return dict(bits=hex(self.scalar('EventGroup_t',address,'uxEventBits')),
                        waiting_tasks=self.waiters('EventGroup_t',address,'xTasksWaitingForBits'))
        if kind==5:
            get=lambda field:self.scalar('StreamBuffer_t',address,field)
            head,tail,length=get('xHead'),get('xTail'),get('xLength')
            require(1<length<=65536 and head<length and tail<length,'invalid stream ring')
            available=(head-tail+length)%length;n=min(available,1024)
            base=get('pucBuffer');require(base,'null stream buffer')
            first=min(n,length-tail)
            data=self.m.read(base+tail,first)+self.m.read(base,n-first)
            return dict(available_bytes=available,space_bytes=length-available-1,
                        trigger_bytes=get('xTriggerLevelBytes'),bytes_hex=data.hex(),truncated=n<available,
                        waiting_to_receive=hex(get('xTaskWaitingToReceive')),waiting_to_send=hex(get('xTaskWaitingToSend')),
                        flags=get('ucFlags'))
        if kind==6:
            get=lambda field:self.scalar('Timer_t',address,field)
            status=get('ucStatus')
            return dict(timer_name=cstring(self.m,get('pcTimerName')),period_ticks=get('xTimerPeriodInTicks'),
                        expiry_tick=get('xTimerListItem.xItemValue'),active=bool(status&1),
                        autoreload=bool(status&4),callback=hex(get('pxCallbackFunction')),
                        timer_id=hex(get('pvTimerID')))
        if kind==7:
            free=self.m.u32(self.elf.symbol('xFreeBytesRemaining'))
            minimum=self.m.u32(self.elf.symbol('xMinimumEverFreeBytesRemaining'))
            end=self.m.u32(self.elf.symbol('pxEnd'));heap=self.elf.symbol('ucHeap')
            heap_size=self.elf.symbols['ucHeap']['size']
            require(heap_size<=1024*1024 and heap<=end<heap+heap_size,'invalid heap boundary')
            item=self.scalar('BlockLink_t',self.elf.symbol('xStart'),'pxNextFreeBlock')
            blocks=[];total=0;seen=set()
            while item!=end:
                require(len(blocks)<256 and item not in seen and heap<=item<end and item%4==0,'damaged heap free list')
                seen.add(item);size=self.scalar('BlockLink_t',item,'xBlockSize')
                following=self.scalar('BlockLink_t',item,'pxNextFreeBlock')
                require(8<=size<=end-item and not size&0x80000000 and item+size<=following<=end,
                        'invalid/overlapping heap block')
                blocks.append(dict(address=hex(item),bytes=size));total+=size;item=following
            require(total==free and minimum<=free,'heap totals inconsistent')
            return dict(free_bytes=free,minimum_free_bytes=minimum,free_blocks=blocks,
                        largest_free_block=max((b['bytes'] for b in blocks),default=0))
        if kind==8:
            tick,count=struct.unpack('<II',self.m.read(address,8));require(count<=32,'register sample limit')
            registers=[]
            for i in range(count):
                name,reg,value,width,source=struct.unpack('<16sIIII',self.m.read(address+8+32*i,32))
                require(b'\0' in name and width in (8,16,32) and value<(1<<width) and source in (1,2),
                        'invalid register sample')
                registers.append(dict(name=name.split(b'\0')[0].decode('utf-8','replace'),address=hex(reg),
                                      value=hex(value),width=width,source='configuration' if source==1 else 'normal-time MMIO sample'))
            return dict(sample_tick=tick,registers=registers,
                        scope='Cached normal-context samples, not arbitrary fault-time MMIO reads')
        if kind==9:
            magic,sequence=struct.unpack('<II',self.m.read(address,8));require(magic==0x31544b43,'invalid trace header')
            events=[];rejected=[]
            for i in range(16):
                state,seq,tick,tag,value,crc=struct.unpack('<6I',self.m.read(address+8+i*24,24))
                if state==0: continue
                if (state!=2 or not max(1,sequence-15)<=seq<=sequence or (seq-1)%16!=i or
                        zlib.crc32(struct.pack('<4I',seq,tick,tag,value))!=crc):
                    rejected.append(i);continue
                events.append(dict(sequence=seq,tick=tick,tag=tag,value=hex(value)))
            events.sort(key=lambda e:e['sequence'])
            return dict(events=events,overwritten=max(0,sequence-16),rejected_slots=rejected,
                        scope='Application-defined tags and tick units; timeline alone does not prove causality')
        raise ValueError('unknown object plugin '+str(kind))

    def report(self):
        section=self.elf.section('.crashkit_objects')
        if not section: return []
        data=section['data'];require(len(data)>=12,'truncated object catalog')
        magic,version,count=struct.unpack_from('<III',data)
        require(magic==0x314f4b43 and version==1 and count<=64 and len(data)==12+24*count,'invalid object catalog')
        results=[]
        for i in range(count):
            kind,slot,name=struct.unpack_from('<II16s',data,12+24*i)
            require(b'\0' in name,'unterminated catalog name')
            result=dict(name=name.split(b'\0')[0].decode('utf-8','replace'),kind=KINDS.get(kind,'unknown'))
            try:
                address=0 if kind==7 else self.m.u32(slot)
                require(kind==7 or address,'object is not initialized')
                result.update(address=hex(address),status='captured',**self.decode(kind,address))
            except ValueError as error:
                result.update(status='unavailable/corrupt',diagnostic=str(error))
            results.append(result)
        return results
