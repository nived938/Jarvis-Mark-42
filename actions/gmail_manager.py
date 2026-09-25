"""Full Gmail agent using Google's official Gmail API and desktop OAuth.

The action supports reading/searching plus safe write operations:
send/reply/forward, drafts, labels, archive/read-state changes, trash,
and persistent Windows scheduled sends.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS = BASE_DIR / "config" / "google_credentials.json"
TOKEN = BASE_DIR / "config" / "gmail_token.json"
SCHEDULE_DIR = BASE_DIR / "memory" / "gmail_schedules"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

_lock = threading.RLock()
_service = None

_auth_thread = None
_auth_state = {
    "status": "idle",
    "started_at": 0.0,
    "finished_at": 0.0,
    "error": "",
}
REQUIRED_SCOPES = set(SCOPES)


class GmailAuthorizationRequired(RuntimeError):
    """Raised when Gmail needs user OAuth without blocking a normal command."""


def _token_has_required_scopes():
    if not TOKEN.exists():
        return False
    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        granted = set(creds.scopes or [])
        return bool(creds) and REQUIRED_SCOPES.issubset(granted)
    except Exception:
        return False


def _auth_worker():
    global _service, _auth_state
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        if not CREDENTIALS.exists():
            raise RuntimeError(f"Google desktop OAuth credentials not found: {CREDENTIALS}")

        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS),
            SCOPES,
        )

        with _lock:
            started = datetime.now().timestamp()
            _auth_state = {
                "status": "waiting_for_browser",
                "started_at": started,
                "finished_at": 0.0,
                "error": "",
            }

        creds = flow.run_local_server(
            port=0,
            open_browser=True,
            timeout=600,
            prompt="consent",
        )

        TOKEN.parent.mkdir(parents=True, exist_ok=True)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")

        with _lock:
            _service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            _auth_state = {
                "status": "authorized",
                "started_at": started,
                "finished_at": datetime.now().timestamp(),
                "error": "",
            }
    except Exception as exc:
        with _lock:
            _auth_state = {
                "status": "failed",
                "started_at": _auth_state.get("started_at", 0.0),
                "finished_at": datetime.now().timestamp(),
                "error": str(exc),
            }


def _start_authorization():
    global _auth_thread
    with _lock:
        if _auth_thread is not None and _auth_thread.is_alive():
            return "Gmail authorization is already running. Finish the Google sign-in in your browser."

        if not CREDENTIALS.exists():
            return f"Google desktop OAuth credentials not found: {CREDENTIALS}"

        _auth_thread = threading.Thread(
            target=_auth_worker,
            daemon=True,
            name="jarvis-gmail-oauth",
        )
        _auth_thread.start()

    return (
        "Gmail authorization started in the background. "
        "A Google sign-in window should open. Complete the permission screen, "
        "then say 'Gmail auth status'. JARVIS will not block while waiting."
    )


def _auth_status() -> str:
    with _lock:
        state = dict(_auth_state)
        alive = bool(_auth_thread and _auth_thread.is_alive())

    if _token_has_required_scopes() and state.get("status") == "authorized":
        return "Gmail is authorized and ready."

    if alive and state.get("status") == "waiting_for_browser":
        return "Gmail authorization is waiting for you to finish Google sign-in in the browser."

    if state.get("status") == "failed":
        return f"Gmail authorization failed: {state.get('error') or 'unknown error'}"

    return "Gmail is not authorized yet. Say 'authorize Gmail' to start Google authorization."




def _service_obj():
    global _service
    with _lock:
        if _service is not None:
            return _service

    if not TOKEN.exists() or not _token_has_required_scopes():
        raise GmailAuthorizationRequired(
            "Gmail authorization is required. Say 'authorize Gmail' first."
        )

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    except Exception as exc:
        raise GmailAuthorizationRequired(
            f"Gmail token could not be loaded: {exc}. Say 'authorize Gmail'."
        ) from exc

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                TOKEN.write_text(creds.to_json(), encoding="utf-8")
            except Exception as exc:
                raise GmailAuthorizationRequired(
                    f"Gmail authorization expired: {exc}. Say 'authorize Gmail'."
                ) from exc
        else:
            raise GmailAuthorizationRequired(
                "Gmail authorization expired. Say 'authorize Gmail' to reauthorize."
            )

    with _lock:
        if _service is None:
            _service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return _service


def _header(headers, name):
    for h in headers or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _body(payload) -> str:
    data = payload or {}
    if data.get("body", {}).get("data"):
        try:
            raw = base64.urlsafe_b64decode(
                data["body"]["data"] + "===",
            )
            text = raw.decode("utf-8", "ignore")
            if text:
                return text
        except Exception:
            pass

    for part in data.get("parts", []) or []:
        out = _body(part)
        if out:
            return out
    return ""


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _code(text, subject=""):
    sample = subject + "\n" + text
    match = re.search(
        r"(?i)(?:otp|verification|security|one[- ]time|login|confirmation)"
        r"\D{0,32}([A-Z0-9]{4,10})",
        sample,
    )
    return match.group(1) if match else ""


def _format(msg, include_body=False):
    headers = (msg.get("payload") or {}).get("headers", [])
    subject = _header(headers, "Subject") or "(no subject)"
    sender = _header(headers, "From") or "(unknown sender)"
    date = _header(headers, "Date")
    snippet = msg.get("snippet", "")
    body = _body(msg.get("payload") or {})
    code = _code(body, subject)

    try:
        date = parsedate_to_datetime(date).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass

    out = (
        f"Message ID: {msg.get('id', '')}\n"
        f"Thread ID: {msg.get('threadId', '')}\n"
        f"{subject}\n"
        f"From: {sender}\n"
        f"Date: {date}\n"
        f"{snippet}"
    )
    if code:
        out += f"\nPOSSIBLE CODE: {code}"
    if include_body and body:
        out += "\n\n" + _strip_html(body)[:7000]
    return out


def _get_message(message_id: str, include_body=True):
    if not message_id:
        raise ValueError("message_id is required")
    return _service_obj().users().messages().get(
        userId="me",
        id=message_id,
        format="full",
    ).execute()


def _message_id_and_headers(message_id: str):
    msg = _get_message(message_id, include_body=False)
    headers = (msg.get("payload") or {}).get("headers", [])
    return msg, headers


def _extract_email(value: str) -> str:
    addresses = getaddresses([str(value or "")])
    return addresses[0][1].strip() if addresses else ""


def _build_raw_message(
    *,
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    in_reply_to: str = "",
    references: str = "",
    attachments: list[str] | None = None,
) -> str:
    msg = EmailMessage()
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    msg.set_content(body or "")

    for raw_path in attachments or []:
        path = Path(str(raw_path)).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Attachment not found: {path}")
        data = path.read_bytes()
        mime, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (mime or "application/octet-stream").split("/", 1)
        msg.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )

    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    return encoded


def _send_now(**kwargs) -> str:
    raw = _build_raw_message(**kwargs)
    sent = _service_obj().users().messages().send(
        userId="me",
        body={"raw": raw},
    ).execute()
    return str(sent.get("id") or "sent")


def _create_draft(**kwargs) -> str:
    raw = _build_raw_message(**kwargs)
    draft = _service_obj().users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}},
    ).execute()
    return str((draft.get("id") or "draft"))


def _find_label_id(name: str, create: bool = True) -> str:
    wanted = str(name or "").strip()
    if not wanted:
        raise ValueError("label is required")

    svc = _service_obj()
    labels = svc.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if str(label.get("name", "")).casefold() == wanted.casefold():
            return str(label["id"])

    if not create:
        raise ValueError(f"Gmail label '{wanted}' does not exist")

    created = svc.users().labels().create(
        userId="me",
        body={
            "name": wanted,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    ).execute()
    return str(created["id"])


def _modify_message(message_id: str, *, add=None, remove=None) -> str:
    _service_obj().users().messages().modify(
        userId="me",
        id=message_id,
        body={
            "addLabelIds": list(add or []),
            "removeLabelIds": list(remove or []),
        },
    ).execute()
    return message_id


def _queue_confirmation(player, key: str, title: str, detail: str, fn):
    try:
        from core import confirm as confirm_gate
        return confirm_gate.request(key, title, detail, fn)
    except Exception:
        # In headless/test mode, never silently perform an external action.
        return f"Confirmation is required before {title.lower()}. Nothing was sent or changed."


def _send_action(parameters, mode: str):
    p = parameters
    to = _extract_email(str(p.get("to", "")).strip())
    subject = str(p.get("subject", "")).strip()
    body = str(p.get("body", "")).strip()
    cc = str(p.get("cc", "") or "").strip()
    bcc = str(p.get("bcc", "") or "").strip()
    attachments = p.get("attachments") or []
    if isinstance(attachments, str):
        attachments = [x.strip() for x in attachments.split(",") if x.strip()]

    if not to:
        return "Provide a recipient email address."
    if not subject:
        return "Provide an email subject."
    if not body:
        return "Provide the email body."

    def run():
        if mode == "send":
            return f"Email sent to {to}: {_send_now(to=to, subject=subject, body=body, cc=cc, bcc=bcc, attachments=attachments)}"
        return f"Email draft created: {_create_draft(to=to, subject=subject, body=body, cc=cc, bcc=bcc, attachments=attachments)}"

    if mode == "draft":
        return run()

    return _queue_confirmation(
        None,
        f"gmail-{mode}-{uuid.uuid4().hex[:8]}",
        f"Send email to {to}",
        f"Subject: {subject}\n\n{body[:800]}",
        run,
    )


def _send_reply(parameters):
    message_id = str(parameters.get("message_id", "")).strip()
    body = str(parameters.get("body", "")).strip()
    if not message_id or not body:
        return "Provide message_id and reply body."

    msg, headers = _message_id_and_headers(message_id)
    original_subject = _header(headers, "Subject") or ""
    sender = _extract_email(_header(headers, "Reply-To") or _header(headers, "From"))
    message_id_header = _header(headers, "Message-ID")
    references = _header(headers, "References").strip()

    subject = original_subject
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject

    def run():
        sent = _send_now(
            to=sender,
            subject=subject,
            body=body,
            in_reply_to=message_id_header,
            references=(references + " " + message_id_header).strip(),
        )
        return f"Reply sent to {sender}: {sent}"

    return _queue_confirmation(
        None,
        f"gmail-reply-{uuid.uuid4().hex[:8]}",
        f"Reply to {sender}",
        f"Subject: {subject}\n\n{body[:800]}",
        run,
    )


def _send_forward(parameters):
    message_id = str(parameters.get("message_id", "")).strip()
    to = _extract_email(str(parameters.get("to", "")).strip())
    note = str(parameters.get("body", "") or "").strip()
    if not message_id or not to:
        return "Provide message_id and forwarding recipient."

    msg, headers = _message_id_and_headers(message_id)
    subject = _header(headers, "Subject") or "(no subject)"
    original_body = _strip_html(_body(msg.get("payload") or {}))
    forward_body = (
        (note + "\n\n" if note else "")
        + "---------- Forwarded message ----------\n"
        + f"Subject: {subject}\n"
        + f"From: {_header(headers, 'From')}\n"
        + f"Date: {_header(headers, 'Date')}\n\n"
        + original_body[:12000]
    )

    def run():
        sent = _send_now(
            to=to,
            subject=("Fwd: " + subject if not subject.lower().startswith("fwd:") else subject),
            body=forward_body,
        )
        return f"Email forwarded to {to}: {sent}"

    return _queue_confirmation(
        None,
        f"gmail-forward-{uuid.uuid4().hex[:8]}",
        f"Forward email to {to}",
        f"Subject: {subject}",
        run,
    )


def _schedule_windows(payload: dict) -> str:
    if os.name != "nt":
        return "Persistent scheduled email currently supports Windows Task Scheduler."

    SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:10]
    path = SCHEDULE_DIR / f"{sid}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    dt = datetime.fromisoformat(str(payload["scheduled_at"]))
    task_name = f"JARVIS_Gmail_{sid}"

    project_root = str(BASE_DIR).replace("\\", "/")
    payload_path = str(path).replace("\\", "/")
    script = (
        "import sys; "
        f"sys.path.insert(0, r'{project_root}'); "
        "from actions.gmail_manager import run_scheduled; "
        f"run_scheduled(r'{payload_path}')"
    )
    python_exe = Path(sys.executable)
    command = [
        "schtasks", "/Create",
        "/TN", task_name,
        "/TR", f'"{python_exe}" -c "{script}"',
        "/SC", "ONCE",
        "/ST", dt.strftime("%H:%M"),
        "/SD", dt.strftime("%m/%d/%Y"),
        "/F",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        path.unlink(missing_ok=True)
        err = (result.stderr or result.stdout).strip()
        return f"Could not schedule the email: {err}"

    return f"Email scheduled for {dt.isoformat()} (task {task_name})."


def run_scheduled(path: str) -> None:
    payload_path = Path(path)
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        _send_now(
            to=payload["to"],
            subject=payload["subject"],
            body=payload["body"],
            cc=payload.get("cc", ""),
            bcc=payload.get("bcc", ""),
            attachments=payload.get("attachments") or [],
        )
    finally:
        payload_path.unlink(missing_ok=True)


def _handler(parameters, player=None, **_):
    p = parameters or {}
    action = str(p.get("action", "latest")).strip().lower()

    if action in {"authorize", "auth", "login"}:
        return _start_authorization()

    if action in {"auth_status", "status"}:
        return _auth_status()

    try:
        svc = _service_obj()
    except GmailAuthorizationRequired as exc:
        return str(exc)

    if action in {"latest", "unread"}:
        q = "in:inbox"
        if action == "unread":
            q += " is:unread"
        n = max(1, min(20, int(p.get("limit", 5) or 5)))
        ids = svc.users().messages().list(
            userId="me", q=q, maxResults=n
        ).execute().get("messages", [])
        if not ids:
            return "No matching Gmail messages."
        return "\n\n---\n\n".join(
            _format(
                svc.users().messages().get(
                    userId="me", id=item["id"], format="full"
                ).execute()
            )
            for item in ids
        )

    if action == "search":
        q = str(p.get("query", "")).strip()
        if not q:
            return "Provide a Gmail search query."
        ids = svc.users().messages().list(
            userId="me", q=q, maxResults=max(1, min(50, int(p.get("limit", 10) or 10)))
        ).execute().get("messages", [])
        return "\n\n---\n\n".join(
            _format(
                svc.users().messages().get(
                    userId="me", id=item["id"], format="full"
                ).execute()
            )
            for item in ids
        ) or "No Gmail messages matched."

    if action == "read":
        return _format(_get_message(str(p.get("message_id", "")).strip()), include_body=True)

    if action in {"send", "draft"}:
        return _send_action(p, action)

    if action == "reply":
        return _send_reply(p)

    if action == "forward":
        return _send_forward(p)

    if action == "list_drafts":
        drafts = svc.users().drafts().list(
            userId="me", maxResults=max(1, min(50, int(p.get("limit", 20) or 20)))
        ).execute().get("drafts", [])
        if not drafts:
            return "No Gmail drafts."
        rows = []
        for item in drafts:
            draft = svc.users().drafts().get(
                userId="me", id=item["id"], format="full"
            ).execute()
            msg = draft.get("message", {})
            rows.append(_format(msg))
        return "\n\n---\n\n".join(rows)

    if action == "archive":
        mid = str(p.get("message_id", "")).strip()
        if not mid:
            return "Provide message_id."
        _modify_message(mid, remove=["INBOX"])
        return f"Archived Gmail message {mid}."

    if action == "mark_read":
        mid = str(p.get("message_id", "")).strip()
        if not mid:
            return "Provide message_id."
        _modify_message(mid, remove=["UNREAD"])
        return f"Marked Gmail message {mid} as read."

    if action == "mark_unread":
        mid = str(p.get("message_id", "")).strip()
        if not mid:
            return "Provide message_id."
        _modify_message(mid, add=["UNREAD"])
        return f"Marked Gmail message {mid} as unread."

    if action in {"trash", "delete"}:
        mid = str(p.get("message_id", "")).strip()
        if not mid:
            return "Provide message_id."

        def run():
            svc.users().messages().trash(userId="me", id=mid).execute()
            return f"Gmail message {mid} moved to Trash."

        return _queue_confirmation(
            player,
            f"gmail-trash-{mid}",
            "Move Gmail message to Trash",
            f"Message ID: {mid}",
            run,
        )

    if action == "purge":
        mid = str(p.get("message_id", "")).strip()
        if not mid:
            return "Provide message_id."

        def run():
            svc.users().messages().delete(userId="me", id=mid).execute()
            return f"Gmail message {mid} permanently deleted."

        return _queue_confirmation(
            player,
            f"gmail-purge-{mid}",
            "Permanently delete Gmail message",
            f"Message ID: {mid}",
            run,
        )

    if action == "label":
        mid = str(p.get("message_id", "")).strip()
        label = str(p.get("label", "")).strip()
        if not mid or not label:
            return "Provide message_id and label."
        lid = _find_label_id(label, create=True)
        _modify_message(mid, add=[lid])
        return f"Applied Gmail label '{label}' to {mid}."

    if action == "schedule":
        to = _extract_email(str(p.get("to", "")).strip())
        subject = str(p.get("subject", "")).strip()
        body = str(p.get("body", "")).strip()
        scheduled_at = str(p.get("scheduled_at", "")).strip()
        if not to or not subject or not body or not scheduled_at:
            return "Scheduled email needs to, subject, body, and scheduled_at (ISO 8601)."
        try:
            dt = datetime.fromisoformat(scheduled_at)
        except ValueError:
            return "scheduled_at must be ISO 8601, for example 2026-09-26T18:30:00."

        payload = {
            "to": to,
            "cc": str(p.get("cc", "") or "").strip(),
            "bcc": str(p.get("bcc", "") or "").strip(),
            "subject": subject,
            "body": body,
            "attachments": p.get("attachments") or [],
            "scheduled_at": dt.isoformat(),
        }

        def run():
            return _schedule_windows(payload)

        return _queue_confirmation(
            player,
            f"gmail-schedule-{uuid.uuid4().hex[:8]}",
            f"Schedule email to {to}",
            f"{dt.isoformat()}\nSubject: {subject}",
            run,
        )

    return (
        "Gmail action must be authorize, auth_status, latest, unread, search, read, "
        "send, reply, forward, draft, list_drafts, archive, mark_read, mark_unread, "
        "trash, purge, label, or schedule."
    )


TOOL = {
    "name": "gmail_manager",
    "description": (
        "Full Gmail agent. Authorize Gmail non-blockingly, check auth status, read/search mail, "
        "compose drafts, send email, reply, forward, list drafts, archive, mark read/unread, "
        "label, trash, permanently delete, and schedule a send on Windows. External sends/deletions "
        "use the HUD confirmation gate."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "authorize | auth_status | latest | unread | search | read | send | reply | forward | draft | list_drafts | archive | mark_read | mark_unread | trash | purge | label | schedule"},
            "limit": {"type": "INTEGER", "description": "Maximum messages/drafts to return"},
            "query": {"type": "STRING", "description": "Gmail search query"},
            "message_id": {"type": "STRING", "description": "Gmail message id"},
            "to": {"type": "STRING", "description": "Recipient email address"},
            "cc": {"type": "STRING", "description": "Optional comma-separated CC recipients"},
            "bcc": {"type": "STRING", "description": "Optional comma-separated BCC recipients"},
            "subject": {"type": "STRING", "description": "Email subject"},
            "body": {"type": "STRING", "description": "Email body or reply text"},
            "attachments": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Optional absolute/local attachment paths"},
            "label": {"type": "STRING", "description": "Gmail label name"},
            "scheduled_at": {"type": "STRING", "description": "ISO 8601 send time for schedule"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
