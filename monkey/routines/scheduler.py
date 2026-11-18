"""Windows Task Scheduler entry for the morning brief: generated for preview, registered only when the user clicks
Enable (never automatically). Times are local wall-clock, so DST is handled by Windows.

The task runs `Monkey.exe --routine morning`, which only builds and caches today's brief (no speech, no
notifications, no network writes). WakeToRun + StartWhenAvailable make a missed run catch up once; the routine
itself refuses to build a second brief for the same day or a "morning" brief after the first class started.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from .morning import DAYS, SCHOOL_DAYS, Schedule, brief_time

TASK_NAME = r"Monkey\Morning brief"
DAY_TAG = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday"}


def task_xml(exe: str, schedule: Schedule, lead_min: int = 90, today: date | None = None) -> str:
    if not schedule.verified:
        raise ValueError("Confirm your class schedule first.")
    today = today or date.today()
    triggers = []
    for i in range(7):
        d = today + timedelta(days=i)
        key = DAYS[d.weekday()]
        if key not in SCHOOL_DAYS or key not in schedule.by_day:
            continue
        bt = brief_time(d, schedule, lead_min)
        if bt is None:
            continue
        triggers.append(f"""    <CalendarTrigger>
      <StartBoundary>{d.isoformat()}T{bt:%H:%M}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek><DaysOfWeek><{DAY_TAG[key]} /></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek>
    </CalendarTrigger>""")
    if not triggers:
        raise ValueError("No weekday classes in the confirmed schedule.")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Monkey: prepare today's morning brief (no notifications)</Description></RegistrationInfo>
  <Triggers>
{chr(10).join(triggers)}
  </Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(exe)}</Command><Arguments>--routine morning</Arguments></Exec></Actions>
</Task>
"""


def register(xml: str) -> None:
    """Create/replace the task (Windows only). Called only from the explicit Enable button."""
    if sys.platform != "win32":
        raise RuntimeError("Task Scheduler is Windows-only.")
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as fh:
        fh.write(xml)
        path = fh.name
    try:
        r = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", path, "/F"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip()[:200])
    finally:
        Path(path).unlink(missing_ok=True)


def unregister() -> None:
    if sys.platform == "win32":
        subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True)
