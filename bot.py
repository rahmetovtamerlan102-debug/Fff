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

# BigBase
BIGBASE_TOKEN = os.getenv("BIGBASE_TOKEN")
BIGBASE_URL = "https://bigbase.top/api/search"

# NightSearch
NIGHTSEARCH_KEY = os.getenv("NIGHTSEARCH_KEY")
NIGHTSEARCH_URL = "https://nightsearch.life/api/search"

# Seon
SEON_TOKEN = os.getenv("SEON_TOKEN")
SEON_URL = "https://api.seon.io/SeonRestService/phone-api/v2"

# Snusbase
SNUSBASE_TOKEN = os.getenv("SNUSBASE_TOKEN")
SNUSBASE_URL = "https://api.snusbase.com/data/search"

# LeakOSINT
LEAKOSINT_TOKENS = []
LEAKOSINT_TOKEN_1 = os.getenv("LEAKOSINT_TOKEN_1")
LEAKOSINT_TOKEN_2 = os.getenv("LEAKOSINT_TOKEN_2")
LEAKOSINT_TOKEN_3 = os.getenv("LEAKOSINT_TOKEN_3")
if LEAKOSINT_TOKEN_1:
    LEAKOSINT_TOKENS.append(LEAKOSINT_TOKEN_1)
if LEAKOSINT_TOKEN_2:
    LEAKOSINT_TOKENS.append(LEAKOSINT_TOKEN_2)
if LEAKOSINT_TOKEN_3:
    LEAKOSINT_TOKENS.append(LEAKOSINT_TOKEN_3)
LEAKOSINT_BASE = "https://leakosintapi.com/"

# Funstat
FUNSTAT_TOKEN = os.getenv("FUNSTAT_TOKEN")
FUNSTAT_BASE = "https://telelog.info/api/v1"

# Канал для подписки
CHANNEL_USERNAME = "@cumoovwinrar"

PORT = int(os.getenv("PORT", 5000))
STATS_FILE = "search_stats.json"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN must be set in environment")

LANG = "ru"
TIMEOUT = 15
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

CURRENT_LEAK_INDEX = 0

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
        [InlineKeyboardButton("По ФИО", callback_data="name")],
        [InlineKeyboardButton("По телефону", callback_data="phone")],
        [InlineKeyboardButton("По СНИЛС", callback_data="snils")],
        [InlineKeyboardButton("По ИНН", callback_data="inn")],
        [InlineKeyboardButton("По паспорту", callback_data="passport")],
        [InlineKeyboardButton("По карте", callback_data="card")],
        [InlineKeyboardButton("По ID Telegram", callback_data="telegram_id")],
    ]
    return InlineKeyboardMarkup(buttons)

def get_subscribe_keyboard():
    buttons = [
        [InlineKeyboardButton("Подписаться на канал", url="https://t.me/cumoovwinrar")],
        [InlineKeyboardButton("Проверить подписку", callback_data="check_subscribe")],
    ]
    return InlineKeyboardMarkup(buttons)

# ========== ПРОВЕРКА ПОДПИСКИ ==========
async def is_subscribed(user_id, context):
    if not CHANNEL_USERNAME:
        return True
    
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False

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

