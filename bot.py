#!/usr/bin/env python3
import os
import re
import logging
import requests
import tempfile
import threading
import time
from urllib.parse import quote
from datetime import datetime
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEP_TOKEN = os.getenv("DEP_TOKEN")
DEP_BASE = os.getenv("DEP_BASE")
DADATA_TOKEN = os.getenv("DADATA_TOKEN")
DADATA_SECRET = os.getenv("DADATA_SECRET")
PORT = int(os.getenv("PORT", 5000))

if not BOT_TOKEN or not DEP_TOKEN or not DEP_BASE:
    raise ValueError("BOT_TOKEN, DEP_TOKEN, DEP_BASE must be set in environment")

LANG = "ru"
TIMEOUT = 30
logging.basicConfig(level=logging.INFO)

# ========== Flask для UptimeRobot ==========
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return jsonify({"status": "ok", "service": "InfoHunt Bot"})

@flask_app.route('/ping')
def ping():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, debug=False)

# ========== КЛАВИАТУРА ==========
def get_keyboard():
    buttons = [
        [InlineKeyboardButton("По ФИО", callback_data="name")],
        [InlineKeyboardButton("По телефону", callback_data="phone")],
        [InlineKeyboardButton("По СНИЛС", callback_data="snils")],
        [InlineKeyboardButton("По ИНН", callback_data="inn")],
        [InlineKeyboardButton("По паспорту", callback_data="passport")],
        [InlineKeyboardButton("По карте", callback_data="card")],
    ]
    return InlineKeyboardMarkup(buttons)

def get_report_button(query, search_type):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Полный отчёт", callback_data=f"report_{search_type}_{query}")]
    ])

# ========== DADATA (информация о номере) ==========
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

# ========== DEPSEARCH (основной поиск) ==========
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

