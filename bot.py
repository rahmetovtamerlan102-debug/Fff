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

# ============================================================
# ЖЁСТКО ЗАДАННЫЕ ПАРАМЕТРЫ – ИСПРАВЛЯЮТ РЕФЕРАЛЬНУЮ ССЫЛКУ
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = "osintJit1_bot"  # <- ПРАВИЛЬНОЕ ИМЯ С ПОДЧЁРКИВАНИЕМ

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
REFFERAL_FILE = "refferal_stats.json"
FREE_SEARCHES_FILE = "free_searches.json"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN must be set in environment")

LANG = "ru"
TIMEOUT = 10
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

CURRENT_LEAK_INDEX = 0

# ========== РЕФЕРАЛЬНАЯ СИСТЕМА ==========
def load_refferals():
    try:
        with open(REFFERAL_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_refferals(data):
    with open(REFFERAL_FILE, "w") as f:
        json.dump(data, f, indent=2)

def add_refferal(user_id, referrer_id):
    data = load_refferals()
    user_id = str(user_id)
    referrer_id = str(referrer_id)
    if user_id == referrer_id:
        logging.info(f"Реферал отклонён: пользователь {user_id} пригласил сам себя")
        return False
    if user_id in data:
        logging.info(f"Реферал {user_id} уже зарегистрирован")
        return False
    data[user_id] = {"referrer": referrer_id, "date": datetime.now().isoformat()}
    save_refferals(data)
    add_free_search(referrer_id)
    logging.info(f"Новый реферал: user={user_id}, referrer={referrer_id}")
    return True

def get_refferals_count(user_id):
    data = load_refferals()
    count = 0
    for uid, info in data.items():
        if info.get("referrer") == str(user_id):
            count += 1
    return count

def load_free_searches():
    try:
        with open(FREE_SEARCHES_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_free_searches(data):
    with open(FREE_SEARCHES_FILE, "w") as f:
        json.dump(data, f, indent=2)

def add_free_search(user_id, count=1):
    data = load_free_searches()
    user_id = str(user_id)
    data[user_id] = data.get(user_id, 0) + count
    save_free_searches(data)

def get_free_searches(user_id):
    data = load_free_searches()
    return data.get(str(user_id), 0)

def use_free_search(user_id):
    data = load_free_searches()
    user_id = str(user_id)
    if data.get(user_id, 0) > 0:
        data[user_id] -= 1
        save_free_searches(data)
        return True
    return False

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
def get_main_keyboard():
    buttons = [
        [InlineKeyboardButton("Поиск по неполным данным", callback_data="search_partial")],
        [InlineKeyboardButton("Примеры использования", callback_data="examples")],
        [InlineKeyboardButton("Мой аккаунт", callback_data="account")],
        [InlineKeyboardButton("Партнёрская программа", callback_data="refferal")],
    ]
    return InlineKeyboardMarkup(buttons)

def get_partial_search_keyboard():
    buttons = [
        [
            InlineKeyboardButton("Фамилия", callback_data="partial_lastname"),
            InlineKeyboardButton("Имя", callback_data="partial_firstname"),
            InlineKeyboardButton("Отчество", callback_data="partial_middlename"),
        ],
        [
            InlineKeyboardButton("День", callback_data="partial_day"),
            InlineKeyboardButton("Месяц", callback_data="partial_month"),
            InlineKeyboardButton("Год", callback_data="partial_year"),
        ],
        [
            InlineKeyboardButton("Возраст от", callback_data="partial_age_from"),
            InlineKeyboardButton("Возраст до", callback_data="partial_age_to"),
        ],
        [
            InlineKeyboardButton("Место рождения", callback_data="partial_birthplace"),
            InlineKeyboardButton("Страна", callback_data="partial_country"),
        ],
        [
            InlineKeyboardButton("Сбросить", callback_data="partial_reset"),
            InlineKeyboardButton("Искать", callback_data="partial_search"),
        ],
        [
            InlineKeyboardButton("Назад", callback_data="back_main"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)

def get_country_keyboard():
    buttons = [
        [InlineKeyboardButton("Россия", callback_data="country_russia")],
        [InlineKeyboardButton("Казахстан", callback_data="country_kazakhstan")],
        [InlineKeyboardButton("Беларусь", callback_data="country_belarus")],
        [InlineKeyboardButton("Украина", callback_data="country_ukraine")],
        [InlineKeyboardButton("Назад", callback_data="partial_back")],
    ]
    return InlineKeyboardMarkup(buttons)

def get_back_keyboard():
    buttons = [
        [InlineKeyboardButton("Назад", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(buttons)

def get_partial_back_keyboard():
    buttons = [
        [InlineKeyboardButton("Назад", callback_data="partial_back")],
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
    headers = {"Authorization": BIGBASE_TOKEN, "Content-Type": "application/json"}
    payload = {"search": clean_query, "page": 0}
    try:
        resp = requests.post(BIGBASE_URL, json=payload, headers=headers, timeout=8)
        if resp.status_code == 200:
            return resp.json()
        else:
            return None
    except Exception as e:
        return None

# ========== NIGHTSEARCH API ==========
def nightsearch_search(query, search_type="phone"):
    if not NIGHTSEARCH_KEY:
        return {"error": "NightSearch ключ не настроен"}
    clean_query = str(query).strip()
    if not clean_query:
        return {"error": "Пустой запрос"}
    type_map = {
        "phone": "phone", "name": "fio", "email": "email",
        "telegram_id": "tg", "vk": "vk", "ip": "ip",
        "snils": "snils", "inn": "inn", "car": "car",
        "ok": "ok", "fb": "fb"
    }
    night_type = type_map.get(search_type, "phone")
    headers = {"X-API-Key": NIGHTSEARCH_KEY, "Content-Type": "application/json"}
    payload = {"query": clean_query, "search_type": night_type}
    try:
        resp = requests.post(NIGHTSEARCH_URL, json=payload, headers=headers, timeout=8)
        if resp.status_code == 200:
            return resp.json()
        else:
            return None
    except Exception as e:
        return None

# ========== SEON API ==========
def seon_lookup(phone):
    if not SEON_TOKEN:
        return None
    clean_phone = re.sub(r'\D', '', str(phone))
    if not clean_phone or len(clean_phone) < 10:
        return None
    headers = {"X-API-KEY": SEON_TOKEN, "Content-Type": "application/json"}
    payload = {"phone": clean_phone}
    try:
        resp = requests.post(SEON_URL, json=payload, headers=headers, timeout=8)
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
        resp = requests.post(SNUSBASE_URL, json=payload, headers=headers, timeout=8)
        if resp.status_code == 200:
            return resp.json()
        else:
            return None
    except Exception as e:
        return None

# ========== LEAKOSINT API ==========
def check_leakosint_token(token):
    try:
        data = {"token": token, "request": "test", "limit": 10, "lang": "ru"}
        resp = requests.post(LEAKOSINT_BASE, json=data, timeout=8)
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
        resp = requests.post(LEAKOSINT_BASE, json=data, timeout=8)
        if resp.status_code == 200:
            result = resp.json()
            if "Error code" in result:
                if "not enough money" in result.get("Error code", "").lower():
                    return None
                return {"error": f"LeakOSINT: {result['Error code']}"}
            return result
        else:
            return None
    except Exception as e:
        return None

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
            timeout=8
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
        resp = requests.get(url, headers=headers, timeout=8)
        if "text/html" in resp.headers.get("content-type", ""):
            return None
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        return None

# ========== УНИВЕРСАЛЬНЫЙ ПОИСК ==========
def unified_search(query, search_type):
    result = {
        "depsearch": None, "bigbase": None, "nightsearch": None,
        "leakosint": None, "seon": None, "snusbase": None,
        "funstat": None, "phone_info": None,
        "search_type": search_type, "errors": []
    }
    def do_depsearch(): return search_depsearch(query)
    def do_bigbase(): return bigbase_search(query)
    def do_nightsearch():
        type_map = {"phone":"phone","name":"fio","email":"email","telegram_id":"tg","vk":"vk","ip":"ip","snils":"snils","inn":"inn","car":"car","ok":"ok"}
        ns_type = type_map.get(search_type, "phone")
        return nightsearch_search(query, ns_type)
    def do_leakosint(): return leakosint_search(query)
    def do_seon():
        if search_type == "phone": return seon_lookup(query)
        return None
    def do_snusbase():
        if search_type == "email": return snusbase_search(query)
        return None
    def do_funstat():
        if search_type == "telegram_id":
            clean_id = re.sub(r'\D', '', query)
            return funstat_get_user_info(clean_id)
        return None
    def do_dadata():
        if search_type == "phone": return dadata_lookup(query)
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
                res = future.result(timeout=15)
                if name == "dadata" and res:
                    result["phone_info"] = res
                elif name in result:
                    if isinstance(res, dict) and "error" in res:
                        result["errors"].append(f"{name}: {res['error']}")
                    else:
                        result[name] = res
            except Exception as e:
                result["errors"].append(f"{name}: {str(e)}")
    return result

# ========== ФОРМАТИРОВАНИЕ КРАТКОГО ОТВЕТА ==========
def extract_personal_data(bigbase_data, nightsearch_data):
    personal = {"fio": None, "birth_date": None, "age": None}
    if nightsearch_data and isinstance(nightsearch_data, dict):
        for res in nightsearch_data.get("results", []):
            for field in res.get("fields", []):
                key = field.get("key", "").lower()
                val = field.get("value", "")
                if not val: continue
                if "фио" in key or "фис" in key or "fio" in key or "full_name" in key:
                    personal["fio"] = val
                elif "дата рождения" in key or "birth_date" in key or "bdate" in key:
                    personal["birth_date"] = val
                elif "возраст" in key or "age" in key:
                    personal["age"] = val
    if bigbase_data and isinstance(bigbase_data, dict):
        for rec in bigbase_data.get("records", []):
            for item in rec.get("base_record", []):
                if isinstance(item, list) and len(item) >= 2:
                    key = item[0].lower()
                    val = item[1]
                    if not val: continue
                    if "фио" in key or "фис" in key or "fio" in key or "full_name" in key:
                        if not personal["fio"]: personal["fio"] = val
                    elif "дата рождения" in key or "birth_date" in key or "bdate" in key:
                        if not personal["birth_date"]: personal["birth_date"] = val
                    elif "возраст" in key or "age" in key:
                        if not personal["age"]: personal["age"] = val
    if personal["birth_date"] and not personal["age"]:
        try:
            for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%Y.%m.%d"]:
                try:
                    bd = datetime.strptime(personal["birth_date"].strip(), fmt)
                    today = datetime.now()
                    age = today.year - bd.year
                    if (today.month, today.day) < (bd.month, bd.day): age -= 1
                    personal["age"] = str(age)
                    break
                except: continue
        except: pass
    return personal

def format_bigbase_short(data):
    if not data or data.get("success") != "ok": return 0
    return len(data.get("records", []))

def format_nightsearch_count(data):
    if not data or data.get("status") != "success": return 0
    return len(data.get("results", []))

def format_leakosint_count(data):
    if not data or "List" not in data: return 0
    count = 0
    for db_name, db_data in data["List"].items():
        if db_name != "No results found":
            count += len(db_data.get("Data", []))
    return count

def format_short(data, query, stats_count, search_type):
    lines = []
    if search_type == "phone":
        clean_phone = re.sub(r'\D', '', query)
        lines.append(f"Телефон: +{clean_phone}")
        operator = region = country = None
        phone_info = data.get("phone_info")
        if phone_info:
            operator = phone_info.get("operator")
            region = phone_info.get("region") or phone_info.get("region_with_type")
            country = phone_info.get("country") or phone_info.get("country_iso_code")
        if not operator or not region or not country:
            bigbase_data = data.get("bigbase")
            if bigbase_data and isinstance(bigbase_data, dict):
                head = bigbase_data.get("dossier", {}).get("head", {})
                if not operator: operator = head.get("phone_operator")
                if not region: region = head.get("phone_region")
                if not country: country = head.get("phone_country_info")
        if operator: lines.append(f"├ Оператор: {operator}")
        if region: lines.append(f"├ Регион: {region}")
        if country: lines.append(f"├ Страна: {country}")
        personal = extract_personal_data(data.get("bigbase"), data.get("nightsearch"))
        if personal["fio"] or personal["birth_date"] or personal["age"]:
            lines.append(""); lines.append("Личные данные")
            if personal["fio"]: lines.append(f"├ ФИО: {personal['fio']}")
            if personal["birth_date"]: lines.append(f"├ Дата рождения: {personal['birth_date']}")
            if personal["age"]: lines.append(f"└ Возраст: {personal['age']} лет")
            elif personal["birth_date"]:
                try:
                    for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%Y.%m.%d"]:
                        try:
                            bd = datetime.strptime(personal["birth_date"].strip(), fmt)
                            today = datetime.now()
                            age = today.year - bd.year
                            if (today.month, today.day) < (bd.month, bd.day): age -= 1
                            lines.append(f"└ Возраст: {age} лет")
                            break
                        except: continue
                except: pass
    elif search_type == "telegram_id":
        clean_id = re.sub(r'\D', '', query)
        lines.append(f"ID Telegram: {clean_id}")
    else:
        lines.append(f"Запрос: {query}")

    source_counts = []
    dep_data = data.get("depsearch", {})
    if dep_data and isinstance(dep_data, dict):
        res = dep_data.get("results", [])
        if res: source_counts.append(f"Depsearch: {len(res)} записей")
    bc = format_bigbase_short(data.get("bigbase"))
    if bc: source_counts.append(f"BigBase: {bc} записей")
    nc = format_nightsearch_count(data.get("nightsearch"))
    if nc: source_counts.append(f"NightSearch: {nc} записей")
    leak = data.get("leakosint")
    if leak and isinstance(leak, dict) and "List" in leak:
        lc = format_leakosint_count(leak)
        if lc: source_counts.append(f"LeakOSINT: {lc} записей")
    seon_data = data.get("seon")
    if seon_data and isinstance(seon_data, dict):
        has = False
        if seon_data.get("cnam_details", {}).get("name"): has = True
        elif seon_data.get("score") is not None: has = True
        elif seon_data.get("email"): has = True
        elif seon_data.get("social_media"): has = True
        if has: source_counts.append("Seon: данные найдены")
    snusbase_data = data.get("snusbase")
    if snusbase_data and isinstance(snusbase_data, dict):
        total = sum(len(recs) for recs in snusbase_data.get("results", {}).values())
        if total: source_counts.append(f"Snusbase: {total} записей")
    if source_counts:
        lines.append(""); lines.extend(source_counts)
    if stats_count and stats_count > 0:
        lines.append(""); lines.append(f"Интересовались этим: {stats_count} раз")
    errors = []
    for err in data.get("errors", []):
        if isinstance(err, dict): continue
        err_str = str(err)
        if "leakosint" in err_str.lower(): continue
        if "seon" in err_str.lower(): continue
        if "depsearch" in err_str.lower(): continue
        if "bigbase" in err_str.lower(): continue
        if err_str and err_str.strip(): errors.append(err_str)
    if errors:
        lines.append("")
        for err in errors[:2]: lines.append(f"Ошибка: {err}")
    return "\n".join(lines)

# ========== ГЕНЕРАЦИЯ HTML-ОТЧЁТА (сокращён для размера) ==========
def generate_html(data, search_type, query):
    # Сокращённая версия – можно оставить как есть, она не влияет на реферал
    return "<html><body>Отчёт сгенерирован</body></html>"

# ========== ОБРАБОТЧИКИ TELEGRAM ==========
last_processed = {}
partial_data = {}

async def start(update, context):
    user_id = update.effective_user.id
    logging.info(f"START args: {context.args}")
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            referrer_id = arg[4:]
            logging.info(f"Получена реферальная ссылка: user={user_id}, ref={referrer_id}")
            if referrer_id.isdigit():
                if add_refferal(user_id, referrer_id):
                    await update.message.reply_text("Вы зарегистрированы по реферальной ссылке.\nРефереру начислен бонус.")
                else:
                    await update.message.reply_text("Вы уже зарегистрированы или ссылка недействительна.")
    if not await is_subscribed(user_id, context):
        await update.message.reply_text("Для использования бота подпишитесь на канал:", reply_markup=get_back_keyboard())
        return
    context.user_data['partial'] = {}
    context.user_data['partial_mode'] = False
    await update.message.reply_text(
        "Приветствую! ты попал в бота кумова.\n\nтут ты сможешь найти информацию о своем обидчике.\n\nудачного поиска!",
        reply_markup=get_main_keyboard()
    )

async def handle_message(update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if not text: return
    if context.user_data.get('partial_mode'):
        field = context.user_data.get('partial_field')
        if field:
            if field not in context.user_data['partial']:
                context.user_data['partial'][field] = []
            context.user_data['partial'][field].append(text)
            await show_partial_form(update, context)
            return
    if not await is_subscribed(user_id, context):
        await update.message.reply_text("Для использования бота подпишитесь на канал:", reply_markup=get_back_keyboard())
        return
    search_type = detect_search_type(text)
    if search_type == "unknown":
        await update.message.reply_text("Не удалось определить тип данных.\n\nПопробуйте ввести данные в другом формате или используйте кнопку 'Поиск по неполным данным'.")
        return
    stats_count = increment_stats(text)
    msg = await update.message.reply_text("Поиск...")
    clean_query = text
    if search_type == "phone": clean_query = re.sub(r'\D', '', text)
    elif search_type == "telegram_id": clean_query = re.sub(r'\D', '', text)
    data = unified_search(clean_query, search_type)
    short = format_short(data, text, stats_count, search_type)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Полный отчёт", callback_data=f"report_{search_type}_{text}")]])
    await msg.edit_text(short, reply_markup=keyboard, parse_mode="Markdown")
    context.user_data['report_data'] = {'search_type': search_type, 'query': text, 'data': data}

async def report_callback(update, context):
    query = update.callback_query
    await query.answer()
    report_data = context.user_data.get('report_data')
    if not report_data:
        await query.edit_message_text("Данные устарели. Отправьте запрос заново.", reply_markup=get_back_keyboard())
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
            await query.message.reply_document(document=f, filename=f"infoHunt_report_{search_type}.html", caption=f"Полный отчёт по запросу: {text}")
    finally:
        if os.path.exists(tmp_path): os.unlink(tmp_path)

async def examples_callback(update, context):
    query = update.callback_query
    await query.answer()
    text = """Примеры для ввода команд

Личность: Навальный Алексей Анатольевич 04.06.1976
Контакты: 79999688666 - номер телефона, 79999688666@mail.ru - email
Транспорт: В395ОК199 - номер автомобиля, XTA211440C5106924 - VIN
Социальные сети: vk.com/sherlock, tiktok.com/@sherlock, instagram.com/sherlock, ok.ru/profile/58460
Telegram: tg123456
Документы: /vu 1234567890, /passport 1234567890, /snils 12345678901, /inn 123456789012
Онлайн-следы: /tag хирург москва, sherlock.com или 1.1.1.1
Недвижимость: /adr Город, Улица, 1 ; 77:01:0004042:6987 - кадастровый номер
Юридическое лицо: /inn 2540214547, 1107449004464 - ОГРН"""
    await query.edit_message_text(text, reply_markup=get_back_keyboard(), parse_mode="Markdown")

async def account_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    free_searches = get_free_searches(user_id)
    refferals = get_refferals_count(user_id)
    # ПРАВИЛЬНАЯ ССЫЛКА С ref_
    text = f"""Мой аккаунт

ID: {user_id}
Бесплатных запросов: {free_searches}
Приглашено друзей: {refferals}

За каждого приглашённого друга вы получаете +1 бесплатный запрос!
Приглашайте друзей по ссылке:
https://t.me/{BOT_USERNAME}?start=ref_{user_id}"""
    await query.edit_message_text(text, reply_markup=get_back_keyboard(), parse_mode="Markdown")

async def refferal_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    refferals = get_refferals_count(user_id)
    free_searches = get_free_searches(user_id)
    text = f"""Партнёрская программа

Ваши рефералы: {refferals}
Бесплатных запросов: {free_searches}

За каждого приглашённого пользователя вы получаете +1 бесплатный запрос.

Ваша реферальная ссылка:
https://t.me/{BOT_USERNAME}?start=ref_{user_id}

Статистика рефералов обновляется автоматически при переходе по ссылке."""
    await query.edit_message_text(text, reply_markup=get_back_keyboard(), parse_mode="Markdown")

async def show_partial_form(update, context):
    partial = context.user_data.get('partial', {})
    fields_display = []
    field_names = {'lastname':'Фамилия','firstname':'Имя','middlename':'Отчество','day':'День','month':'Месяц','year':'Год','age_from':'Возраст от','age_to':'Возраст до','birthplace':'Место рождения','country':'Страна'}
    for field, values in partial.items():
        if values:
            fields_display.append(f"{field_names.get(field, field)}: {values[0]}")
    status_text = "Заполнено:\n" + "\n".join(fields_display) if fields_display else "Ничего не заполнено"
    if isinstance(update, Update) and update.callback_query:
        query = update.callback_query
        await query.edit_message_text(f"Поиск по неполным данным\n\n{status_text}\n\nНажмите на поле, которое хотите заполнить:", reply_markup=get_partial_search_keyboard())
    else:
        await update.message.reply_text(f"Поиск по неполным данным\n\n{status_text}\n\nНажмите на поле, которое хотите заполнить:", reply_markup=get_partial_search_keyboard())

async def partial_search_callback(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['partial'] = {}
    context.user_data['partial_mode'] = True
    await query.edit_message_text("Поиск по неполным данным\n\nВы можете указать любое количество данных: фамилию, имя, отчество, дату или год рождения, возраст, место рождения и т. д.\n\nДостаточно заполнить то, что у вас есть - все поля необязательны.\n\nНажмите на поле, которое хотите заполнить:", reply_markup=get_partial_search_keyboard())

async def partial_field_callback(update, context):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("partial_", "")
    context.user_data['partial_field'] = field
    context.user_data['partial_mode'] = True
    field_names = {'lastname':'Фамилию','firstname':'Имя','middlename':'Отчество','day':'День (1-31)','month':'Месяц (1-12)','year':'Год (например: 1990)','age_from':'Возраст от','age_to':'Возраст до','birthplace':'Место рождения','country':'Страну'}
    name = field_names.get(field, field)
    if field == 'country':
        await query.edit_message_text("Выберите страну:", reply_markup=get_country_keyboard())
    else:
        await query.edit_message_text(f"Введите {name}\n\nОтправьте значение в следующем сообщении.\nЧтобы отменить, нажмите 'Назад'.", reply_markup=get_partial_back_keyboard())

async def country_callback(update, context):
    query = update.callback_query
    await query.answer()
    country = query.data.replace("country_", "")
    country_names = {'russia':'Россия','kazakhstan':'Казахстан','belarus':'Беларусь','ukraine':'Украина'}
    if 'partial' not in context.user_data: context.user_data['partial'] = {}
    if 'country' not in context.user_data['partial']: context.user_data['partial']['country'] = []
    context.user_data['partial']['country'].append(country_names.get(country, country))
    context.user_data['partial_mode'] = True
    await show_partial_form(update, context)

async def partial_back_callback(update, context):
    query = update.callback_query
    await query.answer()
    await show_partial_form(update, context)

async def partial_search_execute(update, context):
    query = update.callback_query
    await query.answer()
    partial = context.user_data.get('partial', {})
    if not partial:
        await query.edit_message_text("Вы не заполнили ни одного поля.\nПожалуйста, укажите хотя бы одно данное для поиска.", reply_markup=get_partial_search_keyboard())
        return
    query_parts = []
    for field, values in partial.items():
        if values:
            if field == 'day': query_parts.append(f"день {values[0]}")
            elif field == 'month': query_parts.append(f"месяц {values[0]}")
            elif field == 'year': query_parts.append(f"год {values[0]}")
            elif field == 'age_from': query_parts.append(f"возраст от {values[0]}")
            elif field == 'age_to': query_parts.append(f"возраст до {values[0]}")
            elif field == 'country': query_parts.append(values[0])
            else: query_parts.append(values[0])
    search_text = " ".join(query_parts)
    await query.edit_message_text(f"Поиск по запросу: {search_text}\n\nВыполняется поиск...", reply_markup=get_back_keyboard())
    stats_count = increment_stats(search_text)
    search_type = "name"
    data = unified_search(search_text, search_type)
    short = format_short(data, search_text, stats_count, search_type)
    short = f"Поиск по неполным данным\n{short}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Полный отчёт", callback_data=f"report_{search_type}_{search_text}")]])
    await query.edit_message_text(short, reply_markup=keyboard, parse_mode="Markdown")
    context.user_data['report_data'] = {'search_type': search_type, 'query': search_text, 'data': data}
    context.user_data['partial_mode'] = False

async def partial_reset_callback(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['partial'] = {}
    context.user_data['partial_mode'] = True
    await query.edit_message_text("Все поля сброшены.\n\nВы можете заполнить их заново:", reply_markup=get_partial_search_keyboard())

async def back_to_main_callback(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['partial'] = {}
    context.user_data['partial_mode'] = False
    await query.edit_message_text(
        "Приветствую! ты попал в бота кумова.\n\nтут ты сможешь найти информацию о своем обидчике.\n\nудачного поиска!",
        reply_markup=get_main_keyboard()
    )

def detect_search_type(query):
    query = query.strip()
    if re.search(r'vk\.com/|vkontakte\.ru/', query, re.I): return "vk"
    if re.search(r'tiktok\.com/@', query, re.I): return "tiktok"
    if re.search(r'instagram\.com/', query, re.I): return "instagram"
    if re.search(r'ok\.ru/', query, re.I): return "ok"
    if re.search(r'^tg\d+$', query, re.I) or re.search(r'^@?\w{5,32}$', query) and not re.search(r'\s', query): return "telegram_id"
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', query): return "ip"
    if re.match(r'^[a-zA-Z0-9][a-zA-Z0-9-]{1,61}[a-zA-Z0-9]\.[a-zA-Z]{2,}$', query): return "domain"
    if re.match(r'^[A-HJ-NPR-Z0-9]{17}$', query, re.I): return "car"
    if re.match(r'^[А-Я]{1}\d{3}[А-Я]{2}\d{2,3}$', query, re.I): return "car"
    if re.match(r'^\d{11}$', query) or re.match(r'^\d{3}-\d{3}-\d{3}-\d{2}$', query): return "snils"
    if re.match(r'^\d{10}$', query) or re.match(r'^\d{12}$', query): return "inn"
    if re.match(r'^\d{4}\s?\d{6}$', query): return "passport"
    if re.search(r'@', query): return "email"
    if re.sub(r'\D', '', query).isdigit() and len(re.sub(r'\D', '', query)) >= 10: return "phone"
    if re.search(r'[а-яА-Я]', query) and len(query.split()) >= 2: return "name"
    return "unknown"

# ========== MAIN ==========
def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    self_ping_thread = threading.Thread(target=self_ping, daemon=True)
    self_ping_thread.start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CallbackQueryHandler(partial_search_callback, pattern="^search_partial$"))
    app.add_handler(CallbackQueryHandler(partial_field_callback, pattern="^partial_"))
    app.add_handler(CallbackQueryHandler(country_callback, pattern="^country_"))
    app.add_handler(CallbackQueryHandler(partial_back_callback, pattern="^partial_back$"))
    app.add_handler(CallbackQueryHandler(partial_search_execute, pattern="^partial_search$"))
    app.add_handler(CallbackQueryHandler(partial_reset_callback, pattern="^partial_reset$"))
    app.add_handler(CallbackQueryHandler(examples_callback, pattern="^examples$"))
    app.add_handler(CallbackQueryHandler(account_callback, pattern="^account$"))
    app.add_handler(CallbackQueryHandler(refferal_callback, pattern="^refferal$"))
    app.add_handler(CallbackQueryHandler(back_to_main_callback, pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(report_callback, pattern="^report_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
