#!/usr/bin/env python3
"""Compatibility wrapper for the historic ``pdf_glyph_replace`` module."""

from __future__ import annotations

import argparse
import tempfile

from pdf_mutation.cli import (
    enforce_expect_count,
    load_json_file,
    main,
    non_negative_int,
    print_audit_report,
    print_plan_report,
)
from pdf_mutation.engine import *  # noqa: F401,F403
from pdf_mutation.engine import __version__


if __name__ == "__main__":
    raise SystemExit(main())
