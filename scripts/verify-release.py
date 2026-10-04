#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify a source package, then build/test in an empty extraction."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import tarfile

from release import unpack


def verify(archive, destination):
    manifest = unpack(archive, destination)
    for command in (['make', 'verify'], ['make', 'sanitize']):
        subprocess.run(command, cwd=destination, check=True)
    print(json.dumps({'result': 'PASS', 'version': manifest['version'],
                      'files': len(manifest['files']),
                      'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                      'scope': 'clean host build/tests/sanitizers; RV32 requires separate clean build'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path, help='Keep a fresh extraction; path must not exist')
    args = parser.parse_args()
    try:
        if args.output:
            verify(args.archive.resolve(), args.output.resolve())
        else:
            with tempfile.TemporaryDirectory(prefix='crashkit-release-') as temporary:
                verify(args.archive.resolve(), Path(temporary) / 'source')
    except (ValueError, OSError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as error:
        parser.exit(2, 'Release verification failed: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