# ========== BIGBASE API ==========
def bigbase_search(query):
    if not BIGBASE_TOKEN:
        return {"error": "BigBase токен не настроен"}
    
    clean_query = str(query).strip()
    if not clean_query:
        return {"error": "Пустой запрос"}

    headers = {
        "Authorization": BIGBASE_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "search": clean_query,
        "page": 0
    }

    try:
        resp = requests.post(BIGBASE_URL, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 429:
            return {"error": "Лимит запросов BigBase"}
        else:
            return {"error": f"BigBase ошибка {resp.status_code}"}
    except Exception as e:
        return {"error": f"BigBase: {str(e)}"}

# ========== NIGHTSEARCH API ==========
def nightsearch_search(query, search_type="phone"):
    if not NIGHTSEARCH_KEY:
        return {"error": "NightSearch ключ не настроен"}
    
    clean_query = str(query).strip()
    if not clean_query:
        return {"error": "Пустой запрос"}

    type_map = {
        "phone": "phone",
        "fio": "fio",
        "email": "email",
        "telegram_id": "tg",
        "vk": "vk",
        "ip": "ip",
        "snils": "snils",
        "inn": "inn",
        "car": "car",
        "ok": "ok",
        "fb": "fb"
    }
    night_type = type_map.get(search_type, "phone")

    headers = {
        "X-API-Key": NIGHTSEARCH_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "query": clean_query,
        "search_type": night_type
    }

    try:
        resp = requests.post(NIGHTSEARCH_URL, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 429:
            return {"error": "Лимит запросов NightSearch"}
        elif resp.status_code == 404:
            return {"error": "Данные не найдены"}
        else:
            return {"error": f"NightSearch ошибка {resp.status_code}"}
    except Exception as e:
        return {"error": f"NightSearch: {str(e)}"}

# ========== SEON API ==========
def seon_lookup(phone):
    if not SEON_TOKEN:
        return None
    
    clean_phone = re.sub(r'\D', '', str(phone))
    if not clean_phone or len(clean_phone) < 10:
        return None

    headers = {
        "X-API-KEY": SEON_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {"phone": clean_phone}

    try:
        resp = requests.post(SEON_URL, json=payload, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        else:
            return None
    except Exception as e:
        return None

# ========== SNUSBASE API ==========
def snusbase_search(query):
    if not SNUSBASE_TOKEN:
        return {"error": "Snusbase токен не настроен"}
    
    clean_query = str(query).strip()
    if not clean_query:
        return {"error": "Пустой запрос"}
    
    headers = {"Auth": SNUSBASE_TOKEN, "Content-Type": "application/json"}
    payload = {"terms": [clean_query], "types": ["email", "username"], "wildcard": False}
    
    try:
        resp = requests.post(SNUSBASE_URL, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 429:
            return {"error": "Лимит запросов Snusbase"}
        else:
            return {"error": f"Snusbase ошибка {resp.status_code}"}
    except Exception as e:
        return {"error": f"Snusbase: {str(e)}"}

# ========== LEAKOSINT API ==========
def check_leakosint_token(token):
    try:
        data = {"token": token, "request": "test", "limit": 10, "lang": "ru"}
        resp = requests.post(LEAKOSINT_BASE, json=data, timeout=10)
        if resp.status_code == 200 and "Error code" not in resp.json():
            return True
        return False
    except:
        return False

def get_working_leakosint_token():
    global CURRENT_LEAK_INDEX
    
    if not LEAKOSINT_TOKENS:
        return None
    
    for i in range(len(LEAKOSINT_TOKENS)):
        idx = (CURRENT_LEAK_INDEX + i) % len(LEAKOSINT_TOKENS)
        token = LEAKOSINT_TOKENS[idx]
        if check_leakosint_token(token):
            CURRENT_LEAK_INDEX = idx
            return token
    
    return LEAKOSINT_TOKENS[0] if LEAKOSINT_TOKENS else None

def leakosint_search(query, limit=200):
    if not query or len(query.strip()) < 1:
        return {"error": "Пустой запрос"}

    token = get_working_leakosint_token()
    if not token:
        return {"error": "Нет доступных токенов LeakOSINT"}

    data = {"token": token, "request": query.strip(), "limit": limit, "lang": "ru"}

    try:
        resp = requests.post(LEAKOSINT_BASE, json=data, timeout=30)
        if resp.status_code == 200:
            result = resp.json()
            if "Error code" in result:
                return {"error": f"LeakOSINT: {result['Error code']}"}
            return result
        elif resp.status_code == 400:
            return {"error": "LeakOSINT: ошибка запроса"}
        else:
            return {"error": f"LeakOSINT ошибка {resp.status_code}"}
    except Exception as e:
        return {"error": f"LeakOSINT: {str(e)}"}

# ========== FUNSTAT API ==========
def funstat_request(endpoint, params=None):
    if not FUNSTAT_TOKEN:
        return None
    url = f"{FUNSTAT_BASE}{endpoint}"
    try:
        resp = requests.get(
            url,
            headers={"accept": "application/json", "Authorization": f"Bearer {FUNSTAT_TOKEN}"},
            params=params,
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except:
        return None

def get_id_by_username(username):
    username = username.replace('@', '').strip()
    result = funstat_request("/users/resolve_username", params={"username": username})
    if result and result.get("success"):
        d = result.get("data", {})
        if isinstance(d, dict):
            return d.get('id')
        elif isinstance(d, list) and d:
            return d[0].get('id')
    return None

def get_user_id(identifier):
    if identifier.isdigit():
        return identifier
    if identifier.startswith('@'):
        identifier = identifier[1:]
    user_id = get_id_by_username(identifier)
    return user_id

def funstat_get_names(user_id):
    result = funstat_request(f"/users/{user_id}/names")
    if result and result.get("success") and result.get("data"):
        return result.get("data", [])
    return None

def funstat_get_usernames(user_id):
    result = funstat_request(f"/users/{user_id}/usernames")
    if result and result.get("success") and result.get("data"):
        return result.get("data", [])
    return None

def funstat_get_gifts(user_id):
    result = funstat_request(f"/users/{user_id}/gifts_relation")
    if result and result.get("success") and result.get("data"):
        return result.get("data", [])
    return None

def funstat_get_user_info(identifier):
    user_id = get_user_id(identifier)
    if not user_id:
        return None
    return {
        "names": funstat_get_names(user_id),
        "usernames": funstat_get_usernames(user_id),
        "gifts": funstat_get_gifts(user_id)
    }

# ========== DEPSEARCH ==========
def search_depsearch(query):
    if not DEP_TOKEN or not DEP_BASE:
        return {"error": "Depsearch не настроен"}
    
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
            return {"error": f"Depsearch ошибка {resp.status_code}"}
        return resp.json()
    except Exception as e:
        return {"error": f"Depsearch: {str(e)}"}

# ========== УНИВЕРСАЛЬНЫЙ ПОИСК ==========
def unified_search(query, search_type):
    result = {
        "depsearch": None,
        "bigbase": None,
        "nightsearch": None,
        "leakosint": None,
        "seon": None,
        "snusbase": None,
        "funstat": None,
        "phone_info": None,
        "search_type": search_type,
        "errors": []
    }
    
    def do_depsearch():
        return search_depsearch(query)
    
    def do_bigbase():
        return bigbase_search(query)
    
    def do_nightsearch():
        search_type_map = {
            "phone": "phone",
            "name": "fio",
            "telegram_id": "tg"
        }
        ns_type = search_type_map.get(search_type, "phone")
        return nightsearch_search(query, ns_type)
    
    def do_leakosint():
        return leakosint_search(query)
    
    def do_seon():
        if search_type == "phone":
            return seon_lookup(query)
        return None
    
    def do_snusbase():
        if search_type == "email":
            return snusbase_search(query)
        return None
    
    def do_funstat():
        if search_type == "telegram_id":
            clean_id = re.sub(r'\D', '', query)
            return funstat_get_user_info(clean_id)
        return None
    
    def do_dadata():
        if search_type == "phone":
            return dadata_lookup(query)
        return None
    
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = {
            "depsearch": executor.submit(do_depsearch),
            "bigbase": executor.submit(do_bigbase),
            "nightsearch": executor.submit(do_nightsearch),
            "leakosint": executor.submit(do_leakosint),
            "dadata": executor.submit(do_dadata),
        }
        
        if search_type == "phone":
            futures["seon"] = executor.submit(do_seon)
        if search_type == "email":
            futures["snusbase"] = executor.submit(do_snusbase)
        if search_type == "telegram_id":
            futures["funstat"] = executor.submit(do_funstat)
        
        for name, future in futures.items():
            try:
                res = future.result(timeout=TIMEOUT + 5)
                if name == "dadata" and res:
                    result["phone_info"] = res
                elif name in result:
                    if isinstance(res, dict) and "error" in res:
                        if name in ["leakosint", "seon"]:
                            if "ошибка" in res.get("error", "").lower() or not res.get("error"):
                                continue
                        result["errors"].append(f"{name}: {res['error']}")
                    else:
                        result[name] = res
            except Exception as e:
                result["errors"].append(f"{name}: {str(e)}")
    
    return result

# ========== ФОРМАТИРОВАНИЕ КРАТКОГО ОТВЕТА ==========
def extract_personal_data(bigbase_data, nightsearch_data):
    """Извлекает ФИО, дату рождения и возраст из данных"""
    personal = {
        "fio": None,
        "birth_date": None,
        "age": None
    }
    
    # Ищем в NightSearch
    if nightsearch_data and isinstance(nightsearch_data, dict):
        results = nightsearch_data.get("results", [])
        for result in results:
            fields = result.get("fields", [])
            for field in fields:
                key = field.get("key", "").lower()
                value = field.get("value", "")
                if not value:
                    continue
                if "фио" in key or "фис" in key or "fio" in key or "full_name" in key:
                    personal["fio"] = value
                elif "дата рождения" in key or "birth_date" in key or "bdate" in key:
                    personal["birth_date"] = value
                elif "возраст" in key or "age" in key:
                    personal["age"] = value
    
    # Ищем в BigBase
    if bigbase_data and isinstance(bigbase_data, dict):
        records = bigbase_data.get("records", [])
        for record in records:
            base_record = record.get("base_record", [])
            for item in base_record:
                if isinstance(item, list) and len(item) >= 2:
                    key = item[0].lower()
                    value = item[1]
                    if not value:
                        continue
                    if "фио" in key or "фис" in key or "fio" in key or "full_name" in key:
                        if not personal["fio"]:
                            personal["fio"] = value
                    elif "дата рождения" in key or "birth_date" in key or "bdate" in key:
                        if not personal["birth_date"]:
                            personal["birth_date"] = value
                    elif "возраст" in key or "age" in key:
                        if not personal["age"]:
                            personal["age"] = value
    
    # Если дата рождения найдена, но возраст не найден — вычисляем
    if personal["birth_date"] and not personal["age"]:
        try:
            # Парсим дату
            date_str = personal["birth_date"]
            # Пробуем разные форматы
            for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%Y.%m.%d"]:
                try:
                    birth_date = datetime.strptime(date_str.strip(), fmt)
                    today = datetime.now()
                    age = today.year - birth_date.year
                    if (today.month, today.day) < (birth_date.month, birth_date.day):
                        age -= 1
                    personal["age"] = str(age)
                    break
                except:
                    continue
        except:
            pass
    
    return personal

def format_bigbase_short(data):
    lines = []
    if not data or data.get("success") != "ok":
        return lines
    
    dossier = data.get("dossier", {})
    if dossier:
        head = dossier.get("head", {})
        if head.get("phone_operator"):
            lines.append(f"├ Оператор: {head.get('phone_operator')}")
        if head.get("phone_region"):
            lines.append(f"├ Регион: {head.get('phone_region')}")
        if head.get("phone_country_info"):
            lines.append(f"├ Страна: {head.get('phone_country_info')}")
    
    records = data.get("records", [])
    for record in records[:5]:
        base_record = record.get("base_record", [])
        if base_record:
            line_parts = []
            for item in base_record[:3]:
                if isinstance(item, list) and len(item) >= 2:
                    line_parts.append(f"{item[0]}: {item[1]}")
            if line_parts:
                lines.append(f"├ {' | '.join(line_parts)}")
    
    return lines

def format_nightsearch_short(data):
    lines = []
    if not data or data.get("status") != "success":
        return lines
    
    results = data.get("results", [])
    seen = set()
    for result in results[:10]:
        fields = result.get("fields", [])
        for field in fields[:3]:
            key = field.get("key")
            value = field.get("value")
            if key and value:
                item = f"{key}: {value}"
                if item not in seen:
                    lines.append(f"├ {item}")
                    seen.add(item)
            elif value:
                if value not in seen:
                    lines.append(f"├ {value}")
                    seen.add(value)
    
    return lines

def format_leakosint_short(data):
    lines = []
    if not data or "List" not in data:
        return lines
    
    for db_name, db_data in data["List"].items():
        if db_name == "No results found":
            continue
        for item in db_data.get("Data", [])[:5]:
            for key, value in item.items():
                if value and key not in ['_domain']:
                    lines.append(f"├ {key}: {value}")
                break
            break
    
    return lines

def format_seon_short(data):
    lines = []
    if not data:
        return lines
    
    cnam = data.get("cnam_details", {})
    if cnam and cnam.get("name"):
        lines.append(f"├ Владелец: {cnam.get('name')}")
    
    score = data.get("score")
    if score is not None:
        lines.append(f"├ Риск: {score}")
    
    email = data.get("email")
    if email:
        lines.append(f"├ Email: {email}")
    
    social = data.get("social_media", [])
    if social:
        for platform, info in social.items():
            if info and isinstance(info, dict):
                url = info.get("url")
                if url:
                    lines.append(f"├ {platform}: {url}")
    
    return lines

def format_snusbase_short(data):
    lines = []
    if not data or "results" not in data:
        return lines
    
    for db_name, records in data.get("results", {}).items():
        if not records:
            continue
        for record in records[:2]:
            for key, value in record.items():
                if value and key not in ['_domain']:
                    lines.append(f"├ {key}: {value}")
                    break
            break
    
    return lines

def format_funstat_short(data):
    lines = []
    if not data:
        return lines
    
    if "names" in data and data["names"]:
        names = data["names"]
        if isinstance(names, list) and names:
            name_str = ", ".join([n.get('name', '') for n in names[:3] if n.get('name')])
            if name_str:
                lines.append(f"├ Имена: {name_str}")
    
    if "usernames" in data and data["usernames"]:
        usernames = data["usernames"]
        if isinstance(usernames, list) and usernames:
            username_str = ", ".join([u.get('name', '') for u in usernames[:3] if u.get('name')])
            if username_str:
                lines.append(f"├ Username: {username_str}")
    
    return lines

def format_short(data, query, stats_count, search_type):
    lines = []
    
    # Проверяем подписку (для Telegram)
    # Эта часть вызывается из обработчика, поэтому подписка проверяется отдельно
    
    if search_type == "phone":
        clean_phone = re.sub(r'\D', '', query)
        lines.append(f"Телефон: +{clean_phone}")
        
        # Оператор, регион, страна из DaData или BigBase
        phone_info = data.get("phone_info")
        if phone_info:
            operator = phone_info.get("operator")
            region = phone_info.get("region") or phone_info.get("region_with_type")
            country = phone_info.get("country") or phone_info.get("country_iso_code")
            if operator:
                lines.append(f"├ Оператор: {operator}")
            if region:
                lines.append(f"├ Регион: {region}")
            if country:
                lines.append(f"├ Страна: {country}")
        else:
            # Если DaData не дал данных, пробуем взять из BigBase
            bigbase_data = data.get("bigbase")
            if bigbase_data and isinstance(bigbase_data, dict):
                dossier = bigbase_data.get("dossier", {})
                head = dossier.get("head", {})
                if head.get("phone_operator"):
                    lines.append(f"├ Оператор: {head.get('phone_operator')}")
                if head.get("phone_region"):
                    lines.append(f"├ Регион: {head.get('phone_region')}")
                if head.get("phone_country_info"):
                    lines.append(f"├ Страна: {head.get('phone_country_info')}")
        
        # Личные данные из NightSearch и BigBase
        personal = extract_personal_data(data.get("bigbase"), data.get("nightsearch"))
        if personal["fio"]:
            lines.append(f"├ ФИО: {personal['fio']}")
        if personal["birth_date"]:
            lines.append(f"├ Дата рождения: {personal['birth_date']}")
        if personal["age"]:
            lines.append(f"└ Возраст: {personal['age']} лет")
        elif personal["birth_date"]:
            # Если возраст не определился, но дата есть, считаем
            try:
                # Пробуем разные форматы
                for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%Y.%m.%d"]:
                    try:
                        birth_date = datetime.strptime(personal["birth_date"].strip(), fmt)
                        today = datetime.now()
                        age = today.year - birth_date.year
                        if (today.month, today.day) < (birth_date.month, birth_date.day):
                            age -= 1
                        lines.append(f"└ Возраст: {age} лет")
                        break
                    except:
                        continue
            except:
                pass
    
    elif search_type == "telegram_id":
        clean_id = re.sub(r'\D', '', query)
        lines.append(f"ID Telegram: {clean_id}")
    else:
        lines.append(f"Запрос: {query}")
    
    # BigBase (дополнительные данные, если они не были показаны)
    bigbase_data = data.get("bigbase")
    if bigbase_data and isinstance(bigbase_data, dict):
        bb_lines = format_bigbase_short(bigbase_data)
        if bb_lines:
            lines.append("")
            lines.append("BigBase:")
            lines.extend(bb_lines)
    
    # NightSearch (дополнительные данные, если они не были показаны)
    nightsearch_data = data.get("nightsearch")
    if nightsearch_data and isinstance(nightsearch_data, dict):
        ns_lines = format_nightsearch_short(nightsearch_data)
        if ns_lines:
            lines.append("")
            lines.append("NightSearch:")
            lines.extend(ns_lines)
    
    # LeakOSINT
    leak_data = data.get("leakosint")
    if leak_data and isinstance(leak_data, dict):
        leak_lines = format_leakosint_short(leak_data)
        if leak_lines:
            lines.append("")
            lines.append("LeakOSINT:")
            lines.extend(leak_lines)
    
    # Seon
    seon_data = data.get("seon")
    if seon_data and isinstance(seon_data, dict):
        seon_lines = format_seon_short(seon_data)
        if seon_lines:
            lines.append("")
            lines.append("Seon:")
            lines.extend(seon_lines)
    
    # Snusbase
    snusbase_data = data.get("snusbase")
    if snusbase_data and isinstance(snusbase_data, dict):
        snus_lines = format_snusbase_short(snusbase_data)
        if snus_lines:
            lines.append("")
            lines.append("Snusbase:")
            lines.extend(snus_lines)
    
    # Depsearch
    dep_data = data.get("depsearch", {})
    if dep_data and isinstance(dep_data, dict):
        results = dep_data.get("results", [])
        if results and len(results) > 0:
            lines.append("")
            lines.append(f"Depsearch: {len(results)} записей")
    
    # Funstat
    funstat_data = data.get("funstat")
    if funstat_data and isinstance(funstat_data, dict):
        fs_lines = format_funstat_short(funstat_data)
        if fs_lines:
            lines.append("")
            lines.append("Funstat:")
            lines.extend(fs_lines)
    
    # Статистика запросов
    if stats_count and stats_count > 0:
        lines.append("")
        lines.append(f"Интересовались этим: {stats_count} раз")
    
    # Ошибки (только если они не пустые и не от leakosint/seon)
    errors = []
    for err in data.get("errors", []):
        if "leakosint" in err.lower() and "ошибка" in err.lower():
            continue
        if "seon" in err.lower() and "{}" in err:
            continue
        if err and err.strip():
            errors.append(err)
    
    if errors:
        lines.append("")
        for err in errors[:2]:
            lines.append(f"Ошибка: {err}")
    
    return "\n".join(lines)

# ========== ГЕНЕРАЦИЯ HTML-ОТЧЁТА ==========
def generate_html(data, search_type, query):
    dep_data = data.get("depsearch", {})
    phone_info = data.get("phone_info")
    bigbase_data = data.get("bigbase")
    nightsearch_data = data.get("nightsearch")
    leakosint_data = data.get("leakosint")
    seon_data = data.get("seon")
    snusbase_data = data.get("snusbase")
    funstat_data = data.get("funstat")
    
    results = dep_data.get("results", []) if isinstance(dep_data, dict) else []
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_sources = 0
    sources_with_data = 0
    
    if phone_info:
        total_sources += 1
        sources_with_data += 1
    if results:
        total_sources += 1
        sources_with_data += 1
    if bigbase_data and bigbase_data.get("success") == "ok":
        total_sources += 1
        sources_with_data += 1
    if nightsearch_data and nightsearch_data.get("status") == "success":
        total_sources += 1
        sources_with_data += 1
    if leakosint_data and "List" in leakosint_data:
        total_sources += 1
        sources_with_data += 1
    if seon_data:
        total_sources += 1
        sources_with_data += 1
    if snusbase_data and "results" in snusbase_data:
        total_sources += 1
        sources_with_data += 1
    if funstat_data:
        total_sources += 1
        sources_with_data += 1
    
    total_sources = max(total_sources, 1)
    accuracy = min(100, max(0, int((sources_with_data / total_sources) * 100)))

    emoji_map = {
        'phone': '📞', 'birth_date': '🎂', 'full_name': '👤', 'name': '👤',
        'fio': '👤', 'email': '📧', 'passport': '📇', 'inn': '🆔',
        'snils': '🆔', 'card': '💳', 'address': '📍', 'city': '🏙️',
        'country': '🌍', 'operator': '📡', 'gender': '⚤', 'username': '👤',
        'telegram_id': '🆔', 'vk': '💙', 'ok': '💛'
    }

    cards_html = ""
    source_counter = 1
    
    # BigBase
    if bigbase_data and bigbase_data.get("success") == "ok":
        rows = ""
        dossier = bigbase_data.get("dossier", {})
        if dossier:
            head = dossier.get("head", {})
            for k, v in head.items():
                if v:
                    emoji = emoji_map.get(k.lower(), '')
                    display_key = f"{emoji} {k}" if emoji else k
                    rows += f'<div class="row"><span class="key">{display_key}</span><span class="val">{v}</span></div>'
        
        records = bigbase_data.get("records", [])
        for record in records[:5]:
            base_record = record.get("base_record", [])
            for item in base_record[:3]:
                if isinstance(item, list) and len(item) >= 2:
                    emoji = emoji_map.get(item[0].lower(), '')
                    display_key = f"{emoji} {item[0]}" if emoji else item[0]
                    rows += f'<div class="row"><span class="key">{display_key}</span><span class="val">{item[1]}</span></div>'
        
        if rows:
            cards_html += f'''
            <div class="card">
                <div class="card-head">
                    <span class="card-name">BigBase #{source_counter}</span>
                    <div class="card-badges">
                        <span class="badge green">ДАННЫЕ</span>
                    </div>
                </div>
                <div class="card-body">
                    <div class="data-block">{rows}</div>
                </div>
                <div class="card-foot"><div class="card-foot-bar" style="width:{accuracy}%;background:#8b5cf6"></div></div>
            </div>
            '''
            source_counter += 1
    
    # NightSearch
    if nightsearch_data and nightsearch_data.get("status") == "success":
        rows = ""
        seen = set()
        for result in nightsearch_data.get("results", [])[:10]:
            fields = result.get("fields", [])
            for field in fields[:4]:
                key = field.get("key")
                value = field.get("value")
                if key and value:
                    item = f"{key}: {value}"
                    if item not in seen:
                        emoji = emoji_map.get(key.lower(), '')
                        display_key = f"{emoji} {key}" if emoji else key
                        rows += f'<div class="row"><span class="key">{display_key}</span><span class="val">{value}</span></div>'
                        seen.add(item)
                elif value and value not in seen:
                    rows += f'<div class="row"><span class="key"></span><span class="val">{value}</span></div>'
                    seen.add(value)
        
        if rows:
            cards_html += f'''
            <div class="card">
                <div class="card-head">
                    <span class="card-name">NightSearch #{source_counter}</span>
                    <div class="card-badges">
                        <span class="badge green">ДАННЫЕ</span>
                    </div>
                </div>
                <div class="card-body">
                    <div class="data-block">{rows}</div>
                </div>
                <div class="card-foot"><div class="card-foot-bar" style="width:{accuracy}%;background:#10b981"></div></div>
            </div>
            '''
            source_counter += 1
    
    # LeakOSINT
    if leakosint_data and "List" in leakosint_data:
        rows = ""
        for db_name, db_data in leakosint_data["List"].items():
            if db_name == "No results found":
                continue
            for item in db_data.get("Data", [])[:3]:
                for key, value in item.items():
                    if value and key not in ['_domain']:
                        emoji = emoji_map.get(key.lower(), '')
                        display_key = f"{emoji} {key}" if emoji else key
                        rows += f'<div class="row"><span class="key">{display_key}</span><span class="val">{value}</span></div>'
        
        if rows:
            cards_html += f'''
            <div class="card">
                <div class="card-head">
                    <span class="card-name">LeakOSINT #{source_counter}</span>
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
            source_counter += 1
    
    # Seon
    if seon_data:
        rows = ""
        cnam = seon_data.get("cnam_details", {})
        if cnam and cnam.get("name"):
            rows += f'<div class="row"><span class="key">👤 Владелец</span><span class="val">{cnam.get("name")}</span></div>'
        
        score = seon_data.get("score")
        if score is not None:
            rows += f'<div class="row"><span class="key">📊 Риск</span><span class="val">{score}</span></div>'
        
        email = seon_data.get("email")
        if email:
            rows += f'<div class="row"><span class="key">📧 Email</span><span class="val">{email}</span></div>'
        
        social = seon_data.get("social_media", [])
        if social:
            for platform, info in social.items():
                if info and isinstance(info, dict):
                    url = info.get("url")
                    if url:
                        emoji = emoji_map.get(platform.lower(), '')
                        display_key = f"{emoji} {platform}" if emoji else platform
                        rows += f'<div class="row"><span class="key">{display_key}</span><span class="val"><a href="{url}" target="_blank">{url}</a></span></div>'
        
        if rows:
            cards_html += f'''
            <div class="card">
                <div class="card-head">
                    <span class="card-name">Seon #{source_counter}</span>
                    <div class="card-badges">
                        <span class="badge green">ДАННЫЕ</span>
                    </div>
                </div>
                <div class="card-body">
                    <div class="data-block">{rows}</div>
                </div>
                <div class="card-foot"><div class="card-foot-bar" style="width:{accuracy}%;background:#ec4899"></div></div>
            </div>
            '''
            source_counter += 1
    
    # Snusbase
    if snusbase_data and "results" in snusbase_data:
        rows = ""
        for db_name, records in snusbase_data.get("results", {}).items():
            if not records:
                continue
            for record in records[:3]:
                for key, value in record.items():
                    if value and key not in ['_domain']:
                        emoji = emoji_map.get(key.lower(), '')
                        display_key = f"{emoji} {key}" if emoji else key
                        rows += f'<div class="row"><span class="key">{display_key}</span><span class="val">{value}</span></div>'
        
        if rows:
            cards_html += f'''
            <div class="card">
                <div class="card-head">
                    <span class="card-name">Snusbase #{source_counter}</span>
                    <div class="card-badges">
                        <span class="badge green">ДАННЫЕ</span>
                    </div>
                </div>
                <div class="card-body">
                    <div class="data-block">{rows}</div>
                </div>
                <div class="card-foot"><div class="card-foot-bar" style="width:{accuracy}%;background:#f43f5e"></div></div>
            </div>
            '''
            source_counter += 1
    
    # Funstat
    if funstat_data:
        rows = ""
        if "names" in funstat_data and funstat_data["names"]:
            names = funstat_data["names"]
            if isinstance(names, list) and names:
                name_str = ", ".join([n.get('name', '') for n in names[:5] if n.get('name')])
                if name_str:
                    rows += f'<div class="row"><span class="key">👤 Имена</span><span class="val">{name_str}</span></div>'
        
        if "usernames" in funstat_data and funstat_data["usernames"]:
            usernames = funstat_data["usernames"]
            if isinstance(usernames, list) and usernames:
                username_str = ", ".join([u.get('name', '') for u in usernames[:5] if u.get('name')])
                if username_str:
                    rows += f'<div class="row"><span class="key">👤 Username</span><span class="val">{username_str}</span></div>'
        
        if "gifts" in funstat_data and funstat_data["gifts"]:
            gifts = funstat_data["gifts"]
            if isinstance(gifts, list) and gifts:
                gift_str = ", ".join([g.get('from_first_name', '') for g in gifts[:3] if g.get('from_first_name')])
                if gift_str:
                    rows += f'<div class="row"><span class="key">🎁 Подарки</span><span class="val">{gift_str}</span></div>'
        
        if rows:
            cards_html += f'''
            <div class="card">
                <div class="card-head">
                    <span class="card-name">Funstat #{source_counter}</span>
                    <div class="card-badges">
                        <span class="badge green">ДАННЫЕ</span>
                    </div>
                </div>
                <div class="card-body">
                    <div class="data-block">{rows}</div>
                </div>
                <div class="card-foot"><div class="card-foot-bar" style="width:{accuracy}%;background:#14b8a6"></div></div>
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

    # Phone info (DaData)
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
    user_id = update.effective_user.id
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(
            "Для использования бота подпишитесь на канал:",
            reply_markup=get_subscribe_keyboard()
        )
        return
    
    await update.message.reply_text(
        "Приветствую! Это бот Кумова.\n\n"
        "Тут ты сможешь найти информацию о своей жертве.\n\n"
        "Выберите тип поиска на клавиатуре:",
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
    
    if query.data == "check_subscribe":
        user_id = query.from_user.id
        if await is_subscribed(user_id, context):
            await query.edit_message_text(
                "Подписка подтверждена! Выберите тип поиска:",
                reply_markup=get_keyboard()
            )
        else:
            await query.edit_message_text(
                "Вы не подписаны на канал. Подпишитесь и нажмите 'Проверить подписку' снова.",
                reply_markup=get_subscribe_keyboard()
            )
        return
    
    search_type = query.data
    context.user_data['search_type'] = search_type
    
    examples = {
        'name': 'Введите ФИО для поиска\n\nПример: Иванов Иван Иванович',
        'phone': 'Введите номер телефона для поиска\n\nПример: 79271234567',
        'snils': 'Введите СНИЛС для поиска\n\nПример: 123-456-789-01',
        'inn': 'Введите ИНН для поиска\n\nПример: 784806113663',
        'passport': 'Введите паспорт для поиска\n\nПример: 4516 123456',
        'card': 'Введите номер карты для поиска\n\nПример: 5337361874187412',
        'telegram_id': 'Введите ID Telegram для поиска\n\nПример: 123456789'
    }
    
    await query.edit_message_text(
        f"Выбран поиск по {type_names.get(search_type, search_type)}\n\n"
        f"{examples.get(search_type, 'Отправьте данные для поиска.')}",
        parse_mode="Markdown"
    )

async def handle_message(update, context):
    user_id = update.effective_user.id
    
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(
            "Для использования бота подпишитесь на канал:",
            reply_markup=get_subscribe_keyboard()
        )
        return
    
    text = update.message.text.strip()
    if not text:
        return
    
    search_type = context.user_data.get('search_type')
    
    if not search_type:
        await update.message.reply_text(
            "Сначала выберите тип поиска!\n\n"
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
    
    msg = await update.message.reply_text("Поиск...")
    
    data = unified_search(q, search_type)
    
    short = format_short(data, text, stats_count, search_type)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Полный отчёт", callback_data=f"report_{search_type}_{text}")]
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
            "Данные устарели. Отправьте запрос заново.",
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
                caption=f"Полный отчёт по запросу: {text}"
            )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

async def help_command(update, context):
    user_id = update.effective_user.id
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(
            "Для использования бота подпишитесь на канал:",
            reply_markup=get_subscribe_keyboard()
        )
        return
    
    await update.message.reply_text(
        "Помощь\n\n"
        "1. Нажмите на кнопку с нужным типом поиска\n"
        "2. Отправьте данные для поиска\n"
        "3. Получите краткий отчёт с кнопкой 'Полный отчёт'\n\n"
        "Примеры данных:\n"
        "  ФИО: Иванов Иван Иванович\n"
        "  Телефон: 79271234567\n"
        "  СНИЛС: 123-456-789-01\n"
        "  ИНН: 784806113663\n"
        "  Паспорт: 4516 123456\n"
        "  Карта: 5337361874187412\n"
        "  ID Telegram: 123456789",
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
