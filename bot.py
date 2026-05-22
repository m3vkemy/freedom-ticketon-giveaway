"""
Telegram-бот для розыгрыша на матче Кайрат vs Кайсар
Регистрация по сектору и месту, выбор 4 победителей, рассылка.
"""

import asyncio
import logging
import os

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ==================== НАСТРОЙКИ ====================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВСТАВЬТЕ_СЮДА_ТОКЕН_БОТА")
SHEETS_URL = os.environ.get("SHEETS_URL", "ВСТАВЬТЕ_СЮДА_ССЫЛКУ_APPS_SCRIPT")
ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "ВСТАВЬТЕ_СЮДА_СВОЙ_TELEGRAM_ID")

ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

# Текст рассылки победителям — без Markdown, чтобы избежать ошибок парсинга
WINNER_MESSAGE = (
    "🏆 Поздравляем! Вы стали победителем розыгрыша "
    "на матче Кайрат vs Кайсар!\n\n"
    "Скоро с вами свяжутся наши организаторы, чтобы вручить приз. "
    "Пожалуйста, оставайтесь на связи в Telegram.\n\n"
    "Спасибо за участие и до встречи! ⚽️"
)

# ===================================================

WAITING_FOR_SECTOR, WAITING_FOR_SEAT, WAITING_FOR_CONFIRMATION = range(3)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def send_to_sheets(payload: dict) -> dict:
    """Отправляем данные в Google Sheets через Apps Script."""
    try:
        response = requests.post(SHEETS_URL, json=payload, timeout=15)
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка отправки в Sheets: {e}")
        return {"status": "error", "message": str(e)}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ==================== РЕГИСТРАЦИЯ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /start — приветствие и запрос сектора."""
    # Очищаем старые данные (на случай повторного запуска регистрации)
    context.user_data.clear()

    # Проверяем статус регистрации
    status_result = send_to_sheets({"action": "get_status"})
    if status_result.get("current") == "closed":
        await update.message.reply_text(
            "🔒 *Регистрация на розыгрыш закрыта.*\n\n"
            "Спасибо всем участникам! Победителей объявим в скором времени.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "⚽️ *Добро пожаловать на розыгрыш!*\n\n"
        "Сегодня на матче *Кайрат vs Кайсар* мы разыгрываем призы "
        "среди тех, кто купил билет на матч.\n\n"
        "📍 Пожалуйста, отправьте *номер вашего сектора* (только цифры):",
        parse_mode="Markdown",
    )
    return WAITING_FOR_SECTOR


async def receive_sector(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем номер сектора (должен быть числом)."""
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text(
            "❌ Номер сектора должен быть числом. Попробуйте ещё раз:"
        )
        return WAITING_FOR_SECTOR

    context.user_data["sector"] = text

    await update.message.reply_text(
        "💺 Теперь отправьте *номер вашего места* (только цифры):",
        parse_mode="Markdown",
    )
    return WAITING_FOR_SEAT


