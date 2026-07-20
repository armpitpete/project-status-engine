#!/usr/bin/env python3
"""Render bounded owner-only evidence details for authority exceptions."""
from __future__ import annotations

import html
from typing import Any


def render_markdown(data: dict[str, Any]) -> str:
    queue = data.get("authority_exception_queue") or []
    lines = ["## Exception evidence details", ""]
    if not queue:
        lines.append("No exception details are currently recorded.")
        return "\n".join(lines).strip() + "\n"
    lines.extend(["| Repository | Bounded detail | Source commit |", "|---|---|---|"])
    for item in queue:
        detail = str(item.get("detail") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{item['full_name']}` | {detail} | `{item.get('source_sha') or ''}` |"
        )
    return "\n".join(lines).strip() + "\n"


def render_html(data: dict[str, Any]) -> str:
    queue = data.get("authority_exception_queue") or []
    if not queue:
        return ""
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('full_name') or 'Unknown'))}</td>"
        f"<td>{html.escape(str(item.get('detail') or ''))}</td>"
        f"<td><code>{html.escape(str(item.get('source_sha') or ''))}</code></td>"
        "</tr>"
        for item in queue
    )
    return (
        "<section id=\"authority-exception-details\">"
        "<h3>Exception evidence details</h3>"
        "<div class=\"table-wrap\"><table><thead><tr>"
        "<th>Repository</th><th>Bounded detail</th><th>Source commit</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></div></section>"
    )
