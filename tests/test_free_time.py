from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from bot.db.models import (
    Group,
    GroupMember,
    GroupTask,
    GroupTaskAssignment,
    Recurrence,
    Task,
    User,
)
from bot.services.free_time import FreeTimeService
from bot.utils.timezone import from_utc, to_utc


class TestInvertIntervals:
    def test_empty_busy(self, ft: FreeTimeService):
        start = datetime(2026, 5, 22, 8, 0)
        end = datetime(2026, 5, 22, 18, 0)
        result = ft._invert_intervals(start, end, [])
        assert result == [(start, end)]

    def test_one_busy_interval(self, ft: FreeTimeService):
        start = datetime(2026, 5, 22, 8, 0)
        end = datetime(2026, 5, 22, 18, 0)
        busy = [(datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 12, 0))]
        result = ft._invert_intervals(start, end, busy)
        assert result == [
            (datetime(2026, 5, 22, 8, 0), datetime(2026, 5, 22, 10, 0)),
            (datetime(2026, 5, 22, 12, 0), datetime(2026, 5, 22, 18, 0)),
        ]

    def test_busy_at_start(self, ft: FreeTimeService):
        start = datetime(2026, 5, 22, 8, 0)
        end = datetime(2026, 5, 22, 18, 0)
        busy = [(datetime(2026, 5, 22, 8, 0), datetime(2026, 5, 22, 10, 0))]
        result = ft._invert_intervals(start, end, busy)
        assert result == [(datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 18, 0))]

    def test_busy_at_end(self, ft: FreeTimeService):
        start = datetime(2026, 5, 22, 8, 0)
        end = datetime(2026, 5, 22, 18, 0)
        busy = [(datetime(2026, 5, 22, 16, 0), datetime(2026, 5, 22, 18, 0))]
        result = ft._invert_intervals(start, end, busy)
        assert result == [(datetime(2026, 5, 22, 8, 0), datetime(2026, 5, 22, 16, 0))]

    def test_busy_covers_all(self, ft: FreeTimeService):
        start = datetime(2026, 5, 22, 8, 0)
        end = datetime(2026, 5, 22, 18, 0)
        busy = [(datetime(2026, 5, 22, 8, 0), datetime(2026, 5, 22, 18, 0))]
        result = ft._invert_intervals(start, end, busy)
        assert result == []

    def test_overlapping_busy_merged(self, ft: FreeTimeService):
        start = datetime(2026, 5, 22, 8, 0)
        end = datetime(2026, 5, 22, 18, 0)
        busy = [
            (datetime(2026, 5, 22, 9, 0), datetime(2026, 5, 22, 11, 0)),
            (datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 12, 0)),
        ]
        result = ft._invert_intervals(start, end, busy)
        assert result == [
            (datetime(2026, 5, 22, 8, 0), datetime(2026, 5, 22, 9, 0)),
            (datetime(2026, 5, 22, 12, 0), datetime(2026, 5, 22, 18, 0)),
        ]

    def test_adjacent_busy_intervals(self, ft: FreeTimeService):
        start = datetime(2026, 5, 22, 8, 0)
        end = datetime(2026, 5, 22, 18, 0)
        busy = [
            (datetime(2026, 5, 22, 9, 0), datetime(2026, 5, 22, 11, 0)),
            (datetime(2026, 5, 22, 11, 0), datetime(2026, 5, 22, 13, 0)),
        ]
        result = ft._invert_intervals(start, end, busy)
        assert len(result) == 2


class TestIntersectTwo:
    def test_no_intersection(self, ft: FreeTimeService):
        a = [(datetime(2026, 5, 22, 8, 0), datetime(2026, 5, 22, 10, 0))]
        b = [(datetime(2026, 5, 22, 11, 0), datetime(2026, 5, 22, 13, 0))]
        result = ft._intersect_two(a, b)
        assert result == []

    def test_full_overlap(self, ft: FreeTimeService):
        a = [(datetime(2026, 5, 22, 8, 0), datetime(2026, 5, 22, 12, 0))]
        b = [(datetime(2026, 5, 22, 9, 0), datetime(2026, 5, 22, 11, 0))]
        result = ft._intersect_two(a, b)
        assert result == [(datetime(2026, 5, 22, 9, 0), datetime(2026, 5, 22, 11, 0))]

    def test_partial_overlap(self, ft: FreeTimeService):
        a = [(datetime(2026, 5, 22, 8, 0), datetime(2026, 5, 22, 12, 0))]
        b = [(datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 14, 0))]
        result = ft._intersect_two(a, b)
        assert result == [(datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 12, 0))]

    def test_multiple_intervals(self, ft: FreeTimeService):
        a = [
            (datetime(2026, 5, 22, 8, 0), datetime(2026, 5, 22, 10, 0)),
            (datetime(2026, 5, 22, 11, 0), datetime(2026, 5, 22, 13, 0)),
        ]
        b = [
            (datetime(2026, 5, 22, 9, 0), datetime(2026, 5, 22, 12, 0)),
        ]
        result = ft._intersect_two(a, b)
        assert result == [
            (datetime(2026, 5, 22, 9, 0), datetime(2026, 5, 22, 10, 0)),
            (datetime(2026, 5, 22, 11, 0), datetime(2026, 5, 22, 12, 0)),
        ]


