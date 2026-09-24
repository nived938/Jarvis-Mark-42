"""Hardware Health Center.

Read-only snapshot of CPU, memory, temperatures, GPU telemetry, disks, battery,
network interfaces, and Windows PnP problem-device count when available.
"""
from __future__ import annotations

import ctypes
import platform
from pathlib import Path

import psutil

_OS = platform.system()
_nvml = None


def _gpu() -> dict:
    out = {"name": None, "util": None, "temp": None, "memory_used_mb": None, "memory_total_mb": None}
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        out["name"] = pynvml.nvmlDeviceGetName(h).decode(errors="replace") if isinstance(
            pynvml.nvmlDeviceGetName(h), (bytes, bytearray)) else str(pynvml.nvmlDeviceGetName(h))
        out["util"] = float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
        out["temp"] = float(pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU))
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        out["memory_used_mb"] = mem.used / 1024**2
        out["memory_total_mb"] = mem.total / 1024**2
    except Exception:
        pass
    return out


def _cpu_temp():
    try:
        temps = psutil.sensors_temperatures()
        preferred = ["coretemp", "k10temp", "cpu_thermal", "acpitz", "zenpower"]
        for name in preferred:
            if name in temps and temps[name]:
                return float(temps[name][0].current)
        for rows in temps.values():
            if rows:
                return float(rows[0].current)
    except Exception:
        pass
    if _OS == "Windows":
        try:
            import wmi  # type: ignore
            zones = wmi.WMI(namespace="root/wmi").MSAcpi_ThermalZoneTemperature()
            if zones:
                return (float(zones[0].CurrentTemperature) / 10.0) - 273.15
        except Exception:
            pass
    return None


def _problems() -> str:
    if _OS != "Windows":
        return "not applicable"
    try:
        import wmi  # type: ignore
        rows = wmi.WMI().Win32_PnPEntity(ConfigManagerErrorCode__ne=0)
        return str(len(list(rows)))
    except Exception:
        return "unavailable"


def snapshot() -> str:
    cpu = psutil.cpu_percent(interval=0.35)
    mem = psutil.virtual_memory()
    gpu = _gpu()
    temp = _cpu_temp()
    lines = [
        "HARDWARE HEALTH CENTER",
        "",
        f"CPU load: {cpu:.1f}%",
        f"CPU temperature: {temp:.1f} C" if temp is not None else "CPU temperature: unavailable",
        f"RAM: {mem.percent:.1f}%  ({mem.used / 1024**3:.1f} / {mem.total / 1024**3:.1f} GB)",
    ]
    if gpu["name"]:
        lines.extend([
            f"GPU: {gpu['name']}",
            f"GPU load: {gpu['util']:.1f}%",
            f"GPU temperature: {gpu['temp']:.1f} C" if gpu["temp"] is not None else "GPU temperature: unavailable",
            f"GPU memory: {gpu['memory_used_mb']:.0f} / {gpu['memory_total_mb']:.0f} MB",
        ])
    else:
        lines.append("GPU telemetry: unavailable")

    lines.append("")
    lines.append("DISKS")
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            lines.append(
                f"- {part.mountpoint}: {usage.used / 1024**3:.1f} / {usage.total / 1024**3:.1f} GB "
                f"({usage.percent:.1f}% used)"
            )
        except Exception:
            pass

    batt = None
    try:
        batt = psutil.sensors_battery()
    except Exception:
        pass
    lines.append("")
    if batt:
        state = "charging" if batt.power_plugged else "on battery"
        lines.append(f"Battery: {batt.percent:.0f}% ({state})")
    else:
        lines.append("Battery: unavailable")

    net = psutil.net_if_stats()
    active = [name for name, stat in net.items() if getattr(stat, "isup", False)]
    lines.append(f"Active network interfaces: {', '.join(active) if active else 'none'}")
    lines.append(f"Windows problem devices: {_problems()}")
    return "\n".join(lines)


def _handler(parameters, **_):
    return snapshot()


TOOL = {
    "name": "hardware_health",
    "description": (
        "Show a detailed read-only Hardware Health Center snapshot with CPU, RAM, "
        "temperature, GPU, VRAM, disks, battery, network interfaces, and Windows problem devices."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
        "required": [],
    },
    "handler": _handler,
}
