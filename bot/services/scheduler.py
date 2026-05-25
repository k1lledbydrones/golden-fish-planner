from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
from telebot import TeleBot
from zoneinfo import ZoneInfo


@dataclass
class ReminderScheduler:
    bot: TeleBot
    scheduler: BackgroundScheduler

    def start(self) -> None:
        self.scheduler.start()
        self.reschedule_all_reminders()

    def shutdown(self) -> None:
        self.scheduler.shutdown()

    def schedule_task_reminders(self, task_id: int, offsets: Iterable[int]) -> None:
        from bot.db.models import Recurrence, Task

        task = Task.get_by_id(task_id)
        if task.is_muted:
            return
        base_start = task.start_dt
        if task.task_type == "recurring":
            recurrence = Recurrence.get_or_none(Recurrence.task == task)
            if recurrence:
                next_start = self._next_occurrence(
                    base_start, recurrence.rule, recurrence.interval
                )
                if next_start:
                    base_start = next_start
        for offset in offsets:
            reminder_time = base_start - timedelta(minutes=offset)
            if reminder_time <= datetime.utcnow():
                continue
            job_id = f"task:{task_id}:offset:{offset}"
            run_date = reminder_time.replace(tzinfo=ZoneInfo("UTC"))
            self.scheduler.add_job(
                self._send_reminder,
                "date",
                run_date=run_date,
                id=job_id,
                replace_existing=True,
                kwargs={"task_id": task_id, "offset": offset},
            )

    def remove_task_reminders(self, task_id: int) -> None:
        for job in self.scheduler.get_jobs():
            if job.id.startswith(f"task:{task_id}:"):
                try:
                    self.scheduler.remove_job(job.id)
                except JobLookupError:
                    continue

    def _send_reminder(self, task_id: int, offset: int) -> None:
        from bot.db.models import GroupMember, GroupTask, Recurrence, Task

        task = Task.get_by_id(task_id)
        if task.is_muted:
            return
        title = task.name or task.task_type
        message = f"Напоминание: {title} (#{task.id}) через {offset} мин"
        if task.is_group:
            group_task = GroupTask.get(GroupTask.task == task)
            members = GroupMember.select().where(
                (GroupMember.group == group_task.group)
                & (GroupMember.mute_notifications == False)
            )
            for member in members:
                self.bot.send_message(member.user.telegram_id, message)
            return
        self.bot.send_message(task.user.telegram_id, message)

        if task.task_type == "recurring":
            recurrence = Recurrence.get_or_none(Recurrence.task == task)
            if recurrence:
                next_occ = self._next_occurrence(
                    task.start_dt,
                    recurrence.rule,
                    recurrence.interval,
                    min_time=(datetime.utcnow() + timedelta(days=1)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ),
                )
                if next_occ:
                    reminder_time = next_occ - timedelta(minutes=offset)
                    if reminder_time > datetime.utcnow():
                        job_id = f"task:{task_id}:offset:{offset}"
                        run_date = reminder_time.replace(tzinfo=ZoneInfo("UTC"))
                        self.scheduler.add_job(
                            self._send_reminder,
                            "date",
                            run_date=run_date,
                            id=job_id,
                            replace_existing=True,
                            kwargs={"task_id": task_id, "offset": offset},
                        )

    def reschedule_all_reminders(self) -> None:
        from bot.db.models import Reminder

        for reminder in Reminder.select():
            self.schedule_task_reminders(reminder.task.id, [reminder.offset_minutes])

    def _next_occurrence(
        self,
        start_dt: datetime,
        rule: str,
        interval: int | None,
        min_time: datetime | None = None,
    ) -> datetime | None:
        now = min_time or datetime.utcnow()
        if start_dt >= now:
            return start_dt
        if rule == "daily":
            days = (now - start_dt).days + 1
            return start_dt + timedelta(days=days)
        if rule == "weekly":
            weeks = ((now - start_dt).days // 7) + 1
            return start_dt + timedelta(weeks=weeks)
        if rule == "monthly":
            current = start_dt
            while current < now:
                month = current.month + 1
                year = current.year
                if month > 12:
                    month = 1
                    year += 1
                try:
                    current = current.replace(year=year, month=month)
                except ValueError:
                    current = current.replace(year=year, month=month, day=1)
            return current
        if rule == "every_n_days" and interval:
            days = ((now - start_dt).days // interval + 1) * interval
            return start_dt + timedelta(days=days)
        return None
