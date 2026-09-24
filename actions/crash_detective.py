"""JARVIS Crash Detective action."""
from __future__ import annotations

from core.crash_detective import format_report, latest_report, list_reports


def _handler(parameters=None, **_):
    p = parameters or {}
    action = str(p.get("action", "latest") or "latest").strip().lower()
    limit = int(p.get("limit", 10) or 10)

    if action == "list":
        rows = list_reports(limit)
        if not rows:
            return "No JARVIS crash reports have been recorded."
        lines = ["Recent JARVIS crash reports:"]
        for row in rows:
            lines.append(
                f"- {row.get('timestamp', '')} | {row.get('exception_type', 'unknown')}: "
                f"{row.get('exception', '')[:160]}"
            )
        return "\n".join(lines)

    if action in {"latest", "show", "analyze", "status"}:
        report = latest_report()
        if action == "status":
            if not report:
                return "Crash Detective is active. No crash reports are recorded."
            return (
                "Crash Detective is active. "
                f"Latest failure: {report.get('exception_type', 'unknown')}: "
                f"{report.get('exception', '')}"
            )
        return format_report(report)

    return "Use action latest, analyze, list, or status."


TOOL = {
    "name": "crash_detective",
    "description": (
        "Inspect JARVIS crash reports captured from unhandled main-thread and "
        "thread exceptions. Reports are stored locally and include traceback, "
        "environment, and likely follow-up guidance."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "latest | analyze | list | status"},
            "limit": {"type": "INTEGER", "description": "Number of reports to list, 1-50"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
