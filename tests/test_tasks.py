from __future__ import annotations

from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

import pytest
from telebot.types import User as TgUser

from unittest.mock import patch

from bot.db.models import (
    Category,
    Group,
    GroupMember,
    GroupTask,
    GroupTaskAssignment,
    Recurrence,
    Reminder,
    Task,
    TaskWizardState,
    User,
)
from bot.services.tasks import TaskService
from bot.utils.timezone import attach_timezone, from_utc, to_utc


class TestParseTaskIds:
    def test_single_id(self, task_service: TaskService):
        assert task_service._parse_task_ids("5") == [5]

    def test_comma_separated(self, task_service: TaskService):
        assert task_service._parse_task_ids("1,2,3") == [1, 2, 3]

    def test_range(self, task_service: TaskService):
        assert task_service._parse_task_ids("1-5") == [1, 2, 3, 4, 5]

    def test_mixed(self, task_service: TaskService):
        assert task_service._parse_task_ids("1-3,5,7-9") == [1, 2, 3, 5, 7, 8, 9]

    def test_single_range_value(self, task_service: TaskService):
        assert task_service._parse_task_ids("5-5") == [5]

    def test_invalid_negative_start(self, task_service: TaskService):
        assert task_service._parse_task_ids("-1") is None

    def test_invalid_range_reversed(self, task_service: TaskService):
        assert task_service._parse_task_ids("5-3") is None

    def test_non_numeric(self, task_service: TaskService):
        assert task_service._parse_task_ids("abc") is None

    def test_empty_string(self, task_service: TaskService):
        assert task_service._parse_task_ids("") == []

    def test_whitespace_parts(self, task_service: TaskService):
        assert task_service._parse_task_ids("1, ,2") == [1, 2]

    def test_trailing_comma(self, task_service: TaskService):
        assert task_service._parse_task_ids("1,") == [1]


class TestIsValidDatetime:
    def test_valid(self, task_service: TaskService):
        assert task_service._is_valid_datetime("24.05.2026 18:30") is True

    def test_invalid_format(self, task_service: TaskService):
        assert task_service._is_valid_datetime("2026-05-24 18:30") is False

    def test_empty(self, task_service: TaskService):
        assert task_service._is_valid_datetime("") is False

    def test_gibberish(self, task_service: TaskService):
        assert task_service._is_valid_datetime("hello") is False


class TestParseTime:
    def test_valid(self, task_service: TaskService):
        assert task_service._parse_time("09:30") == time(9, 30)

    def test_midnight(self, task_service: TaskService):
        assert task_service._parse_time("00:00") == time(0, 0)

    def test_invalid_hour(self, task_service: TaskService):
        assert task_service._parse_time("25:00") is None

    def test_invalid_minute(self, task_service: TaskService):
        assert task_service._parse_time("12:60") is None

    def test_missing_minutes(self, task_service: TaskService):
        assert task_service._parse_time("12") is None


class TestParseOffsets:
    def test_comma_separated(self, task_service: TaskService):
        assert task_service._parse_offsets("15,30,60") == [15, 30, 60]

    def test_empty_string(self, task_service: TaskService):
        assert task_service._parse_offsets("") == []

    def test_skip_keyword(self, task_service: TaskService):
        assert task_service._parse_offsets("skip") == []

    def test_net_keyword(self, task_service: TaskService):
        assert task_service._parse_offsets("нет") == []

    def test_none_keyword(self, task_service: TaskService):
        assert task_service._parse_offsets("none") == []

    def test_dash(self, task_service: TaskService):
        assert task_service._parse_offsets("-") == []

    def test_single_value(self, task_service: TaskService):
        assert task_service._parse_offsets("10") == [10]

    def test_with_spaces(self, task_service: TaskService):
        assert task_service._parse_offsets(" 5 , 10 , 15 ") == [5, 10, 15]


class TestGenerateDays:
    def test_single_day(self, task_service: TaskService):
        d = datetime(2026, 5, 22)
        result = task_service._generate_days(d, d)
        assert len(result) == 1
        assert result[0] == d

    def test_multiple_days(self, task_service: TaskService):
        start = datetime(2026, 5, 22)
        end = datetime(2026, 5, 24)
        result = task_service._generate_days(start, end)
        assert len(result) == 3
        assert result[0].day == 22
        assert result[1].day == 23
        assert result[2].day == 24

    def test_start_after_end(self, task_service: TaskService):
        start = datetime(2026, 5, 24)
        end = datetime(2026, 5, 22)
        result = task_service._generate_days(start, end)
        assert result == []


class TestMaxMinutesFromIntervals:
    def test_empty(self, task_service: TaskService):
        assert task_service._max_minutes_from_intervals([]) == 0

    def test_single_interval(self, task_service: TaskService):
        intervals = [(datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 11, 0))]
        assert task_service._max_minutes_from_intervals(intervals) == 60

    def test_multiple_intervals(self, task_service: TaskService):
        intervals = [
            (datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 11, 0)),
            (datetime(2026, 5, 22, 14, 0), datetime(2026, 5, 22, 16, 30)),
        ]
        assert task_service._max_minutes_from_intervals(intervals) == 210


