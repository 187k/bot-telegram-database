"""Телеграм-бот для учёта клиентов сотрудниками."""

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, TelegramObject, Update

from dotenv import load_dotenv

import db

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")


def parse_employee_ids(raw: str) -> set[int]:
    """EMPLOYEE_IDS из env: числа через запятую, пробел или перенос строки."""
    ids = set()
    for part in raw.replace(",", " ").split():
        if part.lstrip("-").isdigit():
            ids.add(int(part))
        else:
            logging.warning("EMPLOYEE_IDS: пропущено некорректное значение %r", part)
    return ids


EMPLOYEE_IDS = parse_employee_ids(os.getenv("EMPLOYEE_IDS", ""))

BTN_ADD = "➕ Добавить клиента"
BTN_STATS = "📊 Моя статистика"
BTN_ALL = "👥 Все клиенты"

keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_ADD)],
        [KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_ALL)],
    ],
    resize_keyboard=True,
)

dp = Dispatcher()


@dp.update.outer_middleware()
async def access_control(
    handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
    event: Update,
    data: dict[str, Any],
) -> Any:
    """Пропускает дальше только сотрудников из EMPLOYEE_IDS."""
    user = data.get("event_from_user")

    if user is not None and user.id in EMPLOYEE_IDS:
        return await handler(event, data)

    if user is not None:
        logging.warning(
            "Отказано в доступе: id=%s username=%s", user.id, user.username
        )

    if event.message is not None:
        await event.message.answer(
            "⛔ У вас нет доступа к этому боту.\n"
            f"Ваш Telegram ID: <code>{user.id if user else '-'}</code>\n"
            "Передайте его администратору, чтобы получить доступ."
        )
    return None


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        f"Здравствуйте, {message.from_user.full_name}!\n"
        f"Ваш ID сотрудника: <code>{message.from_user.id}</code>\n\n"
        "Чтобы добавить клиента, отправьте его @username.\n\n"
        "Команды:\n"
        "/stats — моя статистика\n"
        "/all — все клиенты\n"
        "/help — помощь",
        reply_markup=keyboard,
    )


@dp.message(Command("help"))
@dp.message(F.text == BTN_ADD)
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Отправьте @username клиента одним сообщением, например:\n"
        "<code>@ivan_petrov</code>\n\n"
        "Подойдёт и ссылка вида <code>t.me/ivan_petrov</code>.\n"
        "Если такой клиент уже есть в базе, бот сообщит, кто его добавил.",
        reply_markup=keyboard,
    )


@dp.message(Command("stats"))
@dp.message(F.text == BTN_STATS)
async def cmd_stats(message: Message) -> None:
    employee_id = message.from_user.id
    clients = db.get_my_clients(employee_id)

    text = [f"📊 <b>Ваша статистика</b>\nДобавлено клиентов: <b>{len(clients)}</b>"]
    if clients:
        text.append("\nПоследние клиенты:")
        for row in clients[:20]:
            text.append(f"• @{row['username']} — {row['added_at']}")
        if len(clients) > 20:
            text.append(f"…и ещё {len(clients) - 20}")

    text.append(render_team_stats(employee_id))
    await message.answer("\n".join(text), reply_markup=keyboard)


def render_team_stats(employee_id: int) -> str:
    """Общая статистика: сколько клиентов добавил каждый сотрудник."""
    rows = db.get_employee_stats()
    if not rows:
        return "\n🏆 <b>Общая статистика</b>\nПока никто не добавил клиентов."

    total = sum(row["clients"] for row in rows)
    lines = [
        f"\n🏆 <b>Общая статистика сотрудников</b>\nВсего клиентов: <b>{total}</b>"
    ]
    for place, row in enumerate(rows, start=1):
        name = row["employee_name"] or f"ID {row['employee_id']}"
        you = " (вы)" if row["employee_id"] == employee_id else ""
        lines.append(f"{place}. {name}{you} — <b>{row['clients']}</b>")

    if employee_id not in {row["employee_id"] for row in rows}:
        lines.append("Вы пока не добавили ни одного клиента.")

    return "\n".join(lines)


@dp.message(Command("all"))
@dp.message(F.text == BTN_ALL)
async def cmd_all(message: Message) -> None:
    total = db.count_all_clients()
    clients = db.get_all_clients(limit=50)

    if not clients:
        await message.answer("База пока пуста.", reply_markup=keyboard)
        return

    text = [f"👥 <b>Все клиенты</b>\nВсего в базе: <b>{total}</b>\n"]
    for row in clients:
        text.append(
            f"• @{row['username']} — сотрудник "
            f"<code>{row['employee_id']}</code> — {row['added_at']}"
        )
    if total > len(clients):
        text.append(f"\nПоказаны последние {len(clients)} из {total}.")

    await message.answer("\n".join(text), reply_markup=keyboard)


@dp.message(F.text)
async def add_client(message: Message) -> None:
    """Любое другое текстовое сообщение считаем @username клиента."""
    username = db.normalize_username(message.text)
    employee_id = message.from_user.id

    if username is None:
        await message.answer(
            "Не похоже на @username. Отправьте имя клиента в Telegram, например "
            "<code>@ivan_petrov</code>.\n"
            "В username допустимы латинские буквы, цифры и подчёркивание "
            "(5–32 символа).",
            reply_markup=keyboard,
        )
        return

    my_username = message.from_user.username or ""
    if username.lower() == my_username.lower():
        await message.answer(
            "Нельзя добавить себя в качестве клиента.", reply_markup=keyboard
        )
        return

    employee_name = (
        f"@{my_username}" if my_username else message.from_user.full_name
    )

    if db.add_client(username, employee_id, employee_name):
        await message.answer(
            f"✅ Клиент @{username} добавлен и закреплён за вами.\n"
            f"Всего ваших клиентов: <b>{db.count_clients(employee_id)}</b>",
            reply_markup=keyboard,
        )
    else:
        owner_id = db.get_client_owner(username)
        if owner_id == employee_id:
            who = "Вы уже добавляли этого клиента."
        else:
            who = f"Его добавил сотрудник <code>{owner_id}</code>."
        await message.answer(
            f"⚠️ Клиент @{username} уже есть в базе. {who}",
            reply_markup=keyboard,
        )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN (переменная окружения).")

    if not EMPLOYEE_IDS:
        raise SystemExit(
            "Не задан EMPLOYEE_IDS — список Telegram ID сотрудников "
            "(например: EMPLOYEE_IDS=111111111,222222222)."
        )

    logging.info("Доступ разрешён сотрудникам: %s", sorted(EMPLOYEE_IDS))

    db.init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
