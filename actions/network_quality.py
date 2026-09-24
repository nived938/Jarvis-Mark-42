"""JARVIS Network Quality Monitor: read-only connectivity diagnostics."""
from __future__ import annotations

import json
import socket
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import psutil

BASE_DIR = Path(__file__).resolve().parent.parent
HISTORY_FILE = BASE_DIR / "memory" / "network_quality_history.json"
MAX_HISTORY = 40


def _tcp_probe(host: str, port: int = 443, timeout: float = 3.0) -> tuple[bool, float, str]:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return True, (time.perf_counter() - started) * 1000.0, "OK"
    except Exception as exc:
        return False, (time.perf_counter() - started) * 1000.0, str(exc)


def _dns_probe() -> tuple[bool, float, str]:
    started = time.perf_counter()
    try:
        socket.gethostbyname("example.com")
        return True, (time.perf_counter() - started) * 1000.0, "OK"
    except Exception as exc:
        return False, (time.perf_counter() - started) * 1000.0, str(exc)


def _https_probe() -> tuple[bool, float, str]:
    started = time.perf_counter()
    try:
        req = urllib.request.Request(
            "https://www.google.com/generate_204",
            method="GET",
            headers={"User-Agent": "JARVIS-Network-Monitor"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            status = int(getattr(response, "status", 200))
        return 200 <= status < 400, (time.perf_counter() - started) * 1000.0, f"HTTP {status}"
    except Exception as exc:
        return False, (time.perf_counter() - started) * 1000.0, str(exc)


def _active_interfaces() -> list[str]:
    try:
        stats = psutil.net_if_stats()
        return [
            name for name, info in stats.items()
            if getattr(info, "isup", False)
        ]
    except Exception:
        return []


def _quality(avg_ms: float | None, loss_pct: float, https_ok: bool, dns_ok: bool) -> str:
    if not dns_ok or not https_ok:
        return "POOR"
    if loss_pct == 0 and avg_ms is not None and avg_ms < 50:
        return "EXCELLENT"
    if loss_pct < 10 and avg_ms is not None and avg_ms < 100:
        return "GOOD"
    if loss_pct < 25 and avg_ms is not None and avg_ms < 200:
        return "FAIR"
    return "POOR"


def snapshot(host: str = "1.1.1.1", probes: int = 4) -> dict:
    probes = max(2, min(int(probes or 4), 8))
    tcp_rows = []
    for _ in range(probes):
        ok, ms, detail = _tcp_probe(host)
        tcp_rows.append({"ok": ok, "ms": round(ms, 1), "detail": detail})

    dns_ok, dns_ms, dns_detail = _dns_probe()
    https_ok, https_ms, https_detail = _https_probe()

    successful = [x["ms"] for x in tcp_rows if x["ok"]]
    loss = ((len(tcp_rows) - len(successful)) / len(tcp_rows)) * 100.0
    avg_ms = sum(successful) / len(successful) if successful else None

    return {
        "timestamp": datetime.now().astimezone().isoformat(),
        "host": host,
        "interfaces": _active_interfaces(),
        "tcp_probe_count": len(tcp_rows),
        "tcp_success_count": len(successful),
        "packet_loss_percent": round(loss, 1),
        "avg_latency_ms": round(avg_ms, 1) if avg_ms is not None else None,
        "min_latency_ms": round(min(successful), 1) if successful else None,
        "max_latency_ms": round(max(successful), 1) if successful else None,
        "dns_ok": dns_ok,
        "dns_ms": round(dns_ms, 1),
        "dns_detail": dns_detail,
        "https_ok": https_ok,
        "https_ms": round(https_ms, 1),
        "https_detail": https_detail,
    }


def _save_history(data: dict) -> None:
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            history = []
        if not isinstance(history, list):
            history = []
        history.append(data)
        HISTORY_FILE.write_text(
            json.dumps(history[-MAX_HISTORY:], indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _format(data: dict) -> str:
    avg = data.get("avg_latency_ms")
    loss = data.get("packet_loss_percent")
    quality = _quality(
        avg,
        float(loss or 0),
        bool(data.get("https_ok")),
        bool(data.get("dns_ok")),
    )
    lines = [
        "JARVIS NETWORK QUALITY",
        f"Quality: {quality}",
        "Interfaces: " + (", ".join(data.get("interfaces") or []) or "none"),
        f"TCP latency to {data.get('host', '1.1.1.1')}: "
        f"{avg if avg is not None else 'N/A'} ms average "
        f"({data.get('min_latency_ms', 'N/A')}–{data.get('max_latency_ms', 'N/A')} ms)",
        f"Packet loss: {loss}%",
        f"DNS: {'OK' if data.get('dns_ok') else 'FAILED'} ({data.get('dns_ms')} ms)",
        f"HTTPS: {'OK' if data.get('https_ok') else 'FAILED'} ({data.get('https_ms')} ms)",
        f"Checked: {data.get('timestamp', 'unknown')}",
    ]
    return "\n".join(lines)


def _handler(parameters=None, **_):
    p = parameters or {}
    action = str(p.get("action", "snapshot") or "snapshot").strip().lower()
    host = str(p.get("host", "1.1.1.1") or "1.1.1.1").strip()
    if action in {"snapshot", "status", "check", "test"}:
        data = snapshot(host=host, probes=int(p.get("probes", 4) or 4))
        _save_history(data)
        return _format(data)

    if action == "history":
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            history = []
        if not history:
            return "No network quality history has been recorded yet."
        rows = history[-max(1, min(int(p.get("limit", 10) or 10), 20)):]
        lines = ["Recent network quality checks:"]
        for row in reversed(rows):
            avg = row.get("avg_latency_ms")
            quality = _quality(
                avg,
                float(row.get("packet_loss_percent") or 0),
                bool(row.get("https_ok")),
                bool(row.get("dns_ok")),
            )
            lines.append(
                f"- {row.get('timestamp', '')} | {quality} | "
                f"{avg if avg is not None else 'N/A'} ms | "
                f"{row.get('packet_loss_percent', 'N/A')}% loss"
            )
        return "\n".join(lines)

    return "Use action snapshot, history, or test."


TOOL = {
    "name": "network_quality",
    "description": (
        "Read-only network quality diagnostics. Measure TCP latency, packet loss, "
        "DNS resolution, HTTPS reachability, active interfaces, and recent history."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "snapshot | status | check | test | history"},
            "host": {"type": "STRING", "description": "Probe target host, default 1.1.1.1"},
            "probes": {"type": "INTEGER", "description": "TCP probe count, 2-8"},
            "limit": {"type": "INTEGER", "description": "History rows, 1-20"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
