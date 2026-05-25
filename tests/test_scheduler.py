from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from bot.db.models import Recurrence, Reminder, Task, User
from bot.services.scheduler import ReminderScheduler


class TestNextOccurrence:
    def test_start_dt_in_future(self, rs: ReminderScheduler):
        future = datetime(2099, 1, 1)
        result = rs._next_occurrence(future, "daily", None)
        assert result == future

    def test_daily(self, rs: ReminderScheduler):
        start = datetime(2026, 1, 1, 10, 0)
        now = datetime(2026, 5, 22, 10, 0)
        result = rs._next_occurrence(start, "daily", None, min_time=now)
        assert result is not None
        assert result > now
        assert result.hour == 10
        assert result.minute == 0

    def test_weekly(self, rs: ReminderScheduler):
        start = datetime(2026, 1, 5, 10, 0)
        now = datetime(2026, 5, 22, 10, 0)
        result = rs._next_occurrence(start, "weekly", None, min_time=now)
        assert result is not None
        assert result > now
        assert result.weekday() == start.weekday()

    def test_monthly(self, rs: ReminderScheduler):
        start = datetime(2026, 1, 15, 10, 0)
        now = datetime(2026, 5, 22, 10, 0)
        result = rs._next_occurrence(start, "monthly", None, min_time=now)
        assert result is not None
        assert result > now
        assert result.day == 15

    def test_every_n_days(self, rs: ReminderScheduler):
        start = datetime(2026, 1, 1, 10, 0)
        now = datetime(2026, 5, 22, 10, 0)
        result = rs._next_occurrence(start, "every_n_days", 3, min_time=now)
        assert result is not None
        assert result > now
        delta_days = (result - start).days
        assert delta_days % 3 == 0

    def test_unknown_rule(self, rs: ReminderScheduler):
        result = rs._next_occurrence(datetime(2026, 1, 1), "unknown", None)
        assert result is None

    def test_monthly_overflow(self, rs: ReminderScheduler):
        start = datetime(2025, 1, 31, 10, 0)
        now = datetime(2026, 2, 1, 10, 0)
        result = rs._next_occurrence(start, "monthly", None, min_time=now)
        assert result is not None
        assert result >= now
        assert result.hour == 10

    def test_no_interval_for_every_n_days(self, rs: ReminderScheduler):
        result = rs._next_occurrence(datetime(2026, 1, 1), "every_n_days", None)
        assert result is None


class TestScheduleTaskReminders:
    def test_muted_task_skipped(self, rs: ReminderScheduler, user: User):
        task = Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2030, 1, 1),
            is_muted=True,
        )
        offsets = [15]
        rs.schedule_task_reminders(task.id, offsets)
        rs.scheduler.add_job.assert_not_called()

    def test_schedules_offsets(self, rs: ReminderScheduler, user: User):
        task = Task.create(
            user=user, task_type="one_time", start_dt=datetime(2030, 1, 1, 10, 0)
        )
        offsets = [15, 60]
        rs.schedule_task_reminders(task.id, offsets)
        assert rs.scheduler.add_job.call_count == 2

    def test_past_reminder_skipped(self, rs: ReminderScheduler, user: User):
        task = Task.create(
            user=user, task_type="one_time", start_dt=datetime(2020, 1, 1, 10, 0)
        )
        offsets = [15]
        rs.schedule_task_reminders(task.id, offsets)
        rs.scheduler.add_job.assert_not_called()

    def test_recurring_uses_next_occurrence(self, rs: ReminderScheduler, user: User):
        start_dt = datetime(2026, 1, 1, 10, 0)
        task = Task.create(user=user, task_type="recurring", start_dt=start_dt)
        Recurrence.create(task=task, rule="daily")
        offsets = [15]
        rs.schedule_task_reminders(task.id, offsets)
        assert rs.scheduler.add_job.call_count == 1


class TestRemoveTaskReminders:
    def test_removes_matching_jobs(self, rs: ReminderScheduler):
        job1 = MagicMock()
        job1.id = "task:1:offset:15"
        job2 = MagicMock()
        job2.id = "task:2:offset:30"
        rs.scheduler.get_jobs.return_value = [job1, job2]
        rs.remove_task_reminders(1)
        rs.scheduler.remove_job.assert_called_once_with("task:1:offset:15")

    def test_no_matching_jobs(self, rs: ReminderScheduler):
        job = MagicMock()
        job.id = "task:3:offset:15"
        rs.scheduler.get_jobs.return_value = [job]
        rs.remove_task_reminders(1)
        rs.scheduler.remove_job.assert_not_called()


class TestRescheduleAllReminders:
    def test_reschedules_all(self, rs: ReminderScheduler, user: User):
        task = Task.create(
            user=user, task_type="one_time", start_dt=datetime(2030, 1, 1, 10, 0)
        )
        Reminder.create(task=task, offset_minutes=15)
        with patch.object(rs, "schedule_task_reminders") as mock_schedule:
            rs.reschedule_all_reminders()
            mock_schedule.assert_called_once_with(task.id, [15])


class TestSendReminder:
    def test_sends_to_user(self, rs: ReminderScheduler, user: User):
        task = Task.create(
            user=user, task_type="one_time", start_dt=datetime(2026, 1, 1), name="Test"
        )
        rs._send_reminder(task.id, 15)
        rs.bot.send_message.assert_called_once()

    def test_sends_to_group_members(
        self, rs: ReminderScheduler, user: User, another_user: User
    ):
        from bot.db.models import Group, GroupMember, GroupTask

        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user)
        GroupMember.create(group=group, user=another_user, mute_notifications=True)
        task = Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2026, 1, 1),
            is_group=True,
        )
        GroupTask.create(group=group, task=task)
        rs._send_reminder(task.id, 15)
        assert rs.bot.send_message.call_count == 1

    def test_muted_task_skips(self, rs: ReminderScheduler, user: User):
        task = Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2026, 1, 1),
            is_muted=True,
        )
        rs._send_reminder(task.id, 15)
        rs.bot.send_message.assert_not_called()

    def test_reschedules_recurring(self, rs: ReminderScheduler, user: User):
        start_dt = datetime(2026, 1, 1, 10, 0)
        task = Task.create(user=user, task_type="recurring", start_dt=start_dt)
        Recurrence.create(task=task, rule="daily")
        rs._send_reminder(task.id, 15)
        assert rs.scheduler.add_job.call_count >= 1


class TestStartAndShutdown:
    def test_start(self, rs: ReminderScheduler):
        with patch.object(rs, "reschedule_all_reminders") as mock_reschedule:
            rs.start()
            rs.scheduler.start.assert_called_once()
            mock_reschedule.assert_called_once()

    def test_shutdown(self, rs: ReminderScheduler):
        rs.shutdown()
        rs.scheduler.shutdown.assert_called_once()


@pytest.fixture
def mock_bot():
    return MagicMock()


@pytest.fixture
def mock_apscheduler():
    sched = MagicMock()
    sched.get_jobs.return_value = []
    return sched


@pytest.fixture
def rs(mock_bot, mock_apscheduler) -> ReminderScheduler:
    return ReminderScheduler(bot=mock_bot, scheduler=mock_apscheduler)
