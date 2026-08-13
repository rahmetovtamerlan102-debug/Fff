#!/usr/bin/env python3
import os
import re
import logging
import requests
import tempfile
import threading
import time
import json
from urllib.parse import quote
from datetime import datetime
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEP_TOKEN = os.getenv("DEP_TOKEN")
DEP_BASE = os.getenv("DEP_BASE")
DADATA_TOKEN = os.getenv("DADATA_TOKEN")
DADATA_SECRET = os.getenv("DADATA_SECRET")
FUNSTAT_TOKEN = os.getenv("FUNSTAT_TOKEN")

# Канал для подписки
REQUIRED_CHANNEL = "@iomoov"

# Токены Jitler (3 штуки)
JITLER_TOKEN_1 = os.getenv("JITLER_TOKEN_1")
JITLER_TOKEN_2 = os.getenv("JITLER_TOKEN_2")
JITLER_TOKEN_3 = os.getenv("JITLER_TOKEN_3")

PORT = int(os.getenv("PORT", 5000))
STATS_FILE = "search_stats.json"

if not BOT_TOKEN or not DEP_TOKEN or not DEP_BASE:
    raise ValueError("BOT_TOKEN, DEP_TOKEN, DEP_BASE must be set in environment")

LANG = "ru"
TIMEOUT = 15
JITLER_TIMEOUT = 10
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Список токенов Jitler
JITLER_TOKENS = []
if JITLER_TOKEN_1:
    JITLER_TOKENS.append(JITLER_TOKEN_1)
if JITLER_TOKEN_2:
    JITLER_TOKENS.append(JITLER_TOKEN_2)
if JITLER_TOKEN_3:
    JITLER_TOKENS.append(JITLER_TOKEN_3)

CURRENT_TOKEN_INDEX = 0

# ========== СТАТИСТИКА ==========
def load_stats():
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)

def increment_stats(query):
    stats = load_stats()
    key = re.sub(r'\D', '', str(query))
    if not key:
        key = str(query).strip().lower()
    stats[key] = stats.get(key, 0) + 1
    save_stats(stats)
    return stats[key]

def get_stats(query):
    stats = load_stats()
    key = re.sub(r'\D', '', str(query))
    if not key:
        key = str(query).strip().lower()
    return stats.get(key, 0)

# ========== ПРОВЕРКА ПОДПИСКИ ==========
async def check_subscription(update, context):
    try:
        user_id = update.effective_user.id
        chat_member = await context.bot.get_chat_member(
            chat_id=REQUIRED_CHANNEL,
            user_id=user_id
        )
        if chat_member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        logging.error(f"Subscription check error: {e}")
        return False

async def require_subscription(update, context):
    await update.message.reply_text(
        f"⚠️ *Для использования бота необходимо подписаться на канал!*\n\n"
        f"👉 Подпишись: {REQUIRED_CHANNEL}\n\n"
        f"После подписки нажми /start заново",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Подписаться", url=f"https://t.me/{REQUIRED_CHANNEL[1:]}")]
        ]),
        parse_mode="Markdown"
    )

# ========== Flask ==========
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return jsonify({"status": "ok", "service": "InfoHunt Bot"})

@flask_app.route('/ping')
def ping():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, debug=False)

def self_ping():
    url = f"http://localhost:{PORT}/ping"
    while True:
        try:
            requests.get(url, timeout=5)
            logging.info("Self-ping отправлен")
        except Exception as e:
            logging.warning(f"Self-ping ошибка: {e}")
        time.sleep(600)

# ========== КЛАВИАТУРА ==========
def get_keyboard():
    buttons = [
        [InlineKeyboardButton("👤 По ФИО", callback_data="name")],
        [InlineKeyboardButton("📱 По телефону", callback_data="phone")],
        [InlineKeyboardButton("🆔 По СНИЛС", callback_data="snils")],
        [InlineKeyboardButton("🆔 По ИНН", callback_data="inn")],
        [InlineKeyboardButton("📇 По паспорту", callback_data="passport")],
        [InlineKeyboardButton("💳 По карте", callback_data="card")],
        [InlineKeyboardButton("🔍 По ID Telegram", callback_data="telegram_id")],
    ]
    return InlineKeyboardMarkup(buttons)

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
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                return data[0]
        return None
    except:
        return None

