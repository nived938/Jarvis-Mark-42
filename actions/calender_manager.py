"""Google Calendar manager. Filename intentionally follows JARVIS's existing naming convention."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from pathlib import Path
import threading
BASE_DIR=Path(__file__).resolve().parent.parent
CREDENTIALS=BASE_DIR/"config"/"google_credentials.json"
TOKEN=BASE_DIR/"config"/"calendar_token.json"
SCOPES=[
"https://www.googleapis.com/auth/calendar.events",
"https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]
_lock=threading.RLock(); _service=None

def _service_obj():
    global _service
    with _lock:
        if _service is not None:return _service
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        creds=None
        if TOKEN.exists(): creds=Credentials.from_authorized_user_file(str(TOKEN),SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
            else:
                if not CREDENTIALS.exists(): raise RuntimeError(f"Google desktop OAuth credentials not found: {CREDENTIALS}")
                flow=InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS),SCOPES)
                creds=flow.run_local_server(port=0)
            TOKEN.write_text(creds.to_json(),encoding="utf-8")
        _service=build("calendar","v3",credentials=creds,cache_discovery=False)
        return _service

def _handler(parameters,**_):
    action=str(parameters.get("action","upcoming")).lower()
    svc=_service_obj()
    cal=str(parameters.get("calendar_id","primary") or "primary")
    if action in {"today","upcoming"}:
        now=datetime.now().astimezone()
        if action=="today":
            start=now.replace(hour=0,minute=0,second=0,microsecond=0)
            end=start+timedelta(days=1)
        else:
            days=max(1,min(30,int(parameters.get("days",7) or 7)))
            start=now; end=now+timedelta(days=days)
        events=svc.events().list(calendarId=cal,timeMin=start.isoformat(),timeMax=end.isoformat(),singleEvents=True,orderBy="startTime",maxResults=50).execute().get("items",[])
        if not events:return "No calendar events in that period."
        rows=[]
        for e in events:
            st=(e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date")
            en=(e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date")
            rows.append(f"{st} -> {en}\n{e.get('summary','(untitled)')}"+(f"\nLocation: {e.get('location')}" if e.get("location") else ""))
        return "\n\n---\n\n".join(rows)
    if action=="create":
        summary=str(parameters.get("summary","")).strip()
        if not summary:return "Provide an event summary."
        start=str(parameters.get("start","")).strip()
        end=str(parameters.get("end","")).strip()
        if not start:return "Provide start as ISO 8601 datetime, for example 2026-09-24T15:00:00+05:30."
        if not end:end=(datetime.fromisoformat(start)+timedelta(minutes=int(parameters.get("duration_minutes",60) or 60))).isoformat()
        body={"summary":summary,"start":{"dateTime":start,"timeZone":parameters.get("time_zone","")},"end":{"dateTime":end,"timeZone":parameters.get("time_zone","")}}
        if parameters.get("location"):body["location"]=str(parameters["location"])
        if parameters.get("description"):body["description"]=str(parameters["description"])
        e=svc.events().insert(calendarId=cal,body=body).execute()
        return f"Created calendar event '{summary}' starting {e['start'].get('dateTime',e['start'].get('date'))}."
    if action=="delete":
        event_id=str(parameters.get("event_id","")).strip()
        if not event_id:return "Provide event_id."
        svc.events().delete(calendarId=cal,eventId=event_id).execute()
        return "Calendar event deleted."
    if action=="update":
        event_id=str(parameters.get("event_id","")).strip()
        if not event_id:return "Provide event_id."
        e=svc.events().get(calendarId=cal,eventId=event_id).execute()
        for k in ("summary","location","description"):
            if parameters.get(k) is not None:e[k]=str(parameters[k])
        if parameters.get("start"):e["start"]["dateTime"]=str(parameters["start"])
        if parameters.get("end"):e["end"]["dateTime"]=str(parameters["end"])
        svc.events().update(calendarId=cal,eventId=event_id,body=e).execute()
        return "Calendar event updated."
    if action=="calendars":
        items=svc.calendarList().list(maxResults=50).execute().get("items",[])
        return "\n".join(f"{x.get('id')}: {x.get('summary','')}" for x in items) or "No calendars returned."
    return "Calendar action must be today, upcoming, create, update, delete, or calendars."

TOOL={"name":"calender_manager","description":"Google Calendar control using the official Calendar API. List today's or upcoming events, create/update/delete events, and list available calendars.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"today | upcoming | create | update | delete | calendars"},"calendar_id":{"type":"STRING","description":"Calendar id; default primary"},"days":{"type":"INTEGER","description":"Upcoming window 1 to 30 days"},"summary":{"type":"STRING","description":"Event title"},"start":{"type":"STRING","description":"ISO 8601 start datetime"},"end":{"type":"STRING","description":"ISO 8601 end datetime"},"duration_minutes":{"type":"INTEGER","description":"Used when end is omitted"},"time_zone":{"type":"STRING","description":"Optional IANA timezone"},"location":{"type":"STRING","description":"Event location"},"description":{"type":"STRING","description":"Event description"},"event_id":{"type":"STRING","description":"Calendar event id"}},"required":["action"]},"handler=_handler}