class TestIntersectIntervals:
    def test_empty(self, ft: FreeTimeService):
        assert ft.intersect_intervals([]) == []

    def test_single_list(self, ft: FreeTimeService):
        intervals = [[(datetime(2026, 5, 22, 8, 0), datetime(2026, 5, 22, 10, 0))]]
        result = ft.intersect_intervals(intervals)
        assert result == intervals[0]

    def test_two_lists(self, ft: FreeTimeService):
        a = [(datetime(2026, 5, 22, 8, 0), datetime(2026, 5, 22, 12, 0))]
        b = [(datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 14, 0))]
        result = ft.intersect_intervals([a, b])
        assert result == [(datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 12, 0))]

    def test_no_common(self, ft: FreeTimeService):
        a = [(datetime(2026, 5, 22, 8, 0), datetime(2026, 5, 22, 9, 0))]
        b = [(datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 11, 0))]
        result = ft.intersect_intervals([a, b])
        assert result == []


class TestRecurringBusyInterval:
    def test_no_recurrence(self, ft: FreeTimeService, user: User):
        task = Task.create(
            user=user, task_type="recurring", start_dt=datetime(2026, 5, 1, 10, 0)
        )
        day_start_utc = datetime(2026, 5, 22, 0, 0)
        day_end_utc = datetime(2026, 5, 23, 0, 0)
        result = ft._recurring_busy_interval(task, user, day_start_utc, day_end_utc)
        assert result == (None, None)

    def test_before_start_date(self, ft: FreeTimeService, user: User):
        task = Task.create(
            user=user, task_type="recurring", start_dt=datetime(2026, 5, 22, 10, 0)
        )
        Recurrence.create(task=task, rule="daily")
        day_start_utc = datetime(2026, 5, 21, 0, 0)
        day_end_utc = datetime(2026, 5, 22, 0, 0)
        result = ft._recurring_busy_interval(task, user, day_start_utc, day_end_utc)
        assert result == (None, None)

    def test_daily_occurs(self, ft: FreeTimeService, user: User):
        start_dt = datetime(2026, 5, 1, 10, 0)
        start_utc = to_utc(start_dt, user.timezone)
        task = Task.create(user=user, task_type="recurring", start_dt=start_utc)
        Recurrence.create(task=task, rule="daily")
        day_start_utc = to_utc(datetime(2026, 5, 22, 0, 0), user.timezone)
        day_end_utc = to_utc(datetime(2026, 5, 23, 0, 0), user.timezone)
        result = ft._recurring_busy_interval(task, user, day_start_utc, day_end_utc)
        assert result[0] is not None
        assert result[1] is not None
        assert result[0] <= result[1]

    def test_weekly_occurs(self, ft: FreeTimeService, user: User):
        start_dt = datetime(2026, 5, 4, 14, 0)
        start_utc = to_utc(start_dt, user.timezone)
        task = Task.create(user=user, task_type="recurring", start_dt=start_utc)
        Recurrence.create(task=task, rule="weekly")
        may_25_utc = to_utc(datetime(2026, 5, 25, 0, 0), user.timezone)
        may_26_utc = to_utc(datetime(2026, 5, 26, 0, 0), user.timezone)
        result = ft._recurring_busy_interval(task, user, may_25_utc, may_26_utc)
        assert result[0] is not None

    def test_every_n_days(self, ft: FreeTimeService, user: User):
        start_dt = datetime(2026, 5, 1, 10, 0)
        start_utc = to_utc(start_dt, user.timezone)
        task = Task.create(user=user, task_type="recurring", start_dt=start_utc)
        Recurrence.create(task=task, rule="every_n_days", interval=3)
        day_utc = to_utc(datetime(2026, 5, 22, 0, 0), user.timezone)
        next_day_utc = to_utc(datetime(2026, 5, 23, 0, 0), user.timezone)
        result = ft._recurring_busy_interval(task, user, day_utc, next_day_utc)
        assert (
            datetime(2026, 5, 22).toordinal() - datetime(2026, 5, 1).toordinal()
        ) % 3 == 0
        assert result[0] is not None

    def test_monthly_no_occurrence(self, ft: FreeTimeService, user: User):
        start_dt = datetime(2026, 5, 15, 9, 0)
        start_utc = to_utc(start_dt, user.timezone)
        task = Task.create(user=user, task_type="recurring", start_dt=start_utc)
        Recurrence.create(task=task, rule="monthly")
        june_16_utc = to_utc(datetime(2026, 6, 16, 0, 0), user.timezone)
        june_17_utc = to_utc(datetime(2026, 6, 17, 0, 0), user.timezone)
        result = ft._recurring_busy_interval(task, user, june_16_utc, june_17_utc)
        assert result == (None, None)


