# SPDX-License-Identifier: MIT
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release', ROOT / 'scripts/release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_deterministic_source_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive, first = release.package(ROOT, directory)
            _, second = release.package(ROOT, directory)
            self.assertEqual(first, second)
            manifest = release.unpack(archive, directory / 'source')
            self.assertEqual(manifest['version'], '0.1.0')
            self.assertIn('.github/workflows/ci.yml', manifest['files'])
            self.assertFalse(any(name.startswith(('build/', 'third_party/', 'evidence/qemu-rv32/'))
                                 for name in manifest['files']))
            with self.assertRaisesRegex(ValueError, 'must not exist'):
                release.unpack(archive, directory / 'source')

    def test_traversal_link_duplicate_and_bad_hash(self):
        for variant in ('traversal', 'link', 'duplicate', 'hash'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                good, _ = release.package(ROOT, directory)
                bad = directory / 'bad.tar.gz'
                with tarfile.open(good) as source, tarfile.open(bad, 'w:gz') as output:
                    members = source.getmembers()
                    for member in members:
                        data = source.extractfile(member).read()
                        if variant == 'hash' and member.name.endswith('/VERSION'):
                            data = b'0.2.0\n'
                            member.size = len(data)
                        output.addfile(member, io.BytesIO(data))
                    entry = tarfile.TarInfo('freertos-crashkit-0.1.0/../../escaped')
                    if variant == 'link':
                        entry.name = 'freertos-crashkit-0.1.0/linked'
                        entry.type = tarfile.SYMTYPE
                        entry.linkname = '/etc/passwd'
                    if variant == 'duplicate':
                        entry = members[0]
                    if variant != 'hash':
                        output.addfile(entry, io.BytesIO(b'\0' * entry.size))
                with self.assertRaises(ValueError):
                    release.unpack(bad, directory / 'source')
                self.assertFalse((directory / 'source').exists())


if __name__ == '__main__':
    unittest.main()
