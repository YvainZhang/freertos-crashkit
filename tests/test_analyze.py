# SPDX-License-Identifier: MIT
import importlib.util
from pathlib import Path
import random
import struct
import unittest
import zlib
import subprocess
import sys
import tempfile

spec=importlib.util.spec_from_file_location('analyze',Path(__file__).resolve().parents[1]/'tools/analyze.py')
analyze=importlib.util.module_from_spec(spec); spec.loader.exec_module(analyze)

class ReaderTests(unittest.TestCase):
    def test_unspecified_identity_cannot_match(self):
        data=bytearray(Path('build/valid.bin').read_bytes())
        data[20:36]=bytes(16)
        struct.pack_into('<I',data,44,zlib.crc32(data[:44]))
        struct.pack_into('<I',data,len(data)-4,zlib.crc32(data[:-16]))
        with tempfile.TemporaryDirectory() as temporary:
            dump=Path(temporary)/'unknown.bin'; dump.write_bytes(data)
            result=subprocess.run([sys.executable,analyze.__file__,str(dump),'--elf',str(dump)],
                                  capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('identity is unspecified',result.stderr)
        self.assertEqual(analyze.parse(data)['matching'],'not_checked')

    def test_elf_profiles_and_invalid_sections(self):
        def image(bits,endian):
            data=bytearray(512); data[:7]=b'\x7fELF'+bytes((bits,endian,1))
            order='<' if endian==1 else '>'
            struct.pack_into(order+'H',data,18,243)
            if bits==1:
                struct.pack_into(order+'I',data,32,128)
                struct.pack_into(order+'HHH',data,46,40,3,1)
                fmt=order+'IIIIIIIIII'; size=40
            else:
                struct.pack_into(order+'Q',data,40,128)
                struct.pack_into(order+'HHH',data,58,64,3,1)
                fmt=order+'IIQQQQIIQQ'; size=64
            names=b'\0.shstrtab\0.crashkit_id\0'; data[384:384+len(names)]=names
            struct.pack_into(fmt,data,128+size,1,3,0,0,384,len(names),0,0,1,0)
            struct.pack_into(fmt,data,128+2*size,11,1,0,0,448,16,0,0,1,0)
            data[448:464]=bytes(range(16))
            return data
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'test.elf'
            for bits in (1,2):
                for endian in (1,2):
                    path.write_bytes(image(bits,endian))
                    identity=analyze.elf_identity(path)
                    self.assertEqual(identity['firmware_id'],bytes(range(16)).hex())
                    self.assertEqual(identity['elf_class'],bits)
            data=image(1,1)
            struct.pack_into('<I',data,128+2*40+4,8) # NOBITS identity is invalid.
            path.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'ID section'): analyze.elf_identity(path)
            data=image(1,1)
            struct.pack_into('<I',data,32,0xffffffff)
            path.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'section table'): analyze.elf_identity(path)

    def test_fixtures(self):
        good=analyze.parse(Path('build/valid.bin').read_bytes())
        self.assertEqual(len(good['records']),3)
        self.assertEqual(good['records'][1]['name'],'wifi_worker')
        self.assertEqual(good['records'][2]['captured'],128)
        degraded=analyze.parse(Path('build/degraded.bin').read_bytes())
        self.assertEqual(degraded['flags'],14)
        self.assertEqual(degraded['records'][1]['captured'],32)
        self.assertEqual(analyze.parse(Path('build/bounded.bin').read_bytes())['flags'],9)
        self.assertEqual(analyze.parse(Path('build/generic64.bin').read_bytes())['pointer_bits'],64)
        self.assertEqual(len(analyze.parse(Path('build/empty.bin').read_bytes())['records']),0)
        registry=analyze.parse(Path('build/registry.bin').read_bytes())
        self.assertTrue(any(r.get('code')==2 and r['value']==1 for r in registry['records']))
        with self.assertRaises(ValueError): analyze.parse(Path('build/interrupted.bin').read_bytes())

    def test_every_prefix_and_single_bit(self):
        good=Path('build/valid.bin').read_bytes()
        for n in range(len(good)):
            with self.assertRaises(ValueError): analyze.parse(good[:n])
        for i in range(len(good)):
            for bit in range(8):
                bad=bytearray(good); bad[i]^=1<<bit
                with self.assertRaises(ValueError): analyze.parse(bad)

    def test_valid_crc_invalid_record(self):
        bad=bytearray(Path('build/valid.bin').read_bytes())
        struct.pack_into('<I',bad,52,0xffffffff)
        struct.pack_into('<I',bad,len(bad)-4,zlib.crc32(bad[:-16]))
        with self.assertRaisesRegex(ValueError,'record size'): analyze.parse(bad)

    def test_random_inputs_are_bounded(self):
        rng=random.Random(7020)
        for _ in range(1000):
            data=bytes(rng.randrange(256) for _ in range(rng.randrange(1024)))
            with self.assertRaises(ValueError): analyze.parse(data)
        with self.assertRaises(ValueError): analyze.elf_identity(Path('build/valid.bin'))

if __name__=='__main__': unittest.main()
