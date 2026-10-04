#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fetch pinned upstream source, or verify an existing extraction without replacing it."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SHA = '0e21928b3bcc4f9bcaf7333fb1c8c0299d97e2ec9e13e3faa2c5a7ac8a3bc573'
NAME = 'FreeRTOS-Kernel-11.1.0'
URL = 'https://github.com/FreeRTOS/FreeRTOS-Kernel/archive/refs/tags/V11.1.0.tar.gz'
LIMIT = 32 * 1024 * 1024


def verify_tree(out, files):
    if out.is_symlink():
        raise ValueError('Linked upstream tree is unsupported')
    actual = set()
    for path in out.rglob('*'):
        if path.is_symlink():
            raise ValueError('Linked upstream source: ' + str(path.relative_to(out)))
        if not path.is_file():
            continue
        relative = path.relative_to(out).as_posix()
        if '__pycache__' in path.parts or path.name == '.DS_Store':
            continue
        actual.add(relative)
        if relative not in files or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(files[relative]).digest():
            raise ValueError('Upstream tree differs from archive: ' + relative)
    if actual != set(files):
        raise ValueError('Upstream tree is incomplete; use a fresh dependency directory')


def fetch(root, local=None):
    target = Path(root) / 'third_party'
    target.mkdir(exist_ok=True)
    if target.is_symlink():
        raise ValueError('Linked dependency directory is unsupported')
    archive = target / 'freertos-V11.1.0.tar.gz'
    if archive.is_symlink():
        raise ValueError('Linked dependency archive is unsupported')
    if local:
        source = Path(local)
        if source.stat().st_size > LIMIT or hashlib.sha256(source.read_bytes()).hexdigest() != SHA:
            raise ValueError('Archive SHA mismatch')
        if source.resolve() != archive.resolve():
            temporary = archive.with_suffix('.tmp')
            shutil.copyfile(source, temporary)
            temporary.replace(archive)
    elif not archive.exists():
        with urllib.request.urlopen(URL, timeout=30) as source:
            data = source.read(LIMIT + 1)
        if len(data) > LIMIT or hashlib.sha256(data).hexdigest() != SHA:
            raise ValueError('Downloaded archive SHA mismatch')
        temporary = archive.with_suffix('.tmp')
        temporary.write_bytes(data)
        temporary.replace(archive)
    if archive.stat().st_size > LIMIT or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA:
        raise ValueError('Archive SHA mismatch')
    files = {}
    with tarfile.open(archive) as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or not path.parts or
                    path.parts[0] != NAME or not (member.isdir() or member.isfile())):
                raise ValueError('Unsafe archive member')
            if member.isfile():
                relative = '/'.join(path.parts[1:])
                if not relative or relative in files:
                    raise ValueError('Duplicate/invalid archive member')
                files[relative] = tar.extractfile(member).read()
    out = target / NAME
    if out.exists():
        verify_tree(out, files)
    else:
        with tempfile.TemporaryDirectory(prefix='freertos-extract-', dir=target) as temporary:
            stage = Path(temporary) / NAME
            stage.mkdir()
            for relative, data in files.items():
                path = stage / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            verify_tree(stage, files)
            stage.rename(out)
    print('Verified official archive AND extracted FreeRTOS V11.1.0: ' + SHA)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Reuse a local official archive after hash verification')
    args = parser.parse_args()
    try:
        fetch(ROOT, args.archive)
    except (ValueError, OSError, tarfile.TarError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
