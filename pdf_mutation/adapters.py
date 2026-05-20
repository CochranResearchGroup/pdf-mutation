"""Narrow subprocess adapters for PDF and layout tools."""

from __future__ import annotations

import shutil
import subprocess
import sys


def run(args: list[str], *, stdin: bytes | None = None) -> bytes:
    proc = subprocess.run(args, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        raise SystemExit(proc.returncode)
    return proc.stdout


def run_status(args: list[str]) -> tuple[int, bytes, bytes]:
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout, proc.stderr


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"required executable not found on PATH: {name}")

__all__ = [
    "require_tool",
    "run",
    "run_status",
]
