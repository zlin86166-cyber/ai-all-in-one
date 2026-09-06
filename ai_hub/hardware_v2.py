from __future__ import annotations

import ctypes
import os
from typing import Any

from .hardware import HardwareMonitor as BaseHardwareMonitor


class HardwareMonitor(BaseHardwareMonitor):
    def resource_policy(self, requested_parallel: int = 3) -> dict[str, Any]:
        snap = super().snapshot()
        memory = float(snap.get("memory", {}).get("percent") or 0)
        cpu = float(snap.get("cpu_percent") or 0)
        free_disk = float(snap.get("disk", {}).get("free_gb") or 0)
        ac = bool(snap.get("power", {}).get("ac_connected", True))
        parallel = max(1, int(requested_parallel))
        reasons = []
        if memory >= 90:
            parallel = 1; reasons.append("RAM >= 90%：暫停新增大型本機並行工作")
        elif memory >= 80:
            parallel = min(parallel, 2); reasons.append("RAM >= 80%：降低並行度")
        if cpu >= 95:
            parallel = 1; reasons.append("CPU >= 95%：降低並行度")
        if not ac:
            parallel = min(parallel, 2); reasons.append("電池供電：限制高負載")
        return {"max_parallel_agents": parallel, "prefer_remote_model": memory >= 88 or free_disk < 15,
                "admit_large_local_model": memory < 80 and free_disk >= 25,
                "reasons": reasons or ["資源正常"]}

    def recommended_parallelism(self, requested: int) -> int:
        return int(self.resource_policy(requested)["max_parallel_agents"])

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["resource_policy"] = self.resource_policy(3)
        return snap

    def update_performance_boost(self, enabled: bool, threshold: int) -> bool:
        # High memory pressure should throttle, not raise process priority.  Priority
        # boost is used only when plugged in and below the configured pressure limit.
        snap = super().snapshot()
        should_boost = bool(enabled and snap["power"]["ac_connected"] and snap["memory"]["percent"] < threshold and snap.get("cpu_percent", 0) < 92)
        if should_boost == self._boost_active:
            return self._boost_active
        if os.name == "nt":
            priority = 0x00000080 if should_boost else 0x00000020
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), priority)
        self._boost_active = should_boost
        return self._boost_active
