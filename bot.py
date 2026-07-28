#!/usr/bin/env python3
import os
import re
import logging
import requests
import tempfile
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# ========== НАСТРОЙКИ (все из окружения) ==========
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

# ========== API ЗАПРОС К DEPSEARCH ==========
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

# ========== ГЕНЕРАЦИЯ HTML-ОТЧЁТА ==========
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
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: #0b0f19;
            color: #e6edf3;
            padding: 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
            background: #161b22;
            border-radius: 16px;
            padding: 30px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.6);
        }}
        h1 {{
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(135deg, #58a6ff, #f0883e);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }}
        .meta {{
            color: #8b949e;
            font-size: 14px;
            margin-bottom: 24px;
            border-bottom: 1px solid #30363d;
            padding-bottom: 12px;
        }}
        .phone-box {{
            background: #0d1117;
            border-left: 4px solid #58a6ff;
            padding: 16px 20px;
            border-radius: 8px;
            margin-bottom: 24px;
        }}
        .phone-box h2 {{
            color: #58a6ff;
            font-size: 18px;
            margin-bottom: 8px;
        }}
        .phone-box .field {{
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            border-bottom: 1px solid #21262d;
        }}
        .phone-box .label {{
            color: #8b949e;
        }}
        .phone-box .value {{
            color: #e6edf3;
            font-weight: 500;
        }}
        .results-title {{
            font-size: 20px;
            font-weight: 600;
            margin: 24px 0 16px;
            color: #f0f6fc;
        }}
        .card {{
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 16px 20px;
            margin-bottom: 12px;
            transition: 0.2s;
        }}
        .card:hover {{
            border-color: #58a6ff;
            background: #131a24;
        }}
        .card .row {{
            display: flex;
            flex-wrap: wrap;
            gap: 4px 16px;
            padding: 2px 0;
        }}
        .card .key {{
            color: #8b949e;
            min-width: 120px;
        }}
        .card .val {{
            color: #e6edf3;
            word-break: break-word;
        }}
        .badge {{
            display: inline-block;
            background: #238636;
            color: #fff;
            font-size: 12px;
            padding: 2px 10px;
            border-radius: 12px;
            margin-left: 10px;
        }}
        .footer {{
            margin-top: 30px;
            text-align: center;
            color: #8b949e;
            font-size: 13px;
            border-top: 1px solid #30363d;
            padding-top: 16px;
        }}
        .error {{
            color: #f85149;
            text-align: center;
            padding: 30px;
            font-size: 18px;
        }}
        @media (max-width: 600px) {{
            .container {{
                padding: 16px;
            }}
            .card .row {{
                flex-direction: column;
                gap: 0;
            }}
            .phone-box .field {{
                flex-direction: column;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 Результаты поиска</h1>
        <div class="meta">
            <strong>Запрос:</strong> {query} &nbsp;·&nbsp; <strong>Тип:</strong> {search_type}
        </div>
"""

    if phone_info:
        html += '<div class="phone-box"><h2>📞 Информация о номере</h2>'
        for k, v in phone_info.items():
            html += f'<div class="field"><span class="label">{k}</span><span class="value">{v if v else "—"}</span></div>'
        html += '</div>'

    if results:
        html += f'<div class="results-title">📋 Найдено записей: {len(results)}</div>'
        for i, rec in enumerate(results[:20], 1):
            html += '<div class="card">'
            html += f'<div style="font-weight:600;color:#f0883e;margin-bottom:6px;">#{i}</div>'
            for key, val in rec.items():
                if val:
                    html += f'<div class="row"><span class="key">{key}</span><span class="val">{val}</span></div>'
            html += '</div>'
        if len(results) > 20:
            html += f'<p style="color:#8b949e;text-align:center;">... и ещё {len(results)-20} записей.</p>'
    else:
        if not phone_info:
            html += '<div class="error">❌ Ничего не найдено</div>'

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

    # Формируем запрос в зависимости от типа
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
    else:
        q = text

    await update.message.reply_text("⏳ Ищу...")

    data = search_depsearch(q)
    if "error" in data:
        await update.message.reply_text(f"❌ Ошибка: {data['error']}")
        return

    # Генерируем HTML
    html_content = generate_html(data, search_type, text)

    # Сохраняем во временный файл и отправляем
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
        f.write(html_content)
        tmp_path = f.name

    try:
        with open(tmp_path, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=f"search_result_{search_type}.html",
                caption=f"📊 Результаты поиска по запросу: {text}"
            )
    finally:
        os.unlink(tmp_path)

async def help_command(update, context):
    await update.message.reply_text(
        "📖 *Помощь*\n\n"
        "1. Выберите тип поиска на клавиатуре.\n"
        "2. Отправьте данные.\n"
        "3. Получите HTML-отчёт.\n\n"
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
