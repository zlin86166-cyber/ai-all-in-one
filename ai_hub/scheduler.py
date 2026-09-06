from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable

from .db import Database, utcnow


class Scheduler:
    def __init__(self, database: Database, dispatch: Callable[[dict[str, Any]], None]):
        self.database = database
        self.dispatch = dispatch
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="ai-hub-scheduler", daemon=True)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)

    def _loop(self) -> None:
        while not self._stop.wait(20):
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            for schedule in self.database.list_schedules():
                if not schedule.get("enabled"):
                    continue
                if now.weekday() not in schedule.get("weekdays", []):
                    continue
                if not (schedule["start_time"] <= current_time <= schedule["end_time"]):
                    continue
                last = schedule.get("last_run_at")
                if last:
                    try:
                        previous = datetime.fromisoformat(last).astimezone()
                        interval = max(5, int(schedule.get("interval_minutes") or 1440))
                        if now - previous < timedelta(minutes=interval):
                            continue
                    except ValueError:
                        pass
                self.database.update_schedule(schedule["id"], {"last_run_at": utcnow()})
                try:
                    self.dispatch(schedule)
                except Exception as error:
                    self.database.audit(
                        "schedule.dispatch_failed", schedule["id"], {"error": str(error)}
                    )
