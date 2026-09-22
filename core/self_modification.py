"""
Guarded self-modification for JARVIS.

JARVIS may propose edits to its own source tree, but never applies a generated
change automatically. The proposed content is validated first, then parked
behind the UI-owned confirmation gate. Successful edits are registered with the
shared undo stack.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core import confirm as confirm_gate
from core.undo import push_undo


BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = BASE_DIR / "memory" / "self_modification.json"
BACKUP_DIR = BASE_DIR / "memory" / "self_modification_backups"

ALLOWED_ROOTS = {
    BASE_DIR / "main.py",
    BASE_DIR / "ui.py",
    BASE_DIR / "Jarvis_Manager.py",
    BASE_DIR / "setup.py",
    BASE_DIR / "readme.md",
    BASE_DIR / "requirements.txt",
}
ALLOWED_DIRS = {
    BASE_DIR / "actions",
    BASE_DIR / "core",
    BASE_DIR / "plugins",
}
BLOCKED_DIRS = {
    BASE_DIR / ".git",
    BASE_DIR / "config",
    BASE_DIR / "memory",
    BASE_DIR / "downloads",
    BASE_DIR / "screenshots",
}


def _resolve(path: str | Path) -> Path:
    raw = Path(path)
    return raw.resolve() if raw.is_absolute() else (BASE_DIR / raw).resolve()


def is_guarded_path(path: str | Path) -> bool:
    """Return True only for source files inside JARVIS's editable code tree."""
    try:
        p = _resolve(path)
    except Exception:
        return False
    if p in ALLOWED_ROOTS:
        return True
    for root in ALLOWED_DIRS:
        try:
            p.relative_to(root)
            return p.suffix.lower() in {".py", ".txt", ".md"}
        except ValueError:
            continue
    return False


def _is_blocked(path: Path) -> bool:
    for root in BLOCKED_DIRS:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _validate(path: Path, content: str) -> tuple[bool, str]:
    """Run cheap local validation before a generated edit can be proposed."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".py":
            compile(content, str(path), "exec")
            return True, "Python syntax OK."
        if suffix == ".json":
            json.loads(content)
            return True, "JSON syntax OK."
    except SyntaxError as e:
        return False, f"Syntax error: {e}"
    except json.JSONDecodeError as e:
        return False, f"JSON syntax error: {e}"
    except Exception as e:
        return False, f"Validation error: {e}"
    return True, "Local validation OK."


def _load() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def status() -> str:
    """Describe the current pending self-modification proposal."""
    state = _load()
    proposal = state.get("pending")
    if not proposal:
        return "No pending JARVIS self-modification proposal."
    return (
        "Pending JARVIS self-modification:\n"
        f"- File: {proposal.get('path', '?')}\n"
        f"- Reason: {proposal.get('reason', '?')}\n"
        f"- Proposed: {proposal.get('created_at', '?')}\n"
        f"- Validation: {proposal.get('validation', '?')}\n"
        f"- Size: {proposal.get('old_size', 0)} → {proposal.get('new_size', 0)} bytes"
    )


def reject_pending() -> str:
    state = _load()
    if not state.get("pending"):
        return "There is no pending JARVIS self-modification to reject."
    path = state["pending"].get("path", "?")
    state.pop("pending", None)
    _save(state)
    return f"Rejected the pending JARVIS self-modification for {path}."


def _apply(path: Path) -> str:
    state = _load()
    proposal = state.get("pending")
    if not proposal:
        return "The self-modification proposal no longer exists."

    if _resolve(proposal.get("path", "")) != path:
        return "The pending self-modification target changed. Nothing was applied."

    new_content = proposal.get("new_content")
    old_content = proposal.get("old_content")
    existed = bool(proposal.get("existed"))
    if not isinstance(new_content, str):
        return "The proposed source is incomplete. Nothing was applied."

    ok, detail = _validate(path, new_content)
    if not ok:
        return f"Final validation failed: {detail}. Nothing was applied."

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return f"Could not apply the self-modification: {e}"

    # Read-back verification catches write/path surprises before declaring success.
    try:
        if path.read_text(encoding="utf-8") != new_content:
            raise IOError("read-back content did not match the approved proposal")
    except Exception as e:
        try:
            if existed:
                path.write_text(old_content or "", encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
        except Exception:
            pass
        return f"Self-modification was rolled back after verification failed: {e}"

    # Keep a local backup as an audit artifact. It is git-ignored.
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:10]
        backup = BACKUP_DIR / f"{stamp}_{digest}_{path.name}.bak"
        if existed:
            backup.write_text(old_content or "", encoding="utf-8")
        else:
            backup.write_text("[FILE DID NOT EXIST BEFORE CHANGE]", encoding="utf-8")
    except Exception:
        pass

    def _undo(p=path, old=old_content, was_there=existed):
        if was_there:
            p.write_text(old or "", encoding="utf-8")
        else:
            p.unlink(missing_ok=True)
        return f"Restored {p.name} to its state before the approved self-modification."

    push_undo(f"self-modified {path.name}", _undo)

    state["last_applied"] = {
        "path": proposal.get("path"),
        "reason": proposal.get("reason"),
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "validation": detail,
    }
    state.pop("pending", None)
    _save(state)
    return f"Applied the approved self-modification to {path}."


def stage_write(path: str | Path, content: str, reason: str, player=None) -> str:
    """Validate and park a source edit behind a human-owned confirmation gate."""
    resolved = _resolve(path)
    if _is_blocked(resolved):
        return "This path is protected from self-modification."
    if not is_guarded_path(resolved):
        return "Self-modification is limited to JARVIS source files."

    if not isinstance(content, str) or not content:
        return "The proposed source is empty. Nothing was changed."

    ok, detail = _validate(resolved, content)
    if not ok:
        return f"Edit rejected before confirmation: {detail}"

    try:
        existed = resolved.exists()
        old_content = resolved.read_text(encoding="utf-8") if existed else ""
    except Exception as e:
        return f"Could not read the current source: {e}"

    relative = str(resolved.relative_to(BASE_DIR)).replace(os.sep, "/")
    proposal = {
        "path": relative,
        "reason": str(reason or "requested JARVIS self-modification")[:500],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "validation": detail,
        "old_content": old_content,
        "new_content": content,
        "existed": existed,
        "old_size": len(old_content.encode("utf-8")),
        "new_size": len(content.encode("utf-8")),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    _save({"pending": proposal, "last_applied": _load().get("last_applied")})

    summary = (
        f"{relative}: {len(old_content.splitlines())} → {len(content.splitlines())} lines. "
        f"Local validation passed ({detail})."
    )

    def _run():
        return _apply(resolved)

    result = confirm_gate.request(
        key="self-modification",
        title="Apply JARVIS code change",
        detail=summary,
        run=_run,
    )

    if player:
        try:
            player.write_log(f"SYS: Self-modification staged — {summary}")
        except Exception:
            pass
    return result


def rollback_last() -> str:
    """Rollback a self-modification only when it is the most recent undo entry."""
    from core import undo as undo_stack
    items = undo_stack.history()
    if items and items[0].startswith("self-modified "):
        return undo_stack.undo_last()
    if any(item.startswith("self-modified ") for item in items):
        return (
            "A self-modification exists in undo history, but unrelated changes were made "
            "after it. Use the normal undo flow so I do not revert those unrelated changes."
        )
    return "No applied JARVIS self-modification is available in the current session to roll back."
