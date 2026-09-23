"""Gmail manager using Google's official Gmail API and desktop OAuth."""
from __future__ import annotations
import base64,re,threading
from pathlib import Path
from email.utils import parsedate_to_datetime
BASE_DIR=Path(__file__).resolve().parent.parent
CREDENTIALS=BASE_DIR/"config"/"google_credentials.json"
TOKEN=BASE_DIR/"config"/"gmail_token.json"
SCOPES=["https://www.googleapis.com/auth/gmail.readonly"]
_lock=threading.RLock()
_service=None

def _service_obj():
    global _service
    with _lock:
        if _service is not None: return _service
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        creds=None
        if TOKEN.exists():
            creds=Credentials.from_authorized_user_file(str(TOKEN),SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDENTIALS.exists():
                    raise RuntimeError(f"Google desktop OAuth credentials not found: {CREDENTIALS}")
                flow=InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS),SCOPES)
                creds=flow.run_local_server(port=0)
            TOKEN.write_text(creds.to_json(),encoding="utf-8")
        _service=build("gmail","v1",credentials=creds,cache_discovery=False)
        return _service

def _header(headers,name):
    for h in headers or []:
        if h.get("name","").lower()==name.lower(): return h.get("value","")
    return ""

def _body(payload):
    data=payload or {}
    if data.get("body",{}).get("data"):
        try: return base64.urlsafe_b64decode(data["body"]["data"]+"==").decode("utf-8","ignore")
        except Exception: pass
    for part in data.get("parts",[]) or []:
        out=_body(part)
        if out: return out
    return ""

def _code(text,subject=""):
    sample=(subject+"\n"+text)
    m=re.search(r"(?i)(?:otp|verification|security|one[- ]time|login|confirmation)\D{0,32}([A-Z0-9]{4,10})",sample)
    if m: return m.group(1)
    candidates=re.findall(r"\b\d{6}\b",sample)
    return candidates[0] if candidates else ""

def _format(msg,include_body=False):
    headers=(msg.get("payload") or {}).get("headers",[])
    subject=_header(headers,"Subject") or "(no subject)"
    sender=_header(headers,"From") or "(unknown sender)"
    date=_header(headers,"Date")
    snippet=msg.get("snippet","")
    body=_body(msg.get("payload") or {})
    code=_code(body,subject)
    try: date=parsedate_to_datetime(date).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception: pass
    out=f"{subject}\nFrom: {sender}\nDate: {date}\n{snippet}"
    if code: out+=f"\nPOSSIBLE CODE: {code}"
    if include_body and body: out+="\n\n"+body[:3500]
    return out

def _handler(parameters,**_):
    action=str(parameters.get("action","latest")).lower()
    svc=_service_obj()
    if action in {"latest","unread"}:
        q="in:inbox"
        if action=="unread": q+=" is:unread"
        n=max(1,min(20,int(parameters.get("limit",5) or 5)))
        resp=svc.users().messages().list(userId="me",q=q,maxResults=n).execute()
        ids=resp.get("messages",[])
        if not ids: return "No matching Gmail messages."
        rows=[]
        for item in ids:
            msg=svc.users().messages().get(userId="me",id=item["id"],format="full").execute()
            rows.append(_format(msg))
        return "\n\n---\n\n".join(rows)
    if action=="search":
        q=str(parameters.get("query","")).strip()
        if not q: return "Provide a Gmail search query."
        resp=svc.users().messages().list(userId="me",q=q,maxResults=10).execute()
        rows=[]
        for item in resp.get("messages",[]):
            msg=svc.users().messages().get(userId="me",id=item["id"],format="full").execute()
            rows.append(_format(msg))
        return "\n\n---\n\n".join(rows) or "No Gmail messages matched."
    if action=="read":
        mid=str(parameters.get("message_id","")).strip()
        if not mid: return "Provide message_id."
        msg=svc.users().messages().get(userId="me",id=mid,format="full").execute()
        return _format(msg,include_body=True)
    return "Gmail action must be latest, unread, search, or read."

TOOL={"name":"gmail_manager","description":"Read Gmail with Google's official Gmail API. It can list latest/unread mail, search messages, read a message body, and detect likely OTP/verification/security codes in mail.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"latest | unread | search | read"},"limit":{"type":"INTEGER","description":"Number of latest messages, 1 to 20"},"query":{"type":"STRING","description":"Gmail search query"},"message_id":{"type":"STRING","description":"Gmail message id"}},"required":["action"]},"handler=_handler}
