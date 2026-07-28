#!/usr/bin/env python3
import os
import re
import logging
import requests
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEP_TOKEN = os.getenv("DEP_TOKEN")
DEP_BASE = os.getenv("DEP_BASE", "https://api.depsearch.sbs")
LANG = "ru"
TIMEOUT = 30

if not BOT_TOKEN or not DEP_TOKEN:
    raise ValueError("BOT_TOKEN and DEP_TOKEN are required in .env")

logging.basicConfig(level=logging.INFO)

# ========== КЛАВИАТУРА ==========
def get_keyboard():
    buttons = [
        [InlineKeyboardButton("👤 По ФИО", callback_data="name")],
        [InlineKeyboardButton("📞 По телефону", callback_data="phone")],
        [InlineKeyboardButton("📛 По юзернейму", callback_data="username")],
        [InlineKeyboardButton("🎫 По СНИЛС", callback_data="snils")],
        [InlineKeyboardButton("📑 По ИНН", callback_data="inn")],
        [InlineKeyboardButton("📇 По паспорту", callback_data="passport")],
        [InlineKeyboardButton("💳 По карте", callback_data="card")],
    ]
    return InlineKeyboardMarkup(buttons)

def search_depsearch(query):
    encoded = quote(query)
    url = f"{DEP_BASE}/quest={encoded}&token={DEP_TOKEN}&lang={LANG}"
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        if resp.status_code != 200:
            return {"error": f"API error {resp.status_code}: {resp.text[:200]}"}
        return resp.json()
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}

def format_result(data, search_type):
    answer = f"🔍 *Результаты поиска ({search_type})*\n"
    phone_info = data.get("phone_info")
    if phone_info:
        answer += "\n📞 *Информация о номере:*\n"
        for k, v in phone_info.items():
            if v:
                answer += f"  {k}: {v}\n"
    results = data.get("results", [])
    if results:
        answer += f"\n📋 *Найдено записей: {len(results)}*\n"
        for i, rec in enumerate(results[:10], 1):
            answer += f"\n*#{i}*\n"
            for key, val in rec.items():
                if val:
                    answer += f"  {key}: {val}\n"
        if len(results) > 10:
            answer += f"\n... и ещё {len(results)-10} записей."
    else:
        if not phone_info:
            answer += "\n❌ Ничего не найдено."
    return answer[:4000]

async def start(update, context):
    await update.message.reply_text(
        "🔍 *InfoHunt Bot*\n\n"
        "Поиск по ФИО, телефону, юзернейму, СНИЛС, ИНН, паспорту, карте.\n\n"
        "Выберите тип поиска на клавиатуре 👇",
        reply_markup=get_keyboard(),
        parse_mode="Markdown"
    )

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['search_type'] = query.data
    await query.edit_message_text(
        f"✍️ Отправьте данные для поиска по *{query.data}*",
        parse_mode="Markdown"
    )

async def handle_message(update, context):
    text = update.message.text.strip()
    if not text:
        return
    search_type = context.user_data.get('search_type', 'name')

    # Очищаем от нецифровых символов там, где это нужно
    if search_type == 'phone':
        q = re.sub(r'\D', '', text)
    elif search_type == 'username':
        q = f"nick:{text.lstrip('@')}"
    elif search_type == 'snils':
        clean_snils = re.sub(r'\D', '', text)
        q = f"snils{clean_snils}"
    elif search_type == 'inn':
        clean_inn = re.sub(r'\D', '', text)
        q = f"inn{clean_inn}"
    elif search_type == 'passport':
        q = text
    elif search_type == 'card':
        q = re.sub(r'\s', '', text)
    else:  # name
        q = text

    await update.message.reply_text("⏳ Ищу...")
    data = search_depsearch(q)
    if "error" in data:
        await update.message.reply_text(f"❌ Ошибка: {data['error']}")
        return
    await update.message.reply_text(format_result(data, search_type), parse_mode="Markdown")

async def help_command(update, context):
    await update.message.reply_text(
        "📖 *Помощь*\n\n"
        "1. Выберите тип поиска на клавиатуре.\n"
        "2. Отправьте данные.\n"
        "3. Получите результат.\n\n"
        "Примеры:\n"
        "  ФИО: Иванов Иван\n"
        "  Телефон: 79277231370\n"
        "  Юзернейм: @durov\n"
        "  СНИЛС: 123-456-789-01\n"
        "  ИНН: 784806113663\n"
        "  Паспорт: 4516 123456\n"
        "  Карта: 5337361874187412",
        parse_mode="Markdown"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
