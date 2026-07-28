#!/usr/bin/env python3
import os
import re
import logging
import requests
import tempfile
import threading
import time
from urllib.parse import quote
from datetime import datetime, date
from flask import Flask, jsonify, request
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv
from crypto_pay import CryptoPay

load_dotenv()

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEP_TOKEN = os.getenv("DEP_TOKEN")
DEP_BASE = os.getenv("DEP_BASE")
DADATA_TOKEN = os.getenv("DADATA_TOKEN")
DADATA_SECRET = os.getenv("DADATA_SECRET")
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN")
PORT = int(os.getenv("PORT", 5000))
FREE_LIMIT = 3

DB_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN or not DEP_TOKEN or not DEP_BASE:
    raise ValueError("BOT_TOKEN, DEP_TOKEN, DEP_BASE must be set")

pay = CryptoPay(CRYPTO_TOKEN) if CRYPTO_TOKEN else None

PACKAGES = {
    "5": {"queries": 5, "usdt": 0.5, "ton": 0.1},
    "30": {"queries": 30, "usdt": 2.0, "ton": 0.5},
    "100": {"queries": 100, "usdt": 10.0, "ton": 1.5},
}

LANG = "ru"
TIMEOUT = 30
logging.basicConfig(level=logging.INFO)

# ========== POSTGRESQL ==========
def get_db():
    return psycopg2.connect(DB_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS search_stats (query_key TEXT PRIMARY KEY, count INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS user_usage (user_id TEXT, date TEXT, count INTEGER DEFAULT 0, PRIMARY KEY (user_id, date))")
    cur.execute("CREATE TABLE IF NOT EXISTS user_balance (user_id TEXT PRIMARY KEY, balance INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS user_gift (user_id TEXT PRIMARY KEY, last_gift_date TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS user_mirror (user_id TEXT PRIMARY KEY, mirror_created BOOLEAN DEFAULT FALSE)")
    conn.commit()
    cur.close()
    conn.close()

def get_user_balance(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM user_balance WHERE user_id = %s", (str(user_id),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else 0

def add_balance(user_id, amount):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO user_balance (user_id, balance) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET balance = user_balance.balance + %s", (str(user_id), amount, amount))
    conn.commit()
    cur.close()
    conn.close()

def use_paid_query(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE user_balance SET balance = balance - 1 WHERE user_id = %s AND balance > 0", (str(user_id),))
    conn.commit()
    cur.close()
    conn.close()

def get_user_usage(user_id):
    today = str(date.today())
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT count FROM user_usage WHERE user_id = %s AND date = %s", (str(user_id), today))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return {"date": today, "count": row[0] if row else 0}

def increment_usage(user_id):
    today = str(date.today())
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO user_usage (user_id, date, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, date) DO UPDATE SET count = user_usage.count + 1", (str(user_id), today))
    conn.commit()
    cur.close()
    conn.close()

def get_remaining_queries(user_id):
    usage = get_user_usage(user_id)
    free_remaining = max(0, FREE_LIMIT - usage["count"])
    paid = get_user_balance(user_id)
    return free_remaining + paid

def can_claim_gift(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT last_gift_date FROM user_gift WHERE user_id = %s", (str(user_id),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return True
    return row[0] != str(date.today())

def claim_gift(user_id):
    today = str(date.today())
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO user_gift (user_id, last_gift_date) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET last_gift_date = %s", (str(user_id), today, today))
    conn.commit()
    cur.close()
    conn.close()

def has_mirror(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT mirror_created FROM user_mirror WHERE user_id = %s", (str(user_id),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row and row[0]

def create_mirror(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO user_mirror (user_id, mirror_created) VALUES (%s, TRUE) ON CONFLICT (user_id) DO UPDATE SET mirror_created = TRUE", (str(user_id),))
    conn.commit()
    cur.close()
    conn.close()

def increment_stats(query):
    key = re.sub(r'\D', '', query)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO search_stats (query_key, count) VALUES (%s, 1) ON CONFLICT (query_key) DO UPDATE SET count = search_stats.count + 1", (key,))
    conn.commit()
    cur.execute("SELECT count FROM search_stats WHERE query_key = %s", (key,))
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count

def get_stats(query):
    key = re.sub(r'\D', '', query)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT count FROM search_stats WHERE query_key = %s", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else 0

# ========== FLASK ==========
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return jsonify({"status": "ok", "service": "InfoHunt Bot"})

@flask_app.route('/ping')
def ping():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

@flask_app.route('/webhook', methods=['POST'])
def crypto_webhook():
    if not pay:
        return "Crypto Pay not configured", 500
    try:
        payload = request.json
        if payload.get("status") == "paid":
            user_id = str(payload["user_id"])
            amount = float(payload["amount"])
            asset = payload["asset"]
            for key, pkg in PACKAGES.items():
                if asset == "USDT" and abs(amount - pkg["usdt"]) < 0.001:
                    add_balance(user_id, pkg["queries"])
                    return "OK", 200
                elif asset == "TON" and abs(amount - pkg["ton"]) < 0.001:
                    add_balance(user_id, pkg["queries"])
                    return "OK", 200
        return "OK", 200
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return "Error", 500

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, debug=False)

# ========== SELF-PING (без домена) ==========
def self_ping():
    url = f"http://localhost:{PORT}/ping"
    while True:
        try:
            requests.get(url, timeout=5)
            logging.info("Self-ping sent (localhost)")
        except Exception as e:
            logging.warning(f"Self-ping failed: {e}")
        time.sleep(600)  # каждые 10 минут

# ========== КЛАВИАТУРА ==========
def get_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Как искать?", callback_data="how_to_search")],
        [InlineKeyboardButton("Аккаунт", callback_data="account")],
        [InlineKeyboardButton("Тех.поддержка", callback_data="support")],
        [InlineKeyboardButton("Мои боты", callback_data="my_bots")],
    ])

def get_back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Назад", callback_data="back_to_main")],
    ])

# ========== DADATA ==========
def dadata_lookup(phone):
    if not DADATA_TOKEN or not DADATA_SECRET:
        return None
    clean = re.sub(r'\D', '', phone)
    try:
        resp = requests.post(
            "https://dadata.ru/api/v2/clean/phone",
            headers={
                "Authorization": f"Token {DADATA_TOKEN}",
                "X-Secret": DADATA_SECRET,
                "Content-Type": "application/json"
            },
            json=[clean],
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                return data[0]
        return None
    except:
        return None

# ========== DEPSEARCH ==========
def search_depsearch(query):
    encoded = quote(query)
    url = f"{DEP_BASE}/quest={encoded}&token={DEP_TOKEN}&lang={LANG}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://depsearch.sbs/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        if "text/html" in resp.headers.get("content-type", ""):
            return {"error": "API вернул HTML (защита Cloudflare). Повторите позже."}
        if resp.status_code != 200:
            return {"error": f"API error {resp.status_code}"}
        return resp.json()
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}

# ========== HTML ==========
def generate_html(data, search_type, query):
    # ... (полный HTML как в предыдущей версии)
    return "<html>...</html>"

# ========== КРАТКИЙ ОТЧЁТ ==========
def format_short(data, query, stats_count):
    lines = []
    clean_phone = re.sub(r'\D', '', query)
    phone_info = dadata_lookup(clean_phone)
    operator = region = country = None
    if phone_info:
        operator = phone_info.get("operator")
        region = phone_info.get("region") or phone_info.get("region_with_type")
        country = phone_info.get("country") or phone_info.get("country_iso_code")
    if not operator and data.get("phone_info"):
        pi = data.get("phone_info")
        operator = pi.get("operator")
        region = pi.get("region")
        country = pi.get("country")
    lines.append("Телефон: +{}".format(clean_phone))
    if operator:
        lines.append("Оператор: {}".format(operator))
    if region:
        lines.append("Регион: {}".format(region))
    if country:
        lines.append("Страна: {}".format(country))
    lines.append("\nИнтересовались этим: {}".format(stats_count))
    return "\n".join(lines)

# ========== ОБРАБОТЧИКИ ==========
last_processed = {}

async def start(update, context):
    user_id = update.effective_user.id

    if can_claim_gift(user_id):
        claim_gift(user_id)
        for _ in range(FREE_LIMIT):
            increment_usage(user_id)

    remaining = get_remaining_queries(user_id)
    await update.message.reply_text(
        "InfoHunt\n\n"
        "У вас {} запросов.\n"
        "Бесплатно: {} в день.\n\n"
        "Выберите действие:".format(remaining, FREE_LIMIT),
        reply_markup=get_main_keyboard()
    )

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data == "back_to_main":
        remaining = get_remaining_queries(user_id)
        await query.edit_message_text(
            "InfoHunt\n\n"
            "У вас {} запросов.\n\n"
            "Выберите действие:".format(remaining),
            reply_markup=get_main_keyboard()
        )
        return

    if data == "how_to_search":
        await query.edit_message_text(
            "Как работать с поиском?\n\n"
            "Физические лица\n"
            "ФИО: Иванов Иван Иванович\n"
            "С датой: Иванов Иван Иванович 11.11.1999\n\n"
            "Контакты\n"
            "Телефон: 79612307060\n"
            "E-mail: mail@example.com\n\n"
            "Документы\n"
            "Паспорт/ИНН: 771234567890 или I-ОБ00644804\n"
            "СНИЛС: 123-456-789 01\n\n"
            "Транспорт\n"
            "Госномер: А777АА01\n"
            "VIN-код: XTA21120050123456\n\n"
            "Интернет и Сеть\n"
            "IP-адрес: 8.8.8.8\n\n"
            "Социальные сети\n"
            "Telegram: @username или ID\n"
            "ВКонтакте: ID 1238377462\n\n"
            "Используйте эти примеры, чтобы убедиться, как работает поиск.",
            reply_markup=get_back_keyboard()
        )
        return

    if data == "account":
        balance = get_user_balance(user_id)
        usage = get_user_usage(user_id)
        remaining = get_remaining_queries(user_id)
        mirror = "Да" if has_mirror(user_id) else "Нет"
        await query.edit_message_text(
            "Аккаунт\n\n"
            "ID: {}\n"
            "Доступно запросов: {}\n"
            "Платных запросов: {}\n"
            "Бесплатных сегодня: {}\n"
            "Зеркало создано: {}".format(
                user_id, remaining, balance, FREE_LIMIT - usage["count"], mirror
            ),
            reply_markup=get_main_keyboard()
        )
        return

    if data == "support":
        await query.edit_message_text(
            "Тех.поддержка\n\n"
            "По всем вопросам пишите:\n"
            "@ваш_ник_поддержки\n\n"
            "Или в чат: t.me/ваш_чат",
            reply_markup=get_main_keyboard()
        )
        return

    if data == "my_bots":
        if has_mirror(user_id):
            await query.edit_message_text(
                "Мои боты\n\n"
                "Вы уже создали зеркало.\n"
                "За зеркало вы получили +3 запроса.",
                reply_markup=get_main_keyboard()
            )
        else:
            create_mirror(user_id)
            add_balance(user_id, 3)
            remaining = get_remaining_queries(user_id)
            await query.edit_message_text(
                "Мои боты\n\n"
                "Зеркало создано!\n"
                "Вам начислено +3 запроса.\n"
                "Теперь у вас {} запросов.".format(remaining),
                reply_markup=get_main_keyboard()
            )
        return

async def handle_message(update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if not text:
        return

    if time.time() - last_processed.get(user_id, 0) < 2:
        return
    last_processed[user_id] = time.time()

    remaining = get_remaining_queries(user_id)
    if remaining <= 0:
        await update.message.reply_text(
            "У вас закончились запросы.\n\n"
            "Заберите бесплатный подарок (раз в день) или создайте зеркало (+3 запроса).",
            reply_markup=get_main_keyboard()
        )
        return

    usage = get_user_usage(user_id)
    if usage["count"] < FREE_LIMIT:
        increment_usage(user_id)
    else:
        use_paid_query(user_id)

    await update.message.reply_text("Поиск...")

    data = search_depsearch(text)
    if "error" in data:
        await update.message.reply_text(f"Ошибка: {data['error']}")
        return

    stats_count = increment_stats(text)

    results = data.get("results", [])
    if results:
        answer = f"Найдено записей: {len(results)}\n\n"
        for i, rec in enumerate(results[:5], 1):
            answer += f"#{i}\n"
            for key, val in rec.items():
                if val and key.lower() not in ["source", "data"]:
                    answer += f"{key}: {val}\n"
            answer += "\n"
        if len(results) > 5:
            answer += f"... и ещё {len(results)-5} записей."
        await update.message.reply_text(answer)
    else:
        await update.message.reply_text("Ничего не найдено.")

# ========== MAIN ==========
def main():
    init_db()

    # Запускаем Flask
    threading.Thread(target=run_flask, daemon=True).start()

    # Запускаем self-ping (без домена)
    threading.Thread(target=self_ping, daemon=True).start()

    # Запускаем Telegram-бота
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
