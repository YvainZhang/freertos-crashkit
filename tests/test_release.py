# SPDX-License-Identifier: MIT
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import json

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
            self.assertEqual(manifest['version'], '0.2.0')
            self.assertIn('.github/workflows/ci.yml', manifest['files'])
            self.assertFalse(any(name.startswith(('build/', 'third_party/', 'evidence/qemu-rv32/'))
                                 for name in manifest['files']))
            self.assertNotIn('AGENTS.md', manifest['files'])
            self.assertEqual({name for name in manifest['files'] if name.startswith('docs/')},
                             set(release.PUBLIC_DOCS))
            with self.assertRaisesRegex(ValueError, 'must not exist'):
                release.unpack(archive, directory / 'source')

    def test_local_notes_are_not_packaged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/'source'
            root.mkdir()
            for name, data in release.payload(ROOT).items():
                target=root/name; target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(data)
            for name in ('AGENTS.md', 'PLAN.internal.md', 'docs/internal-plan.md'):
                (root/name).write_text('# Local-only example\n',encoding='utf-8')
            archive,_=release.package(root, Path(temporary)/'output')
            manifest=release.unpack(archive,Path(temporary)/'extracted')
            self.assertFalse(any(name in manifest['files'] for name in
                                 ('AGENTS.md','PLAN.internal.md','docs/internal-plan.md')))

    def test_traversal_link_duplicate_and_bad_hash(self):
        for variant in ('traversal', 'link', 'duplicate', 'hash', 'schema', 'version'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                good, _ = release.package(ROOT, directory)
                bad = directory / 'bad.tar.gz'
                with tarfile.open(good) as source, tarfile.open(bad, 'w:gz') as output:
                    members = source.getmembers()
                    for member in members:
                        data = source.extractfile(member).read()
                        if variant == 'hash' and member.name.endswith('/VERSION'):
                            data = b'9.9.9\n'
                            member.size = len(data)
                        if member.name.endswith('/MANIFEST.json') and variant in ('schema', 'version'):
                            manifest = json.loads(data)
                            if variant == 'schema':
                                manifest = []
                            else:
                                manifest['version'] = '9.9.9'
                            data = json.dumps(manifest).encode('utf-8')
                            member.size = len(data)
                        output.addfile(member, io.BytesIO(data))
                    entry = tarfile.TarInfo('freertos-crashkit-0.2.0/../../escaped')
                    if variant == 'link':
                        entry.name = 'freertos-crashkit-0.2.0/linked'
                        entry.type = tarfile.SYMTYPE
                        entry.linkname = '/etc/passwd'
                    if variant == 'duplicate':
                        entry = members[0]
                    if variant not in ('hash', 'schema', 'version'):
                        output.addfile(entry, io.BytesIO(b'\0' * entry.size))
                with self.assertRaises(ValueError):
                    release.unpack(bad, directory / 'source')
                self.assertFalse((directory / 'source').exists())


if __name__ == '__main__':
    unittest.main()
