"""Safe storage cleanup intelligence.

Scans reclaimable cache/temp locations and large user files without changing
anything. Cleanup only removes known cache/temp contents after the user asks
for an executing cleanup.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _roots() -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    temp = Path(os.environ.get("TEMP") or (Path.home() / "AppData" / "Local" / "Temp"))
    roots.append(("Windows temp" if os.name == "nt" else "User temp", temp))
    pip_cache = Path.home() / "AppData" / "Local" / "pip" / "Cache"
    if pip_cache.exists():
        roots.append(("pip cache", pip_cache))
    local_cache = Path.home() / ".cache"
    if local_cache.exists() and os.name != "nt":
        roots.append(("user cache", local_cache))
    return roots


def _scan_root(label: str, root: Path, max_items: int = 20000) -> tuple[int, int, int]:
    total = count = old = 0
    cutoff = time.time() - 3 * 86400
    seen = 0
    if not root.exists() or not root.is_dir():
        return 0, 0, 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".git")]
        for name in files:
            seen += 1
            if seen > max_items:
                return total, count, old
            p = Path(base) / name
            try:
                size = p.stat().st_size
                total += size
                count += 1
                if p.stat().st_mtime < cutoff:
                    old += 1
            except OSError:
                continue
    return total, count, old


def scan_storage() -> str:
    lines = ["STORAGE CLEANUP INTELLIGENCE", ""]
    grand = 0
    for label, root in _roots():
        size, count, old = _scan_root(label, root)
        grand += size
        lines.append(
            f"- {label}: {size / (1024**2):.1f} MB across {count} file(s); "
            f"{old} older than 3 days"
        )
    try:
        usage = shutil.disk_usage(BASE_DIR)
        lines.extend([
            "",
            f"Drive total: {usage.total / (1024**3):.1f} GB",
            f"Drive used:  {usage.used / (1024**3):.1f} GB ({usage.used / usage.total * 100:.1f}%)",
            f"Drive free:  {usage.free / (1024**3):.1f} GB",
            f"Known reclaimable cache/temp: {grand / (1024**3):.2f} GB",
        ])
    except Exception:
        pass
    lines.extend([
        "",
        "Safe target policy: cache/temp locations only.",
        "User documents, Downloads, Desktop, project folders, and personal media are never deleted by this action."
    ])
    return "\n".join(lines)


def clean_storage(days: int = 3) -> str:
    cutoff = time.time() - max(1, min(int(days or 3), 30)) * 86400
    deleted = 0
    reclaimed = 0
    skipped = 0
    for _label, root in _roots():
        if not root.exists():
            continue
        for base, _dirs, files in os.walk(root):
            for name in files:
                p = Path(base) / name
                try:
                    st = p.stat()
                    if st.st_mtime >= cutoff:
                        continue
                    size = st.st_size
                    p.unlink()
                    deleted += 1
                    reclaimed += size
                except OSError:
                    skipped += 1
    return (
        f"Storage cleanup complete: reclaimed {reclaimed / (1024**2):.1f} MB "
        f"from {deleted} old cache/temp file(s); {skipped} file(s) were locked or skipped."
    )


def _handler(parameters, **_):
    action = str(parameters.get("action", "scan") or "scan").lower()
    if action in {"scan", "status", "preview"}:
        return scan_storage()
    if action == "clean":
        if not bool(parameters.get("confirm", False)):
            return (
                "Cleanup not executed. This action requires confirm=true after the "
                "user explicitly asked to remove old cache/temp data."
            )
        return clean_storage(int(parameters.get("days", 3) or 3))
    return "Unknown storage_cleanup action."


TOOL = {
    "name": "storage_cleanup",
    "description": (
        "Analyze storage pressure and safely reclaim old cache/temp data. "
        "Use scan or preview for a read-only plan. Use clean only after the user "
        "explicitly asks to remove the identified cache/temp data. Never delete personal files."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "scan | preview | clean | status"},
            "days": {"type": "INTEGER", "description": "Only clean cache/temp files older than this many days, 1-30."},
            "confirm": {"type": "BOOLEAN", "description": "Must be true only after the user explicitly asked to execute cleanup."},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