# ========== ГЕНЕРАЦИЯ HTML-ОТЧЁТА ==========
def generate_html(data, search_type, query):
    phone_info = data.get("phone_info")
    results = data.get("results", [])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_sources = len(results)
    sources_with_data = sum(1 for r in results if r)
    accuracy = min(100, max(0, int((sources_with_data / max(1, total_sources)) * 100))) if total_sources else 0

    emoji_map = {
        'phone': '📞', 'phone2': '📞', 'telephone': '📞',
        'birth_date': '🎂', 'birthday': '🎂', 'bdate': '🎂', 'bday': '🎂',
        'full_name': '👤', 'name': '👤', 'first_name': '👤', 'last_name': '👤', 'fio': '👤',
        'email': '📧', 'mail': '📧',
        'passport': '📇', 'passport_series_number': '📇',
        'inn': '🆔', 'snils': '🆔',
        'card': '💳', 'credit_card': '💳', 'card_expiration': '📅', 'card_id': '💳',
        'address': '📍',
        'password': '🔑', 'password_hash': '🔑', 'non_crypt_paswd': '🔑',
        'region': '📍', 'city': '🏙️', 'country': '🌍', 'operator': '📡',
        'timezone': '🕐', 'local_time': '🕐', 'localtime': '🕐',
        'gender': '⚤', 'sex': '⚤',
    }

    cards_html = ""
    for i, rec in enumerate(results[:20], 1):
        filtered = {}
        for k, v in rec.items():
            k_lower = k.lower()
            if 'source' in k_lower or 'источник' in k_lower or k_lower == 'data':
                continue
            if v is None or v == "":
                continue
            filtered[k] = v

        rows = ""
        for k, v in filtered.items():
            emoji = emoji_map.get(k.lower(), '')
            display_key = f"{emoji} {k}" if emoji else k
            rows += f'<div class="row"><span class="key">{display_key}</span><span class="val">{v}</span></div>'
        if not rows:
            rows = '<div class="row"><span class="key">Данные</span><span class="val">пусто</span></div>'

        size_kb = max(1, len(str(filtered)) // 1024)
        cards_html += f'''
        <div class="card">
            <div class="card-head">
                <span class="card-name">Base #{i}</span>
                <div class="card-badges">
                    <span class="badge green">ДАННЫЕ</span>
                    <span class="badge">{size_kb} KB</span>
                    <span class="badge">{accuracy}%</span>
                </div>
            </div>
            <div class="card-body">
                <div class="data-block">{rows}</div>
            </div>
            <div class="card-foot"><div class="card-foot-bar" style="width:{accuracy}%"></div></div>
        </div>
        '''

    html = f"""
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>InfoHunt | Отчёт</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  background: #1a1a1f;
  color: #ffffff;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  font-size: 13px;
  padding: 20px;
  line-height: 1.6;
}}
.container {{
  max-width: 920px;
  margin: 0 auto;
  background: #25252b;
  border: 1px solid #3a3a44;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.6);
}}
.header {{
  border-bottom: 2px solid #3a3a44;
  padding-bottom: 16px;
  margin-bottom: 20px;
}}
.header h1 {{
  font-size: 22px;
  font-weight: 800;
  color: #a78bfa;
  letter-spacing: 3px;
  text-transform: uppercase;
}}
.header .sub {{
  font-size: 11px;
  color: #8888aa;
  margin-top: 4px;
  font-weight: 400;
}}
.query-box {{
  background: #1e1e24;
  border: 1px solid #3a3a44;
  border-radius: 10px;
  padding: 12px 16px;
  margin: 16px 0 20px;
  font-size: 13px;
  color: #c4b5fd;
}}
.query-box .label {{
  font-size: 9px;
  color: #8888aa;
  letter-spacing: 2px;
  text-transform: uppercase;
  display: block;
  margin-bottom: 4px;
  font-weight: 600;
}}
.stats {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}}
.stat {{
  background: #1e1e24;
  border: 1px solid #3a3a44;
  border-radius: 12px;
  padding: 14px 12px;
  text-align: center;
}}
.stat-n {{
  font-size: 24px;
  font-weight: 800;
  color: #a78bfa;
}}
.stat-l {{
  font-size: 9px;
  color: #8888aa;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-top: 4px;
  font-weight: 600;
}}
.accuracy-block {{
  background: #1e1e24;
  border: 2px solid #7c3aed;
  border-radius: 12px;
  padding: 16px 20px;
  margin: 16px 0 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}}
.accuracy-label {{
  font-size: 11px;
  color: #ccccdd;
  font-weight: 600;
}}
.accuracy-value {{
  font-size: 32px;
  font-weight: 800;
  color: #a78bfa;
}}
.accuracy-bar-wrap {{
  flex: 1;
  min-width: 120px;
}}
.accuracy-bar {{
  width: 100%;
  height: 8px;
  background: #3a3a44;
  border-radius: 10px;
  overflow: hidden;
}}
.accuracy-bar-fill {{
  height: 100%;
  border-radius: 10px;
  background: linear-gradient(90deg, #7c3aed, #a78bfa);
  transition: width 1s ease;
}}
.accuracy-labels {{
  display: flex;
  justify-content: space-between;
  font-size: 8px;
  color: #8888aa;
  margin-top: 4px;
}}
.chips {{
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}}
.chip {{
  background: #1e1e24;
  border: 1px solid #3a3a44;
  border-radius: 20px;
  padding: 4px 16px;
  font-size: 11px;
  color: #ffffff;
  display: flex;
  align-items: center;
  gap: 6px;
}}
.chip-label {{
  color: #8888aa;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 1px;
  font-weight: 600;
}}
.chip-val {{
  color: #c4b5fd;
  font-weight: 600;
}}
.cards {{
  display: flex;
  flex-direction: column;
  gap: 14px;
}}
.card {{
  background: #1e1e24;
  border: 1px solid #3a3a44;
  border-radius: 12px;
  overflow: hidden;
}}
.card-head {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: #16161c;
  border-bottom: 1px solid #3a3a44;
  flex-wrap: wrap;
  gap: 6px;
}}
.card-name {{
  font-size: 13px;
  font-weight: 700;
  color: #ffffff;
}}
.card-badges {{
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}}
.badge {{
  background: #25252b;
  border: 1px solid #3a3a44;
  border-radius: 16px;
  padding: 2px 10px;
  font-size: 9px;
  color: #ccccdd;
  font-weight: 600;
}}
.badge.green {{
  border-color: #7c3aed;
  color: #a78bfa;
  background: rgba(124, 58, 237, 0.08);
}}
.card-body {{
  padding: 14px 16px;
}}
.data-block {{
  background: #16161c;
  border: 1px solid #2a2a32;
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 12px;
  line-height: 1.8;
  max-height: 380px;
  overflow-y: auto;
  color: #dddddd;
  font-family: 'Inter', sans-serif;
}}
.data-block .row {{
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 16px;
  padding: 3px 0;
  border-bottom: 1px solid rgba(255,255,255,0.03);
}}
.data-block .row:last-child {{
  border-bottom: none;
}}
.data-block .key {{
  color: #8b949e;
  min-width: 140px;
  font-weight: 600;
  flex-shrink: 0;
}}
.data-block .val {{
  color: #e6edf3;
  word-break: break-word;
  flex: 1;
}}
.card-foot {{
  height: 3px;
  background: #2a2a32;
}}
.card-foot-bar {{
  height: 100%;
  background: #7c3aed;
  border-radius: 3px;
}}
.footer {{
  margin-top: 28px;
  padding-top: 16px;
  border-top: 1px solid #3a3a44;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
  color: #8888aa;
  flex-wrap: wrap;
  gap: 8px;
}}
.footer-brand {{
  font-weight: 700;
  color: #a78bfa;
  letter-spacing: 2px;
}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>InfoHunt</h1>
    <div class="sub">osint report &bull; {now}</div>
  </div>
  <div class="query-box">
    <span class="label">Запрос</span>
    {search_type}: {query}
  </div>
  <div class="stats">
    <div class="stat">
      <div class="stat-n">{total_sources}</div>
      <div class="stat-l">Источников</div>
    </div>
    <div class="stat">
      <div class="stat-n">{sources_with_data}</div>
      <div class="stat-l">С данными</div>
    </div>
    <div class="stat">
      <div class="stat-n">{now[11:16]}</div>
      <div class="stat-l">Время</div>
    </div>
  </div>
  <div class="accuracy-block">
    <div>
      <div class="accuracy-label">Общая точность данных</div>
      <div class="accuracy-value">{accuracy}%</div>
    </div>
    <div class="accuracy-bar-wrap">
      <div class="accuracy-bar">
        <div class="accuracy-bar-fill" style="width:{accuracy}%"></div>
      </div>
      <div class="accuracy-labels">
        <span>0%</span>
        <span>100%</span>
      </div>
    </div>
  </div>
  <div class="chips">
    <div class="chip"><span class="chip-label">Тип</span><span class="chip-val">{search_type}</span></div>
    <div class="chip"><span class="chip-label">Запросов</span><span class="chip-val">1</span></div>
    <div class="chip"><span class="chip-label">Статус</span><span class="chip-val">завершён</span></div>
  </div>
  <div class="cards">
    {cards_html}
  </div>
  <div class="footer">
    <span class="footer-brand">InfoHunt</span>
    <span>#66c245db</span>
    <span>{now}</span>
  </div>
</div>
</body>
</html>
"""
    return html

# ========== КРАТКИЙ ОТЧЁТ ==========
def format_short(data, phone_info, query):
    results = data.get("results", [])
    lines = []

    # Номер, оператор, регион, страна (из DaData или DepSearch)
    phone_display = query
    operator = None
    region = None
    country = None

    if phone_info:
        if phone_info.get("phone"):
            phone_display = phone_info.get("phone")
        if phone_info.get("operator"):
            operator = phone_info.get("operator")
        if phone_info.get("region"):
            region = phone_info.get("region")
        if phone_info.get("country"):
            country = phone_info.get("country")
    elif data.get("phone_info"):
        pi = data.get("phone_info")
        if pi.get("phone"):
            phone_display = pi.get("phone")
        if pi.get("operator"):
            operator = pi.get("operator")
        if pi.get("region"):
            region = pi.get("region")
        if pi.get("country"):
            country = pi.get("country")

    lines.append("📱")
    lines.append(f"├ Телефон: {phone_display}")
    if operator:
        lines.append(f"├ Оператор: {operator}")
    if region:
        lines.append(f"├ Регион: {region}")
    if country:
        lines.append(f"└ Страна: {country}")

    # ФИО
    fio = None
    for r in results[:10]:
        if "full_name" in r and r["full_name"]:
            fio = r["full_name"]
            break
        if "fio" in r and r["fio"]:
            fio = r["fio"]
            break
        if "name" in r and r["name"]:
            fio = r["name"]
            break
    lines.append("\n👤 Основные данные")
    lines.append(f"└ ФИО: {fio if fio else 'не найдено'}")

    lines.append(f"\n👁 Интересовались этим: {len(results)}")
    return "\n".join(lines)

# ========== ОБРАБОТЧИКИ TELEGRAM ==========
last_processed = {}

async def start(update, context):
    await update.message.reply_text(
        "InfoHunt Bot\n\n"
        "Поиск по ФИО, телефону, СНИЛС, ИНН, паспорту, карте.\n\n"
        "Выберите тип поиска на клавиатуре.",
        reply_markup=get_keyboard(),
        parse_mode="Markdown"
    )

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['search_type'] = query.data
    await query.edit_message_text(
        f"Отправьте данные для поиска по {query.data}",
        parse_mode="Markdown"
    )

async def handle_message(update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if not text:
        return

    now = time.time()
    if user_id in last_processed and (now - last_processed[user_id] < 2):
        return
    last_processed[user_id] = now

    search_type = context.user_data.get('search_type', 'name')

    if search_type == 'phone':
        q = re.sub(r'\D', '', text)
        phone_info = dadata_lookup(text)
    else:
        q = text
        phone_info = None

    await update.message.reply_text("Поиск...")

    data = search_depsearch(q)
    if "error" in data:
        await update.message.reply_text(f"Ошибка: {data['error']}")
        return

    # Краткий отчёт + кнопка "Полный отчёт"
    short = format_short(data, phone_info, text)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Полный отчёт", callback_data=f"report_{search_type}_{text}")]
    ])
    await update.message.reply_text(short, reply_markup=keyboard, parse_mode="Markdown")

    # Сохраняем данные для кнопки
    context.user_data['report_data'] = {
        'search_type': search_type,
        'query': text,
        'data': data
    }

