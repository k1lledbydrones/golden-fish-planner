from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from bot.db.models import GroupTask, GroupTaskAssignment, Task, User
from bot.utils.timezone import from_utc, to_utc


@dataclass
class FreeTimeService:

    def get_free_intervals(
        self, user_id: int, day: datetime
    ) -> list[tuple[datetime, datetime]]:
        user = User.get_by_id(user_id)
        local_day = day
        start_hour = user.day_start_hour
        end_hour = user.day_end_hour
        day_start_local = datetime.combine(local_day.date(), time(start_hour, 0))
        day_end_local = datetime.combine(local_day.date(), time(end_hour, 0))
        day_start_utc = to_utc(day_start_local, user.timezone)
        day_end_utc = to_utc(day_end_local, user.timezone)

        group_tasks = (
            GroupTask.select(GroupTask.task)
            .join(GroupTaskAssignment)
            .where(GroupTaskAssignment.user == user)
        )
        tasks = (
            Task.select()
            .where(
                ((Task.user == user) | (Task.id.in_(group_tasks)))
                & (Task.is_muted == False)
                & (Task.start_dt < day_end_utc)
            )
            .order_by(Task.start_dt)
        )

        busy: list[tuple[datetime, datetime]] = []
        for task in tasks:
            if task.task_type == "recurring":
                task_start, task_end = self._recurring_busy_interval(
                    task, user, day_start_utc, day_end_utc
                )
                if task_start and task_end and task_start < task_end:
                    busy.append((task_start, task_end))
                continue
            if task.task_type == "deadline":
                continue
            task_start = max(task.start_dt, day_start_utc)
            task_end = task.end_dt or task.start_dt + timedelta(minutes=1)
            task_end = min(task_end, day_end_utc)
            if task_start < task_end:
                busy.append((task_start, task_end))

        free_utc = self._invert_intervals(day_start_utc, day_end_utc, busy)
        return [
            (from_utc(start, user.timezone), from_utc(end, user.timezone))
            for start, end in free_utc
        ]

    def intersect_intervals(
        self,
        intervals: list[list[tuple[datetime, datetime]]],
    ) -> list[tuple[datetime, datetime]]:
        if not intervals:
            return []
        result = intervals[0]
        for current in intervals[1:]:
            result = self._intersect_two(result, current)
        return result

    def _invert_intervals(
        self,
        start: datetime,
        end: datetime,
        busy: list[tuple[datetime, datetime]],
    ) -> list[tuple[datetime, datetime]]:
        if not busy:
            return [(start, end)]
        busy_sorted = sorted(busy, key=lambda x: x[0])
        merged: list[tuple[datetime, datetime]] = []
        for item in busy_sorted:
            if not merged:
                merged.append(item)
                continue
            last_start, last_end = merged[-1]
            if item[0] <= last_end:
                merged[-1] = (last_start, max(last_end, item[1]))
            else:
                merged.append(item)
        free: list[tuple[datetime, datetime]] = []
        cursor = start
        for b_start, b_end in merged:
            if cursor < b_start:
                free.append((cursor, b_start))
            cursor = max(cursor, b_end)
        if cursor < end:
            free.append((cursor, end))
        return free

    def _intersect_two(
        self,
        a: list[tuple[datetime, datetime]],
        b: list[tuple[datetime, datetime]],
    ) -> list[tuple[datetime, datetime]]:
        result: list[tuple[datetime, datetime]] = []
        i = 0
        j = 0
        while i < len(a) and j < len(b):
            start = max(a[i][0], b[j][0])
            end = min(a[i][1], b[j][1])
            if start < end:
                result.append((start, end))
            if a[i][1] < b[j][1]:
                i += 1
            else:
                j += 1
        return result

    def _recurring_busy_interval(
        self,
        task: Task,
        user: User,
        day_start_utc: datetime,
        day_end_utc: datetime,
    ) -> tuple[datetime | None, datetime | None]:
        from bot.db.models import Recurrence

        recurrence = Recurrence.get_or_none(Recurrence.task == task)
        if recurrence is None:
            return None, None
        start_local = from_utc(task.start_dt, user.timezone)
        day_local = from_utc(day_start_utc, user.timezone).date()
        if day_local < start_local.date():
            return None, None
        if recurrence.rule == "daily":
            occurs = True
        elif recurrence.rule == "weekly":
            occurs = day_local.weekday() == start_local.weekday()
        elif recurrence.rule == "monthly":
            occurs = day_local.day == start_local.day
        elif recurrence.rule == "every_n_days" and recurrence.interval:
            delta = (day_local - start_local.date()).days
            occurs = delta % recurrence.interval == 0
        else:
            occurs = False
        if not occurs:
            return None, None
        occ_start_local = datetime.combine(
            day_local, start_local.time(), tzinfo=start_local.tzinfo
        )
        occ_start = to_utc(occ_start_local.replace(tzinfo=None), user.timezone)
        if task.end_dt:
            end_local = from_utc(task.end_dt, user.timezone)
            duration = end_local - start_local
            occ_end = occ_start + duration
        else:
            occ_end = occ_start + timedelta(minutes=1)
        occ_start = max(occ_start, day_start_utc)
        occ_end = min(occ_end, day_end_utc)
        return occ_start, occ_end
