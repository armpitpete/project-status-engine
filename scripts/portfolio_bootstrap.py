#!/usr/bin/env python3
"""Load the reviewable ordered source segments for the portfolio bootstrap."""
from pathlib import Path

_parts = Path(__file__).with_name("portfolio_bootstrap_parts")
_source = "".join(path.read_text(encoding="utf-8") for path in sorted(_parts.glob("part*.inc")))
exec(compile(_source, __file__, "exec"), globals(), globals())
