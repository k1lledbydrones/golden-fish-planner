from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from bot.db.models import (
    Group,
    GroupMember,
    GroupTask,
    GroupTaskAssignment,
    Task,
    TaskWizardState,
    User,
)
from bot.services.free_time import FreeTimeService
from bot.services.groups import GroupService
from bot.services.tasks import TaskService
from bot.utils.timezone import to_utc


class TestCreateGroup:
    def test_creates_group(self, gs: GroupService, mock_message):
        mock_message.text = "/group_create My Group"
        result = gs.create_group(mock_message)
        assert "Код приглашения" in result
        assert Group.select().count() == 1

    def test_no_name(self, gs: GroupService, mock_message):
        mock_message.text = "/group_create"
        result = gs.create_group(mock_message)
        assert "Нужно имя" in result

    def test_creates_admin_membership(self, gs: GroupService, user: User, mock_message):
        mock_message.text = "/group_create My Group"
        gs.create_group(mock_message)
        gm = GroupMember.get()
        assert gm.user.id == user.id
        assert gm.is_admin is True


class TestJoinGroup:
    def test_joins_group(self, gs: GroupService, mock_message):
        group = Group.create(name="Existing", join_code="Join123")
        mock_message.text = f"/group_join {group.join_code}"
        result = gs.join_group(mock_message)
        assert "присоединились" in result
        assert GroupMember.select().count() == 1

    def test_no_id(self, gs: GroupService, mock_message):
        mock_message.text = "/group_join"
        result = gs.join_group(mock_message)
        assert "код" in result

    def test_non_existent_group(self, gs: GroupService, mock_message):
        mock_message.text = "/group_join MissingCode"
        result = gs.join_group(mock_message)
        assert "не найдена" in result


class TestAddGroupTask:
    def test_no_id(self, gs: GroupService, mock_message):
        mock_message.text = "/group_add_task"
        result = gs.add_group_task(mock_message)
        assert "Нужен код" in result

    def test_not_admin(
        self, gs: GroupService, user: User, another_user: User, mock_message
    ):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user, is_admin=False)
        mock_message.from_user = MagicMock(
            id=another_user.telegram_id, is_bot=False, first_name="Other"
        )
        mock_message.text = f"/group_add_task {group.id}"
        result = gs.add_group_task(mock_message)
        assert "Нет прав" in result

    def test_creates_wizard_state(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user, is_admin=True)
        mock_message.text = f"/group_add_task {group.id}"
        result = gs.add_group_task(mock_message)
        assert "Создаем" in result
        state = TaskWizardState.get_or_none(TaskWizardState.user == user)
        assert state is not None
        assert state.step == "type"


class TestGroupFreeTime:
    def test_no_args(self, gs: GroupService, mock_message):
        mock_message.text = "/group_free"
        result = gs.group_free_time(mock_message)
        assert "Нужны" in result

    def test_invalid_date(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user)
        mock_message.text = f"/group_free {group.id} not-a-date"
        result = gs.group_free_time(mock_message)
        assert "Неверный формат" in result

    def test_no_free_time(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user)
        gs.free_time.get_free_intervals.return_value = []
        mock_message.text = f"/group_free {group.id} 22.05.2026 18:30"
        result = gs.group_free_time(mock_message)
        assert "Свободного времени нет" in result

    def test_with_free_time(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user)
        intervals = [(datetime(2026, 5, 22, 10, 0), datetime(2026, 5, 22, 12, 0))]
        gs.free_time.get_free_intervals.return_value = intervals
        gs.free_time.intersect_intervals.side_effect = lambda iv: iv[0] if iv else []
        mock_message.text = f"/group_free {group.id} 22.05.2026 18:30"
        result = gs.group_free_time(mock_message)
        assert "10:00" in result

    def test_not_member(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        mock_message.text = f"/group_free {group.id} 22.05.2026 18:30"
        result = gs.group_free_time(mock_message)
        assert "не состоите" in result


class TestLeaveGroup:
    def test_leaves_group(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user)
        mock_message.text = f"/group_leave {group.join_code}"
        result = gs.leave_group(mock_message)
        assert "вышли" in result
        assert GroupMember.select().count() == 0

    def test_no_code(self, gs: GroupService, mock_message):
        mock_message.text = "/group_leave"
        result = gs.leave_group(mock_message)
        assert "Нужен" in result

    def test_not_in_group(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        mock_message.text = f"/group_leave {group.join_code}"
        result = gs.leave_group(mock_message)
        assert "не состоите" in result

    def test_removes_group_task_assignments(
        self, gs: GroupService, user: User, another_user: User, mock_message
    ):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user)
        GroupMember.create(group=group, user=another_user, is_admin=True)
        task = Task.create(
            user=another_user,
            task_type="one_time",
            start_dt=datetime(2026, 5, 25, 10, 0),
        )
        group_task = GroupTask.create(group=group, task=task)
        GroupTaskAssignment.create(group_task=group_task, user=user)
        assert GroupTaskAssignment.select().count() == 1
        mock_message.text = f"/group_leave {group.join_code}"
        gs.leave_group(mock_message)
        assert GroupTaskAssignment.select().count() == 0


class TestFetchGroupTasks:
    def test_adds_group_tasks(
        self, gs: GroupService, user: User, another_user: User, mock_message
    ):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user)
        GroupMember.create(group=group, user=another_user, is_admin=True)
        task = Task.create(
            user=another_user,
            task_type="one_time",
            start_dt=datetime(2026, 5, 25, 10, 0),
        )
        group_task = GroupTask.create(group=group, task=task)
        mock_message.text = f"/group_fetch {group.join_code}"
        result = gs.fetch_group_tasks(mock_message)
        assert "Добавлено" in result
        assert GroupTaskAssignment.select().count() == 1

    def test_not_member(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        mock_message.text = f"/group_fetch {group.join_code}"
        result = gs.fetch_group_tasks(mock_message)
        assert "не состоите" in result

    def test_no_tasks(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user)
        mock_message.text = f"/group_fetch {group.join_code}"
        result = gs.fetch_group_tasks(mock_message)
        assert "нет задач" in result

    def test_detects_collisions(
        self, gs: GroupService, user: User, another_user: User, mock_message
    ):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user)
        GroupMember.create(group=group, user=another_user, is_admin=True)
        start = to_utc(datetime(2026, 5, 25, 10, 0), user.timezone)
        end = to_utc(datetime(2026, 5, 25, 12, 0), user.timezone)
        existing_task = Task.create(
            user=user, task_type="one_time", start_dt=start, end_dt=end
        )
        group_task_obj = Task.create(
            user=another_user, task_type="one_time", start_dt=start, end_dt=end
        )
        group_task = GroupTask.create(group=group, task=group_task_obj)
        mock_message.text = f"/group_fetch {group.join_code}"
        result = gs.fetch_group_tasks(mock_message)
        assert "пересечения" in result


