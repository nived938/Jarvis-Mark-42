"""Inspect/replay-ready summaries from JARVIS execution traces."""
from __future__ import annotations
from core.execution_trace import list_traces, read_trace

def _handler(parameters, **_):
    action=str(parameters.get("action","list")).lower()
    trace_id=str(parameters.get("trace_id","") or "").strip()
    if action=="list":
        rows=list_traces()
        return "\n".join(f"{x['id']}  {x['started']}  {x['events']} events" for x in rows[-20:]) or "No execution traces recorded."
    if action in {"inspect","replay"}:
        if not trace_id: return "Provide trace_id."
        events=read_trace(trace_id)
        if not events: return f"Trace not found: {trace_id}"
        lines=[]
        for e in events:
            if e.get("type")=="tool_start": lines.append(f"CALL {e.get('tool')} {e.get('args')}")
            elif e.get("type")=="tool_end": lines.append(f"RESULT {e.get('tool')} -> {str(e.get('result'))[:500]}")
        if action=="replay":
            return "DRY-RUN REPLAY (no tools executed):\n"+"\n".join(lines)
        return "\n".join(lines)
    return "Trace action must be list, inspect, or replay."

TOOL={"name":"trace_replay","description":"Inspect and dry-run replay JARVIS execution traces to debug exactly what tools were called and what they returned.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"list | inspect | replay"},"trace_id":{"type":"STRING","description":"Trace identifier"}},"required":["action"]},"handler":_handler}
