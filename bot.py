#!/usr/bin/env python3
import os
import re
import logging
import requests
import tempfile
import threading
import time
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEP_TOKEN = os.getenv("DEP_TOKEN")
DEP_BASE = os.getenv("DEP_BASE")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in environment")
if not DEP_TOKEN:
    raise ValueError("DEP_TOKEN is not set in environment")
if not DEP_BASE:
    raise ValueError("DEP_BASE is not set in environment")

LANG = "ru"
TIMEOUT = 30
KEEP_ALIVE_URL = os.getenv("RENDER_EXTERNAL_URL")  # URL бота на Render

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://depsearch.sbs/",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        if "text/html" in resp.headers.get("content-type", ""):
            return {"error": "API вернул HTML (возможно, защита Cloudflare). Попробуйте позже."}
        if resp.status_code != 200:
            return {"error": f"API error {resp.status_code}: {resp.text[:200]}"}
        return resp.json()
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}

# ========== ГЕНЕРАЦИЯ HTML-ОТЧЁТА (без смайликов, улучшенный дизайн) ==========
def generate_html(data, search_type, query):
    phone_info = data.get("phone_info")
    results = data.get("results", [])

    html = f"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Результаты поиска</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Segoe UI', -apple-system, system-ui, sans-serif;
            background: linear-gradient(145deg, #0b0f1a 0%, #141a26 100%);
            color: #e6edf3;
            padding: 24px;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .container {{
            max-width: 1000px;
            width: 100%;
            background: rgba(22, 27, 34, 0.8);
            backdrop-filter: blur(12px);
            border-radius: 24px;
            padding: 36px 40px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.8), 0 0 0 1px rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.03);
            transition: all 0.2s;
        }}
        h1 {{
            font-size: 32px;
            font-weight: 700;
            letter-spacing: -0.5px;
            background: linear-gradient(to right, #58a6ff, #f0883e);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 6px;
        }}
        .meta {{
            color: #8b949e;
            font-size: 14px;
            padding-bottom: 16px;
            border-bottom: 1px solid rgba(255,255,255,0.06);
            margin-bottom: 24px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px 20px;
        }}
        .meta span {{
            background: rgba(255,255,255,0.04);
            padding: 4px 12px;
            border-radius: 20px;
            font-weight: 400;
        }}
        .phone-box {{
            background: rgba(13, 17, 23, 0.7);
            border-left: 4px solid #58a6ff;
            padding: 18px 22px;
            border-radius: 12px;
            margin-bottom: 28px;
            backdrop-filter: blur(4px);
        }}
        .phone-box h2 {{
            font-size: 18px;
            color: #58a6ff;
            margin-bottom: 10px;
            font-weight: 600;
            letter-spacing: 0.3px;
        }}
        .phone-box .field {{
            display: flex;
            justify-content: space-between;
            padding: 5px 0;
            border-bottom: 1px solid rgba(255,255,255,0.04);
        }}
        .phone-box .field:last-child {{
            border-bottom: none;
        }}
        .phone-box .label {{
            color: #8b949e;
        }}
        .phone-box .value {{
            color: #f0f6fc;
            font-weight: 500;
        }}
        .results-title {{
            font-size: 20px;
            font-weight: 600;
            margin: 24px 0 16px;
            color: #f0f6fc;
            letter-spacing: -0.2px;
        }}
        .card {{
            background: rgba(13, 17, 23, 0.6);
            backdrop-filter: blur(4px);
            border: 1px solid rgba(255,255,255,0.05);
            border-radius: 14px;
            padding: 18px 22px;
            margin-bottom: 12px;
            transition: all 0.25s ease;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        }}
        .card:hover {{
            border-color: rgba(88, 166, 255, 0.3);
            background: rgba(20, 30, 44, 0.7);
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.4);
        }}
        .card .row {{
            display: flex;
            flex-wrap: wrap;
            gap: 4px 16px;
            padding: 3px 0;
        }}
        .card .key {{
            color: #8b949e;
            min-width: 120px;
            font-size: 14px;
        }}
        .card .val {{
            color: #e6edf3;
            word-break: break-word;
            font-weight: 400;
        }}
        .badge {{
            display: inline-block;
            background: rgba(35, 134, 54, 0.25);
            color: #3fb950;
            font-size: 11px;
            padding: 2px 12px;
            border-radius: 20px;
            margin-left: 10px;
            border: 1px solid rgba(35, 134, 54, 0.2);
        }}
        .footer {{
            margin-top: 32px;
            text-align: center;
            color: #484f58;
            font-size: 13px;
            border-top: 1px solid rgba(255,255,255,0.05);
            padding-top: 18px;
            letter-spacing: 0.3px;
        }}
        .error {{
            color: #f85149;
            text-align: center;
            padding: 30px 0;
            font-size: 18px;
            background: rgba(248, 81, 73, 0.08);
            border-radius: 12px;
            border: 1px solid rgba(248, 81, 73, 0.15);
        }}
        @media (max-width: 640px) {{
            .container {{
                padding: 20px 16px;
            }}
            .card .row {{
                flex-direction: column;
                gap: 0;
            }}
            .phone-box .field {{
                flex-direction: column;
            }}
            .phone-box .field .value {{
                margin-top: 2px;
            }}
            h1 {{
                font-size: 24px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Результаты поиска</h1>
        <div class="meta">
            <span>Запрос: {query}</span>
            <span>Тип: {search_type}</span>
        </div>
"""

    if phone_info:
        html += '<div class="phone-box"><h2>Информация о номере</h2>'
        for k, v in phone_info.items():
            html += f'<div class="field"><span class="label">{k}</span><span class="value">{v if v else "—"}</span></div>'
        html += '</div>'

    if results:
        html += f'<div class="results-title">Найдено записей: {len(results)}</div>'
        for i, rec in enumerate(results[:20], 1):
            html += '<div class="card">'
            html += f'<div style="font-weight:600;color:#f0883e;margin-bottom:6px;font-size:15px;">#{i}</div>'
            for key, val in rec.items():
                if val:
                    html += f'<div class="row"><span class="key">{key}</span><span class="val">{val}</span></div>'
            html += '</div>'
        if len(results) > 20:
            html += f'<p style="color:#8b949e;text-align:center;font-size:14px;">... и ещё {len(results)-20} записей.</p>'
    else:
        if not phone_info:
            html += '<div class="error">Ничего не найдено</div>'

    html += """
        <div class="footer">InfoHunt Bot &bull; Данные предоставлены DepSearch API</div>
    </div>
</body>
</html>
"""
    return html

# ========== ОБРАБОТЧИКИ TELEGRAM ==========
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
    text = update.message.text.strip()
    if not text:
        return
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
                filename=f"search_result_{search_type}.html",
                caption=f"Результаты поиска по запросу: {text}"
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

# ========== KEEP-ALIVE (чтобы бот не засыпал на Render) ==========
def keep_alive():
    if not KEEP_ALIVE_URL:
        logging.warning("RENDER_EXTERNAL_URL not set, keep-alive disabled")
        return
    while True:
        try:
            requests.get(KEEP_ALIVE_URL, timeout=10)
            logging.info("Keep-alive ping sent")
        except Exception as e:
            logging.warning(f"Keep-alive error: {e}")
        time.sleep(600)  # каждые 10 минут

# ========== MAIN ==========
def main():
    # Запускаем поток keep-alive, если есть URL
    if KEEP_ALIVE_URL:
        t = threading.Thread(target=keep_alive, daemon=True)
        t.start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
