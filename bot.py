"""
Telegram-бот для розыгрыша на матче Кайрат vs Кайсар
Простая версия: данные отправляются в Google Sheets через Apps Script (без Google Cloud!)
"""

import logging
import os

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
# Заполните эти три значения перед запуском:

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВСТАВЬТЕ_СЮДА_ТОКЕН_БОТА")
SHEETS_URL = os.environ.get("SHEETS_URL", "ВСТАВЬТЕ_СЮДА_ССЫЛКУ_APPS_SCRIPT")
ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "ВСТАВЬТЕ_СЮДА_СВОЙ_TELEGRAM_ID")

ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

# ===================================================

WAITING_FOR_TICKET, WAITING_FOR_CONFIRMATION = range(2)

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


# ==================== РЕГИСТРАЦИЯ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /start — приветствуем и просим номер билета."""
    await update.message.reply_text(
        "⚽️ *Добро пожаловать на розыгрыш!*\n\n"
        "Сегодня на матче *Кайрат vs Кайсар* мы разыгрываем призы "
        "среди тех, кто купил билет через *Freedom SuperApp*.\n\n"
        "📩 Пожалуйста, отправьте *номер вашего билета*:",
        parse_mode="Markdown",
    )
    return WAITING_FOR_TICKET


async def receive_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем номер билета и просим подтверждение."""
    ticket_number = update.message.text.strip()

    if not ticket_number or len(ticket_number) > 50:
        await update.message.reply_text(
            "❌ Похоже, номер билета указан некорректно. Попробуйте ещё раз:"
        )
        return WAITING_FOR_TICKET

    context.user_data["ticket_number"] = ticket_number

    keyboard = [
        [
            InlineKeyboardButton("✅ Да, всё верно", callback_data="confirm_yes"),
            InlineKeyboardButton("✏️ Изменить", callback_data="confirm_no"),
        ]
    ]
    await update.message.reply_text(
        f"Вы указали номер билета: *{ticket_number}*\n\nВсё верно?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_FOR_CONFIRMATION


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатываем подтверждение от пользователя."""
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_no":
        await query.edit_message_text("Хорошо, отправьте номер билета ещё раз:")
        return WAITING_FOR_TICKET

    ticket_number = context.user_data.get("ticket_number")
    user = query.from_user

    result = send_to_sheets({
        "action": "register",
        "telegram_id": user.id,
        "username": f"@{user.username}" if user.username else "—",
        "name": user.full_name or "—",
        "ticket_number": ticket_number,
    })

    if result.get("status") == "ok":
        await query.edit_message_text(
            "🎉 *Вы успешно зарегистрированы на розыгрыш!*\n\n"
            f"Номер билета: *{ticket_number}*\n\n"
            "Победителей объявим после матча. Удачи! ⚽️🏆",
            parse_mode="Markdown",
        )
    elif result.get("status") == "already_registered":
        await query.edit_message_text(
            "👋 Вы уже зарегистрированы на розыгрыш! Удачи!"
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


# ==================== АДМИН-КОМАНДЫ ====================

async def draw_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /draw — выбрать 10 случайных победителей."""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Эта команда доступна только организаторам.")
        return

    await update.message.reply_text("🎲 Выбираю победителей...")

    result = send_to_sheets({"action": "draw"})

    if result.get("status") == "empty":
        await update.message.reply_text("В таблице пока нет участников.")
        return

    if result.get("status") != "ok":
        await update.message.reply_text(f"Ошибка: {result.get('message', 'неизвестная')}")
        return

    winners = result.get("winners", [])
    total = result.get("total", 0)

    text = f"🏆 *Победители розыгрыша* ({len(winners)} из {total} участников):\n\n"
    for i, w in enumerate(winners, 1):
        text += (
            f"{i}. {w['name']} ({w['username']})\n"
            f"   🎫 Билет: `{w['ticket']}`\n"
            f"   🆔 ID: `{w['telegram_id']}`\n\n"
        )

    await update.message.reply_text(text, parse_mode="Markdown")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats — количество зарегистрированных."""
    if update.effective_user.id not in ADMIN_IDS:
        return

    result = send_to_sheets({"action": "stats"})
    if result.get("status") == "ok":
        await update.message.reply_text(
            f"📊 Зарегистрировано участников: *{result.get('count', 0)}*",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("Ошибка при получении статистики.")


# ==================== ЗАПУСК ====================

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FOR_TICKET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ticket)],
            WAITING_FOR_CONFIRMATION: [CallbackQueryHandler(confirm, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("draw", draw_winners))
    application.add_handler(CommandHandler("stats", stats))

    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
