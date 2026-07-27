#!/usr/bin/env python3
import re
import logging
import requests
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# ========== НАСТРОЙКИ (вписаны вручную) ==========
BOT_TOKEN = "8621713290:AAHcQnxKlSYMCN-45ixenBkLUL7jsMFFATA"
API_TOKEN = "OsMTcjyHTRtfABnWA4V3d12SYKVIYE8z"
BASE_URL = "https://api.depsearch.sbs"

# =================================================

logging.basicConfig(level=logging.INFO)

# ========== КЛАВИАТУРА ==========
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📞 По телефону", callback_data="phone")],
        [InlineKeyboardButton("👤 По ФИО", callback_data="name")],
        [InlineKeyboardButton("📧 По Email", callback_data="email")],
        [InlineKeyboardButton("🆔 По ИНН", callback_data="inn")],
        [InlineKeyboardButton("🆔 По СНИЛС", callback_data="snils")],
        [InlineKeyboardButton("🌐 По IP", callback_data="ip")],
        [InlineKeyboardButton("📛 По никнейму", callback_data="nick")],
        [InlineKeyboardButton("🚗 По ГРЗ/VIN", callback_data="auto")],
        [InlineKeyboardButton("🏚 По адресу", callback_data="address")],
        [InlineKeyboardButton("👨 По соцсети", callback_data="social")],
        [InlineKeyboardButton("💳 По карте", callback_data="card")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== КОМАНДЫ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 *InfoHunt Bot*\n\n"
        "Я ищу информацию по ФИО, телефону, email, ИНН, СНИЛС, IP, никнейму, авто, адресу, соцсетям и картам.\n\n"
        "📌 *Примеры запросов:*\n"
        "👤 *ФИО:* Иванов Иван Иванович\n"
        "📞 *Телефон:* 79277231370\n"
        "📧 *Email:* user@mail.ru\n"
        "🆔 *ИНН:* 784806113663\n"
        "🎫 *СНИЛС:* 13046964250\n"
        "🌐 *IP:* 8.8.8.8\n"
        "📛 *Никнейм:* @durov\n"
        "🚗 *ГРЗ:* А777АА777\n"
        "🚗 *VIN:* XTA211440B5049434\n"
        "🏚 *Адрес:* г. Москва, Тверская, д.1\n"
        "👨 *Соцсети:* vk.com/id15671234, instagram.com/eye\n"
        "💳 *Карта:* 4111 1111 1111 1111\n\n"
        "🔹 Отправь любой текст — я сам определю, что искать.\n"
        "🔹 Используй кнопки для выбора типа поиска.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Помощь*\n\n"
        "👤 *Поиск по имени:*\n  Иванов Иван Иванович\n  Иванов Иван 05.02.1994\n\n"
        "🚗 *Поиск по авто:*\n  А777АА777 - ГРЗ\n  XTA211440B5049434 - VIN\n\n"
        "👨 *Социальные сети:*\n  instagram.com/eye\n  vk.com/id15671234\n  facebook.com/profile.php?id=1\n  ok.ru/profile/162853188111\n\n"
        "📞 *Телефон:* 79999939919\n"
        "📧 *Email:* tema@gmail.com\n"
        "📛 *Telegram:* @durov или #1006503122\n\n"
        "🏚 *Адрес:* /adr Москва, Тверская, д 1, кв 1\n"
        "🏘 *Кадастр:* 77:01:0001075:1361\n\n"
        "🏛 *Компания:* /company ИНН или ОГРН\n"
        "📑 *ИНН:* /inn 784806113663\n"
        "🎫 *СНИЛС:* /snils 13046964250\n"
        "📇 *Паспорт:* /passport 6113825395\n"
        "🗂 *ВУ:* /vy 9902371011\n\n"
        "💳 *Карта:* 4111 1111 1111 1111\n\n"
        "📸 *Фото:* Отправь фото (в разработке)",
        parse_mode="Markdown"
    )

# ========== ОБРАБОТЧИК КНОПОК ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['search_type'] = query.data
    await query.edit_message_text(
        f"✍️ Отправь данные для поиска по *{query.data}*",
        parse_mode="Markdown"
    )