class TestPromoteAdmin:
    def test_promotes_user(
        self, gs: GroupService, user: User, another_user: User, mock_message
    ):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user, is_admin=True)
        GroupMember.create(group=group, user=another_user, is_admin=False)
        mock_message.text = (
            f"/group_promote {group.join_code} {another_user.telegram_id}"
        )
        result = gs.promote_admin(mock_message)
        assert "администратором" in result
        member = GroupMember.get(GroupMember.user == another_user)
        assert member.is_admin is True

    def test_not_admin(
        self, gs: GroupService, user: User, another_user: User, mock_message
    ):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user, is_admin=False)
        GroupMember.create(group=group, user=another_user)
        mock_message.text = (
            f"/group_promote {group.join_code} {another_user.telegram_id}"
        )
        result = gs.promote_admin(mock_message)
        assert "Нет прав" in result

    def test_invalid_telegram_id(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user, is_admin=True)
        mock_message.text = f"/group_promote {group.join_code} notanid"
        result = gs.promote_admin(mock_message)
        assert "Неверный" in result

    def test_user_not_in_group(
        self, gs: GroupService, user: User, another_user: User, mock_message
    ):
        group = Group.create(name="G", join_code="Join123")
        GroupMember.create(group=group, user=user, is_admin=True)
        mock_message.text = (
            f"/group_promote {group.join_code} {another_user.telegram_id}"
        )
        result = gs.promote_admin(mock_message)
        assert "не в группе" in result


class TestMuteNotifications:
    def test_mutes_notifications(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        member = GroupMember.create(group=group, user=user)
        assert member.mute_notifications is False
        mock_message.text = f"/group_mute {group.join_code}"
        result = gs.mute_group_notifications(mock_message)
        assert "выключены" in result
        member = GroupMember.get(GroupMember.user == user)
        assert member.mute_notifications is True

    def test_unmutes_notifications(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        member = GroupMember.create(group=group, user=user, mute_notifications=True)
        mock_message.text = f"/group_unmute {group.join_code}"
        result = gs.unmute_group_notifications(mock_message)
        assert "включены" in result
        member = GroupMember.get(GroupMember.user == user)
        assert member.mute_notifications is False

    def test_not_member(self, gs: GroupService, user: User, mock_message):
        group = Group.create(name="G", join_code="Join123")
        mock_message.text = f"/group_mute {group.join_code}"
        result = gs.mute_group_notifications(mock_message)
        assert "не состоите" in result


@pytest.fixture
def gs(user, task_service) -> GroupService:
    from unittest.mock import MagicMock

    mock_ft = MagicMock()
    mock_ft.get_free_intervals.return_value = []
    mock_ft.intersect_intervals.side_effect = lambda intervals: (
        intervals[0] if intervals else []
    )
    return GroupService(free_time=mock_ft, task_service=task_service)