class TestRecurringOccurrenceOnDay:
    def test_no_recurrence_returns_none(self, task_service: TaskService, user: User):
        task = Task.create(
            user=user, task_type="recurring", start_dt=datetime(2026, 5, 1)
        )
        day_start = datetime(2026, 5, 22, 0, 0)
        day_end = datetime(2026, 5, 23, 0, 0)
        assert (
            task_service._recurring_occurrence_on_day(task, day_start, day_end, user)
            is None
        )

    def test_before_start_date_returns_none(
        self, task_service: TaskService, user: User
    ):
        task = Task.create(
            user=user, task_type="recurring", start_dt=datetime(2026, 5, 22)
        )
        Recurrence.create(task=task, rule="daily")
        day_start = datetime(2026, 5, 21, 0, 0)
        day_end = datetime(2026, 5, 22, 0, 0)
        assert (
            task_service._recurring_occurrence_on_day(task, day_start, day_end, user)
            is None
        )

    def test_daily_occurs(self, task_service: TaskService, user: User):
        start_dt = datetime(2026, 5, 1, 10, 0)
        task = Task.create(user=user, task_type="recurring", start_dt=start_dt)
        Recurrence.create(task=task, rule="daily")
        day_start = attach_timezone(datetime(2026, 5, 22, 0, 0), user.timezone)
        day_end = attach_timezone(datetime(2026, 5, 23, 0, 0), user.timezone)
        result = task_service._recurring_occurrence_on_day(
            task, day_start, day_end, user
        )
        assert result is not None
        occ_start, occ_end = result
        expected_hour = 10 + 3  # Moscow is UTC+3
        assert occ_start.hour == expected_hour
        assert occ_start.day == 22

    def test_weekly_occurs(self, task_service: TaskService, user: User):
        start_dt = datetime(2026, 5, 4, 14, 0)
        task = Task.create(user=user, task_type="recurring", start_dt=start_dt)
        Recurrence.create(task=task, rule="weekly")
        may_25 = attach_timezone(datetime(2026, 5, 25, 0, 0), user.timezone)
        may_26 = attach_timezone(datetime(2026, 5, 26, 0, 0), user.timezone)
        result = task_service._recurring_occurrence_on_day(task, may_25, may_26, user)
        occ_start, occ_end = result
        assert occ_start.weekday() == start_dt.weekday()

    def test_weekly_no_occurrence_wrong_day(
        self, task_service: TaskService, user: User
    ):
        start_dt = datetime(2026, 5, 4, 14, 0)
        task = Task.create(user=user, task_type="recurring", start_dt=start_dt)
        Recurrence.create(task=task, rule="weekly")
        may_26 = datetime(2026, 5, 26, 0, 0)
        may_27 = datetime(2026, 5, 27, 0, 0)
        result = task_service._recurring_occurrence_on_day(task, may_26, may_27, user)
        assert result is None

    def test_monthly_occurs(self, task_service: TaskService, user: User):
        start_dt = datetime(2026, 5, 15, 9, 0)
        task = Task.create(user=user, task_type="recurring", start_dt=start_dt)
        Recurrence.create(task=task, rule="monthly")
        june_15_start = attach_timezone(datetime(2026, 6, 15, 0, 0), user.timezone)
        june_16_start = attach_timezone(datetime(2026, 6, 16, 0, 0), user.timezone)
        result = task_service._recurring_occurrence_on_day(
            task, june_15_start, june_16_start, user
        )
        assert result is not None
        assert result[0].day == 15

    def test_monthly_no_occurrence_wrong_day(
        self, task_service: TaskService, user: User
    ):
        start_dt = datetime(2026, 5, 15, 9, 0)
        task = Task.create(user=user, task_type="recurring", start_dt=start_dt)
        Recurrence.create(task=task, rule="monthly")
        june_16_start = datetime(2026, 6, 16, 0, 0)
        june_17_start = datetime(2026, 6, 17, 0, 0)
        result = task_service._recurring_occurrence_on_day(
            task, june_16_start, june_17_start, user
        )
        assert result is None

    def test_every_n_days_occurs(self, task_service: TaskService, user: User):
        start_dt = datetime(2026, 5, 1, 10, 0)
        task = Task.create(user=user, task_type="recurring", start_dt=start_dt)
        Recurrence.create(task=task, rule="every_n_days", interval=3)
        may_22 = attach_timezone(datetime(2026, 5, 22, 0, 0), user.timezone)
        may_23 = attach_timezone(datetime(2026, 5, 23, 0, 0), user.timezone)
        result = task_service._recurring_occurrence_on_day(task, may_22, may_23, user)
        delta = (date(2026, 5, 22) - date(2026, 5, 1)).days
        assert delta % 3 == 0
        assert result is not None

    def test_every_n_days_no_occurrence(self, task_service: TaskService, user: User):
        start_dt = datetime(2026, 5, 1, 10, 0)
        task = Task.create(user=user, task_type="recurring", start_dt=start_dt)
        Recurrence.create(task=task, rule="every_n_days", interval=3)
        may_23 = datetime(2026, 5, 23, 0, 0)
        may_24 = datetime(2026, 5, 24, 0, 0)
        delta = (date(2026, 5, 23) - date(2026, 5, 1)).days
        assert delta % 3 != 0
        result = task_service._recurring_occurrence_on_day(task, may_23, may_24, user)
        assert result is None

    def test_with_end_dt(self, task_service: TaskService, user: User):
        start_dt = datetime(2026, 5, 1, 10, 0)
        end_dt = datetime(2026, 5, 1, 12, 0)
        task = Task.create(
            user=user, task_type="recurring", start_dt=start_dt, end_dt=end_dt
        )
        Recurrence.create(task=task, rule="daily")
        day_start = attach_timezone(datetime(2026, 5, 22, 0, 0), user.timezone)
        day_end = attach_timezone(datetime(2026, 5, 23, 0, 0), user.timezone)
        result = task_service._recurring_occurrence_on_day(
            task, day_start, day_end, user
        )
        assert result is not None
        _, occ_end = result
        assert occ_end == result[0] + timedelta(hours=2)

    def test_occ_after_day_end(self, task_service: TaskService, user: User):
        start_dt = datetime(2026, 5, 1, 23, 30)
        task = Task.create(user=user, task_type="recurring", start_dt=start_dt)
        Recurrence.create(task=task, rule="daily")
        day_start = attach_timezone(datetime(2026, 5, 22, 0, 0), user.timezone)
        day_end = attach_timezone(datetime(2026, 5, 22, 2, 0), user.timezone)
        result = task_service._recurring_occurrence_on_day(
            task, day_start, day_end, user
        )
        assert result is None