async def report_callback(update, context):
    query = update.callback_query
    await query.answer()

    # Получаем данные из кэша
    report_data = context.user_data.get('report_data')
    if not report_data:
        await query.edit_message_text("❌ Данные устарели. Отправьте запрос заново.")
        return

    search_type = report_data['search_type']
    text = report_data['query']
    data = report_data['data']

    # Генерируем HTML
    html_content = generate_html(data, search_type, text)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
        f.write(html_content)
        tmp_path = f.name

    try:
        with open(tmp_path, 'rb') as f:
            await query.message.reply_document(
                document=f,
                filename=f"infoHunt_report_{search_type}.html",
                caption=f"📊 Полный отчёт по запросу: {text}"
            )
    finally:
        os.unlink(tmp_path)

async def help_command(update, context):
    await update.message.reply_text(
        "Помощь\n\n"
        "1. Выберите тип поиска на клавиатуре.\n"
        "2. Отправьте данные.\n"
        "3. Получите краткий отчёт с кнопкой 'Полный отчёт'.\n\n"
        "Примеры:\n"
        "  ФИО: Иванов Иван\n"
        "  Телефон: 79277231370\n"
        "  СНИЛС: 123-456-789-01\n"
        "  ИНН: 784806113663\n"
        "  Паспорт: 4516 123456\n"
        "  Карта: 5337361874187412",
        parse_mode="Markdown"
    )

# ========== KEEP-ALIVE ==========
def keep_alive():
    if not KEEP_ALIVE_URL:
        return
    while True:
        try:
            requests.get(KEEP_ALIVE_URL, timeout=10)
            logging.info("Keep-alive ping sent")
        except:
            pass
        time.sleep(600)

# ========== MAIN ==========
def main():
    if KEEP_ALIVE_URL:
        threading.Thread(target=keep_alive, daemon=True).start()

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(?!report_)"))
    app.add_handler(CallbackQueryHandler(report_callback, pattern="^report_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