class TestGetFreeIntervals:
    def test_no_tasks(self, ft: FreeTimeService, user: User):
        day = datetime(2026, 5, 22)
        intervals = ft.get_free_intervals(user.id, day)
        assert len(intervals) == 1
        start_h, end_h = intervals[0][0].hour, intervals[0][1].hour
        assert start_h == user.day_start_hour
        assert end_h == user.day_end_hour

    def test_with_one_time_task(self, ft: FreeTimeService, user: User):
        start = to_utc(datetime(2026, 5, 22, 10, 0), user.timezone)
        end = to_utc(datetime(2026, 5, 22, 12, 0), user.timezone)
        Task.create(user=user, task_type="one_time", start_dt=start, end_dt=end)
        day = datetime(2026, 5, 22)
        intervals = ft.get_free_intervals(user.id, day)
        assert len(intervals) == 2

    def test_recurring_task_shows_busy(self, ft: FreeTimeService, user: User):
        start_dt = datetime(2026, 5, 1, 10, 0)
        start_utc = to_utc(start_dt, user.timezone)
        task = Task.create(user=user, task_type="recurring", start_dt=start_utc)
        Recurrence.create(task=task, rule="daily")
        day = datetime(2026, 5, 22)
        intervals = ft.get_free_intervals(user.id, day)
        all_day_free = (
            len(intervals) == 1 and intervals[0][1].hour - intervals[0][0].hour == 15
        )
        assert not all_day_free

    def test_deadline_skipped(self, ft: FreeTimeService, user: User):
        task = Task.create(
            user=user,
            task_type="deadline",
            start_dt=datetime(2026, 5, 22, 10, 0),
            end_dt=datetime(2026, 5, 22, 12, 0),
        )
        day = datetime(2026, 5, 22)
        intervals = ft.get_free_intervals(user.id, day)
        assert len(intervals) == 1

    def test_group_member_tasks_included(
        self, ft: FreeTimeService, user: User, another_user: User
    ):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user)
        task = Task.create(
            user=another_user,
            task_type="one_time",
            start_dt=to_utc(datetime(2026, 5, 22, 10, 0), user.timezone),
            end_dt=to_utc(datetime(2026, 5, 22, 12, 0), user.timezone),
        )
        group_task = GroupTask.create(group=group, task=task)
        GroupTaskAssignment.create(group_task=group_task, user=user)
        day = datetime(2026, 5, 22)
        intervals = ft.get_free_intervals(user.id, day)
        busy_hours = []
        for s, e in intervals:
            busy_hours.append((s.hour, e.hour))
        assert not any(s == 10 for s, e in busy_hours)


class TestRecurringBusyIntervalEdgeCases:
    def test_no_end_dt(self, ft: FreeTimeService, user: User):
        from bot.utils.timezone import to_utc

        start_local = datetime(2026, 5, 1, 10, 0)
        start_utc = to_utc(start_local, user.timezone)
        task = Task.create(user=user, task_type="recurring", start_dt=start_utc)
        Recurrence.create(task=task, rule="daily")
        day_start_utc = to_utc(datetime(2026, 5, 22, 0, 0), user.timezone)
        day_end_utc = to_utc(datetime(2026, 5, 23, 0, 0), user.timezone)
        result = ft._recurring_busy_interval(task, user, day_start_utc, day_end_utc)
        assert result[0] is not None
        assert result[1] is not None
        assert result[1] - result[0] == timedelta(minutes=1)

    def test_unknown_rule(self, ft: FreeTimeService, user: User):
        start_utc = to_utc(datetime(2026, 5, 1, 10, 0), user.timezone)
        task = Task.create(user=user, task_type="recurring", start_dt=start_utc)
        Recurrence.create(task=task, rule="unknown")
        day_start_utc = to_utc(datetime(2026, 5, 22, 0, 0), user.timezone)
        day_end_utc = to_utc(datetime(2026, 5, 23, 0, 0), user.timezone)
        result = ft._recurring_busy_interval(task, user, day_start_utc, day_end_utc)
        assert result == (None, None)


@pytest.fixture
def ft() -> FreeTimeService:
    return FreeTimeService()