class TestFindOverlaps:
    def test_no_end_dt_returns_empty(self, task_service: TaskService, user: User):
        task = Task.create(
            user=user, task_type="one_time", start_dt=datetime(2026, 5, 22, 10, 0)
        )
        assert task_service._find_overlaps(user, task) == []

    def test_no_overlap(self, task_service: TaskService, user: User):
        task = Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2026, 5, 22, 10, 0),
            end_dt=datetime(2026, 5, 22, 11, 0),
        )
        Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2026, 5, 22, 12, 0),
            end_dt=datetime(2026, 5, 22, 13, 0),
        )
        assert task_service._find_overlaps(user, task) == []

    def test_finds_overlap(self, task_service: TaskService, user: User):
        task = Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2026, 5, 22, 10, 0),
            end_dt=datetime(2026, 5, 22, 12, 0),
        )
        overlapping = Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2026, 5, 22, 11, 0),
            end_dt=datetime(2026, 5, 22, 13, 0),
        )
        result = task_service._find_overlaps(user, task)
        assert overlapping.id in result

    def test_excludes_work_sessions(self, task_service: TaskService, user: User):
        task = Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2026, 5, 22, 10, 0),
            end_dt=datetime(2026, 5, 22, 12, 0),
        )
        Task.create(
            user=user,
            task_type="work_session",
            start_dt=datetime(2026, 5, 22, 11, 0),
            end_dt=datetime(2026, 5, 22, 12, 0),
        )
        assert task_service._find_overlaps(user, task) == []

    def test_excludes_self(self, task_service: TaskService, user: User):
        task = Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2026, 5, 22, 10, 0),
            end_dt=datetime(2026, 5, 22, 12, 0),
        )
        assert task_service._find_overlaps(user, task) == []

    def test_excludes_muted_tasks(self, task_service: TaskService, user: User):
        task = Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2026, 5, 22, 10, 0),
            end_dt=datetime(2026, 5, 22, 12, 0),
        )
        Task.create(
            user=user,
            task_type="one_time",
            is_muted=True,
            start_dt=datetime(2026, 5, 22, 11, 0),
            end_dt=datetime(2026, 5, 22, 13, 0),
        )
        assert task_service._find_overlaps(user, task) == []

    def test_excludes_tasks_without_end_dt(self, task_service: TaskService, user: User):
        task = Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2026, 5, 22, 10, 0),
            end_dt=datetime(2026, 5, 22, 12, 0),
        )
        Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2026, 5, 22, 11, 0),
        )
        assert task_service._find_overlaps(user, task) == []


class TestSelectUserTasks:
    def test_excludes_muted(self, task_service: TaskService, user: User):
        Task.create(user=user, task_type="one_time", start_dt=datetime(2026, 5, 1))
        Task.create(
            user=user,
            task_type="one_time",
            start_dt=datetime(2026, 5, 2),
            is_muted=True,
        )
        result = task_service._select_user_tasks(user)
        assert result.count() == 1

    def test_includes_group_tasks(
        self, task_service: TaskService, user: User, another_user: User
    ):
        group = Group.create(name="test", join_code="Join123")
        GroupMember.create(group=group, user=user)
        other_task = Task.create(
            user=another_user, task_type="one_time", start_dt=datetime(2026, 5, 1)
        )
        group_task = GroupTask.create(group=group, task=other_task)
        GroupTaskAssignment.create(group_task=group_task, user=user)
        result = task_service._select_user_tasks(user)
        assert other_task in result

    def test_own_tasks_included(self, task_service: TaskService, user: User):
        t = Task.create(user=user, task_type="one_time", start_dt=datetime(2026, 5, 1))
        result = task_service._select_user_tasks(user)
        assert t in result