# ========== FUNSTAT API ==========
def funstat_request(endpoint, params=None):
    """Запрос к Funstat API"""
    if not FUNSTAT_TOKEN:
        return None
    
    url = f"https://funstat.ru/api/v1{endpoint}"
    headers = {
        "Authorization": f"Bearer {FUNSTAT_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        logging.warning(f"Funstat error {resp.status_code}: {resp.text}")
        return None
    except Exception as e:
        logging.error(f"Funstat request error: {e}")
        return None

def funstat_get_names(user_id):
    """Получить историю имен пользователя"""
    result = funstat_request(f"/users/{user_id}/names")
    if result and result.get("data"):
        return result["data"]
    return None

def funstat_get_usernames(user_id):
    """Получить историю username'ов"""
    result = funstat_request(f"/users/{user_id}/usernames")
    if result and result.get("data"):
        return result["data"]
    return None

def funstat_get_gifts(user_id):
    """Получить информацию о подарках"""
    result = funstat_request(f"/users/{user_id}/gifts_relation")
    if result and result.get("data"):
        return result["data"]
    return None

def funstat_get_stats_min(user_id):
    """Минимальная статистика (бесплатно)"""
    result = funstat_request(f"/users/{user_id}/stats_min")
    if result and result.get("data"):
        return result["data"]
    return None

def funstat_get_basic_info(user_id):
    """Базовая информация по ID (0.1 кредита)"""
    result = funstat_request(f"/users/basic_info_by_id", params={"ids": user_id})
    if result and result.get("data"):
        return result["data"]
    return None

# ========== JITLER API ==========
def get_jitler_token():
    global CURRENT_TOKEN_INDEX
    
    if not JITLER_TOKENS:
        return None
    
    for i in range(len(JITLER_TOKENS)):
        idx = (CURRENT_TOKEN_INDEX + i) % len(JITLER_TOKENS)
        token = JITLER_TOKENS[idx]
        
        try:
            resp = requests.get(
                "https://api.jitler.top/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("result"):
                    plan = data.get("plan", {})
                    daily = plan.get("daily", {})
                    monthly = plan.get("monthly", {})
                    parallel = plan.get("parallel_tasks", {})
                    
                    if (daily.get("current", 0) < daily.get("limit", 0) and 
                        monthly.get("current", 0) < monthly.get("limit", 0) and
                        parallel.get("current", 0) < parallel.get("limit", 0)):
                        CURRENT_TOKEN_INDEX = idx
                        return token
        except:
            continue
    
    return JITLER_TOKENS[0] if JITLER_TOKENS else None

def jitler_search_number(phone):
    token = get_jitler_token()
    if not token:
        return None
    
    clean_phone = re.sub(r'\D', '', phone)
    
    try:
        resp = requests.post(
            "https://api.jitler.top/search",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={"type": "number", "query": clean_phone, "page": 1},
            timeout=JITLER_TIMEOUT
        )
        
        if resp.status_code != 200:
            return None
        
        data = resp.json()
        
        if not data.get("result"):
            return None
        
        if "response" in data:
            return data["response"]
        
        if "id" in data:
            return jitler_wait_for_result_fast(data["id"], token)
        
        return None
        
    except requests.Timeout:
        return None
    except Exception as e:
        logging.error(f"Jitler search error: {e}")
        return None

def jitler_search_id(search_id):
    token = get_jitler_token()
    if not token:
        return None
    
    try:
        resp = requests.post(
            "https://api.jitler.top/search",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={"type": "sherlock", "query": str(search_id), "page": 1},
            timeout=JITLER_TIMEOUT
        )
        
        if resp.status_code != 200:
            return None
        
        data = resp.json()
        
        if not data.get("result"):
            return None
        
        if "response" in data:
            return data["response"]
        
        if "id" in data:
            return jitler_wait_for_result_fast(data["id"], token)
        
        return None
        
    except requests.Timeout:
        return None
    except Exception as e:
        logging.error(f"Jitler ID search error: {e}")
        return None

def jitler_wait_for_result_fast(task_id, token, max_attempts=5):
    for attempt in range(max_attempts):
        try:
            resp = requests.get(
                f"https://api.jitler.top/search/{task_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5
            )
            
            if resp.status_code == 501:
                time.sleep(1)
                continue
                
            if resp.status_code == 200:
                data = resp.json()
                if data.get("result") and "response" in data:
                    return data["response"]
                    
            return None
            
        except Exception:
            time.sleep(1)
            continue
    
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
            return {"error": "API вернул HTML. Повторите позже."}
        if resp.status_code != 200:
            return {"error": f"API error {resp.status_code}"}
        return resp.json()
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}

# ========== УНИВЕРСАЛЬНЫЙ ПОИСК ==========
def unified_search(query, search_type):
    result = {
        "depsearch": None,
        "jitler": None,
        "phone_info": None,
        "funstat": None,
        "search_type": search_type,
        "errors": []
    }
    
    def do_depsearch():
        return search_depsearch(query)
    
    def do_jitler():
        if search_type == "phone":
            clean_phone = re.sub(r'\D', '', query)
            return jitler_search_number(clean_phone)
        elif search_type == "telegram_id":
            clean_id = re.sub(r'\D', '', query)
            return jitler_search_id(clean_id)
        return None
    
    def do_dadata():
        if search_type == "phone":
            clean_phone = re.sub(r'\D', '', query)
            return dadata_lookup(clean_phone)
        return None
    
    def do_funstat():
        if search_type == "telegram_id":
            clean_id = re.sub(r'\D', '', query)
            if clean_id:
                return {
                    "names": funstat_get_names(clean_id),
                    "usernames": funstat_get_usernames(clean_id),
                    "gifts": funstat_get_gifts(clean_id),
                    "stats_min": funstat_get_stats_min(clean_id)
                }
        return None
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        dep_future = executor.submit(do_depsearch)
        jitler_future = executor.submit(do_jitler) if search_type in ["phone", "telegram_id"] else None
        dadata_future = executor.submit(do_dadata) if search_type == "phone" else None
        funstat_future = executor.submit(do_funstat) if search_type == "telegram_id" else None
        
        try:
            dep_result = dep_future.result(timeout=TIMEOUT)
            if "error" not in dep_result:
                result["depsearch"] = dep_result
            else:
                result["errors"].append(f"Depsearch: {dep_result['error']}")
        except Exception as e:
            result["errors"].append(f"Depsearch timeout: {str(e)}")
        
        if jitler_future:
            try:
                jitler_result = jitler_future.result(timeout=JITLER_TIMEOUT + 5)
                if jitler_result:
                    result["jitler"] = jitler_result
                    logging.info("Jitler данные получены")
                else:
                    result["errors"].append("Jitler: данные не найдены")
            except Exception as e:
                result["errors"].append(f"Jitler: {str(e)}")
        
        if dadata_future:
            try:
                phone_info = dadata_future.result(timeout=5)
                if phone_info:
                    result["phone_info"] = phone_info
            except Exception as e:
                pass
        
        if funstat_future:
            try:
                funstat_result = funstat_future.result(timeout=10)
                if funstat_result:
                    result["funstat"] = funstat_result
                    logging.info("Funstat данные получены")
            except Exception as e:
                result["errors"].append(f"Funstat: {str(e)}")
    
    return result

# ========== ФОРМАТИРОВАНИЕ КРАТКОГО ОТВЕТА ==========
def format_jitler_data(jitler_data):
    lines = []
    
    if not jitler_data or not isinstance(jitler_data, dict):
        return lines
    
    if "phonebooks" in jitler_data:
        phonebooks = jitler_data["phonebooks"]
        if isinstance(phonebooks, list) and phonebooks:
            clean_list = [str(p).strip() for p in phonebooks if p and str(p).strip()]
            if clean_list:
                lines.append(f"├ 📇 Телефонные книги: {', '.join(clean_list)}")
    
    if "profiles" in jitler_data:
        profiles = jitler_data["profiles"]
        if isinstance(profiles, dict):
            for platform, items in profiles.items():
                if not items:
                    continue
                
                if isinstance(items, list):
                    platform_name = str(platform).strip().lower()
                    
                    for item in items:
                        if not item:
                            continue
                        
                        if platform_name == "vk" and isinstance(item, dict):
                            name = item.get("name", "")
                            url = item.get("url", "")
                            if name:
                                lines.append(f"├ 🔵 VK: {name}")
                            if url:
                                lines.append(f"├ 🔗 {url}")
                        
                        elif platform_name == "ok" and isinstance(item, dict):
                            name = item.get("name", "")
                            url = item.get("url", "")
                            if name:
                                lines.append(f"├ 🟠 OK: {name}")
                            if url:
                                lines.append(f"├ 🔗 {url}")
                        
                        elif platform_name == "telegram" and isinstance(item, dict):
                            username = item.get("username", "")
                            tg_id = item.get("id", "")
                            if username:
                                lines.append(f"├ ✈️ Telegram: {username}")
                            if tg_id:
                                lines.append(f"├ 🆔 TG ID: {tg_id}")
                        
                        elif isinstance(item, dict):
                            name = item.get("name") or item.get("username") or item.get("nickname")
                            url = item.get("url")
                            if name:
                                lines.append(f"├ {platform}: {name}")
                            if url:
                                lines.append(f"├ 🔗 {url}")
                            if not name and not url and item:
                                lines.append(f"├ {platform}: {item}")
                        
                        else:
                            lines.append(f"├ {platform}: {item}")
                
                elif isinstance(items, dict):
                    platform_name = str(platform).strip().lower()
                    if platform_name == "vk":
                        name = items.get("name", "")
                        url = items.get("url", "")
                        if name:
                            lines.append(f"├ 🔵 VK: {name}")
                        if url:
                            lines.append(f"├ 🔗 {url}")
                    elif platform_name == "ok":
                        name = items.get("name", "")
                        url = items.get("url", "")
                        if name:
                            lines.append(f"├ 🟠 OK: {name}")
                        if url:
                            lines.append(f"├ 🔗 {url}")
                    elif platform_name == "telegram":
                        username = items.get("username", "")
                        tg_id = items.get("id", "")
                        if username:
                            lines.append(f"├ ✈️ Telegram: {username}")
                        if tg_id:
                            lines.append(f"├ 🆔 TG ID: {tg_id}")
                    else:
                        lines.append(f"├ {platform}: {items}")
    
    if "telegram" in jitler_data:
        tg_list = jitler_data["telegram"]
        if isinstance(tg_list, list):
            for tg in tg_list:
                if isinstance(tg, dict):
                    username = tg.get("username", "")
                    tg_id = tg.get("id", "")
                    if username:
                        lines.append(f"├ ✈️ Telegram: {username}")
                    if tg_id:
                        lines.append(f"├ 🆔 TG ID: {tg_id}")
        elif isinstance(tg_list, dict):
            username = tg_list.get("username", "")
            tg_id = tg_list.get("id", "")
            if username:
                lines.append(f"├ ✈️ Telegram: {username}")
            if tg_id:
                lines.append(f"├ 🆔 TG ID: {tg_id}")
    
    useful_keys = {
        'full_name': '👤 ФИО',
        'name': '👤 Имя',
        'first_name': '👤 Имя',
        'last_name': '👤 Фамилия',
        'fio': '👤 ФИО',
        'email': '📧 Email',
        'address': '📍 Адрес',
        'city': '🏙️ Город',
        'region': '📍 Регион',
        'country': '🌍 Страна',
        'birth_date': '🎂 Дата рождения',
        'birthday': '🎂 День рождения',
        'inn': '🆔 ИНН',
        'snils': '🆔 СНИЛС',
        'phone': '📱 Телефон',
        'username': '👤 Username',
        'user_id': '🆔 User ID'
    }
    
    for key, label in useful_keys.items():
        if key in jitler_data and jitler_data[key]:
            value = jitler_data[key]
            if isinstance(value, (dict, list)):
                continue
            lines.append(f"├ {label}: {value}")
    
    if "counts" in jitler_data:
        counts = jitler_data["counts"]
        if isinstance(counts, dict):
            count_parts = []
            for k, v in counts.items():
                if v:
                    names = {
                        'Телефонные книги': '📇 Телефонные книги',
                        'VK профили': '🔵 VK',
                        'OK профили': '🟠 OK',
                        'Telegram': '✈️ Telegram'
                    }
                    name = names.get(k, k)
                    count_parts.append(f"{name}: {v}")
            if count_parts:
                lines.append(f"├ 📊 Статистика: {', '.join(count_parts)}")
    
    return lines

def format_short(data, query, stats_count, search_type):
    lines = []
    
    if search_type == "phone":
        clean_phone = re.sub(r'\D', '', query)
        lines.append(f"📱 *Телефон:* +{clean_phone}")
        
        phone_info = data.get("phone_info")
        if phone_info:
            operator = phone_info.get("operator")
            region = phone_info.get("region") or phone_info.get("region_with_type")
            country = phone_info.get("country") or phone_info.get("country_iso_code")
            
            if operator:
                lines.append(f"├ 📡 Оператор: {operator}")
            if region:
                lines.append(f"├ 📍 Регион: {region}")
            if country:
                lines.append(f"└ 🌍 Страна: {country}")
    
    elif search_type == "telegram_id":
        clean_id = re.sub(r'\D', '', query)
        lines.append(f"🆔 *ID Telegram:* {clean_id}")
    
    else:
        lines.append(f"🔍 *Запрос:* {query}")
    
    # Jitler данные
    jitler_data = data.get("jitler")
    if jitler_data and isinstance(jitler_data, dict):
        lines.append("")
        lines.append("📊 *Найденные данные:*")
        jitler_lines = format_jitler_data(jitler_data)
        lines.extend(jitler_lines)
        if jitler_lines:
            lines.append("└ *Источник: Jitler*")
    
    # Depsearch
    dep_data = data.get("depsearch", {})
    if dep_data and isinstance(dep_data, dict):
        results = dep_data.get("results", [])
        if results and len(results) > 0:
            lines.append("")
            lines.append(f"📁 *Depsearch:* {len(results)} записей")
    
    # Статистика запросов
    if stats_count and stats_count > 0:
        lines.append("")
        lines.append(f"👁 *Интересовались этим:* {stats_count} раз")
    
    # Ошибки
    errors = data.get("errors", [])
    if errors:
        lines.append("")
        lines.append(f"⚠️ {errors[0]}")
        if len(errors) > 1:
            lines.append(f"⚠️ {errors[1]}")
    
    return "\n".join(lines)

# ========== ГЕНЕРАЦИЯ HTML-ОТЧЁТА ==========
def generate_html(data, search_type, query):
    dep_data = data.get("depsearch", {})
    jitler_data = data.get("jitler")
    phone_info = data.get("phone_info")
    funstat_data = data.get("funstat")
    
    results = dep_data.get("results", []) if isinstance(dep_data, dict) else []
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_sources = len(results) + (1 if jitler_data else 0) + (1 if phone_info else 0) + (1 if funstat_data else 0)
    sources_with_data = sum(1 for r in results if r) + (1 if jitler_data else 0) + (1 if phone_info else 0) + (1 if funstat_data else 0)
    accuracy = min(100, max(0, int((sources_with_data / max(1, total_sources)) * 100))) if total_sources else 0

    emoji_map = {
        'phone': '📞', 'phone2': '📞', 'telephone': '📞',
        'birth_date': '🎂', 'birthday': '🎂', 'bdate': '🎂', 'bday': '🎂',
        'full_name': '👤', 'name': '👤', 'first_name': '👤', 'last_name': '👤', 'fio': '👤',
        'email': '📧', 'mail': '📧',
        'passport': '📇', 'passport_series_number': '📇',
        'inn': '🆔', 'snils': '🆔',
        'card': '💳', 'credit_card': '💳', 'card_expiration': '📅', 'card_id': '💳',
        'address': '📍', 'region': '📍', 'city': '🏙️', 'country': '🌍', 'operator': '📡',
        'gender': '⚤', 'sex': '⚤',
        'raw': '📄', 'username': '👤', 'nickname': '👤', 'user_id': '🆔',
        'telegram_id': '🆔', 'tg_id': '🆔', 'phonebooks': '📇',
        'profiles': '👤', 'counts': '📊', 'names': '📝', 'usernames': '@',
        'gifts': '🎁', 'stats_min': '📊'
    }

    cards_html = ""
    source_counter = 1
    
    # Phone info
    if phone_info:
        rows = ""
        for k, v in phone_info.items():
            if v and k not in ['source', 'qc']:
                emoji = emoji_map.get(k.lower(), '')
                display_key = f"{emoji} {k}" if emoji else k
                rows += f'<div class="row"><span class="key">{display_key}</span><span class="val">{v}</span></div>'
        
        if rows:
            cards_html += f'''
            <div class="card">
                <div class="card-head">
                    <span class="card-name">DaData #{source_counter}</span>
                    <div class="card-badges">
                        <span class="badge green">ДАННЫЕ</span>
                    </div>
                </div>
                <div class="card-body">
                    <div class="data-block">{rows}</div>
                </div>
                <div class="card-foot"><div class="card-foot-bar" style="width:{accuracy}%;background:#059669"></div></div>
            </div>
            '''
            source_counter += 1
    
    # Depsearch
    for rec in results[:10]:
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
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False, indent=2)[:300]
            rows += f'<div class="row"><span class="key">{display_key}</span><span class="val">{v}</span></div>'
        if not rows:
            rows = '<div class="row"><span class="key">Данные</span><span class="val">пусто</span></div>'

        size_kb = max(1, len(str(filtered)) // 1024)
        cards_html += f'''
        <div class="card">
            <div class="card-head">
                <span class="card-name">Depsearch #{source_counter}</span>
                <div class="card-badges">
                    <span class="badge green">ДАННЫЕ</span>
                    <span class="badge">{size_kb} KB</span>
                </div>
            </div>
            <div class="card-body">
                <div class="data-block">{rows}</div>
            </div>
            <div class="card-foot"><div class="card-foot-bar" style="width:{accuracy}%;background:#7c3aed"></div></div>
        </div>
        '''
        source_counter += 1
    
    # Jitler
    if jitler_data and isinstance(jitler_data, dict):
        clean_data = {}
        for k, v in jitler_data.items():
            if k in ['result', 'response']:
                continue
            if v is None or v == "":
                continue
            if k == 'phonebooks' and isinstance(v, list):
                clean_data[k] = ', '.join(str(p) for p in v if p)
            elif k == 'profiles' and isinstance(v, dict):
                profile_str = []
                for platform, items in v.items():
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                name = item.get('name') or item.get('username')
                                url = item.get('url')
                                if name:
                                    profile_str.append(f"{platform}: {name}")
                                elif url:
                                    profile_str.append(f"{platform}: {url}")
                            elif item:
                                profile_str.append(f"{platform}: {item}")
                    elif isinstance(items, dict):
                        name = items.get('name') or items.get('username')
                        url = items.get('url')
                        if name:
                            profile_str.append(f"{platform}: {name}")
                        elif url:
                            profile_str.append(f"{platform}: {url}")
                        elif items:
                            profile_str.append(f"{platform}: {items}")
                clean_data[k] = '; '.join(profile_str) if profile_str else v
            elif k == 'telegram' and isinstance(v, list):
                tg_str = []
                for tg in v:
                    if isinstance(tg, dict):
                        username = tg.get('username', '')
                        tg_id = tg.get('id', '')
                        if username:
                            tg_str.append(f"username: {username}")
                        if tg_id:
                            tg_str.append(f"id: {tg_id}")
                clean_data[k] = '; '.join(tg_str) if tg_str else v
            elif k == 'counts' and isinstance(v, dict):
                count_str = []
                for ck, cv in v.items():
                    if cv:
                        count_str.append(f"{ck}: {cv}")
                clean_data[k] = ', '.join(count_str) if count_str else v
            else:
                clean_data[k] = v

        rows = ""
        for k, v in clean_data.items():
            emoji = emoji_map.get(k.lower(), '')
            display_key = f"{emoji} {k}" if emoji else k
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False, indent=2)[:300]
            rows += f'<div class="row"><span class="key">{display_key}</span><span class="val">{v}</span></div>'
        if not rows:
            rows = '<div class="row"><span class="key">Данные</span><span class="val">найдены</span></div>'

        size_kb = max(1, len(str(clean_data)) // 1024)
        cards_html += f'''
        <div class="card">
            <div class="card-head">
                <span class="card-name">Jitler #{1}</span>
                <div class="card-badges">
                    <span class="badge green">ДАННЫЕ</span>
                    <span class="badge">{size_kb} KB</span>
                </div>
            </div>
            <div class="card-body">
                <div class="data-block">{rows}</div>
            </div>
            <div class="card-foot"><div class="card-foot-bar" style="width:{accuracy}%;background:#8b5cf6"></div></div>
        </div>
        '''
    
    # Funstat карточка
    if funstat_data and isinstance(funstat_data, dict):
        rows = ""
        
        # История имен
        if "names" in funstat_data and funstat_data["names"]:
            names = funstat_data["names"]
            if isinstance(names, list):
                for item in names[:10]:
                    if isinstance(item, dict):
                        name = item.get("name", "")
                        date = item.get("date", "")
                        if name:
                            rows += f'<div class="row"><span class="key">📝 Имя</span><span class="val">{name}</span></div>'
                            if date:
                                rows += f'<div class="row"><span class="key">📅 Дата</span><span class="val">{date}</span></div>'
        
        # История username'ов
        if "usernames" in funstat_data and funstat_data["usernames"]:
            usernames = funstat_data["usernames"]
            if isinstance(usernames, list):
                for item in usernames[:10]:
                    if isinstance(item, dict):
                        username = item.get("username", "")
                        date = item.get("date", "")
                        if username:
                            rows += f'<div class="row"><span class="key">@ Username</span><span class="val">{username}</span></div>'
                            if date:
                                rows += f'<div class="row"><span class="key">📅 Дата</span><span class="val">{date}</span></div>'
        
        # Подарки
        if "gifts" in funstat_data and funstat_data["gifts"]:
            gifts = funstat_data["gifts"]
            if isinstance(gifts, list):
                for item in gifts[:10]:
                    if isinstance(item, dict):
                        from_user = item.get("from", "")
                        to_user = item.get("to", "")
                        gift_name = item.get("gift", "")
                        if from_user:
                            rows += f'<div class="row"><span class="key">🎁 От</span><span class="val">{from_user}</span></div>'
                        if to_user:
                            rows += f'<div class="row"><span class="key">🎁 Кому</span><span class="val">{to_user}</span></div>'
                        if gift_name:
                            rows += f'<div class="row"><span class="key">🎁 Подарок</span><span class="val">{gift_name}</span></div>'
        
        # Статистика
        if "stats_min" in funstat_data and funstat_data["stats_min"]:
            stats_min = funstat_data["stats_min"]
            if isinstance(stats_min, dict):
                for k, v in stats_min.items():
                    if v:
                        rows += f'<div class="row"><span class="key">📊 {k}</span><span class="val">{v}</span></div>'
        
        if rows:
            cards_html += f'''
            <div class="card">
                <div class="card-head">
                    <span class="card-name">Funstat #{1}</span>
                    <div class="card-badges">
                        <span class="badge green">ДАННЫЕ</span>
                    </div>
                </div>
                <div class="card-body">
                    <div class="data-block">{rows}</div>
                </div>
                <div class="card-foot"><div class="card-foot-bar" style="width:{accuracy}%;background:#f59e0b"></div></div>
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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
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

# ========== ОБРАБОТЧИКИ TELEGRAM ==========
last_processed = {}

async def start(update, context):
    if not await check_subscription(update, context):
        await require_subscription(update, context)
        return
    
    await update.message.reply_text(
        "🔍 *InfoHunt Bot*\n\n"
        "Я помогаю искать информацию по различным данным.\n\n"
        "👇 *Чтобы начать, выберите тип поиска на клавиатуре:*",
        reply_markup=get_keyboard(),
        parse_mode="Markdown"
    )
    context.user_data['search_type'] = None

type_names = {
    'name': 'ФИО',
    'phone': 'телефону',
    'snils': 'СНИЛС',
    'inn': 'ИНН',
    'passport': 'паспорту',
    'card': 'карте',
    'telegram_id': 'ID Telegram'
}

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    
    if not await check_subscription(update, context):
        await query.edit_message_text(
            f"⚠️ *Для использования бота необходимо подписаться на канал!*\n\n"
            f"👉 Подпишись: {REQUIRED_CHANNEL}\n\n"
            f"После подписки нажми /start заново",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Подписаться", url=f"https://t.me/{REQUIRED_CHANNEL[1:]}")]
            ]),
            parse_mode="Markdown"
        )
        return
    
    search_type = query.data
    context.user_data['search_type'] = search_type
    
    examples = {
        'name': '👤 *Введите ФИО для поиска*\n\nПример: Иванов Иван Иванович',
        'phone': '📱 *Введите номер телефона для поиска*\n\nПример: 79271234567',
        'snils': '🆔 *Введите СНИЛС для поиска*\n\nПример: 123-456-789-01',
        'inn': '🆔 *Введите ИНН для поиска*\n\nПример: 784806113663',
        'passport': '📇 *Введите паспорт для поиска*\n\nПример: 4516 123456',
        'card': '💳 *Введите номер карты для поиска*\n\nПример: 5337361874187412',
        'telegram_id': '🔍 *Введите ID Telegram для поиска*\n\nПример: 123456789'
    }
    
    await query.edit_message_text(
        f"✅ Выбран поиск по *{type_names.get(search_type, search_type)}*\n\n"
        f"{examples.get(search_type, '📤 Отправьте данные для поиска.')}",
        parse_mode="Markdown"
    )

async def handle_message(update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if not text:
        return
    
    if not await check_subscription(update, context):
        await require_subscription(update, context)
        return
    
    search_type = context.user_data.get('search_type')
    
    if not search_type:
        await update.message.reply_text(
            "⚠️ *Сначала выберите тип поиска!*\n\n"
            "Нажмите на одну из кнопок ниже:",
            reply_markup=get_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    now = time.time()
    if user_id in last_processed and (now - last_processed[user_id] < 2):
        return
    last_processed[user_id] = now
    
    q = text
    if search_type == 'phone':
        q = re.sub(r'\D', '', text)
    elif search_type == 'telegram_id':
        q = re.sub(r'\D', '', text)
    
    stats_count = increment_stats(text)
    
    msg = await update.message.reply_text("⏳ Поиск...")
    
    data = unified_search(q, search_type)
    
    dep_data = data.get("depsearch", {})
    if "error" in dep_data and not data.get("jitler"):
        await msg.edit_text(f"❌ Ошибка: {dep_data['error']}")
        context.user_data['search_type'] = None
        return
    
    short = format_short(data, text, stats_count, search_type)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Полный отчёт", callback_data=f"report_{search_type}_{text}")]
    ])
    await msg.edit_text(short, reply_markup=keyboard, parse_mode="Markdown")
    
    context.user_data['report_data'] = {
        'search_type': search_type,
        'query': text,
        'data': data
    }

async def report_callback(update, context):
    query = update.callback_query
    await query.answer()
    
    report_data = context.user_data.get('report_data')
    if not report_data:
        await query.edit_message_text(
            "❌ Данные устарели. Отправьте запрос заново.",
            reply_markup=get_keyboard()
        )
        return
    
    search_type = report_data['search_type']
    text = report_data['query']
    data = report_data['data']
    
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
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

async def help_command(update, context):
    await update.message.reply_text(
        "📖 *Помощь*\n\n"
        "1️⃣ Нажмите на кнопку с нужным типом поиска\n"
        "2️⃣ Отправьте данные для поиска\n"
        "3️⃣ Получите краткий отчёт с кнопкой 'Полный отчёт'\n\n"
        "*Примеры данных:*\n"
        "  👤 ФИО: Иванов Иван Иванович\n"
        "  📱 Телефон: 79271234567\n"
        "  🆔 СНИЛС: 123-456-789-01\n"
        "  🆔 ИНН: 784806113663\n"
        "  📇 Паспорт: 4516 123456\n"
        "  💳 Карта: 5337361874187412\n"
        "  🔍 ID Telegram: 123456789\n\n"
        "⚠️ *Важно:* сначала выберите тип поиска!\n"
        f"📢 *Подпишись:* {REQUIRED_CHANNEL}",
        reply_markup=get_keyboard(),
        parse_mode="Markdown"
    )

# ========== MAIN ==========
def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    self_ping_thread = threading.Thread(target=self_ping, daemon=True)
    self_ping_thread.start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(?!report_)"))
    app.add_handler(CallbackQueryHandler(report_callback, pattern="^report_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logging.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
