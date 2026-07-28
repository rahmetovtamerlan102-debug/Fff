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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEP_TOKEN = os.getenv("DEP_TOKEN")
DEP_BASE = os.getenv("DEP_BASE")

if not BOT_TOKEN or not DEP_TOKEN or not DEP_BASE:
    raise ValueError("BOT_TOKEN, DEP_TOKEN, DEP_BASE must be set in environment")

LANG = "ru"
TIMEOUT = 30
KEEP_ALIVE_URL = os.getenv("RENDER_EXTERNAL_URL")  # автоматически подставляется Render'ом

logging.basicConfig(level=logging.INFO)

# ========== КЛАВИАТУРА (без юзернейма) ==========
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

# ========== API ЗАПРОС ==========
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

# ========== ГЕНЕРАЦИЯ HTML (стиль Router Search) ==========
def generate_html(data, search_type, query):
    phone_info = data.get("phone_info")
    results = data.get("results", [])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_sources = len(results)
    sources_with_data = sum(1 for r in results if r)
    accuracy = min(100, max(0, int((sources_with_data / max(1, total_sources)) * 100))) if total_sources else 0

    # Формируем список источников
    sources = []
    for i in range(1, total_sources + 1):
        sources.append(f"Base №{i}")
    sources_html = "".join(f'<div class="src-pill"><span class="ico">BA</span> {s}</div>' for s in sources[:20])

    # Карточки баз
    cards_html = ""
    for i, rec in enumerate(results[:20], 1):
        rec_str = str(rec)
        card_badges = f'<span class="badge green">ДАННЫЕ</span>'
        size_kb = max(1, len(rec_str) // 1024)
        cards_html += f'''
        <div class="card">
            <div class="card-head">
                <span class="card-name">Base №{i}</span>
                <div class="card-badges">
                    <span class="badge green">ДАННЫЕ</span>
                    <span class="badge">{size_kb} KB</span>
                    <span class="badge">{accuracy}%</span>
                </div>
            </div>
            <div class="card-body">
                <div class="data-block"><pre>{rec_str}</pre></div>
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
<title>Router Search | Отчёт</title>
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
.sources-panel {{
  background: #1e1e24;
  border: 1px solid #3a3a44;
  border-radius: 12px;
  padding: 14px 18px;
  margin: 16px 0 20px;
}}
.sources-panel .title {{
  font-size: 10px;
  color: #8888aa;
  text-transform: uppercase;
  letter-spacing: 2px;
  margin-bottom: 8px;
  font-weight: 600;
}}
.src-list {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}}
.src-pill {{
  background: #25252b;
  border: 1px solid #3a3a44;
  border-radius: 20px;
  padding: 3px 12px;
  font-size: 10px;
  color: #ccccdd;
  display: flex;
  align-items: center;
  gap: 5px;
}}
.src-pill .ico {{
  background: #7c3aed;
  color: #ffffff;
  border-radius: 12px;
  padding: 1px 6px;
  font-size: 7px;
  font-weight: 700;
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
  font-family: 'JetBrains Mono', 'SF Mono', monospace;
}}
.data-block pre {{
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
}}
.data-block b {{
  color: #a78bfa;
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
    <h1>Router Search</h1>
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
  <div class="sources-panel">
    <div class="title">Источники</div>
    <div class="src-list">
      {sources_html}
    </div>
  </div>
  <div class="cards">
    {cards_html}
  </div>
  <div class="footer">
    <span class="footer-brand">Router Search</span>
    <span>#66c245db</span>
    <span>{now}</span>
  </div>
</div>
</body>
</html>
"""
    return html

# ========== ОБРАБОТЧИКИ TELEGRAM ==========
# Блокировка дублирования
last_processed = {}

async def start(update, context):
    await update.message.reply_text(
        "🔍 *InfoHunt Bot*\n\n"
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
        f"Отправьте данные для поиска по *{query.data}*",
        parse_mode="Markdown"
    )

async def handle_message(update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if not text:
        return

    # Блокировка дублирования (2 секунды)
    now = time.time()
    if user_id in last_processed and (now - last_processed[user_id] < 2):
        return
    last_processed[user_id] = now

    search_type = context.user_data.get('search_type', 'name')

    if search_type == 'phone':
        q = re.sub(r'\D', '', text)
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

    await update.message.reply_text("Поиск...")

    data = search_depsearch(q)
    if "error" in data:
        await update.message.reply_text(f"Ошибка: {data['error']}")
        return

    html_content = generate_html(data, search_type, text)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
        f.write(html_content)
        tmp_path = f.name

    try:
        with open(tmp_path, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=f"search_report_{search_type}.html",
                caption=f"Отчёт по запросу: {text}"
            )
    finally:
        os.unlink(tmp_path)

async def help_command(update, context):
    await update.message.reply_text(
        "Помощь\n\n"
        "1. Выберите тип поиска на клавиатуре.\n"
        "2. Отправьте данные.\n"
        "3. Получите HTML-отчёт.\n\n"
        "Примеры:\n"
        "  ФИО: Иванов Иван\n"
        "  Телефон: 79277231370\n"
        "  СНИЛС: 123-456-789-01\n"
        "  ИНН: 784806113663\n"
        "  Паспорт: 4516 123456\n"
        "  Карта: 5337361874187412",
        parse_mode="Markdown"
    )

# ========== KEEP-ALIVE (автоматически через RENDER_EXTERNAL_URL) ==========
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

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
