#!/usr/bin/env python3
"""Compatibility wrapper for the historic ``pdf_glyph_replace`` module."""

from __future__ import annotations

from pdf_mutation.engine import *  # noqa: F401,F403
from pdf_mutation.engine import __version__, main


if __name__ == "__main__":
    raise SystemExit(main())
