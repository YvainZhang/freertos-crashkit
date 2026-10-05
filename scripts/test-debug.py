#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the offline and actual-GDB acceptance suites in the independent tool image."""
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
for script in ('test-offline.py','test-gdb.py'):
    subprocess.run([sys.executable,str(root/'scripts'/script)],cwd=root,check=True)
