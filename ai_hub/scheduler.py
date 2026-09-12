from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable

from .db import Database, utcnow


class Scheduler:
    def __init__(self, database: Database, dispatch: Callable[[dict[str, Any]], dict[str, Any] | None]):
        self.database = database
        self.dispatch = dispatch
        self._stop = threading.Event()
        self._inflight: dict[str, str] = {}
        self._thread = threading.Thread(target=self._loop, name="ai-hub-scheduler", daemon=True)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)

    @staticmethod
    def _within_window(current: str, start: str, end: str) -> bool:
        return start <= current <= end if start <= end else current >= start or current <= end

    @staticmethod
    def _weekday_in_window(now: datetime, weekdays: set[int], start: str, end: str) -> bool:
        day = now.weekday()
        if start > end and now.strftime("%H:%M") <= end:
            day = (day - 1) % 7
        return day in weekdays

    @staticmethod
    def _elapsed_since(now: datetime, value: str) -> float | None:
        try:
            previous = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        timezone_info = now.tzinfo
        if timezone_info is None:
            timezone_info = datetime.now().astimezone().tzinfo
            now = now.replace(tzinfo=timezone_info)
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone_info)
        else:
            previous = previous.astimezone(timezone_info)
        return (now - previous).total_seconds()

    def _busy(self, schedule_id: str) -> bool:
        task_id = self._inflight.get(schedule_id)
        if not task_id:
            return False
        task = self.database.get_task(task_id)
        if task and task.get("status") in {"queued", "running", "cancelling"}:
            return True
        self._inflight.pop(schedule_id, None)
        return False

    def _loop(self) -> None:
        while not self._stop.wait(20):
            now = datetime.now().astimezone()
            current = now.strftime("%H:%M")
            for schedule in self.database.list_schedules():
                if not schedule.get("enabled"):
                    continue
                start = str(schedule.get("start_time") or "00:00")
                end = str(schedule.get("end_time") or start)
                try:
                    weekdays = {int(day) for day in schedule.get("weekdays", [])}
                except (TypeError, ValueError):
                    continue
                if not self._weekday_in_window(now, weekdays, start, end):
                    continue
                if not self._within_window(current, start, end):
                    continue
                if self._busy(str(schedule["id"])):
                    continue
                last = schedule.get("last_run_at")
                if last:
                    interval = max(5, int(schedule.get("interval_minutes") or 1440))
                    elapsed = self._elapsed_since(now, str(last))
                    if elapsed is not None and elapsed < interval * 60:
                        continue
                try:
                    task = self.dispatch(schedule)
                except Exception as error:
                    self.database.audit(
                        "schedule.dispatch_failed",
                        str(schedule["id"]),
                        {"error": str(error)},
                    )
                    continue
                self.database.update_schedule(schedule["id"], {"last_run_at": utcnow()})
                if task and task.get("id"):
                    self._inflight[str(schedule["id"])] = str(task["id"])
