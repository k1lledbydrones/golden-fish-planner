from __future__ import annotations

from telebot import TeleBot
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
)

from telegram_bot_calendar import DetailedTelegramCalendar, WMonthTelegramCalendar

import json

from bot.services.tasks import TaskService


def register_task_handlers(bot: TeleBot, task_service: TaskService) -> None:
    def normalize_calendar_markup(calendar_markup: object) -> InlineKeyboardMarkup:
        if isinstance(calendar_markup, InlineKeyboardMarkup):
            return calendar_markup
        if isinstance(calendar_markup, str):
            calendar_markup = json.loads(calendar_markup)
        if isinstance(calendar_markup, dict):
            rows = calendar_markup.get("inline_keyboard", [])
        elif isinstance(calendar_markup, list):
            rows = calendar_markup
        else:
            rows = []
        keyboard = InlineKeyboardMarkup()
        for row in rows:
            if isinstance(row, dict):
                row = [row]
            if not isinstance(row, list):
                continue
            buttons: list[InlineKeyboardButton] = []
            for item in row:
                if isinstance(item, list):
                    for nested in item:
                        if isinstance(nested, dict):
                            buttons.append(InlineKeyboardButton(**nested))
                elif isinstance(item, dict):
                    buttons.append(InlineKeyboardButton(**item))
            if buttons:
                keyboard.row(*buttons)
        return keyboard

    @bot.message_handler(commands=["add"])
    def handle_add(message: Message) -> None:
        response = task_service.start_task_wizard(message)
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("Разовая 🗓️", callback_data="task_type:one_time"),
            InlineKeyboardButton("Повтор 🔁", callback_data="task_type:recurring"),
            InlineKeyboardButton("Дедлайн ⏰", callback_data="task_type:deadline"),
        )
        bot.reply_to(message, response, reply_markup=keyboard)

    @bot.message_handler(commands=["list"])
    def handle_list(message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "Укажите режим: /list day или /list category")
            return
        mode = parts[1].strip().lower()
        if mode == "day":
            calendar, _ = WMonthTelegramCalendar(
                calendar_id="listday",
                locale="ru",
                additional_buttons=[
                    {"text": "Выбрать год", "callback_data": "calendar:list_day_year"}
                ],
            ).build()
            bot.reply_to(
                message,
                "📅 Выберите дату",
                reply_markup=normalize_calendar_markup(calendar),
            )
        elif mode == "category":
            from bot.db.models import Category

            user = task_service.ensure_user_for_callback(message.from_user)
            categories = Category.select().where(Category.user == user)
            keyboard = InlineKeyboardMarkup()
            row = []
            for cat in categories:
                row.append(
                    InlineKeyboardButton(
                        cat.name, callback_data=f"list_category:{cat.id}"
                    )
                )
            if row:
                keyboard.add(*row)
            keyboard.add(
                InlineKeyboardButton("❌ Отмена", callback_data="list_category:cancel")
            )
            bot.reply_to(message, "🏷️ Выберите категорию", reply_markup=keyboard)
            return
        else:
            bot.reply_to(message, "Не понимаю режим. Используйте day или category")

    @bot.message_handler(commands=["free"])
    def handle_free(message: Message) -> None:
        calendar, _ = WMonthTelegramCalendar(
            calendar_id="free",
            locale="ru",
            additional_buttons=[
                {"text": "Выбрать год", "callback_data": "calendar:free_year"}
            ],
        ).build()
        bot.reply_to(
            message,
            "📅 Выберите дату",
            reply_markup=normalize_calendar_markup(calendar),
        )

    @bot.message_handler(commands=["delete"])
    def handle_delete(message: Message) -> None:
        response = task_service.delete_task(message)
        bot.reply_to(message, response)

    @bot.message_handler(commands=["cancel"])
    def handle_cancel(message: Message) -> None:
        if task_service.cancel_wizard(message.from_user.id):
            bot.reply_to(message, "❌ Мастер создания задачи отменён.")
        else:
            bot.reply_to(message, "Нет активного мастера для отмены.")

    @bot.message_handler(commands=["unmute"])
    def handle_unmute(message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "Нужен id задачи: /unmute 123")
            return
        try:
            task_id = int(parts[1])
        except ValueError:
            bot.reply_to(message, "⚠️ Неверный id")
            return
        response = task_service.unmute_task(task_id)
        bot.reply_to(message, response)

    # Important: don't swallow commands. TeleBot stops at the first matching handler
    # unless it returns ContinueHandling, so this catch-all must ignore `/...` messages.
    @bot.message_handler(
        func=lambda m: not (getattr(m, "text", None) and m.text.startswith("/"))
    )
    def handle_wizard(message: Message) -> None:
        step = task_service.handle_wizard_message(message)
        if not step:
            return
        if (
            step.startswith("Неверн")
            or step.startswith("Конец должен")
            or step.startswith("⚠️")
        ):
            bot.reply_to(message, step)
            return
        if step.startswith("Задача создана, но есть пересечения"):
            bot.reply_to(message, step)
            return
        if step == "type":
            keyboard = InlineKeyboardMarkup()
            keyboard.add(
                InlineKeyboardButton("Разовая 🗓️", callback_data="task_type:one_time"),
                InlineKeyboardButton("Повтор 🔁", callback_data="task_type:recurring"),
                InlineKeyboardButton("Дедлайн ⏰", callback_data="task_type:deadline"),
            )
            bot.reply_to(message, "Выберите тип задачи", reply_markup=keyboard)
            return
        if step == "recurrence_rule":
            keyboard = InlineKeyboardMarkup()
            keyboard.add(
                InlineKeyboardButton("Каждый день", callback_data="recurrence:daily"),
                InlineKeyboardButton(
                    "Каждую неделю", callback_data="recurrence:weekly"
                ),
            )
            keyboard.add(
                InlineKeyboardButton(
                    "Каждый месяц", callback_data="recurrence:monthly"
                ),
                InlineKeyboardButton(
                    "Каждые N дней", callback_data="recurrence:every_n_days"
                ),
            )
            bot.reply_to(
                message, "🔁 Выберите правило повторения", reply_markup=keyboard
            )
            return
        if step == "name":
            bot.reply_to(message, "✏️ Введите название задачи")
        elif step == "end_dt":
            calendar, _ = WMonthTelegramCalendar(
                calendar_id="fast",
                locale="ru",
                additional_buttons=[
                    {"text": "Выбрать год", "callback_data": "calendar:year"}
                ],
            ).build()
            bot.reply_to(
                message,
                "⏰ Выберите дату дедлайна",
                reply_markup=normalize_calendar_markup(calendar),
            )
        elif step == "expected_work_hours":
            bot.reply_to(message, "⏱️ Сколько часов нужно на задачу?")
        elif step == "recurrence_rule":
            bot.reply_to(message, "Правило: daily | weekly | monthly | every_n_days")
        elif step == "recurrence_interval":
            bot.reply_to(message, "🔁 Интервал в днях (целое число)")
        elif step == "start_dt":
            calendar, _ = WMonthTelegramCalendar(
                calendar_id="fast",
                locale="ru",
                additional_buttons=[
                    {"text": "Выбрать год", "callback_data": "calendar:year"}
                ],
            ).build()
            bot.reply_to(
                message,
                "📅 Выберите дату",
                reply_markup=normalize_calendar_markup(calendar),
            )
        elif step == "start_time":
            bot.reply_to(message, "🕒 Введите время начала (ЧЧ:ММ)")
        elif step == "end_time":
            bot.reply_to(
                message, "🕓 Введите время окончания (ЧЧ:ММ) или `skip` / `нет`"
            )
        elif step == "category":
            from bot.db.models import Category

            user = task_service.ensure_user_for_callback(message.from_user)
            categories = Category.select().where(Category.user == user)
            keyboard = InlineKeyboardMarkup()
            row = []
            for cat in categories:
                row.append(
                    InlineKeyboardButton(
                        cat.name, callback_data=f"category:select:{cat.id}"
                    )
                )
            if row:
                keyboard.add(*row)
            keyboard.add(
                InlineKeyboardButton("➕ Новая категория", callback_data="category:new")
            )
            bot.reply_to(message, "🏷️ Выберите категорию", reply_markup=keyboard)
            return
        elif step == "awaiting_category_name":
            bot.reply_to(message, "➕ Введите название новой категории")
        elif step == "reminders":
            bot.reply_to(
                message,
                "🔔 Напоминания в минутах через запятую, например: 15,60,180. "
                "Напишите `нет` или `skip`, если напоминания не нужны",
            )
        elif step == "complete":
            bot.reply_to(message, "✅ Задача создана")
        elif step.startswith("Задача создана, но есть пересечения") or step.startswith(
            "Не хватило"
        ):
            bot.reply_to(message, step)

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("list_category:")
    )
    def handle_list_category_callback(call: CallbackQuery) -> None:
        action = call.data.split(":", 1)[1]
        if action == "cancel":
            bot.edit_message_text(
                "❌ Отменено", call.message.chat.id, call.message.message_id
            )
            return
        category_id = int(action)
        user = task_service.ensure_user_for_callback(call.from_user)
        response = task_service.list_tasks_by_category_id(user, category_id)
        bot.edit_message_text(response, call.message.chat.id, call.message.message_id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("category:"))
    def handle_category_callback(call: CallbackQuery) -> None:
        action = call.data.split(":", 1)[1]
        if action == "new":
            task_service.set_wizard_substep(call.from_user, "awaiting_category_name")
            bot.edit_message_text(
                "➕ Введите название новой категории",
                call.message.chat.id,
                call.message.message_id,
            )
            return
        if action.startswith("select:"):
            category_id = int(action.split(":", 1)[1])
            from bot.db.models import Category

            category = Category.get_or_none(Category.id == category_id)
            if category is None:
                bot.edit_message_text(
                    "Категория не найдена",
                    call.message.chat.id,
                    call.message.message_id,
                )
                return
            ok = task_service.set_wizard_category(call.from_user, category.name)
            if not ok:
                bot.edit_message_text(
                    "⚠️ Состояние мастера потеряно. Начните заново: /add",
                    call.message.chat.id,
                    call.message.message_id,
                )
                return
            bot.edit_message_text(
                f"🏷️ Категория: {category.name}. Теперь введите напоминания "
                "(минуты через запятую) или `skip`",
                call.message.chat.id,
                call.message.message_id,
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("task_type:"))
    def handle_task_type_callback(call: CallbackQuery) -> None:
        task_type = call.data.split(":", 1)[1]
        task_service.set_wizard_type(call.from_user, task_type)
        bot.edit_message_text(
            "✏️ Введите название задачи",
            call.message.chat.id,
            call.message.message_id,
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("recurrence:"))
    def handle_recurrence_callback(call: CallbackQuery) -> None:
        rule = call.data.split(":", 1)[1]
        next_step = task_service.set_wizard_recurrence(call.from_user, rule)
        if next_step == "recurrence_interval":
            bot.edit_message_text(
                "🔁 Интервал в днях (целое число)",
                call.message.chat.id,
                call.message.message_id,
            )
            return
        calendar, _ = WMonthTelegramCalendar(
            calendar_id="fast",
            locale="ru",
            additional_buttons=[
                {"text": "Выбрать год", "callback_data": "calendar:year"}
            ],
        ).build()
        bot.edit_message_text(
            "📅 Выберите дату",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=normalize_calendar_markup(calendar),
        )

    @bot.callback_query_handler(func=lambda call: call.data == "calendar:year")
    def handle_calendar_year_switch(call: CallbackQuery) -> None:
        calendar, _ = DetailedTelegramCalendar(calendar_id="full", locale="ru").build()
        bot.edit_message_text(
            "📅 Выберите дату",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=normalize_calendar_markup(calendar),
        )

    @bot.callback_query_handler(func=lambda call: call.data == "calendar:free_year")
    def handle_calendar_free_year_switch(call: CallbackQuery) -> None:
        calendar, _ = DetailedTelegramCalendar(
            calendar_id="freefull", locale="ru"
        ).build()
        bot.edit_message_text(
            "📅 Выберите дату",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=normalize_calendar_markup(calendar),
        )

    @bot.callback_query_handler(func=WMonthTelegramCalendar.func(calendar_id="fast"))
    def handle_calendar_fast_callback(call: CallbackQuery) -> None:
        result, key, _ = WMonthTelegramCalendar(
            calendar_id="fast", locale="ru"
        ).process(call.data)
        if not result and key:
            bot.edit_message_text(
                "📅 Выберите дату",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=normalize_calendar_markup(key),
            )
            return
        if result:
            next_step, response = task_service.set_wizard_date(call.from_user, result)
            if next_step == "error":
                bot.edit_message_text(
                    response,
                    call.message.chat.id,
                    call.message.message_id,
                )
                return
            if next_step == "start_time" or next_step == "end_time":
                bot.edit_message_text(
                    response,
                    call.message.chat.id,
                    call.message.message_id,
                )
                return
            bot.edit_message_text(
                response,
                call.message.chat.id,
                call.message.message_id,
            )

    @bot.callback_query_handler(func=DetailedTelegramCalendar.func(calendar_id="full"))
    def handle_calendar_full_callback(call: CallbackQuery) -> None:
        result, key, _ = DetailedTelegramCalendar(
            calendar_id="full", locale="ru"
        ).process(call.data)
        if not result and key:
            bot.edit_message_text(
                "📅 Выберите дату",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=normalize_calendar_markup(key),
            )
            return
        if result:
            next_step, response = task_service.set_wizard_date(call.from_user, result)
            if next_step == "error":
                bot.edit_message_text(
                    response,
                    call.message.chat.id,
                    call.message.message_id,
                )
                return
            if next_step == "start_time" or next_step == "end_time":
                bot.edit_message_text(
                    response,
                    call.message.chat.id,
                    call.message.message_id,
                )
                return
            bot.edit_message_text(
                response,
                call.message.chat.id,
                call.message.message_id,
            )

    @bot.callback_query_handler(func=WMonthTelegramCalendar.func(calendar_id="listday"))
    def handle_list_day_calendar_callback(call: CallbackQuery) -> None:
        result, key, _ = WMonthTelegramCalendar(
            calendar_id="listday", locale="ru"
        ).process(call.data)
        if not result and key:
            bot.edit_message_text(
                "Выберите дату",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=normalize_calendar_markup(key),
            )
            return
        if result:
            user = task_service.ensure_user_for_callback(call.from_user)
            response = task_service.list_tasks_for_date(user, result)
            bot.edit_message_text(
                response,
                call.message.chat.id,
                call.message.message_id,
            )

    @bot.callback_query_handler(func=lambda call: call.data == "calendar:list_day_year")
    def handle_list_day_year_switch(call: CallbackQuery) -> None:
        calendar, _ = DetailedTelegramCalendar(
            calendar_id="listdayfull", locale="ru"
        ).build()
        bot.edit_message_text(
            "📅 Выберите дату",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=normalize_calendar_markup(calendar),
        )

    @bot.callback_query_handler(
        func=DetailedTelegramCalendar.func(calendar_id="listdayfull")
    )
    def handle_list_day_full_callback(call: CallbackQuery) -> None:
        result, key, _ = DetailedTelegramCalendar(
            calendar_id="listdayfull", locale="ru"
        ).process(call.data)
        if not result and key:
            bot.edit_message_text(
                "📅 Выберите дату",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=normalize_calendar_markup(key),
            )
            return
        if result:
            user = task_service.ensure_user_for_callback(call.from_user)
            response = task_service.list_tasks_for_date(user, result)
            bot.edit_message_text(
                response,
                call.message.chat.id,
                call.message.message_id,
            )

    @bot.callback_query_handler(func=WMonthTelegramCalendar.func(calendar_id="free"))
    def handle_calendar_free_callback(call: CallbackQuery) -> None:
        result, key, _ = WMonthTelegramCalendar(
            calendar_id="free", locale="ru"
        ).process(call.data)
        if not result and key:
            bot.edit_message_text(
                "📅 Выберите дату",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=normalize_calendar_markup(key),
            )
            return
        if result:
            user = task_service.ensure_user_for_callback(call.from_user)
            response = task_service.list_free_time_for_date(user, result)
            bot.edit_message_text(
                response,
                call.message.chat.id,
                call.message.message_id,
            )

    @bot.callback_query_handler(
        func=DetailedTelegramCalendar.func(calendar_id="freefull")
    )
    def handle_calendar_free_full_callback(call: CallbackQuery) -> None:
        result, key, _ = DetailedTelegramCalendar(
            calendar_id="freefull", locale="ru"
        ).process(call.data)
        if not result and key:
            bot.edit_message_text(
                "📅 Выберите дату",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=normalize_calendar_markup(key),
            )
            return
        if result:
            user = task_service.ensure_user_for_callback(call.from_user)
            response = task_service.list_free_time_for_date(user, result)
            bot.edit_message_text(
                response,
                call.message.chat.id,
                call.message.message_id,
            )
