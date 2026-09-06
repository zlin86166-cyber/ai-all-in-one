from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable

from .db import Database, utcnow


class Scheduler:
    def __init__(self, database: Database, dispatch: Callable[[dict[str, Any]], dict[str, Any] | None]):
        self.database=database; self.dispatch=dispatch; self._stop=threading.Event(); self._inflight={}
        self._thread=threading.Thread(target=self._loop, name="ai-hub-scheduler", daemon=True)
    def start(self):
        if not self._thread.is_alive(): self._thread.start()
    def stop(self):
        self._stop.set()
        if self._thread.is_alive(): self._thread.join(timeout=3)
    @staticmethod
    def _within_window(current: str, start: str, end: str) -> bool:
        return start <= current <= end if start <= end else current >= start or current <= end
    def _busy(self, schedule_id: str) -> bool:
        task_id=self._inflight.get(schedule_id)
        if not task_id: return False
        task=self.database.get_task(task_id)
        if task and task.get("status") in {"queued","running","cancelling"}: return True
        self._inflight.pop(schedule_id, None); return False
    def _loop(self):
        while not self._stop.wait(20):
            now=datetime.now(); current=now.strftime("%H:%M")
            for schedule in self.database.list_schedules():
                if not schedule.get("enabled") or now.weekday() not in schedule.get("weekdays", []): continue
                if not self._within_window(current, schedule["start_time"], schedule["end_time"]): continue
                if self._busy(schedule["id"]): continue
                last=schedule.get("last_run_at")
                if last:
                    try:
                        previous=datetime.fromisoformat(last).astimezone(); interval=max(5,int(schedule.get("interval_minutes") or 1440))
                        if now-previous < timedelta(minutes=interval): continue
                    except ValueError: pass
                try:
                    task=self.dispatch(schedule)
                except Exception as error:
                    self.database.audit("schedule.dispatch_failed", schedule["id"], {"error":str(error)}); continue
                self.database.update_schedule(schedule["id"], {"last_run_at":utcnow()})
                if task and task.get("id"): self._inflight[schedule["id"]]=task["id"]
