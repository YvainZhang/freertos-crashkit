#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check repository-local Markdown file links; generated evidence is explicit."""
from pathlib import Path
import re
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
documents = sorted(ROOT.glob('*.md')) + sorted((ROOT / 'docs').rglob('*.md'))
documents += sorted((ROOT / '.github').rglob('*.md')) + [ROOT / 'evidence/README.md']
errors = []
for path in documents:
    text = path.read_text(encoding='utf-8')
    if text.startswith('---\n'):
        text = text.split('---\n', 2)[-1].lstrip()
    if not text.startswith('# '):
        errors.append(str(path.relative_to(ROOT)) + ': missing title')
    if text.count('```') % 2:
        errors.append(str(path.relative_to(ROOT)) + ': unclosed code fence')
    for target in re.findall(r'\]\(([^)]+)\)', text):
        target = unquote(target.strip('<>').split('#')[0])
        if not target or re.match(r'[a-z]+:', target):
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.is_relative_to(ROOT):
            errors.append(str(path.relative_to(ROOT)) + ': external local link ' + target)
        elif not resolved.exists():
            relative = resolved.relative_to(ROOT).as_posix()
            if not relative.startswith(('evidence/host/', 'evidence/qemu-rv32/')):
                errors.append(str(path.relative_to(ROOT)) + ': missing ' + target)
if errors:
    raise SystemExit('\n'.join(errors))
print('DOCS_PASS: ' + str(len(documents)) + ' Markdown files; generated evidence links checked by test generation')