async def receive_seat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем номер места (должен быть числом) и просим подтверждение."""
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text(
            "❌ Номер места должен быть числом. Попробуйте ещё раз:"
        )
        return WAITING_FOR_SEAT

    context.user_data["seat"] = text

    sector = context.user_data["sector"]
    seat = context.user_data["seat"]

    keyboard = [
        [
            InlineKeyboardButton("✅ Да, всё верно", callback_data="confirm_yes"),
            InlineKeyboardButton("✏️ Изменить", callback_data="confirm_no"),
        ]
    ]
    await update.message.reply_text(
        f"Проверьте данные:\n\n"
        f"📍 Сектор: *{sector}*\n"
        f"💺 Место: *{seat}*\n\n"
        f"Всё верно?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_FOR_CONFIRMATION


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатываем подтверждение от пользователя."""
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_no":
        await query.edit_message_text(
            "Хорошо, начнём заново. Отправьте *номер вашего сектора*:",
            parse_mode="Markdown",
        )
        return WAITING_FOR_SECTOR

    sector = context.user_data.get("sector")
    seat = context.user_data.get("seat")
    user = query.from_user

    result = send_to_sheets({
        "action": "register",
        "telegram_id": user.id,
        "username": f"@{user.username}" if user.username else "—",
        "name": user.full_name or "—",
        "sector": sector,
        "seat": seat,
    })

    if result.get("status") == "ok":
        await query.edit_message_text(
            "🎉 *Вы успешно зарегистрированы на розыгрыш!*\n\n"
            f"📍 Сектор: *{sector}*\n"
            f"💺 Место: *{seat}*\n\n"
            "Победителей объявим после матча. Удачи! ⚽️🏆",
            parse_mode="Markdown",
        )
    elif result.get("status") == "already_registered":
        await query.edit_message_text("👋 Вы уже зарегистрированы на розыгрыш! Удачи!")
    elif result.get("status") == "closed":
        await query.edit_message_text(
            "🔒 *Регистрация уже закрыта.* Спасибо за интерес!",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text(
            "⚠️ Произошла ошибка при регистрации. Попробуйте ещё раз через минуту "
            "или обратитесь к организаторам."
        )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Регистрация отменена. Чтобы начать заново — /start")
    return ConversationHandler.END


async def non_text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Фолбэк: пользователь прислал стикер/фото/голосовое во время регистрации."""
    state_msg = {
        WAITING_FOR_SECTOR: "📍 Пришлите, пожалуйста, *номер сектора* (только цифры).",
        WAITING_FOR_SEAT: "💺 Пришлите, пожалуйста, *номер места* (только цифры).",
    }
    # Определяем, в каком мы шаге, по тому, что уже сохранено
    if "sector" in context.user_data:
        msg = state_msg[WAITING_FOR_SEAT]
        next_state = WAITING_FOR_SEAT
    else:
        msg = state_msg[WAITING_FOR_SECTOR]
        next_state = WAITING_FOR_SECTOR
    await update.message.reply_text(msg, parse_mode="Markdown")
    return next_state


# ==================== АДМИН-КОМАНДЫ ====================

async def open_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /open — открыть регистрацию."""
    if not is_admin(update.effective_user.id):
        return
    result = send_to_sheets({"action": "set_status", "value": "open"})
    if result.get("status") == "ok":
        await update.message.reply_text(
            "✅ Регистрация *ОТКРЫТА*. Пользователи могут регистрироваться.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(f"Ошибка: {result.get('message', 'неизвестная')}")


async def close_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /close — закрыть регистрацию."""
    if not is_admin(update.effective_user.id):
        return
    result = send_to_sheets({"action": "set_status", "value": "closed"})
    if result.get("status") == "ok":
        await update.message.reply_text(
            "🔒 Регистрация *ЗАКРЫТА*. Новые участники не смогут зарегистрироваться.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(f"Ошибка: {result.get('message', 'неизвестная')}")


async def draw_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /draw — выбрать 4 случайных победителей.
    Если победители уже есть — переспрашивает у админа, что делать.
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только организаторам.")
        return

    # Проверяем, есть ли уже победители
    check = send_to_sheets({"action": "get_winners"})
    existing = check.get("winners", []) if check.get("status") == "ok" else []

    if existing:
        keyboard = [
            [
                InlineKeyboardButton("🔄 Переиграть (сбросить и выбрать заново)", callback_data="draw_redo"),
            ],
            [
                InlineKeyboardButton("❌ Отмена", callback_data="draw_cancel"),
            ],
        ]
        await update.message.reply_text(
            f"⚠️ Победители уже выбраны ({len(existing)} человек).\n\n"
            "Если запустите розыгрыш ещё раз, *прошлые победители будут сброшены* "
            "и выберутся новые 4 случайных участника.\n\n"
            "Что делать?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    await _perform_draw(update.effective_chat.id, context)


async def _perform_draw(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Внутренняя функция: делает сам розыгрыш и шлёт результат в указанный чат."""
    await context.bot.send_message(chat_id=chat_id, text="🎲 Выбираю победителей...")

    result = send_to_sheets({"action": "draw"})

    if result.get("status") == "empty":
        await context.bot.send_message(chat_id=chat_id, text="В таблице пока нет участников.")
        return

    if result.get("status") != "ok":
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Ошибка: {result.get('message', 'неизвестная')}",
        )
        return

    winners = result.get("winners", [])
    total = result.get("total", 0)

    text = f"🏆 *Победители розыгрыша* ({len(winners)} из {total} участников):\n\n"
    for i, w in enumerate(winners, 1):
        text += (
            f"{i}. {w['name']} ({w['username']})\n"
            f"   📍 Сектор: *{w['sector']}*, 💺 Место: *{w['seat']}*\n"
            f"   🆔 ID: `{w['telegram_id']}`\n\n"
        )
    text += "\nЧтобы отправить рассылку победителям, используйте /notify"

    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


async def draw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок переигровки/отмены при повторном /draw."""
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    if query.data == "draw_cancel":
        await query.edit_message_text("Розыгрыш отменён. Прошлые победители сохранены.")
        return

    if query.data == "draw_redo":
        # Сбрасываем старых победителей и проводим новый розыгрыш
        reset = send_to_sheets({"action": "reset_winners"})
        if reset.get("status") != "ok":
            await query.edit_message_text(f"Не удалось сбросить победителей: {reset.get('message', 'ошибка')}")
            return
        await query.edit_message_text("♻️ Прошлые победители сброшены. Выбираю новых...")
        await _perform_draw(query.from_user.id, context)


async def notify_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /notify — отправить рассылку всем победителям (с подтверждением)."""
    if not is_admin(update.effective_user.id):
        return

    keyboard = [
        [
            InlineKeyboardButton("✅ Отправить", callback_data="notify_confirm"),
            InlineKeyboardButton("❌ Отмена", callback_data="notify_cancel"),
        ]
    ]
    # Текст рассылки показываем БЕЗ Markdown, чтобы избежать ошибок отображения
    await update.message.reply_text(
        "📨 Сейчас будет отправлена такая рассылка победителям:\n\n"
        "————————————————————————\n"
        f"{WINNER_MESSAGE}\n"
        "————————————————————————\n\n"
        "Подтвердить отправку?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def notify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок подтверждения рассылки."""
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    if query.data == "notify_cancel":
        await query.edit_message_text("Рассылка отменена.")
        return

    result = send_to_sheets({"action": "get_winners"})
    if result.get("status") != "ok":
        await query.edit_message_text(f"Ошибка: {result.get('message', 'неизвестная')}")
        return

    winners = result.get("winners", [])
    if not winners:
        await query.edit_message_text("Победителей пока нет. Сначала запустите /draw")
        return

    await query.edit_message_text(f"📨 Отправляю рассылку {len(winners)} победителям...")

    sent = 0
    failed = 0
    failed_list = []

    for w in winners:
        try:
            # БЕЗ parse_mode — простой текст, никакие спецсимволы не сломают
            await context.bot.send_message(
                chat_id=int(w["telegram_id"]),
                text=WINNER_MESSAGE,
            )
            sent += 1
            await asyncio.sleep(0.1)
        except Forbidden:
            failed += 1
            failed_list.append(f"{w['name']} (заблокировал бота)")
        except BadRequest as e:
            failed += 1
            failed_list.append(f"{w['name']} (BadRequest: {e})")
        except TelegramError as e:
            failed += 1
            failed_list.append(f"{w['name']} ({e})")

    report = f"✅ Отправлено: {sent}\n"
    if failed:
        report += f"❌ Не доставлено: {failed}\n\n"
        report += "Не получили (свяжитесь вручную):\n" + "\n".join(f"• {x}" for x in failed_list)

    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=report,
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats — количество зарегистрированных и статус регистрации."""
    if not is_admin(update.effective_user.id):
        return

    result = send_to_sheets({"action": "stats"})
    if result.get("status") == "ok":
        count = result.get("count", 0)
        reg_status = result.get("registration_status", "open")
        status_label = "🟢 открыта" if reg_status == "open" else "🔴 закрыта"
        await update.message.reply_text(
            f"📊 Зарегистрировано: *{count}*\n"
            f"Регистрация: {status_label}",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("Ошибка при получении статистики.")


async def help_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin — список админских команд."""
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🛠 *Команды организатора:*\n\n"
        "/open — открыть регистрацию\n"
        "/close — закрыть регистрацию\n"
        "/stats — статистика участников\n"
        "/draw — выбрать 4 случайных победителей\n"
        "/notify — отправить рассылку победителям",
        parse_mode="Markdown",
    )


# ==================== ЗАПУСК ====================

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FOR_SECTOR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_sector),
                # Фолбэк на стикеры/фото/голосовые:
                MessageHandler(~filters.TEXT & ~filters.COMMAND, non_text_fallback),
            ],
            WAITING_FOR_SEAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_seat),
                MessageHandler(~filters.TEXT & ~filters.COMMAND, non_text_fallback),
            ],
            WAITING_FOR_CONFIRMATION: [CallbackQueryHandler(confirm, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        # КЛЮЧЕВОЙ ФИКС: разрешаем повторный /start в середине регистрации
        allow_reentry=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("open", open_registration))
    application.add_handler(CommandHandler("close", close_registration))
    application.add_handler(CommandHandler("draw", draw_winners))
    application.add_handler(CommandHandler("notify", notify_winners))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("admin", help_admin))
    application.add_handler(CallbackQueryHandler(notify_callback, pattern="^notify_"))
    application.add_handler(CallbackQueryHandler(draw_callback, pattern="^draw_"))

    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
