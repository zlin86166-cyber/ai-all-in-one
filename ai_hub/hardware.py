from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


def _filetime_value(value: FILETIME) -> int:
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


class HardwareMonitor:
    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.Lock()
        self._last_cpu: tuple[int, int, int] | None = None
        self._static = self._static_info()
        self._boost_active = False

    def _static_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "os": platform.platform(),
            "machine": platform.machine(),
            "cpu": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "Unknown"),
            "logical_cores": os.cpu_count() or 1,
            "gpu": "Unknown",
        }
        if os.name == "nt":
            script = (
                "Get-CimInstance Win32_VideoController | "
                "Select-Object -First 1 Name,AdapterRAM | ConvertTo-Json -Compress"
            )
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", script],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                data = json.loads(result.stdout.strip())
                info["gpu"] = data.get("Name") or "Unknown"
                info["vram_gb"] = round((data.get("AdapterRAM") or 0) / 1024**3, 1)
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
                info["vram_gb"] = None
        return info

    def _memory(self) -> dict[str, Any]:
        if os.name == "nt":
            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return {
                    "percent": int(status.dwMemoryLoad),
                    "total_gb": round(status.ullTotalPhys / 1024**3, 1),
                    "available_gb": round(status.ullAvailPhys / 1024**3, 1),
                }
        return {"percent": 0, "total_gb": None, "available_gb": None}

    def _power(self) -> dict[str, Any]:
        if os.name == "nt":
            status = SYSTEM_POWER_STATUS()
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
                return {
                    "ac_connected": status.ACLineStatus == 1,
                    "battery_percent": None if status.BatteryLifePercent == 255 else status.BatteryLifePercent,
                    "charging": bool(status.BatteryFlag & 8),
                }
        return {"ac_connected": True, "battery_percent": None, "charging": False}

    def _cpu_percent(self) -> float:
        if os.name != "nt":
            return 0.0
        idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return 0.0
        current = (_filetime_value(idle), _filetime_value(kernel), _filetime_value(user))
        with self._lock:
            previous = self._last_cpu
            self._last_cpu = current
        if not previous:
            return 0.0
        idle_delta = current[0] - previous[0]
        total_delta = (current[1] - previous[1]) + (current[2] - previous[2])
        if total_delta <= 0:
            return 0.0
        return round(max(0.0, min(100.0, 100 * (1 - idle_delta / total_delta))), 1)

    def snapshot(self) -> dict[str, Any]:
        memory = self._memory()
        power = self._power()
        disk = shutil.disk_usage(self.root)
        return {
            **self._static,
            "cpu_percent": self._cpu_percent(),
            "memory": memory,
            "power": power,
            "disk": {
                "total_gb": round(disk.total / 1024**3, 1),
                "free_gb": round(disk.free / 1024**3, 1),
                "percent": round((disk.used / disk.total) * 100, 1),
            },
            "performance_boost_active": self._boost_active,
            "timestamp": time.time(),
        }

    def update_performance_boost(self, enabled: bool, threshold: int) -> bool:
        snapshot = self.snapshot()
        should_boost = bool(
            enabled
            and snapshot["power"]["ac_connected"]
            and snapshot["memory"]["percent"] >= threshold
        )
        if should_boost == self._boost_active:
            return self._boost_active
        if os.name == "nt":
            priority = 0x00000080 if should_boost else 0x00000020
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, priority)
        self._boost_active = should_boost
        return self._boost_active
