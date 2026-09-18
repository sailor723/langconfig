#!/usr/bin/env python3
"""Run a Python script and capture output."""
import subprocess, sys

script_path = sys.argv[1]
result = subprocess.run([sys.executable, script_path], capture_output=True, text=True, timeout=30)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr[:2000])
print("RC:", result.returncode)
