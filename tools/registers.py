#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Board-supplied register fields and bounded clock-tree decoding from cached samples."""
from elf_image import require


def integer(value):
    result=int(value,0) if isinstance(value,str) else value
    require(type(result) is int and 0 <= result <= 0xffffffff,'invalid register profile integer')
    return result


def decode_profile(objects,profile):
    require(isinstance(profile,dict) and profile.get('version')==1,'invalid register profile version')
    rows=profile.get('registers',[]);clocks=profile.get('clocks',[])
    require(isinstance(rows,list) and isinstance(clocks,list) and len(rows)<=64 and len(clocks)<=64,
            'register profile exceeds limits')
    samples={}
    for obj in objects:
        if obj['kind']=='register-samples' and obj['status']=='captured':
            for r in obj['registers']:
                require(r['name'] not in samples,'ambiguous register sample name')
                samples[r['name']]=r
    def field(spec):
        require(isinstance(spec,dict) and isinstance(spec.get('register'),str),'invalid field source')
        require(spec['register'] in samples,'register sample unavailable: '+spec['register'])
        sample=samples[spec['register']]
        mask=integer(spec['mask']);shift=integer(spec.get('shift',0))
        require(shift<sample['width'] and 0<mask<(1 << sample['width']) and
                not mask&((1 << shift)-1),'invalid register field mask')
        return (int(sample['value'],16)&mask)>>shift
    registers=[]
    for row in rows:
        require(isinstance(row,dict) and isinstance(row.get('name'),str) and
                isinstance(row.get('fields',[]),list) and len(row.get('fields',[]))<=64,'invalid register row')
        result=dict(name=row['name'],fields=[])
        for spec in row.get('fields',[]):
            require(isinstance(spec,dict) and isinstance(spec.get('name'),str),'invalid register field')
            try:
                value=field(dict(spec,register=row['name']))
                result['fields'].append(dict(name=spec['name'],value=value))
            except ValueError as error:
                result['fields'].append(dict(name=spec['name'],value=None,diagnostic=str(error)))
        registers.append(result)
    definitions={}
    for clock in clocks:
        require(isinstance(clock,dict) and isinstance(clock.get('name'),str) and clock['name'] not in definitions,
                'invalid/duplicate clock definition')
        definitions[clock['name']]=clock
    resolved={}
    def rate(name,path=()):
        require(name in definitions and name not in path and len(path)<16,'missing/cyclic clock parent')
        if name in resolved:return resolved[name]['hz']
        spec=definitions[name]
        try:
            if 'source_register' in spec:
                require(spec['source_register'] in samples,'clock source sample unavailable')
                hz=int(samples[spec['source_register']]['value'],16)
            elif 'parents' in spec:
                parents=spec['parents'];require(isinstance(parents,list) and 0<len(parents)<=32,'invalid clock mux')
                index=field(spec['mux']);require(index<len(parents),'clock mux selection outside parents')
                hz=rate(parents[index],path+(name,))
            elif 'parent' in spec: hz=rate(spec['parent'],path+(name,))
            else: hz=integer(spec['input_hz'])
            divider=field(spec['divider'])+integer(spec['divider'].get('add',0)) if isinstance(spec.get('divider'),dict) else integer(spec.get('divider',1))
            multiplier=integer(spec.get('multiplier',1));require(divider and multiplier,'zero clock ratio')
            if 'gate' in spec and field(spec['gate']) != integer(spec['gate'].get('equals',1)):hz=0
            require(hz is not None,'clock parent unavailable')
            hz=hz*multiplier//divider;require(hz<=10**12,'clock rate exceeds limit')
            resolved[name]=dict(name=name,hz=hz,scope='Derived from captured samples/configuration; not measured')
            return hz
        except (ValueError,KeyError,TypeError) as error:
            resolved[name]=dict(name=name,hz=None,diagnostic=str(error));return None
    for name in definitions: rate(name)
    return dict(registers=registers,clocks=list(resolved.values()))