# ========== ОПРЕДЕЛЕНИЕ ТИПА ПОИСКА ==========
def detect_search_type(text):
    text = text.strip()

    if text.startswith('/adr'):
        return 'address', text[4:].strip()
    if text.startswith('/company'):
        return 'company', text[8:].strip()
    if text.startswith('/inn'):
        return 'inn', text[4:].strip()
    if text.startswith('/snils'):
        return 'snils', text[6:].strip()
    if text.startswith('/passport'):
        return 'passport', text[9:].strip()
    if text.startswith('/vy'):
        return 'vy', text[3:].strip()

    if 'vk.com/' in text or 'vkontakte.ru/' in text:
        match = re.search(r'(?:vk\.com/|vkontakte\.ru/)(id|club|public|event)(\d+)', text)
        if match:
            return 'vk', f"vkid{match.group(2)}"
        return 'vk', text
    if 'instagram.com/' in text:
        match = re.search(r'instagram\.com/([^/?]+)', text)
        if match:
            return 'instagram', match.group(1)
    if 'facebook.com/' in text:
        match = re.search(r'facebook\.com/profile\.php\?id=(\d+)', text)
        if match:
            return 'facebook', match.group(1)
    if 'ok.ru/' in text:
        match = re.search(r'ok\.ru/profile/(\d+)', text)
        if match:
            return 'ok', match.group(1)

    if text.startswith('@'):
        return 'telegram', f"nick:{text[1:]}"
    if text.startswith('#'):
        return 'telegram', f"nick:{text[1:]}"

    if re.match(r'^\+?\d{10,15}$', text):
        return 'phone', text
    if '@' in text and '.' in text:
        return 'email', text
    if re.match(r'^[A-Z0-9]{17}$', text.upper()):
        return 'auto', text
    if re.match(r'^[А-ЯA-Z]{1}\d{3}[А-ЯA-Z]{2}\d{2,3}$', text.upper()):
        return 'auto', text
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', text):
        return 'ip', text
    if re.match(r'^\d{2}:\d{2}:\d{7}:\d+$', text):
        return 'cadastre', text
    if re.sub(r'\s', '', text).isdigit() and len(re.sub(r'\s', '', text)) in [15, 16]:
        return 'card', text

    return 'name', text

# ========== ОБРАБОТКА СООБЩЕНИЙ ==========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        return

    search_type = context.user_data.get('search_type', 'auto')
    if search_type != 'auto':
        q = text
        if search_type == 'inn':
            q = f"inn{text}"
        elif search_type == 'snils':
            q = f"snils{text}"
        elif search_type == 'nick':
            q = f"nick:{text}"
        elif search_type == 'address':
            q = f"addr:{text}"
        elif search_type == 'card':
            q = f"card:{text}"
        elif search_type == 'social':
            detected, q = detect_search_type(text)
            search_type = detected
        else:
            q = text
    else:
        detected_type, q = detect_search_type(text)
        search_type = detected_type

    # Кодируем запрос (для кириллицы) и формируем URL
    q_encoded = quote(q)
    url = f"{BASE_URL}/quest={q_encoded}&token={API_TOKEN}&lang=ru"

    # ========== ОТЛАДОЧНЫЙ ВЫВОД (временно) ==========
    print("\n" + "="*50)
    print("🔍 ОТЛАДКА ЗАПРОСА:")
    print("API_TOKEN =", repr(API_TOKEN))
    print("URL =", url)
    print("="*50 + "\n")
    # ===============================================

    await update.message.reply_text("⏳ Ищу...")

    try:
        resp = requests.get(url, timeout=30)

        # ========== ОТЛАДОЧНЫЙ ВЫВОД (временно) ==========
        print("\n" + "="*50)
        print("📡 ОТВЕТ API:")
        print("STATUS CODE =", resp.status_code)
        print("RESPONSE TEXT =", resp.text[:500])  # первые 500 символов
        print("="*50 + "\n")
        # ===============================================

        if resp.status_code != 200:
            await update.message.reply_text(f"❌ Ошибка API: {resp.status_code}")
            return

        try:
            data = resp.json()
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка парсинга JSON: {str(e)}")
            return

        phone_info = data.get("phone_info")
        ip_info = data.get("ip_info")
        results = data.get("results", [])

        if not phone_info and not ip_info and not results:
            await update.message.reply_text("❌ Ничего не найдено.")
            return

        answer = "🔍 *Результаты поиска:*\n"

        if phone_info:
            answer += "\n📞 *Информация о номере:*\n"
            for key, val in phone_info.items():
                if val:
                    answer += f"  {key}: {val}\n"

        if ip_info:
            answer += "\n🌐 *Информация об IP:*\n"
            for key, val in ip_info.items():
                if val:
                    answer += f"  {key}: {val}\n"

        if results:
            answer += f"\n📋 *Найдено записей: {len(results)}*\n"
            for i, rec in enumerate(results[:10], 1):
                answer += f"\n*#{i}*\n"
                for key, val in rec.items():
                    if val:
                        answer += f"  {key}: {val}\n"

            if len(results) > 10:
                answer += f"\n... и ещё {len(results) - 10} записей."

        if len(answer) > 4096:
            answer = answer[:4000] + "\n... (обрезано)"

        await update.message.reply_text(answer, parse_mode="Markdown")

    except requests.exceptions.Timeout:
        await update.message.reply_text("❌ Таймаут API. Попробуй позже.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# ========== ОБРАБОТКА ФОТО ==========
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Поиск по фото пока не поддерживается. Функция в разработке.")

# ========== MAIN ==========
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
