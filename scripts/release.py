#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Deterministic source-only release. The manifest is integrity, not authentication."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ('LICENSE', 'VERSION', 'Makefile', 'README.md',
              'README.zh-CN.md', 'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md',
              'THIRD_PARTY_NOTICES.md', '.gitignore', '.dockerignore')
DIRECTORIES = ('include', 'src', 'ports', 'examples', 'tools', 'tests', 'scripts',
               'docs', '.github')
SUFFIXES = {'.c', '.h', '.S', '.ld', '.py', '.md', '.yml', '.yaml'}
MAX_FILE = 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def payload(root):
    root = Path(root)
    paths = [root / name for name in ROOT_FILES] + [root / 'evidence/README.md']
    for name in DIRECTORIES:
        directory = root / name
        require(directory.is_dir() and not directory.is_symlink(), 'missing/linked directory: ' + name)
        for path in directory.rglob('*'):
            require(not path.is_symlink(), 'symlink in source: ' + str(path.relative_to(root)))
            if path.is_dir() or '__pycache__' in path.parts or path.name in ('.DS_Store',):
                continue
            require(path.suffix in SUFFIXES or path.name == 'Dockerfile.rv32',
                    'unexpected source file: ' + str(path.relative_to(root)))
            paths.append(path)
    result = {}
    for path in sorted(paths):
        require(path.is_file() and not path.is_symlink(), 'missing/linked source file: ' + str(path))
        require(path.resolve().is_relative_to(root.resolve()), 'source escapes repository')
        require(path.stat().st_size <= MAX_FILE, 'oversized source file')
        data = path.read_bytes()
        text = data.decode('utf-8')
        private_pattern = '/' + r'Users/[^\s]+|/' + r'home/[^\s]+|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'
        require(not re.search(private_pattern, text),
                'private path/key in source: ' + str(path.relative_to(root)))
        result[path.relative_to(root).as_posix()] = data
    require(sum(map(len, result.values())) <= MAX_TOTAL, 'oversized source release')
    return result


def version(root):
    value = (root / 'VERSION').read_text(encoding='utf-8').strip()
    require(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value), 'invalid VERSION')
    header = (root / 'include/crashkit.h').read_text(encoding='utf-8')
    require('#define CK_VERSION_STRING "' + value + '"' in header, 'VERSION/header mismatch')
    for field, part in zip(('MAJOR', 'MINOR', 'PATCH'), value.split('.')):
        require(re.search(r'#define CK_VERSION_' + field + r'\s+' + part + r'u\b', header),
                'VERSION numeric macro mismatch')
    return value


def package(root, output):
    root, output = Path(root), Path(output)
    value = version(root)
    files = payload(root)
    manifest = {'version': value, 'format_version': 1, 'scope': 'source-only',
                'files': {name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in sorted(files.items())}}
    files['MANIFEST.json'] = (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    prefix = 'freertos-crashkit-' + value
    output.mkdir(parents=True, exist_ok=True)
    target = output / (prefix + '.tar.gz')
    temporary = target.with_suffix('.tmp')
    with temporary.open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as tar:
                for name, data in sorted(files.items()):
                    entry = tarfile.TarInfo(prefix + '/' + name)
                    entry.size = len(data)
                    entry.mode = 0o644
                    entry.mtime = 0
                    tar.addfile(entry, io.BytesIO(data))
    temporary.replace(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (output / 'SHA256SUMS').write_text(digest + '  ' + target.name + '\n', encoding='utf-8')
    return target, digest


def unpack(archive, destination):
    """Verify before writing. Reject links, duplicate entries and traversal."""
    archive, destination = Path(archive), Path(destination)
    require(not destination.exists(), 'output directory must not exist')
    require(archive.stat().st_size <= MAX_TOTAL, 'oversized archive')
    files = {}
    prefix = None
    total = 0
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            require(member.isfile() and not path.is_absolute() and len(path.parts) >= 2
                    and '..' not in path.parts and str(path) == member.name, 'unsafe archive member')
            require(member.size <= MAX_FILE and member.size >= 0, 'oversized archive member')
            if prefix is None:
                prefix = path.parts[0]
            require(path.parts[0] == prefix, 'multiple archive roots')
            name = '/'.join(path.parts[1:])
            require(name not in files, 'duplicate archive member')
            total += member.size
            require(total <= MAX_TOTAL and len(files) < 512, 'oversized expanded archive')
            files[name] = tar.extractfile(member).read()
    require('MANIFEST.json' in files, 'missing manifest')
    manifest = json.loads(files.pop('MANIFEST.json').decode('utf-8'))
    require(manifest.get('scope') == 'source-only' and manifest.get('format_version') == 1,
            'invalid release manifest')
    require(prefix == 'freertos-crashkit-' + manifest['version'], 'release root/version mismatch')
    require(set(manifest['files']) == set(files), 'manifest membership mismatch')
    for name, data in files.items():
        require(manifest['files'][name] == {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()},
                'file hash/size mismatch: ' + name)
    # Enforce our source-only allowlist even for a self-consistent altered manifest.
    for name in files:
        parts = PurePosixPath(name).parts
        require(name in ROOT_FILES or name == 'evidence/README.md' or
                (len(parts) > 1 and parts[0] in DIRECTORIES and
                 (PurePosixPath(name).suffix in SUFFIXES or parts[-1] == 'Dockerfile.rv32')),
                'non-source payload: ' + name)
    destination.mkdir(parents=True)
    for name, data in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (destination / 'MANIFEST.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    version(destination)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/release')
    args = parser.parse_args()
    try:
        target, digest = package(ROOT, args.output)
        print(target.name + ' SHA256=' + digest)
    except (ValueError, OSError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
