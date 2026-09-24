"""JARVIS Resource Manager: detailed CPU/RAM/GPU/disk/process intelligence."""
from __future__ import annotations

import os
import platform
from collections import Counter
from pathlib import Path

import psutil


def _gpu_snapshot() -> dict:
    result = {"utilization_percent": None, "memory_used_mb": None, "memory_total_mb": None}
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        result.update(
            utilization_percent=float(util.gpu),
            memory_used_mb=round(mem.used / 1024**2),
            memory_total_mb=round(mem.total / 1024**2),
        )
    except Exception:
        pass
    return result


def _process_rows(limit: int, sort_by: str) -> list[dict]:
    rows = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
        try:
            info = proc.info
            mem = getattr(info.get("memory_info"), "rss", 0) / 1024**2
            cpu = float(info.get("cpu_percent") or 0.0)
            rows.append(
                {
                    "pid": int(info.get("pid") or 0),
                    "name": str(info.get("name") or "unknown"),
                    "cpu_percent": round(cpu, 1),
                    "memory_mb": round(mem, 1),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    key = "memory_mb" if sort_by == "memory" else "cpu_percent"
    return sorted(rows, key=lambda x: x[key], reverse=True)[:max(1, min(limit, 20))]


def snapshot() -> dict:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(Path.cwd().anchor or os.getcwd())
    net = psutil.net_io_counters()
    gpu = _gpu_snapshot()
    load = getattr(os, "getloadavg", lambda: (0.0, 0.0, 0.0))()
    return {
        "platform": f"{platform.system()} {platform.release()}",
        "cpu_percent": round(psutil.cpu_percent(interval=0.2), 1),
        "cpu_count": psutil.cpu_count(logical=True),
        "ram_percent": round(vm.percent, 1),
        "ram_used_gb": round(vm.used / 1024**3, 2),
        "ram_total_gb": round(vm.total / 1024**3, 2),
        "ram_available_gb": round(vm.available / 1024**3, 2),
        "disk_percent": round(disk.percent, 1),
        "disk_free_gb": round(disk.free / 1024**3, 2),
        "gpu": gpu,
        "process_count": len(psutil.pids()),
        "network_sent_mb": round(net.bytes_sent / 1024**2, 1),
        "network_recv_mb": round(net.bytes_recv / 1024**2, 1),
        "load_average": [round(float(x), 2) for x in load],
    }


def _recommendations(data: dict) -> list[str]:
    recs: list[str] = []
    if data["ram_percent"] >= 90:
        recs.append("RAM is critically high. Close unused applications before starting another heavy task.")
    elif data["ram_percent"] >= 80:
        recs.append("RAM usage is high. Prefer lighter local models and close unused applications.")
    if data["cpu_percent"] >= 90:
        recs.append("CPU usage is very high. Identify the top CPU process before launching more work.")
    if data["disk_percent"] >= 90:
        recs.append("System disk is nearly full. Free storage before large downloads or builds.")
    gpu = data.get("gpu", {})
    if isinstance(gpu, dict) and gpu.get("memory_total_mb") and gpu.get("memory_used_mb"):
        pct = (gpu["memory_used_mb"] / gpu["memory_total_mb"]) * 100
        if pct >= 90:
            recs.append("GPU memory is nearly full. Close GPU-heavy applications before starting vision workloads.")
    if not recs:
        recs.append("System resources are within normal operating ranges.")
    return recs


def _handler(parameters=None, **_):
    p = parameters or {}
    action = str(p.get("action", "status")).strip().lower()
    limit = int(p.get("limit", 8) or 8)

    if action in {"status", "snapshot", "analyze"}:
        data = snapshot()
        if action == "status":
            return (
                f"CPU {data['cpu_percent']}% | RAM {data['ram_percent']}% "
                f"({data['ram_available_gb']} GB available) | Disk {data['disk_percent']}% | "
                f"Processes {data['process_count']}"
            )
        lines = [
            "JARVIS RESOURCE SNAPSHOT",
            f"Platform: {data['platform']}",
            f"CPU: {data['cpu_percent']}% across {data['cpu_count']} logical cores",
            f"RAM: {data['ram_used_gb']} / {data['ram_total_gb']} GB ({data['ram_percent']}%), "
            f"{data['ram_available_gb']} GB available",
            f"Disk: {data['disk_percent']}% used, {data['disk_free_gb']} GB free",
            f"GPU: {data['gpu'].get('utilization_percent')}% utilization, "
            f"{data['gpu'].get('memory_used_mb')} / {data['gpu'].get('memory_total_mb')} MB VRAM"
            if data["gpu"].get("memory_total_mb") else "GPU: NVIDIA metrics unavailable",
            f"Processes: {data['process_count']}",
        ]
        if action == "analyze":
            lines.append("Recommendations:")
            lines.extend(f"- {x}" for x in _recommendations(data))
        return "\n".join(lines)

    if action in {"top_cpu", "cpu"}:
        rows = _process_rows(limit, "cpu")
        return "Top CPU processes:\n" + "\n".join(
            f"- {r['name']} (PID {r['pid']}): {r['cpu_percent']}% CPU, {r['memory_mb']} MB RAM"
            for r in rows
        ) if rows else "No process data available."

    if action in {"top_memory", "memory", "ram"}:
        rows = _process_rows(limit, "memory")
        return "Top memory processes:\n" + "\n".join(
            f"- {r['name']} (PID {r['pid']}): {r['memory_mb']} MB RAM, {r['cpu_percent']}% CPU"
            for r in rows
        ) if rows else "No process data available."

    if action == "disk":
        return (
            f"Disk: {psutil.disk_usage(Path.cwd().anchor or os.getcwd()).percent}% used; "
            f"{psutil.disk_usage(Path.cwd().anchor or os.getcwd()).free / 1024**3:.1f} GB free."
        )

    return "Use action status, analyze, top_cpu, top_memory, or disk."


TOOL = {
    "name": "resource_manager",
    "description": (
        "Inspect detailed computer resources and find what is consuming CPU or RAM. "
        "Use for performance problems, heavy applications, local AI model selection, "
        "disk pressure, GPU/VRAM pressure, and resource analysis. Read-only."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "status | analyze | top_cpu | top_memory | disk"
            },
            "limit": {
                "type": "INTEGER",
                "description": "Number of top processes to return, 1-20"
            }
        },
        "required": ["action"],
    },
    "handler": _handler,
}
