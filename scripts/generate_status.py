#!/usr/bin/env python3
"""Generate public, private-dashboard and internal completion outputs."""
from __future__ import annotations

import sys

import dual_status as dual
import internal_completion as internal


def main() -> int:
    ranked, errors, now = dual.collect_ranked()
    public_data, private_data = dual.build_views(ranked, errors, now)
    internal_data = internal.build_data(ranked, errors, now)

    dual.write_public_outputs(public_data)
    dual.write_private_outputs(private_data)
    internal.write_output(internal_data)

    print(
        f"Generated public view for {public_data['project_count']} repositories, "
        f"private top {private_data['project_count']}, and internal completion data "
        f"for {internal_data['repository_count']} repositories from "
        f"{public_data['scanned_candidate_count']} candidates."
    )
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