class TestCreateTask:
    def test_empty_payload_returns_none(self, task_service: TaskService, user: User):
        task, conflicts, warning = task_service.create_task(user, {})
        assert task is None
        assert conflicts == []
        assert warning == ""

    def test_recurring_without_rule_returns_none(
        self, task_service: TaskService, user: User
    ):
        payload = {"task_type": "recurring", "start_dt": "22.05.2026 10:00"}
        task, _, _ = task_service.create_task(user, payload)
        assert task is None

    def test_deadline_without_work_hours_returns_none(
        self, task_service: TaskService, user: User
    ):
        payload = {"task_type": "deadline", "end_dt": "22.05.2026 18:00"}
        task, _, _ = task_service.create_task(user, payload)
        assert task is None

    def test_one_time_requires_start_dt(self, task_service: TaskService, user: User):
        payload = {"task_type": "one_time", "name": "test"}
        task, _, _ = task_service.create_task(user, payload)
        assert task is None

    def test_creates_one_time_task(self, task_service: TaskService, user: User):
        payload = {
            "task_type": "one_time",
            "name": "My Task",
            "start_dt": "22.05.2026 10:00",
        }
        with patch("bot.services.tasks.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.now.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.strptime = datetime.strptime
            task, conflicts, warning = task_service.create_task(user, payload)
        assert task is not None
        assert task.task_type == "one_time"
        assert task.name == "My Task"
        assert task.user.id == user.id
        assert conflicts == []
        assert warning == ""

    def test_creates_with_category(self, task_service: TaskService, user: User):
        payload = {
            "task_type": "one_time",
            "name": "Categorized",
            "start_dt": "22.05.2026 10:00",
            "category": "work",
        }
        with patch("bot.services.tasks.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.now.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.strptime = datetime.strptime
            task, _, _ = task_service.create_task(user, payload)
        assert task is not None
        assert task.category is not None
        assert task.category.name == "work"

    def test_creates_with_reminders(self, task_service: TaskService, user: User):
        payload = {
            "task_type": "one_time",
            "name": "Reminded",
            "start_dt": "22.05.2026 10:00",
            "reminders": [15, 30],
        }
        with patch("bot.services.tasks.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.now.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.strptime = datetime.strptime
            task, _, _ = task_service.create_task(user, payload)
        assert task is not None
        reminders = Reminder.select().where(Reminder.task == task)
        offsets = [r.offset_minutes for r in reminders]
        assert sorted(offsets) == [15, 30]

    def test_creates_recurrence(self, task_service: TaskService, user: User):
        payload = {
            "task_type": "recurring",
            "name": "Recur",
            "start_dt": "22.05.2026 10:00",
            "recurrence_rule": "daily",
            "recurrence_interval": None,
        }
        with patch("bot.services.tasks.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.now.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.strptime = datetime.strptime
            task, _, _ = task_service.create_task(user, payload)
        assert task is not None
        rec = Recurrence.get_or_none(Recurrence.task == task)
        assert rec is not None
        assert rec.rule == "daily"

    def test_deadline_auto_sets_start_dt(self, task_service: TaskService, user: User):
        payload = {
            "task_type": "deadline",
            "name": "Deadline",
            "end_dt": "25.05.2026 18:00",
            "expected_work_hours": 3,
        }
        with patch("bot.services.tasks.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 5, 22, 10, 0)
            task, _, _ = task_service.create_task(user, payload)
        assert task is not None
        assert task.task_type == "deadline"

    def test_deadline_past_due_rejected(self, task_service: TaskService, user: User):
        payload = {
            "task_type": "deadline",
            "name": "Past",
            "end_dt": "21.05.2026 18:00",
            "expected_work_hours": 3,
        }
        with patch("bot.services.tasks.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 5, 22, 10, 0)
            task, _, warning = task_service.create_task(user, payload)
        assert task is None
        assert "Дедлайн" in warning

    def test_deadline_impossible_workload_rejected(
        self, task_service: TaskService, user: User
    ):
        payload = {
            "task_type": "deadline",
            "name": "Huge",
            "end_dt": "25.05.2026 18:00",
            "expected_work_hours": 1000,
        }
        with patch("bot.services.tasks.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 5, 22, 10, 0)
            task, _, warning = task_service.create_task(user, payload)
        assert task is None
        assert "Нереалист" in warning

    def test_creates_group_task(self, task_service: TaskService, user: User):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user, is_admin=True)
        payload = {
            "task_type": "one_time",
            "name": "Group Task",
            "start_dt": "22.05.2026 10:00",
            "is_group": True,
            "group_id": group.id,
        }
        with patch("bot.services.tasks.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.now.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.strptime = datetime.strptime
            task, _, _ = task_service.create_task(user, payload)
        assert task is not None
        gt = GroupTask.get_or_none(GroupTask.task == task)
        assert gt is not None
        assert gt.group.id == group.id

    def test_cleans_up_wizard_state(self, task_service: TaskService, user: User):
        TaskWizardState.create(user=user, step="reminders", payload="{}")
        payload = {
            "task_type": "one_time",
            "name": "Cleanup",
            "start_dt": "22.05.2026 10:00",
        }
        with patch("bot.services.tasks.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.now.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.strptime = datetime.strptime
            task_service.create_task(user, payload)
        state = TaskWizardState.get_or_none(TaskWizardState.user == user)
        assert state is None

    def test_schedules_reminders(self, task_service: TaskService, user: User):
        payload = {
            "task_type": "one_time",
            "name": "Scheduled",
            "start_dt": "22.05.2026 10:00",
            "reminders": [15],
        }
        with patch.object(
            task_service.scheduler, "schedule_task_reminders"
        ) as mock_sched:
            with patch("bot.services.tasks.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 5, 21, 10, 0)
                mock_dt.now.return_value = datetime(2026, 5, 21, 10, 0)
                mock_dt.strptime = datetime.strptime
                task, _, _ = task_service.create_task(user, payload)
            mock_sched.assert_called_with(task.id, [15])

    def test_deadline_with_warning(self, task_service: TaskService, user: User):
        with patch.object(
            task_service.free_time, "get_free_intervals", return_value=[]
        ):
            payload = {
                "task_type": "deadline",
                "name": "Big Deadline",
                "end_dt": "22.05.2026 18:00",
                "expected_work_hours": 5,
            }
            with patch("bot.services.tasks.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 5, 22, 10, 0)
                task, _, warning = task_service.create_task(user, payload)
            assert warning != "" or task is None


class TestDeleteTask:
    def test_no_id_returns_help(self, task_service: TaskService, mock_message):
        mock_message.text = "/delete"
        result = task_service.delete_task(mock_message)
        assert "Нужен id" in result

    def test_invalid_format(self, task_service: TaskService, mock_message):
        mock_message.text = "/delete abc"
        result = task_service.delete_task(mock_message)
        assert "не найдена" in result

    def test_deletes_one_time_task(
        self, task_service: TaskService, user: User, mock_message
    ):
        task = Task.create(
            user=user, task_type="one_time", start_dt=datetime(2026, 5, 22)
        )
        mock_message.text = f"/delete {task.id}"
        result = task_service.delete_task(mock_message)
        assert "удалена" in result
        assert Task.get_or_none(Task.id == task.id) is None

    def test_mutes_recurring_task(
        self, task_service: TaskService, user: User, mock_message
    ):
        task = Task.create(
            user=user, task_type="recurring", start_dt=datetime(2026, 5, 22)
        )
        Recurrence.create(task=task, rule="daily")
        mock_message.text = f"/delete {task.id}"
        result = task_service.delete_task(mock_message)
        assert "заглушена" in result
        refreshed = Task.get_by_id(task.id)
        assert refreshed.is_muted is True

    def test_not_found(self, task_service: TaskService, mock_message):
        mock_message.text = "/delete 9999"
        result = task_service.delete_task(mock_message)
        assert "не найдена" in result

    def test_removes_reminders(
        self, task_service: TaskService, user: User, mock_message
    ):
        task = Task.create(
            user=user, task_type="one_time", start_dt=datetime(2026, 5, 22)
        )
        Reminder.create(task=task, offset_minutes=15)
        with patch.object(
            task_service.scheduler, "remove_task_reminders"
        ) as mock_remove:
            mock_message.text = f"/delete {task.id}"
            task_service.delete_task(mock_message)
            mock_remove.assert_called_with(task.id)

    def test_empty_ids(self, task_service: TaskService, mock_message):
        mock_message.text = "/delete "
        result = task_service.delete_task(mock_message)
        assert "Нужен id" in result or "Не указаны" in result

    def test_delete_by_name_single_match(
        self, task_service: TaskService, user: User, mock_message
    ):
        task = Task.create(
            user=user, task_type="one_time", name="Same", start_dt=datetime(2026, 5, 22)
        )
        mock_message.text = "/delete Same"
        result = task_service.delete_task(mock_message)
        assert "удалена" in result
        assert Task.get_or_none(Task.id == task.id) is None

    def test_delete_by_name_multiple_matches(
        self, task_service: TaskService, user: User, mock_message
    ):
        Task.create(
            user=user, task_type="one_time", name="Same", start_dt=datetime(2026, 5, 22)
        )
        Task.create(
            user=user, task_type="one_time", name="Same", start_dt=datetime(2026, 5, 23)
        )
        mock_message.text = "/delete Same"
        result = task_service.delete_task(mock_message)
        assert "несколько задач" in result
        assert "#" in result


class TestUnmuteTask:
    def test_unmutes_task(self, task_service: TaskService, user: User):
        task = Task.create(
            user=user,
            task_type="recurring",
            is_muted=True,
            start_dt=datetime(2026, 5, 22),
        )
        Reminder.create(task=task, offset_minutes=15)
        with patch.object(task_service.scheduler, "schedule_task_reminders"):
            result = task_service.unmute_task(task.id)
        assert "включен" in result or "активна" in result
        refreshed = Task.get_by_id(task.id)
        assert refreshed.is_muted is False

    def test_not_found(self, task_service: TaskService):
        result = task_service.unmute_task(9999)
        assert "не найдена" in result

    def test_already_active(self, task_service: TaskService, user: User):
        task = Task.create(
            user=user,
            task_type="one_time",
            is_muted=False,
            start_dt=datetime(2026, 5, 22),
        )
        result = task_service.unmute_task(task.id)
        assert "активна" in result


class TestStartTaskWizard:
    def test_creates_wizard_state(self, task_service: TaskService, mock_message):
        task_service.start_task_wizard(mock_message)
        state = TaskWizardState.get_or_none(TaskWizardState.user == User.get_by_id(1))
        assert state is not None
        assert state.step == "type"

    def test_returns_prompt(self, task_service: TaskService, mock_message):
        result = task_service.start_task_wizard(mock_message)
        assert "Создаем" in result
        assert "one_time" in result


class TestSetWizardType:
    def test_sets_type_and_advances(self, task_service: TaskService, tg_user: TgUser):
        task_service.start_task_wizard(MagicMock(from_user=tg_user, text=""))
        task_service.set_wizard_type(tg_user, "one_time")
        state = TaskWizardState.get_or_none(TaskWizardState.user == User.get_by_id(1))
        assert state is not None
        assert state.step == "name"

    def test_sets_type_in_payload(self, task_service: TaskService, tg_user: TgUser):
        task_service.start_task_wizard(MagicMock(from_user=tg_user, text=""))
        task_service.set_wizard_type(tg_user, "deadline")
        state = TaskWizardState.get_or_none(TaskWizardState.user == User.get_by_id(1))
        import json

        payload = json.loads(state.payload)
        assert payload["task_type"] == "deadline"


class TestSetWizardRecurrence:
    def test_sets_rule_and_advances(self, task_service: TaskService, tg_user: TgUser):
        task_service.start_task_wizard(MagicMock(from_user=tg_user, text=""))
        task_service.set_wizard_type(tg_user, "recurring")
        result = task_service.set_wizard_recurrence(tg_user, "daily")
        assert result == "start_dt"

    def test_every_n_days_goes_to_interval(
        self, task_service: TaskService, tg_user: TgUser
    ):
        task_service.start_task_wizard(MagicMock(from_user=tg_user, text=""))
        task_service.set_wizard_type(tg_user, "recurring")
        result = task_service.set_wizard_recurrence(tg_user, "every_n_days")
        assert result == "recurrence_interval"


class TestListTasksForDate:
    def test_no_tasks(self, task_service: TaskService, user: User):
        selected = date(2026, 5, 22)
        result = task_service.list_tasks_for_date(user, selected)
        assert "На этот день задач нет" in result

    def test_lists_one_time_task(self, task_service: TaskService, user: User):
        dt = datetime(2026, 5, 22, 10, 0)
        start_utc = to_utc(dt, user.timezone)
        Task.create(user=user, task_type="one_time", start_dt=start_utc, name="Test")
        result = task_service.list_tasks_for_date(user, date(2026, 5, 22))
        assert "Test" in result

    def test_lists_recurring_task(self, task_service: TaskService, user: User):
        start_dt = datetime(2026, 5, 1, 10, 0)
        start_utc = to_utc(start_dt, user.timezone)
        task = Task.create(
            user=user, task_type="recurring", start_dt=start_utc, name="Daily"
        )
        Recurrence.create(task=task, rule="daily")
        result = task_service.list_tasks_for_date(user, date(2026, 5, 22))
        assert "Daily" in result


class TestHandleWizardMessage:
    def test_no_state_returns_none(self, task_service: TaskService, mock_message):
        assert task_service.handle_wizard_message(mock_message) is None

    def test_step_type(self, task_service: TaskService, user: User, mock_message):
        TaskWizardState.create(user=user, step="type", payload='{"step":"type"}')
        result = task_service.handle_wizard_message(mock_message)
        assert result == "type"

    def test_step_name_valid(self, task_service: TaskService, user: User, mock_message):
        import json

        payload = {"step": "name", "task_type": "one_time"}
        TaskWizardState.create(user=user, step="name", payload=json.dumps(payload))
        mock_message.text = "My Task"
        result = task_service.handle_wizard_message(mock_message)
        assert result == "start_dt" or result == "name"

    def test_step_name_too_long(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "name", "task_type": "one_time"}
        TaskWizardState.create(user=user, step="name", payload=json.dumps(payload))
        mock_message.text = "A" * 101
        result = task_service.handle_wizard_message(mock_message)
        assert "100" in result

    def test_step_name_empty(self, task_service: TaskService, user: User, mock_message):
        import json

        payload = {"step": "name", "task_type": "one_time"}
        TaskWizardState.create(user=user, step="name", payload=json.dumps(payload))
        mock_message.text = ""
        result = task_service.handle_wizard_message(mock_message)
        assert "1 до 100" in result

    def test_step_expected_work_hours_valid(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "expected_work_hours", "task_type": "deadline"}
        TaskWizardState.create(
            user=user, step="expected_work_hours", payload=json.dumps(payload)
        )
        mock_message.text = "5"
        result = task_service.handle_wizard_message(mock_message)
        assert result == "end_dt"

    def test_step_expected_work_hours_invalid(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "expected_work_hours", "task_type": "deadline"}
        TaskWizardState.create(
            user=user, step="expected_work_hours", payload=json.dumps(payload)
        )
        mock_message.text = "abc"
        result = task_service.handle_wizard_message(mock_message)
        assert "Неверное" in result

    def test_step_recurrence_rule(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "recurrence_rule"}
        TaskWizardState.create(
            user=user, step="recurrence_rule", payload=json.dumps(payload)
        )
        result = task_service.handle_wizard_message(mock_message)
        assert result == "recurrence_rule"

    def test_step_recurrence_interval_valid(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "recurrence_interval"}
        TaskWizardState.create(
            user=user, step="recurrence_interval", payload=json.dumps(payload)
        )
        mock_message.text = "3"
        result = task_service.handle_wizard_message(mock_message)
        assert result == "start_dt"

    def test_step_recurrence_interval_invalid(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "recurrence_interval"}
        TaskWizardState.create(
            user=user, step="recurrence_interval", payload=json.dumps(payload)
        )
        mock_message.text = "-1"
        result = task_service.handle_wizard_message(mock_message)
        assert "Неверный" in result

    def test_step_start_dt_now(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "start_dt"}
        TaskWizardState.create(user=user, step="start_dt", payload=json.dumps(payload))
        mock_message.text = "сейчас"
        result = task_service.handle_wizard_message(mock_message)
        assert result == "end_time"

    def test_step_start_dt_valid(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        future_day = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
        payload = {"step": "start_dt"}
        TaskWizardState.create(user=user, step="start_dt", payload=json.dumps(payload))
        mock_message.text = f"{future_day} 18:30"
        result = task_service.handle_wizard_message(mock_message)
        assert result == "end_time"

    def test_step_start_dt_invalid(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "start_dt"}
        TaskWizardState.create(user=user, step="start_dt", payload=json.dumps(payload))
        mock_message.text = "bad"
        result = task_service.handle_wizard_message(mock_message)
        assert "Неверный" in result

    def test_step_start_time_valid(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        future_date = (datetime.now() + timedelta(days=1)).date().isoformat()
        payload = {"step": "start_time", "start_date": future_date}
        TaskWizardState.create(
            user=user, step="start_time", payload=json.dumps(payload)
        )
        mock_message.text = "09:30"
        result = task_service.handle_wizard_message(mock_message)
        assert result == "end_time"

    def test_step_start_time_no_date(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "start_time"}
        TaskWizardState.create(
            user=user, step="start_time", payload=json.dumps(payload)
        )
        mock_message.text = "09:30"
        result = task_service.handle_wizard_message(mock_message)
        assert "Неверная" in result

    def test_step_start_time_invalid(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "start_time", "start_date": "2026-05-24"}
        TaskWizardState.create(
            user=user, step="start_time", payload=json.dumps(payload)
        )
        mock_message.text = "25:00"
        result = task_service.handle_wizard_message(mock_message)
        assert "Неверный" in result

    def test_step_end_time_skip(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "end_time", "start_date": "2026-05-24"}
        TaskWizardState.create(user=user, step="end_time", payload=json.dumps(payload))
        mock_message.text = "skip"
        result = task_service.handle_wizard_message(mock_message)
        assert result == "category"

    def test_step_end_time_valid(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {
            "step": "end_time",
            "start_date": "2026-05-24",
            "start_dt": "24.05.2026 10:00",
        }
        TaskWizardState.create(user=user, step="end_time", payload=json.dumps(payload))
        mock_message.text = "12:00"
        result = task_service.handle_wizard_message(mock_message)
        assert result == "category"

    def test_step_end_time_before_start(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {
            "step": "end_time",
            "start_date": "2026-05-24",
            "start_dt": "24.05.2026 14:00",
        }
        TaskWizardState.create(user=user, step="end_time", payload=json.dumps(payload))
        mock_message.text = "10:00"
        result = task_service.handle_wizard_message(mock_message)
        assert "Конец должен быть позже" in result

    def test_step_end_time_deadline_past(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {
            "step": "end_time",
            "task_type": "deadline",
            "end_date": "2026-05-22",
        }
        TaskWizardState.create(user=user, step="end_time", payload=json.dumps(payload))
        with patch("bot.services.tasks.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 22, 12, 0)
            mock_dt.strptime = datetime.strptime
            mock_dt.combine = datetime.combine
            mock_dt.timedelta = timedelta
            mock_message.text = "10:00"
            result = task_service.handle_wizard_message(mock_message)
        assert "Дедлайн" in result

    def test_step_reminders_returns_success_with_notifications(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {
            "step": "reminders",
            "task_type": "one_time",
            "name": "Test",
            "start_dt": "25.05.2026 10:00",
        }
        TaskWizardState.create(user=user, step="reminders", payload=json.dumps(payload))
        mock_message.text = "15,30"
        with patch("bot.services.tasks.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.now.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.strptime = datetime.strptime
            result = task_service.handle_wizard_message(mock_message)
        assert "Задача создана" in result or result == "complete"

    def test_step_category(self, task_service: TaskService, user: User, mock_message):
        import json

        payload = {"step": "category"}
        TaskWizardState.create(user=user, step="category", payload=json.dumps(payload))
        result = task_service.handle_wizard_message(mock_message)
        assert result == "category"

    def test_step_awaiting_category_name_valid(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "awaiting_category_name"}
        TaskWizardState.create(
            user=user, step="awaiting_category_name", payload=json.dumps(payload)
        )
        mock_message.text = "NewCat"
        result = task_service.handle_wizard_message(mock_message)
        assert result == "reminders"

    def test_step_awaiting_category_name_too_long(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "awaiting_category_name"}
        TaskWizardState.create(
            user=user, step="awaiting_category_name", payload=json.dumps(payload)
        )
        mock_message.text = "A" * 51
        result = task_service.handle_wizard_message(mock_message)
        assert "50" in result

    def test_step_reminders_complete(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {
            "step": "reminders",
            "task_type": "one_time",
            "name": "Test",
            "start_dt": "25.05.2026 10:00",
        }
        TaskWizardState.create(user=user, step="reminders", payload=json.dumps(payload))
        mock_message.text = "skip"
        with patch("bot.services.tasks.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.now.return_value = datetime(2026, 5, 21, 10, 0)
            mock_dt.strptime = datetime.strptime
            result = task_service.handle_wizard_message(mock_message)
        assert result == "complete"

    def test_step_group_id_valid(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "group_id"}
        TaskWizardState.create(user=user, step="group_id", payload=json.dumps(payload))
        mock_message.text = "42"
        result = task_service.handle_wizard_message(mock_message)
        assert result == "start_dt"

    def test_step_group_id_invalid(
        self, task_service: TaskService, user: User, mock_message
    ):
        import json

        payload = {"step": "group_id"}
        TaskWizardState.create(user=user, step="group_id", payload=json.dumps(payload))
        mock_message.text = "abc"
        result = task_service.handle_wizard_message(mock_message)
        assert "Неверный" in result


class TestSetWizardDate:
    def test_start_dt_step(
        self, task_service: TaskService, tg_user: TgUser, user: User
    ):
        TaskWizardState.create(
            user=user, step="start_dt", payload='{"step":"start_dt"}'
        )
        next_step, response = task_service.set_wizard_date(tg_user, date(2026, 5, 25))
        assert next_step == "start_time"
        assert "Введите время" in response

    def test_end_dt_step(self, task_service: TaskService, tg_user: TgUser, user: User):
        TaskWizardState.create(user=user, step="end_dt", payload='{"step":"end_dt"}')
        next_step, response = task_service.set_wizard_date(tg_user, date(2026, 5, 25))
        assert next_step == "end_time"
        assert "дедлайна" in response

    def test_unknown_step(self, task_service: TaskService, tg_user: TgUser, user: User):
        TaskWizardState.create(user=user, step="unknown", payload='{"step":"unknown"}')
        next_step, response = task_service.set_wizard_date(tg_user, date(2026, 5, 25))
        assert next_step == ""
        assert response == ""

    def test_handles_datetime_input(
        self, task_service: TaskService, tg_user: TgUser, user: User
    ):
        TaskWizardState.create(
            user=user, step="start_dt", payload='{"step":"start_dt"}'
        )
        next_step, response = task_service.set_wizard_date(
            tg_user, datetime(2026, 5, 25, 14, 0)
        )
        assert next_step == "start_time"


class TestSetWizardCategory:
    def test_returns_true(self, task_service: TaskService, tg_user: TgUser, user: User):
        TaskWizardState.create(
            user=user, step="category", payload='{"step":"category"}'
        )
        result = task_service.set_wizard_category(tg_user, "work")
        assert result is True

    def test_no_state_returns_false(self, task_service: TaskService, tg_user: TgUser):
        result = task_service.set_wizard_category(tg_user, "work")
        assert result is False


class TestListTasksByCategory:
    def test_no_tasks(self, task_service: TaskService, mock_message):
        result = task_service.list_tasks_by_category(mock_message)
        assert "нет" in result

    def test_with_tasks(self, task_service: TaskService, user: User, mock_message):
        cat = Category.create(user=user, name="work")
        Task.create(
            user=user,
            category=cat,
            task_type="one_time",
            name="CatTask",
            start_dt=datetime(2026, 5, 22),
        )
        result = task_service.list_tasks_by_category(mock_message)
        assert "CatTask" in result


class TestListTasksByCategoryId:
    def test_category_not_found(self, task_service: TaskService, user: User):
        result = task_service.list_tasks_by_category_id(user, 999)
        assert "не найдена" in result

    def test_no_tasks_in_category(self, task_service: TaskService, user: User):
        cat = Category.create(user=user, name="empty")
        result = task_service.list_tasks_by_category_id(user, cat.id)
        assert "нет" in result

    def test_lists_tasks(self, task_service: TaskService, user: User):
        cat = Category.create(user=user, name="work")
        Task.create(
            user=user,
            category=cat,
            task_type="one_time",
            name="Task1",
            start_dt=datetime(2026, 5, 22),
        )
        result = task_service.list_tasks_by_category_id(user, cat.id)
        assert "Task1" in result


class TestListFreeTimeForDate:
    def test_no_free_time(self, task_service: TaskService, user: User):
        with patch.object(
            task_service.free_time, "get_free_intervals", return_value=[]
        ):
            result = task_service.list_free_time_for_date(user, date(2026, 5, 22))
            assert "Свободного времени нет" in result

    def test_with_intervals(self, task_service: TaskService, user: User):
        intervals = [(datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 12, 0))]
        with patch.object(
            task_service.free_time, "get_free_intervals", return_value=intervals
        ):
            result = task_service.list_free_time_for_date(user, date(2026, 5, 22))
            assert "10:00" in result


class TestCreateWorkSessions:
    def test_creates_session_tasks(self, task_service: TaskService, user: User):
        task = Task.create(
            user=user, task_type="deadline", start_dt=datetime(2026, 5, 22, 10, 0)
        )
        free = [
            (datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 11, 0)),
        ]
        task_service._create_work_sessions(user, task, free, 60)
        sessions = Task.select().where(Task.task_type == "work_session")
        assert sessions.count() == 1

    def test_consumes_partial_interval(self, task_service: TaskService, user: User):
        task = Task.create(
            user=user, task_type="deadline", start_dt=datetime(2026, 5, 22, 10, 0)
        )
        free = [
            (datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 12, 0)),
        ]
        task_service._create_work_sessions(user, task, free, 30)
        sessions = Task.select().where(Task.task_type == "work_session")
        assert sessions.count() == 1
        session = sessions.first()
        duration = (session.end_dt - session.start_dt).total_seconds() / 60
        assert duration == 30


class TestGroupIdStep:
    def test_empty_group_id(self, task_service: TaskService, user: User, mock_message):
        import json

        payload = {"step": "group_id"}
        TaskWizardState.create(user=user, step="group_id", payload=json.dumps(payload))
        mock_message.text = ""
        result = task_service.handle_wizard_message(mock_message)
        assert result == "start_dt"


class TestEnsureUserForCallback:
    def test_returns_user(self, task_service: TaskService, tg_user: TgUser):
        user = task_service.ensure_user_for_callback(tg_user)
        assert user.telegram_id == 12345
