#!/usr/bin/env python3
"""Run CLI commands via subprocess to avoid CliRunner issues."""
import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"


def run_cli(*args, cwd=None, env=None):
    """Run inventory CLI with given args via subprocess."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    pythonpath = str(SRC)
    if "PYTHONPATH" in full_env:
        pythonpath = os.pathsep.join([pythonpath, full_env["PYTHONPATH"]])
    full_env["PYTHONPATH"] = pythonpath
    
    cmd = [sys.executable, "-m", "inventory_cli.cli"] + list(args)
    print(f"\n$ inventory {' '.join(args)}")
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else str(ROOT),
        env=full_env,
        capture_output=True,
        text=True
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print("STDERR:", result.stderr.rstrip(), file=sys.stderr)
    print(f"[exit {result.returncode}]")
    return result


if __name__ == "__main__":
    run_cli(*sys.argv[1:])
