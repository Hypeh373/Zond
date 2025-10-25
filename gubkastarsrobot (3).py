import sqlite3
import time
import random
from functools import wraps
import telebot
from telebot import types
from telebot.util import escape
import requests
import json
import re

# ================== Настройки ==================
BOT_TOKEN = "7647406503:AAG2ECMSnFhHX1Tx4uH4oi2fP8ZnZHH6_1I"   # <-- ВАШ ТОКЕН
DB_PATH = "gubka1_bot.db"
START_BALANCE = 0.0
ADMINS = [1264898025,8384858757]  # <-- ВАШ ID АДМИНА
SUBGRAM_API_URL = "https://api.subgram.org"
# ================================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ========== БД ==========
# ИСПРАВЛЕНИЕ: Добавляем isolation_level=None для автосохранения и решения проблемы с кэшированием
conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
# Создаем один курсор для инициализации
initial_cursor = conn.cursor()

initial_cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    balance REAL DEFAULT 0.0,
    invited INTEGER DEFAULT 0,
    subscribed INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    created_at INTEGER,
    referrer_id INTEGER DEFAULT NULL,
    last_click_at REAL DEFAULT 0.0,
    last_bonus_at REAL DEFAULT 0.0
)""")
initial_cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
initial_cursor.execute("CREATE TABLE IF NOT EXISTS withdraw_options (code TEXT PRIMARY KEY, price REAL, label TEXT)")
initial_cursor.execute("CREATE TABLE IF NOT EXISTS withdraw_requests (request_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, option_code TEXT, status TEXT DEFAULT 'pending', created_at INTEGER)")
initial_cursor.execute("CREATE TABLE IF NOT EXISTS channels (channel_id INTEGER PRIMARY KEY, username TEXT, title TEXT)")
initial_cursor.execute("CREATE TABLE IF NOT EXISTS promo_codes (code TEXT PRIMARY KEY, reward REAL, uses_left INTEGER)")
initial_cursor.execute("CREATE TABLE IF NOT EXISTS promo_activations (code TEXT, user_id INTEGER, PRIMARY KEY(code, user_id))")
initial_cursor.execute("""
CREATE TABLE IF NOT EXISTS completed_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    link TEXT,
    completion_time INTEGER,
    reward_amount REAL,
    is_checked INTEGER DEFAULT 0
)""")

def add_column_if_not_exists(table, column, definition):
    local_cursor = conn.cursor()
    local_cursor.execute(f"PRAGMA table_info({table})")
    columns = [info[1] for info in local_cursor.fetchall()]
    if column not in columns:
        local_cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        print(f"Added column '{column}' to table '{table}'")

add_column_if_not_exists("users", "last_click_at", "REAL DEFAULT 0.0")
add_column_if_not_exists("users", "referrer_id", "INTEGER DEFAULT NULL")
add_column_if_not_exists("users", "last_bonus_at", "REAL DEFAULT 0.0")
add_column_if_not_exists("completed_tasks", "link", "TEXT")

# ========== Функции ==========
def set_setting(key, value):
    local_cursor = conn.cursor()
    local_cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))

def get_setting(key, default=None):
    local_cursor = conn.cursor()
    local_cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    r = local_cursor.fetchone()
    return r[0] if r else default

# Заполнение таблиц по умолчанию
local_cursor = conn.cursor()
if local_cursor.execute("SELECT COUNT(*) FROM withdraw_options").fetchone()[0] == 0:
    default_options = [("wd_15_bear", 15.0, "15 ⭐ (🐻)"), ("wd_15_heart", 15.0, "15 ⭐ (💖)"), ("wd_25_rose", 25.0, "25 ⭐ (🌹)"), ("wd_25_box", 25.0, "25 ⭐ (🎁)"),("wd_50_champ", 50.0, "50 ⭐ (🍾)"), ("wd_50_flowers", 50.0, "50 ⭐ (💐)"), ("wd_50_rocket", 50.0, "50 ⭐ (🚀)"), ("wd_50_cake", 50.0, "50 ⭐ (🎂)"),("wd_100_trophy", 100.0, "100 ⭐ (🏆)"), ("wd_100_ring", 100.0, "100 ⭐ (💍)"), ("wd_100_diamond", 100.0, "100 ⭐ (💎)"),("wd_tg_prem", 1700.0, "Telegram Premium 6мес. (1700⭐)")]
    local_cursor.executemany("INSERT INTO withdraw_options (code, price, label) VALUES (?, ?, ?)", default_options)

default_settings = {
    "start_text_v2": "1️⃣ Получи свою личную ссылку — жми «⭐️ Заработать звезды»\n2️⃣ Приглашай друзей — 3⭐️ за каждого!\n\n✅ Дополнительно:\n— Ежедневные награды и промокоды (Профиль)\n— Выполняй задания\n— Крути рулетку и удвой баланс!\n— Участвуй в конкурсе на топ\n\n🔻 <b>Главное меню</b>",
    "start_image": "", "earn_image": "https://i.imgur.com/k6rQhQp.jpeg", "profile_media": "", "profile_media_type": "none",
    "withdraw_media": "", "withdraw_media_type": "none", "top_image": "", "roulette_image": "", "transfer_image": "",
    "click_reward": "0.1", "click_cooldown": "300", "daily_bonus_amount": "1.0", "referral_reward": "3.0",
    "min_invites_for_withdraw": "5", "min_invites_for_transfer": "5", "bot_name": "Губка Боб", "review_channel_link": "",
    "clicker_popup_title": "gubkastarsrobot", "roulette_win_chance": "45", "share_text": "⭐ Получай звёзды в Губке и обменивай их на подарки!",
    "subgram_api_key": "", "subgram_op_image": "", "subgram_task_image": "", "subgram_max_sponsors": "4", "subgram_task_reward": "2.0"
}
for key, value in default_settings.items():
    if get_setting(key) is None:
        set_setting(key, value)

def get_user(user_id):
    local_cursor = conn.cursor()
    row = local_cursor.execute("SELECT user_id, username, first_name, balance, invited, subscribed, clicks, last_click_at, referrer_id, last_bonus_at FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row: return {"user_id": row[0], "username": row[1], "first_name": row[2], "balance": float(row[3]), "invited": int(row[4]), "subscribed": int(row[5]), "clicks": int(row[6]), "last_click_at": float(row[7]), "referrer_id": row[8], "last_bonus_at": float(row[9])}
    return None

def ensure_user(user, referrer_id=None):
    u = get_user(user.id)
    local_cursor = conn.cursor()
    if not u:
        local_cursor.execute("INSERT INTO users (user_id, username, first_name, balance, invited, subscribed, clicks, created_at, last_click_at, referrer_id, last_bonus_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (user.id, user.username or "", user.first_name or "", START_BALANCE, 0, 0, 0, int(time.time()), 0.0, referrer_id, 0.0))
        return get_user(user.id), True
    if u['username'] != (user.username or "") or u['first_name'] != (user.first_name or ""):
        local_cursor.execute("UPDATE users SET username = ?, first_name = ? WHERE user_id = ?", (user.username or "", user.first_name or "", user.id))
    return get_user(user.id), False

def add_balance(user_id, amount):
    local_cursor = conn.cursor()
    local_cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (float(amount), user_id))

if not hasattr(bot, "temp"):
    bot.temp = {"admin_sessions": {}, "promo_temp": {}, "transfer_mode": {}, "pending_transfer": {}, "pending_broadcast": {}}

# ========== Клавиатуры ==========
def main_menu_inline():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("✨ Кликер", callback_data="do_click"), types.InlineKeyboardButton("⭐ Заработать звезды", callback_data="menu_earn"))
    kb.add(types.InlineKeyboardButton("👤 Профиль", callback_data="menu_profile"), types.InlineKeyboardButton("💰 Вывод звёзд", callback_data="menu_withdraw"))
    kb.add(types.InlineKeyboardButton("📝 Задания", callback_data="menu_tasks"), types.InlineKeyboardButton("🏆 Топ", callback_data="menu_top"))
    kb.add(types.InlineKeyboardButton("🎰 Рулетка", callback_data="menu_roulette"))
    review_link = get_setting("review_channel_link")
    if review_link: kb.add(types.InlineKeyboardButton("💌 Отзывы", url=review_link))
    else: kb.add(types.InlineKeyboardButton("💌 Отзывы", callback_data="menu_reviews_placeholder"))
    return kb

def earn_menu_kb(user_id):
    kb = types.InlineKeyboardMarkup(row_width=1)
    share_text = get_setting("share_text", "⭐ Получай звёзды в Губке и обменивай их на подарки!")
    kb.add(types.InlineKeyboardButton("✅ Отправить друзьям", switch_inline_query=share_text))
    kb.add(types.InlineKeyboardButton("⬅️ В главное меню", callback_data="to_main"))
    return kb

def profile_kb_new():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🎉 Промокод", callback_data="profile_promo"))
    kb.add(types.InlineKeyboardButton("🎁 Ежедневка", callback_data="profile_daily_bonus"))
    kb.add(types.InlineKeyboardButton("⭐ Перевести ⭐ другу", callback_data="profile_transfer"))
    kb.add(types.InlineKeyboardButton("⬅️ В главное меню", callback_data="to_main"))
    return kb
    
def transfer_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_transfer"))
    kb.add(types.InlineKeyboardButton("⬅️ В главное меню", callback_data="to_main"))
    return kb

def back_to_main_kb():
    return types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅ В главное меню", callback_data="to_main"))

def roulette_kb():
    kb = types.InlineKeyboardMarkup(row_width=3)
    bet_amounts = [0.5, 1, 2, 3, 5, 10, 50, 100, 500]
    buttons = [types.InlineKeyboardButton(f"{b} ⭐", callback_data=f"roulette_spin|{b}") for b in bet_amounts]
    kb.add(*buttons)
    kb.add(types.InlineKeyboardButton("⬅ В главное меню", callback_data="to_main"))
    return kb

def withdraw_menu_kb():
    local_cursor = conn.cursor()
    options = local_cursor.execute("SELECT code, label FROM withdraw_options ORDER BY price").fetchall()
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(label, callback_data=f"wd_request|{code}") for code, label in options]
    kb.add(*buttons)
    kb.add(types.InlineKeyboardButton("⬅ В главное меню", callback_data="to_main"))
    return kb

def admin_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("📋 Пользователи", callback_data="adm_list_users"), types.InlineKeyboardButton("💰 Выдать/Забрать ⭐", callback_data="adm_change_balance"))
    kb.add(types.InlineKeyboardButton("📢 Рассылка", callback_data="adm_broadcast"), types.InlineKeyboardButton("🎁 Промокоды", callback_data="adm_promo"))
    kb.add(types.InlineKeyboardButton("🔗 Обяз. подписки", callback_data="adm_channels"), types.InlineKeyboardButton("⚙️ Настройки", callback_data="adm_settings"))
    kb.add(types.InlineKeyboardButton("⬅ В главное меню", callback_data="to_main"))
    return kb

def admin_promo_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("➕ Создать промо", callback_data="adm_promo_add"), types.InlineKeyboardButton("📄 Список промо", callback_data="adm_promo_list"))
    kb.add(types.InlineKeyboardButton("🗑 Удалить промо", callback_data="adm_promo_delete"), types.InlineKeyboardButton("⬅️ Назад", callback_data="adm_main"))
    return kb
    
def admin_channels_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("➕ Добавить канал", callback_data="adm_channel_add"), types.InlineKeyboardButton("📄 Список каналов", callback_data="adm_channel_list"))
    kb.add(types.InlineKeyboardButton("🗑 Удалить канал", callback_data="adm_channel_delete"), types.InlineKeyboardButton("⬅️ Назад", callback_data="adm_main"))
    return kb

def admin_settings_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("🖼 Настройки медиа", callback_data="adm_settings_media"), types.InlineKeyboardButton("💰 Настройки наград", callback_data="adm_settings_rewards"))
    kb.add(types.InlineKeyboardButton("✏️ Общие настройки", callback_data="adm_settings_general"), types.InlineKeyboardButton("📊 Настройки SubGram", callback_data="adm_settings_subgram"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm_main"))
    return kb

def admin_media_settings_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🖼 Ред. старт", callback_data="adm_edit_start"))
    kb.add(types.InlineKeyboardButton("🖼 Ред. 'Заработать'", callback_data="adm_edit_earn_photo"))
    kb.add(types.InlineKeyboardButton("🖼 Ред. профиль", callback_data="adm_edit_profile"))
    kb.add(types.InlineKeyboardButton("🖼 Ред. вывод", callback_data="adm_edit_withdraw"))
    kb.add(types.InlineKeyboardButton("🖼 Ред. перевод", callback_data="adm_edit_transfer_photo"))
    kb.add(types.InlineKeyboardButton("🖼 Фото топа", callback_data="adm_edit_top_photo"))
    kb.add(types.InlineKeyboardButton("🖼 Фото рулетки", callback_data="adm_edit_roulette_photo"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm_settings"))
    return kb

def admin_rewards_settings_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("💰 Награда клика", callback_data="adm_set_click_reward"), types.InlineKeyboardButton("💰 Ежедневный бонус", callback_data="adm_set_daily_bonus"))
    kb.add(types.InlineKeyboardButton("⏱ КД клика (мин)", callback_data="adm_set_click_cooldown"), types.InlineKeyboardButton("🤝 Награда за реферала", callback_data="adm_set_referral_reward"))
    kb.add(types.InlineKeyboardButton("📈 Мин. реф. для вывода", callback_data="adm_set_min_invites"), types.InlineKeyboardButton("📈 Мин. реф. для перевода", callback_data="adm_set_min_invites_transfer"))
    kb.add(types.InlineKeyboardButton("🍀 Шанс победы в рулетке %", callback_data="adm_set_win_chance"), types.InlineKeyboardButton("⬅️ Назад", callback_data="adm_settings"))
    return kb

def admin_general_settings_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("✏️ Имя бота", callback_data="adm_set_bot_name"), types.InlineKeyboardButton("🔗 Канал отзывов", callback_data="adm_set_review_link"))
    kb.add(types.InlineKeyboardButton("✏️ Юз в кликере", callback_data="adm_set_clicker_title"), types.InlineKeyboardButton("✏️ Текст для 'поделиться'", callback_data="adm_set_share_text"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm_settings"))
    return kb

def admin_subgram_settings_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    api_key_status = "Установлен" if get_setting("subgram_api_key") else "Не установлен"
    kb.add(types.InlineKeyboardButton(f"🔑 API Ключ ({api_key_status})", callback_data="adm_set_subgram_key"))
    kb.add(types.InlineKeyboardButton("💰 Награда за Задание", callback_data="adm_set_subgram_task_reward"))
    kb.add(types.InlineKeyboardButton("🖼 Фото для ОП", callback_data="adm_edit_subgram_op_photo"))
    kb.add(types.InlineKeyboardButton("🖼 Фото для Заданий", callback_data="adm_edit_subgram_task_photo"))
    kb.add(types.InlineKeyboardButton("🔢 Макс. спонсоров в ОП", callback_data="adm_set_subgram_max_sponsors"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm_settings"))
    return kb

# ========== Декоратор ==========
def admin_only(f):
    @wraps(f)
    def wrapper(obj, *a, **k):
        user_id = getattr(obj, "from_user", getattr(obj, "chat", None)).id
        if user_id not in ADMINS:
            if isinstance(obj, types.CallbackQuery): bot.answer_callback_query(obj.id, "Доступно только админам.", show_alert=True)
            else: bot.send_message(obj.chat.id, "Доступно только админам.", parse_mode="HTML")
            return
        return f(obj, *a, **k)
    return wrapper

# ========== Вспомогательные функции ==========
def show_main_menu(chat_id, message_id=None):
    if message_id:
        try: bot.delete_message(chat_id, message_id)
        except Exception: pass
    text, img = get_setting("start_text_v2"), get_setting("start_image")
    if img: bot.send_photo(chat_id, img, caption=text, reply_markup=main_menu_inline(), parse_mode="HTML")
    else: bot.send_message(chat_id, text, reply_markup=main_menu_inline(), parse_mode="HTML")

def show_profile_menu(user, chat_id, message_id=None):
    media, m_type = get_setting("profile_media"), get_setting("profile_media_type")
    u = get_user(user['user_id'])
    txt = f"✨ <b>Профиль</b>\n\n💬 <b>Имя:</b> {escape(u['first_name']) or 'Не указано'}\n🆔 <b>ID:</b> <code>{u['user_id']}</code>\n👤 @{u['username'] if u['username'] else 'Не указан'}\n\n✅ <b>Всего друзей:</b> {u['invited']}\n💰 <b>Баланс:</b> {u['balance']:.2f} ⭐\n\n<b>⁉️ Как получить ежедневный бонус?</b>\n<blockquote>Поставь свою личную ссылку на бота в описание тг аккаунта, и получай +1⭐ каждый день.</blockquote>"
    send_or_edit(None, txt, profile_kb_new(), photo=media if m_type == 'photo' else None, video=media if m_type == 'video' else None, chat_id=chat_id, message_id=message_id)

def process_initial_access(user, chat_id, message_id=None):
    if user['referrer_id'] and user['subscribed'] == 0:
        referrer = get_user(user['referrer_id'])
        if referrer:
            reward = float(get_setting("referral_reward", "3.0"))
            add_balance(referrer['user_id'], reward)
            local_cursor = conn.cursor()
            local_cursor.execute("UPDATE users SET invited = invited + 1 WHERE user_id = ?", (referrer['user_id'],))
            local_cursor.execute("UPDATE users SET subscribed = 1 WHERE user_id = ?", (user['user_id'],))
            try: bot.send_message(referrer['user_id'], f"🎉 Ваш друг <a href='tg://user?id={user['user_id']}'>{escape(user['first_name'])}</a> присоединился по вашей ссылке и прошел подписку! Вам начислено <b>{reward} ⭐</b>.", parse_mode="HTML")
            except Exception: pass
    show_main_menu(chat_id, message_id)

def check_local_subscriptions(user_id):
    local_cursor = conn.cursor()
    unsubscribed = []
    channels = local_cursor.execute("SELECT channel_id, username, title FROM channels").fetchall()
    if not channels: return []
    for channel_id, username, title in channels:
        try:
            member = bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                unsubscribed.append({'link': f"https://t.me/{username}", 'button_text': title, 'type': 'channel'})
        except Exception: unsubscribed.append({'link': f"https://t.me/{username}", 'button_text': title, 'type': 'channel'})
    return unsubscribed

def subgram_api_request(endpoint, data):
    api_key = get_setting("subgram_api_key")
    print("[SubGram] Используется API-ключ:", api_key)
    if not api_key:
        print("[SubGram] Запрос пропущен: API-ключ не установлен.")
        return {"status": "ok"}
    headers = {"Auth": api_key, "Content-Type": "application/json"}
    try:
        response = requests.post(f"{SUBGRAM_API_URL}/{endpoint}", headers=headers, json=data, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"[SubGram] HTTP Ошибка /{endpoint}: {e.response.status_code} {e.response.text}")
        if e.response.status_code == 404: return {"status": "ok"}
        return {"status": "error", "message": f"HTTP {e.response.status_code}: {e.response.text}"}
    except requests.exceptions.RequestException as e: 
        print(f"[SubGram] Ошибка запроса /{endpoint}: {e}")
        return {"status": "error", "message": str(e)}

def send_or_edit(call, text, kb, photo=None, video=None, chat_id=None, message_id=None):
    if call:
        chat_id = call.message.chat.id
        message_id = call.message.message_id
    new_media_type = 'video' if video else 'photo' if photo else 'text'
    try: current_media_type = call.message.content_type if call and call.message else 'text'
    except Exception: current_media_type = 'text'
    try:
        if not message_id: raise ValueError("No message_id")
        if new_media_type == 'text' and current_media_type == 'text':
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="HTML")
        elif new_media_type == current_media_type and photo:
             bot.edit_message_media(types.InputMediaPhoto(photo, caption=text, parse_mode="HTML"), chat_id, message_id, reply_markup=kb)
        elif new_media_type == current_media_type and video:
             bot.edit_message_media(types.InputMediaVideo(video, caption=text, parse_mode="HTML"), chat_id, message_id, reply_markup=kb)
        else:
            bot.delete_message(chat_id, message_id)
            if photo: bot.send_photo(chat_id, photo, caption=text, reply_markup=kb, parse_mode="HTML")
            elif video: bot.send_video(chat_id, video, caption=text, reply_markup=kb, parse_mode="HTML")
            else: bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            if message_id: bot.delete_message(chat_id, message_id)
        except Exception: pass
        if photo: bot.send_photo(chat_id, photo, caption=text, reply_markup=kb, parse_mode="HTML")
        elif video: bot.send_video(chat_id, video, caption=text, reply_markup=kb, parse_mode="HTML")
        else: bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")

def handle_subscription_check(user, chat_id, message_id=None, is_recheck=False):
    unsubscribed_local = check_local_subscriptions(user['user_id'])
    
    print(f"[SubGram] Запрос ОП для пользователя {user['user_id']}...")
    payload = {"chat_id": chat_id, "user_id": user['user_id'], "first_name": user['first_name'], "username": user['username'], "max_sponsors": int(get_setting('subgram_max_sponsors', 4))}
    sg_response = subgram_api_request("get-sponsors", payload)
    
    if sg_response.get("status") == "register":
        reg_url = sg_response['additional']['registration_url']
        builder = types.InlineKeyboardBuilder()
        builder.button(text="✅ Пройти быструю регистрацию", web_app=types.WebAppInfo(url=reg_url))
        builder.button(text="Я выполнил(а)", callback_data="check_subs")
        builder.adjust(1)
        send_or_edit(None, "Для продолжения, пожалуйста, укажите ваш пол и возраст.", builder.as_markup(), chat_id=chat_id, message_id=message_id)
        return
        
    if sg_response.get("status") in ["error", "gender", "age"]: sg_response['status'] = 'ok'

    unsubscribed_sg = []
    if sg_response.get("status") == "warning":
        sponsors = sg_response.get("additional", {}).get("sponsors", [])
        unsubscribed_sg = [s for s in sponsors if s.get('status') == 'unsubscribed' and s.get('available_now')]
    print(f"[SubGram] Получено {len(unsubscribed_sg)} каналов для подписки для пользователя {user['user_id']}.")

    combined_unsubscribed = unsubscribed_local + unsubscribed_sg
    
    if not combined_unsubscribed:
        if is_recheck:
            try: bot.edit_message_text("✅ <b>Спасибо за подписку!</b>", chat_id, message_id, reply_markup=None, parse_mode="HTML")
            except Exception: pass
            process_initial_access(user, chat_id)
        else:
            process_initial_access(user, chat_id, message_id)
    else:
        kb = types.InlineKeyboardMarkup(row_width=1)
        for channel in combined_unsubscribed:
            link, button_text, res_type = channel.get('link'), channel.get('button_text', 'Подписаться'), channel.get('type', 'channel')
            prefix = "🔗" if res_type == 'channel' else "🤖"
            kb.add(types.InlineKeyboardButton(f"{prefix} {button_text}", url=link))
        kb.add(types.InlineKeyboardButton("✅ Я подписался", callback_data="check_subs"))
        text = "<b>Добро пожаловать! 🎉</b>\n\nЧтобы пользоваться ботом, пожалуйста, подпишитесь на каналы наших спонсоров:"
        photo = get_setting("subgram_op_image")
        send_or_edit(None, text, kb, photo=photo, chat_id=chat_id, message_id=message_id)

def check_for_unsubscribes(user_id):
    local_cursor = conn.cursor()
    seven_days_ago = int(time.time()) - 7 * 86400
    
    tasks_to_check = local_cursor.execute("SELECT id, link, reward_amount FROM completed_tasks WHERE user_id = ? AND is_checked = 0 AND completion_time > ?", (user_id, seven_days_ago)).fetchall()
    
    if not tasks_to_check:
        local_cursor.execute("UPDATE completed_tasks SET is_checked = 1 WHERE user_id = ? AND is_checked = 0 AND completion_time <= ?", (user_id, seven_days_ago))
        return

    print(f"[SubGram] Проверка {len(tasks_to_check)} активных заданий для пользователя {user_id}...")
    links = [row[1] for row in tasks_to_check]
    payload = {"user_id": user_id, "links": links}
    sg_response = subgram_api_request("get-user-subscriptions", payload)

    if sg_response.get("status") == "ok":
        subscriptions = {sub['link']: sub['status'] for sub in sg_response.get("additional", {}).get("sponsors", [])}
        for task_id, link, reward in tasks_to_check:
            if subscriptions.get(link) != 'subscribed':
                add_balance(user_id, -reward)
                update_cursor = conn.cursor()
                update_cursor.execute("UPDATE completed_tasks SET is_checked = 1 WHERE id = ?", (task_id,))
                try: bot.send_message(user_id, f"❗️ Вы отписались от ресурса до истечения 7 дней. Награда за задание в размере <b>{reward} ⭐</b> была списана.", parse_mode="HTML")
                except Exception: pass
    
    final_cursor = conn.cursor()
    final_cursor.execute("UPDATE completed_tasks SET is_checked = 1 WHERE user_id = ? AND is_checked = 0 AND completion_time <= ?", (user_id, seven_days_ago))


# ========== Команды ==========
@bot.message_handler(commands=['start'])
def cmd_start(msg: types.Message):
    referrer_id = None
    if msg.text and len(msg.text.split()) > 1:
        try:
            ref_candidate = int(msg.text.split()[1])
            if ref_candidate != msg.from_user.id: referrer_id = ref_candidate
        except (ValueError, IndexError): pass
    
    user, is_new = ensure_user(msg.from_user, referrer_id)
    temp_msg = bot.send_message(msg.chat.id, "⏳ Загрузка...", parse_mode="HTML")
    handle_subscription_check(user, msg.chat.id, temp_msg.message_id, is_recheck=False)

@bot.message_handler(commands=['adm'])
@admin_only
def cmd_adm(msg):
    bot.send_message(msg.chat.id, "<b>Админ-меню:</b>", reply_markup=admin_menu_kb(), parse_mode="HTML")

@bot.inline_handler(func=lambda query: True)
def inline_handler(query: types.InlineQuery):
    try:
        user_id = query.from_user.id
        ref_link = f"https://t.me/{bot.get_me().username}?start={user_id}"
        share_text = get_setting("share_text", "⭐ Получай звёзды в Губке и обменивай их на подарки!")
        r = types.InlineQueryResultArticle(id='1', title="Нажми сюда, чтобы отправить ссылку", description=share_text, input_message_content=types.InputTextMessageContent(message_text=f"{share_text}\n\n➡️ <b>{ref_link}", parse_mode="HTML"), reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🎁 Начать игру!", url=ref_link)))
        bot.answer_inline_query(query.id, [r], cache_time=1)
    except Exception: pass

@bot.callback_query_handler(func=lambda c: True)
def callbacks(call: types.CallbackQuery):
    try:
        data, uid = call.data, call.from_user.id
        u = ensure_user(call.from_user)[0]
        check_for_unsubscribes(uid)

        if data == "to_main":
            bot.temp.get('transfer_mode', {}).pop(uid, None)
            show_main_menu(call.message.chat.id, call.message.message_id)
        
        elif data == "check_subs":
            bot.edit_message_text("⏳ Повторная проверка...", call.message.chat.id, call.message.message_id, parse_mode="HTML")
            handle_subscription_check(u, call.message.chat.id, call.message.message_id, is_recheck=True)

        elif data == "menu_tasks":
            print(f"[SubGram] Пользователь {uid} запросил задание.")
            api_key = get_setting("subgram_api_key")
            if not api_key:
                send_or_edit(call, "📝 <b>Задания</b>\n\nНа данный момент доступных заданий нет.", back_to_main_kb())
                return
            payload = {"chat_id": call.message.chat.id, "user_id": uid, "action": "newtask", "max_sponsors": 1}
            sg_response = subgram_api_request("get-sponsors", payload)
            if sg_response.get("status") in ["ok", "error"] or not sg_response.get("additional", {}).get("sponsors"):
                kb = types.InlineKeyboardMarkup(row_width=1).add(types.InlineKeyboardButton("🔄 Попробовать снова", callback_data="menu_tasks"), types.InlineKeyboardButton("⬅️ В главное меню", callback_data="to_main"))
                send_or_edit(call, "📝 <b>Задания</b>\n\nСейчас для вас нет доступных заданий. Попробуйте позже!", kb)
                return
            
            sponsor = sg_response["additional"]["sponsors"][0]
            task_photo = get_setting("subgram_task_image")
            task_reward = float(get_setting("subgram_task_reward", "2.0"))
            kb = types.InlineKeyboardMarkup(row_width=2)
            check_callback = f"check_task_subgram|{sponsor['ads_id']}|{sponsor['link']}"

            if sponsor['type'] == 'bot':
                text = f"✨ <b>Новое задание!</b> ✨\n\n• <b>Запусти бота</b>\n\n<b>Награда: {task_reward} ⭐</b>\n\nПосле выполнения жми «✅ Подтвердить запуск»"
                kb.add(types.InlineKeyboardButton(f"🤖 {sponsor['button_text']}", url=sponsor['link']))
                kb.add(types.InlineKeyboardButton("✅ Подтвердить запуск", callback_data=check_callback))
            else:
                text = f"✨ <b>Новое задание!</b> ✨\n\n• <b>Подпишись на канал</b>\n\n<b>Награда: {task_reward} ⭐</b>\n\n‼️ Чтобы получить награду полностью, подпишись и <b>НЕ отписывайся</b> от канала/бота в течение 7-ми дней\n\nПосле выполнения жми «✅ Подтвердить подписку»"
                kb.add(types.InlineKeyboardButton(f"🔗 {sponsor['button_text']}", url=sponsor['link']))
                kb.add(types.InlineKeyboardButton("✅ Подтвердить подписку", callback_data=check_callback))

            kb.add(types.InlineKeyboardButton("⬅️ В главное меню", callback_data="to_main"), types.InlineKeyboardButton("Пропустить задание ➡️", callback_data="menu_tasks"))
            send_or_edit(call, text, kb, photo=task_photo)

        elif data.startswith("check_task_subgram|"):
            _, ads_id, link = data.split("|", 2)
            payload = {"user_id": uid, "links": [link]}
            sg_response = subgram_api_request("get-user-subscriptions", payload)
            
            task_completed = False
            if sg_response.get("status") == "ok":
                sponsors = sg_response.get("additional", {}).get("sponsors", [])
                if sponsors and sponsors[0]['status'] == 'subscribed':
                    task_completed = True

            if task_completed:
                task_reward = float(get_setting("subgram_task_reward", "2.0"))
                add_balance(uid, task_reward)
                local_cursor = conn.cursor()
                local_cursor.execute("INSERT INTO completed_tasks (user_id, link, completion_time, reward_amount) VALUES (?, ?, ?, ?)", (uid, link, int(time.time()), task_reward))
                bot.answer_callback_query(call.id, f"✅ Задание выполнено! Вам начислено {task_reward} ⭐.", show_alert=True)
                send_or_edit(call, "📝 <b>Задания\nВыбери следующее задание:</b>", types.InlineKeyboardMarkup(row_width=1).add(types.InlineKeyboardButton("Выполнить еще задание", callback_data="menu_tasks"), types.InlineKeyboardButton("⬅️ В главное меню", callback_data="to_main")))
            else:
                bot.answer_callback_query(call.id, "❌ Вы еще не выполнили задание. Попробуйте снова.", show_alert=True)
        
        elif data == "menu_earn":
            ref_link = f"https://t.me/{bot.get_me().username}?start={uid}"
            text = f"✨ <b>Приглашай друзей и получай по {get_setting('referral_reward', '3.0')} ⭐ от Губки Боба за каждого, кто активирует бота по твоей ссылке!</b>\n\n🔗 <b><u>Твоя личная ссылка (нажми чтобы скопировать):</u></b>\n<code>{ref_link}</code>\n\n🚀 <b>Как набрать много переходов по ссылке?</b>\n• Отправь её друзьям в личные сообщения 👥\n• Поделись ссылкой в истории в своем ТГ или в своем Telegram канале 📲\n• Оставь её в комментариях или чатах 💬\n• Распространяй ссылку в соцсетях: TikTok, Instagram, WhatsApp и других 🌍"
            send_or_edit(call, text, earn_menu_kb(uid), photo=get_setting("earn_image"))
        
        elif data == "do_click":
            reward = float(get_setting('click_reward', '0.1'))
            cooldown = float(get_setting('click_cooldown', '300'))
            if (time.time() - u['last_click_at']) < cooldown:
                wait_str = time.strftime('%M мин %S сек', time.gmtime(cooldown - (time.time() - u['last_click_at'])))
                bot.answer_callback_query(call.id, f"Следующий клик через: {wait_str}", show_alert=True)
                return
            local_cursor = conn.cursor()
            local_cursor.execute("UPDATE users SET last_click_at = ? WHERE user_id = ?", (time.time(), uid));
            add_balance(uid, reward)
            bot.answer_callback_query(call.id, f"{get_setting('clicker_popup_title', 'bot')}\n\nТы получил(а) {reward:.2f} ⭐", show_alert=True)

        elif data == "menu_roulette":
            u_updated = get_user(uid)
            text = f"🎰 <b>Крути рулетку и удвой свой баланс!</b>\n\n💰 <b>Баланс:</b> {u_updated['balance']:.2f} ⭐\n⬇️ Выбери ставку:"
            send_or_edit(call, text, roulette_kb(), photo=get_setting("roulette_image"))

        elif data.startswith("roulette_spin|"):
            bet_amount = float(data.split('|')[1])
            u_current = get_user(uid)
            if u_current['balance'] < bet_amount: return bot.answer_callback_query(call.id, "❌ Недостаточно средств для этой ставки!", show_alert=True)
            add_balance(uid, -bet_amount)
            if random.uniform(0, 100) < float(get_setting("roulette_win_chance", 45)):
                winnings = bet_amount * 2; add_balance(uid, winnings)
                popup_text = f"🎉 Поздравляем! Вы выиграли {winnings:.2f} ⭐"
            else:
                popup_text = f"😕 Увы, не повезло. Вы проиграли {bet_amount:.2f} ⭐"
            bot.answer_callback_query(call.id, popup_text, show_alert=True)
            new_text = f"🎰 <b>Крути рулетку и удвой свой баланс!</b>\n\n💰 <b>Баланс:</b> {get_user(uid)['balance']:.2f} ⭐\n⬇️ Выбери ставку:"
            send_or_edit(call, new_text, roulette_kb(), photo=get_setting("roulette_image"))

        elif data == "menu_withdraw":
            media, m_type = get_setting("withdraw_media"), get_setting("withdraw_media_type")
            text = f"💰 <b>Баланс:</b> {u['balance']:.2f} ⭐\n\n‼️ Для вывода требуется:\n— минимум <b>{get_setting('min_invites_for_withdraw', 5)} приглашенных</b> друзей\n\n✅ <b>Моментальный автоматический вывод!</b>\n\nВыбери количество звезд и подарок:"
            send_or_edit(call, text, withdraw_menu_kb(), photo=media if m_type == 'photo' else None, video=media if m_type == 'video' else None)

        elif data.startswith("wd_request|"):
            min_invites = int(get_setting('min_invites_for_withdraw', 5))
            code = data.split("|", 1)[1]
            local_cursor = conn.cursor()
            price, label = local_cursor.execute("SELECT price, label FROM withdraw_options WHERE code = ?", (code,)).fetchone()
            if u['balance'] < price: return bot.answer_callback_query(call.id, f"Недостаточно средств. Нужно {price} ⭐", show_alert=True)
            if u['invited'] < min_invites: return bot.answer_callback_query(call.id, f"Нужно пригласить еще {min_invites - u['invited']} друзей.", show_alert=True)
            request_id = local_cursor.execute("INSERT INTO withdraw_requests (user_id, option_code, created_at) VALUES (?, ?, ?)", (uid, code, int(time.time()))).lastrowid
            admin_text = f"❗️ <b>Новая заявка на вывод #{request_id}</b>\n\n👤 <a href='tg://user?id={uid}'>{escape(u['first_name'])}</a> (<code>{uid}</code>)\n💰 <b>Баланс:</b> {u['balance']:.2f} ⭐\n🤝 <b>Друзей:</b> {u['invited']}\n\n🎁 <b>Запросил:</b> {label} ({price} ⭐)"
            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ Одобрить", callback_data=f"wd_approve|{request_id}"), types.InlineKeyboardButton("❌ Отклонить", callback_data=f"wd_decline|{request_id}"))
            for admin_id in ADMINS:
                try: bot.send_message(admin_id, admin_text, reply_markup=kb, parse_mode="HTML")
                except Exception: pass
            bot.answer_callback_query(call.id, "✅ Ваша заявка отправлена на рассмотрение!", show_alert=True)
            show_main_menu(call.message.chat.id, call.message.message_id)

        elif data.startswith(("wd_approve|", "wd_decline|")):
            if uid not in ADMINS: return
            action, request_id = data.split("|", 1)
            local_cursor = conn.cursor()
            req = local_cursor.execute("SELECT user_id, option_code, status FROM withdraw_requests WHERE request_id = ?", (request_id,)).fetchone()
            if not req: return bot.edit_message_text("Заявка не найдена.", call.message.chat.id, call.message.message_id, parse_mode="HTML")
            target_uid, code, status = req
            if status != 'pending': return bot.answer_callback_query(call.id, f"Заявка уже обработана (статус: {status})", show_alert=True)
            price, label = local_cursor.execute("SELECT price, label FROM withdraw_options WHERE code = ?", (code,)).fetchone()
            if action == "wd_approve":
                new_status, admin_fb = 'approved', f"✅ <b>ОДОБРЕНО</b> (админ {uid})"
                add_balance(target_uid, -price)
                review_link = get_setting("review_channel_link")
                user_msg = f"🎊 {get_setting('bot_name', 'Бот')} отправил тебе твой подарок!\n\nОставь, пожалуйста, отзыв и скорее начинай зарабатывать ⭐ на новый подарок 💖"
                kb = types.InlineKeyboardMarkup()
                if review_link: kb.add(types.InlineKeyboardButton("✅ Оставить отзыв", url=review_link))
                try: bot.send_message(target_uid, user_msg, reply_markup=kb if review_link else None, parse_mode="HTML")
                except Exception: pass
            else:
                new_status, admin_fb = 'declined', f"❌ <b>ОТКЛОНЕНО</b> (админ {uid})"
                try: bot.send_message(target_uid, f"❌ Ваша заявка «{label}» <b>отклонена</b>.", parse_mode="HTML")
                except Exception: pass
            local_cursor.execute("UPDATE withdraw_requests SET status = ? WHERE request_id = ?", (new_status, request_id))
            bot.edit_message_text(call.message.text + f"\n\n---\n{admin_fb}", call.message.chat.id, call.message.message_id, reply_markup=None, parse_mode="HTML")
        
        elif data == "menu_profile":
            bot.temp.get('transfer_mode', {}).pop(uid, None)
            show_profile_menu(u, call.message.chat.id, call.message.message_id)
            
        elif data == "profile_promo":
            bot.temp["promo_temp"][uid] = True
            send_or_edit(call, "<b>🎁 Введите ваш промокод:</b>", types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️ Назад в профиль", callback_data="menu_profile")))
        
        elif data == "profile_transfer":
            min_invites = int(get_setting('min_invites_for_transfer', 5))
            if u['invited'] < min_invites: return bot.answer_callback_query(call.id, f"❌ Для перевода нужно пригласить минимум {min_invites} друзей.", show_alert=True)
            bot.temp['transfer_mode'][uid] = True
            text = f"🎁 <b>Поделись звёздами с другом!</b>\n\n<b>Чтобы отправить ⭐ с твоего баланса другу:</b>\n\n1️⃣ Напиши боту его <b>Telegram ID</b>\n(узнать его можно, нажав «Профиль» в нашем боте или в @userinfobot)\n2️⃣ Введи <b>сумму звёзд</b>\n\nОтправь боту ID друга и сумму перевода 👇"
            send_or_edit(call, text, transfer_kb(), photo=get_setting("transfer_image"))

        elif data == "confirm_transfer":
            pending = bot.temp.get('pending_transfer', {}).get(uid)
            if not pending: return bot.answer_callback_query(call.id, "Сначала отправьте боту ID получателя и сумму.", show_alert=True)
            recipient_id, amount = pending['recipient'], pending['amount']
            if get_user(uid)['balance'] < amount: return bot.answer_callback_query(call.id, "На вашем балансе уже недостаточно средств.", show_alert=True)
            add_balance(uid, -amount); add_balance(recipient_id, amount)
            bot.answer_callback_query(call.id, f"✅ Вы успешно перевели {amount} ⭐ пользователю {recipient_id}!", show_alert=True)
            try: bot.send_message(recipient_id, f"🎉 Вам поступил перевод <b>{amount} ⭐</b> от <a href='tg://user?id={uid}'>{escape(u['first_name'])}</a>!", parse_mode="HTML")
            except: pass
            bot.temp['pending_transfer'].pop(uid, None)
            bot.temp['transfer_mode'].pop(uid, None)
            show_profile_menu(u, call.message.chat.id, call.message.message_id)

        elif data == "profile_daily_bonus":
            cooldown = 86400
            time_since_last_bonus = time.time() - u['last_bonus_at']
            if time_since_last_bonus < cooldown:
                wait_str = time.strftime('%H ч %M мин', time.gmtime(cooldown - time_since_last_bonus))
                return bot.answer_callback_query(call.id, f"Следующий бонус будет доступен через: {wait_str}", show_alert=True)
            ref_link = f"https://t.me/{bot.get_me().username}?start={uid}"
            try:
                user_profile = bot.get_chat(uid)
                if ref_link in (user_profile.bio or ""):
                    bonus_amount = float(get_setting('daily_bonus_amount', 1.0))
                    add_balance(uid, bonus_amount)
                    local_cursor = conn.cursor()
                    local_cursor.execute("UPDATE users SET last_bonus_at = ? WHERE user_id = ?", (time.time(), uid))
                    bot.answer_callback_query(call.id, f"✅ Вам начислено {bonus_amount} ⭐! Следующий бонус через 24 часа.", show_alert=True)
                else:
                    bot.answer_callback_query(call.id, "❌ Сначала поставьте свою личную ссылку в описание профиля.", show_alert=True)
            except Exception:
                bot.answer_callback_query(call.id, "❌ Не удалось проверить ваше описание. Пожалуйста, измените настройки конфиденциальности.", show_alert=True)
        
        elif data == "menu_reviews_placeholder":
            bot.answer_callback_query(call.id, "Администратор еще не добавил ссылку на отзывы.", show_alert=True)
        
        elif data == "menu_top":
            local_cursor = conn.cursor()
            top_users = local_cursor.execute("SELECT first_name, invited FROM users WHERE invited > 0 ORDER BY invited DESC LIMIT 10").fetchall()
            text = "🏆 <b>Топ пока пуст. Приглашайте друзей!</b>" if not top_users else "🏆 <b>Топ 10 по приглашениям:</b>\n\n" + "\n".join([f"{'🥇🥈🥉'[i] if i < 3 else f'<b>{i+1}</b>.'} {escape(name)} | <b>Друзей:</b> {invited}" for i, (name, invited) in enumerate(top_users)])
            send_or_edit(call, text, back_to_main_kb(), photo=get_setting("top_image"))
        
        elif data.startswith("adm_"):
            if uid not in ADMINS: return
            local_cursor = conn.cursor()
            if data == "adm_main": send_or_edit(call, "<b>Админ-меню:</b>", admin_menu_kb())
            
            elif data == "adm_broadcast_confirm":
                broadcast_data = bot.temp.get('pending_broadcast', {}).pop(uid, None)
                if not broadcast_data: return bot.edit_message_text("Ошибка: данные для рассылки не найдены.", call.message.chat.id, call.message.message_id, parse_mode="HTML")
                
                all_users = local_cursor.execute("SELECT user_id FROM users").fetchall()
                sent_count, failed_count = 0, 0
                bot.edit_message_text(f"Начинаю рассылку для {len(all_users)} пользователей...", call.message.chat.id, call.message.message_id, parse_mode="HTML")
                for (user_id,) in all_users:
                    try:
                        if broadcast_data['photo_id']: bot.send_photo(user_id, broadcast_data['photo_id'], caption=broadcast_data['text'], reply_markup=broadcast_data['kb'], parse_mode="HTML")
                        elif broadcast_data['video_id']: bot.send_video(user_id, broadcast_data['video_id'], caption=broadcast_data['text'], reply_markup=broadcast_data['kb'], parse_mode="HTML")
                        else: bot.send_message(user_id, broadcast_data['text'], reply_markup=broadcast_data['kb'], disable_web_page_preview=True, parse_mode="HTML")
                        sent_count += 1
                    except Exception: failed_count += 1
                    time.sleep(0.1)
                bot.send_message(uid, f"✅ Рассылка завершена!\n\n<b>Отправлено:</b> {sent_count}\n<b>Не удалось:</b> {failed_count}", parse_mode="HTML")
                return

            elif data == "adm_broadcast_cancel":
                bot.temp.get('pending_broadcast', {}).pop(uid, None)
                bot.edit_message_text("Рассылка отменена.", call.message.chat.id, call.message.message_id, parse_mode="HTML")
                return
            
            elif data == "adm_list_users":
                rows = local_cursor.execute("SELECT user_id, username, first_name, balance, invited FROM users ORDER BY created_at DESC LIMIT 50").fetchall()
                txt = "<b>Последние пользователи:</b>\n\n" + "\n".join([f"👤 <code>{r[0]}</code> — {escape(r[2]) or (r[1] and '@'+r[1]) or f'ID: {r[0]}'} \n💰 <b>{float(r[3]):.2f} ⭐</b> | 🤝 <b>{r[4]}</b> инв." for r in rows])
                send_or_edit(call, txt, types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm_main")))
            elif data == "adm_settings": send_or_edit(call, "<b>⚙️ Настройки:</b>", admin_settings_kb())
            elif data == "adm_settings_media": send_or_edit(call, "<b>🖼 Настройки медиа:</b>", admin_media_settings_kb())
            elif data == "adm_settings_rewards": send_or_edit(call, "<b>💰 Настройки наград:</b>", admin_rewards_settings_kb())
            elif data == "adm_settings_general": send_or_edit(call, "<b>✏️ Общие настройки:</b>", admin_general_settings_kb())
            elif data == "adm_settings_subgram": send_or_edit(call, "<b>📊 Настройки SubGram:</b>", admin_subgram_settings_kb())
            elif data == "adm_promo": send_or_edit(call, "<b>🎁 Управление промокодами:</b>", admin_promo_kb())
            elif data == "adm_channels": send_or_edit(call, "<b>🔗 Управление обязательными подписками:</b>", admin_channels_kb())
            elif data == "adm_promo_list":
                promos = local_cursor.execute("SELECT code, reward, uses_left FROM promo_codes").fetchall()
                text = "Промокодов нет." if not promos else "<b>Активные промокоды:</b>\n" + "\n".join([f"<code>{p[0]}</code> | <b>{p[1]} ⭐</b> | {p[2] if p[2] != -1 else '∞'} исп." for p in promos])
                send_or_edit(call, text, types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm_promo")))
            elif data == "adm_channel_list":
                channels = local_cursor.execute("SELECT channel_id, title, username FROM channels").fetchall()
                text = "Каналов для подписки нет." if not channels else "<b>Ваши каналы для обязательной подписки:</b>\n" + "\n".join([f"• {escape(c[1])} (<code>{c[0]}</code> / @{c[2]})" for c in channels])
                send_or_edit(call, text, types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm_channels")))
            elif data in ["adm_change_balance", "adm_broadcast", "adm_edit_start", "adm_edit_earn_photo", "adm_edit_profile", "adm_edit_withdraw", "adm_edit_top_photo", "adm_edit_roulette_photo", "adm_edit_transfer_photo", "adm_set_click_reward", "adm_set_click_cooldown", "adm_set_min_invites", "adm_set_min_invites_transfer", "adm_set_bot_name", "adm_set_review_link", "adm_set_clicker_title", "adm_set_win_chance", "adm_set_referral_reward", "adm_set_daily_bonus", "adm_promo_add", "adm_promo_delete", "adm_channel_add", "adm_channel_delete", "adm_set_share_text", "adm_set_subgram_key", "adm_edit_subgram_op_photo", "adm_edit_subgram_task_photo", "adm_set_subgram_max_sponsors", "adm_set_subgram_task_reward"]:
                prompts = { "adm_change_balance": "Ожидаю: <code>user_id amount</code>", "adm_broadcast": "Отправь текст для рассылки. Для добавления кнопки, напиши ее на **новой строке** в формате:\n<code>Текст кнопки|https://ссылка.com</code>", "adm_edit_start": "Ожидаю фото для старта. 'нет' для удаления", "adm_edit_earn_photo": "Ожидаю фото для экрана 'Заработать'. 'нет' для удаления.", "adm_edit_profile": "Ожидаю фото/видео для профиля. 'нет' для удаления", "adm_edit_withdraw": "Ожидаю фото/видео для вывода. 'нет' для удаления", "adm_edit_top_photo": f"Ожидаю фото для топа. 'нет' для удаления", "adm_edit_roulette_photo": f"Ожидаю фото для рулетки. 'нет' для удаления", "adm_edit_transfer_photo": f"Ожидаю фото для экрана перевода. 'нет' для удаления", "adm_set_click_reward": f"Отправь новую награду за клик.\n<b>Текущая:</b> {get_setting('click_reward')}", "adm_set_daily_bonus": f"Отправь сумму ежедневного бонуса.\n<b>Текущая:</b> {get_setting('daily_bonus_amount')}", "adm_set_click_cooldown": f"Отправь новый кулдаун в минутах.\n<b>Текущий:</b> {float(get_setting('click_cooldown')) / 60} мин", "adm_set_referral_reward": f"Отправь новую награду за реферала.\n<b>Текущая:</b> {get_setting('referral_reward')}", "adm_set_min_invites": f"Отправь мин. кол-во рефералов для вывода.\n<b>Текущее:</b> {get_setting('min_invites_for_withdraw')}", "adm_set_min_invites_transfer": f"Отправь мин. кол-во рефералов для перевода.\n<b>Текущее:</b> {get_setting('min_invites_for_transfer')}", "adm_set_bot_name": f"Отправь новое имя бота.\n<b>Текущее:</b> {get_setting('bot_name')}", "adm_set_review_link": f"Отправь ссылку на канал с отзывами. 'нет' для удаления.", "adm_set_clicker_title": f"Отправь юзернейм для заголовка кликера.\n<b>Текущий:</b> {get_setting('clicker_popup_title')}", "adm_set_share_text": f"Отправь текст для кнопки 'поделиться'.\n<b>Текущий:</b> {get_setting('share_text')}", "adm_set_win_chance": f"Отправь новый шанс победы в рулетке (0-100).\n<b>Текущий:</b> {get_setting('roulette_win_chance')}%", "adm_promo_add": "Отправь: <code>НАЗВАНИЕ НАГРАДА КОЛ_ВО</code> (-1 для ∞)", "adm_promo_delete": "Отправь название промокода для удаления.", "adm_channel_add": "Перешли любое сообщение из канала/чата или отправь его ID/username.", "adm_channel_delete": "Отправь ID или username (@username) канала для удаления.", "adm_set_subgram_key": f"Отправьте ваш API-ключ от SubGram. 'нет' для удаления.\n<b>Текущий:</b> {get_setting('subgram_api_key')[:4]}..." if get_setting('subgram_api_key') else "Не установлен", "adm_edit_subgram_op_photo": f"Ожидаю фото для ОП. 'нет' для удаления.", "adm_edit_subgram_task_photo": f"Ожидаю фото для Заданий. 'нет' для удаления.", "adm_set_subgram_max_sponsors": f"Отправьте макс. кол-во спонсоров от SubGram в ОП (1-10).\n<b>Текущее:</b> {get_setting('subgram_max_sponsors')}", "adm_set_subgram_task_reward": f"Отправь награду за выполнение задания.\n<b>Текущая:</b> {get_setting('subgram_task_reward')}", }
                bot.temp["admin_sessions"][uid] = {"action": data.replace('adm_', '')}
                send_or_edit(call, prompts[data], types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️ Отмена", callback_data="adm_main")))

    except Exception as e:
        import traceback
        print(f"!!! ОШИБКА в callback'ах: {e}")
        traceback.print_exc()
    finally:
        try: bot.answer_callback_query(call.id)
        except: pass

@bot.message_handler(content_types=['text','photo', 'video'])
def handle_media_and_text(message: types.Message):
    uid = message.from_user.id
    try: u = ensure_user(message.from_user)[0]
    except Exception: return

    if uid in ADMINS and uid in bot.temp.get("admin_sessions", {}):
        sess = bot.temp["admin_sessions"].pop(uid)
        action = sess.get("action")
        local_cursor = conn.cursor()
        
        if action == "broadcast":
            text = message.text or message.caption
            photo_id = message.photo[-1].file_id if message.photo else None
            video_id = message.video.file_id if message.video else None
            buttons = re.findall(r'^(.+)\|(.+)$', text, re.MULTILINE)
            kb = None
            if buttons:
                clean_text = re.sub(r'^(.+)\|(.+)\n?', '', text, flags=re.MULTILINE).strip()
                kb = types.InlineKeyboardMarkup()
                for btn_text, btn_url in buttons:
                    kb.add(types.InlineKeyboardButton(btn_text.strip(), url=btn_url.strip()))
                text = clean_text
            
            bot.temp.setdefault('pending_broadcast', {})[uid] = {'text': text, 'photo_id': photo_id, 'video_id': video_id, 'kb': kb}
            
            confirm_kb = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("✅ Начать рассылку", callback_data="adm_broadcast_confirm"),
                types.InlineKeyboardButton("❌ Отмена", callback_data="adm_broadcast_cancel")
            )
            bot.send_message(uid, "👇 <b>ПРЕДПРОСМОТР РАССЫЛКИ</b> 👇", parse_mode="HTML")
            if photo_id: bot.send_photo(uid, photo_id, caption=text, reply_markup=kb, parse_mode="HTML")
            elif video_id: bot.send_video(uid, video_id, caption=text, reply_markup=kb, parse_mode="HTML")
            else: bot.send_message(uid, text, reply_markup=kb, disable_web_page_preview=True, parse_mode="HTML")
            bot.send_message(uid, "Подтвердите отправку:", reply_markup=confirm_kb, parse_mode="HTML")
            return
        
        elif action in ["edit_profile", "edit_withdraw", "edit_start", "edit_earn_photo", "edit_top_photo", "edit_roulette_photo", "edit_transfer_photo", "edit_subgram_op_photo", "edit_subgram_task_photo"]:
            key_map = { "edit_profile": ("profile_media", "profile_media_type"), "edit_withdraw": ("withdraw_media", "withdraw_media_type"), "edit_start": ("start_image", None), "edit_earn_photo": ("earn_image", None), "edit_top_photo": ("top_image", None), "edit_roulette_photo": ("roulette_image", None), "edit_transfer_photo": ("transfer_image", None), "edit_subgram_op_photo": ("subgram_op_image", None), "edit_subgram_task_photo": ("subgram_task_image", None) }
            key1, key2 = key_map[action]
            if message.photo:
                set_setting(key1, message.photo[-1].file_id)
                if key2: set_setting(key2, "photo")
                bot.send_message(uid, "✅ <b>Медиа обновлено.</b>", parse_mode="HTML")
            elif message.video and key2:
                set_setting(key1, message.video.file_id)
                if key2: set_setting(key2, "video")
                bot.send_message(uid, "✅ <b>Медиа обновлено.</b>", parse_mode="HTML")
            elif message.text and message.text.lower() in ['нет', 'удали', 'delete']:
                set_setting(key1, "")
                if key2: set_setting(key2, "none")
                bot.send_message(uid, "✅ <b>Медиа удалено.</b>", parse_mode="HTML")
            return

        # ================== ИСПРАВЛЕННЫЙ БЛОК ==================
        numeric_settings_map = {
            "set_click_reward": "click_reward",
            "set_daily_bonus": "daily_bonus_amount",
            "set_referral_reward": "referral_reward",
            "set_win_chance": "roulette_win_chance",
            "set_subgram_task_reward": "subgram_task_reward",
            "set_click_cooldown": "click_cooldown",
            "set_min_invites": "min_invites_for_withdraw",
            "set_min_invites_transfer": "min_invites_for_transfer",
            "set_subgram_max_sponsors": "subgram_max_sponsors",
        }
        text_settings_map = {
            "set_bot_name": "bot_name",
            "set_clicker_title": "clicker_popup_title",
            "set_share_text": "share_text",
            "set_review_link": "review_channel_link",
            "set_subgram_key": "subgram_api_key",
        }

        if action in numeric_settings_map:
            try:
                value_str = message.text.strip().replace(',', '.')
                setting_key = numeric_settings_map[action]

                if action == "set_click_cooldown":
                    set_setting(setting_key, str(float(value_str) * 60))
                elif "min_invites" in action or "max_sponsors" in action:
                    set_setting(setting_key, str(int(value_str)))
                else:
                    set_setting(setting_key, str(float(value_str)))

                bot.send_message(uid, "✅ <b>Настройка обновлена.</b>", parse_mode="HTML")
            except ValueError:
                bot.send_message(uid, "❌ Ошибка: введите корректное число.", parse_mode="HTML")
            return

        if action in text_settings_map:
            value = "" if message.text.lower() in ['нет', 'удали', 'delete'] else message.text.strip()
            setting_key = text_settings_map[action]
            set_setting(setting_key, value)
            bot.send_message(uid, "✅ <b>Настройка обновлена.</b>", parse_mode="HTML")
            return
        # ================== КОНЕЦ ИСПРАВЛЕННОГО БЛОКА ==================
        
        if action == "change_balance":
            try:
                target_id, amount = map(float, message.text.strip().split()); target_id = int(target_id)
                if not get_user(target_id): bot.send_message(uid, "Пользователь не найден.", parse_mode="HTML")
                else: add_balance(target_id, amount); new_balance = get_user(target_id)['balance']; bot.send_message(uid, f"Баланс {target_id} изменён. Новый: <b>{new_balance:.2f} ⭐</b>", parse_mode="HTML"); bot.send_message(target_id, f"Ваш баланс изменён. Текущий: <b>{new_balance:.2f} ⭐</b>", disable_notification=True, parse_mode="HTML")
            except: bot.send_message(uid, "Ошибка формата. Нужно: <code>user_id amount</code>", parse_mode="HTML")
        elif action == "promo_add":
            try:
                code, reward, uses = message.text.strip().split(); reward = float(reward); uses = int(uses)
                local_cursor.execute("INSERT OR REPLACE INTO promo_codes (code, reward, uses_left) VALUES (?, ?, ?)", (code, reward, uses))
                bot.send_message(uid, f"✅ Промокод <code>{code}</code> создан/обновлен.", parse_mode="HTML")
            except: bot.send_message(uid, "❌ Ошибка формата.", parse_mode="HTML")
        elif action == "promo_delete":
            code = message.text.strip()
            local_cursor.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
            bot.send_message(uid, f"✅ Промокод <code>{code}</code> {'удален' if local_cursor.rowcount > 0 else 'не найден'}.", parse_mode="HTML")
        elif action == "channel_add":
            try:
                chat_id = message.forward_from_chat.id if message.forward_from_chat else message.text.strip()
                chat = bot.get_chat(chat_id)
                local_cursor.execute("INSERT OR REPLACE INTO channels (channel_id, username, title) VALUES (?, ?, ?)", (chat.id, chat.username or "", chat.title))
                bot.send_message(uid, f"✅ Канал «{escape(chat.title)}» добавлен.", parse_mode="HTML")
            except Exception as e: bot.send_message(uid, f"❌ Не удалось добавить канал.\n<b>Ошибка:</b> {e}", parse_mode="HTML")
        elif action == "channel_delete":
            channel_id = message.text.strip()
            local_cursor.execute("DELETE FROM channels WHERE channel_id = ? OR username = ?", (channel_id, channel_id.replace('@', '')))
            bot.send_message(uid, f"✅ Канал <code>{channel_id}</code> {'удален' if local_cursor.rowcount > 0 else 'не найден'}.", parse_mode="HTML")
        return

    if message.text and uid in bot.temp.get("promo_temp", {}):
        promo_code = message.text.strip()
        local_cursor = conn.cursor()
        promo = local_cursor.execute("SELECT reward, uses_left FROM promo_codes WHERE code = ?", (promo_code,)).fetchone()
        if not promo: bot.send_message(uid, "❌ <b>Промокод не найден.</b>", parse_mode="HTML")
        else:
            if local_cursor.execute("SELECT 1 FROM promo_activations WHERE code = ? AND user_id = ?", (promo_code, uid)).fetchone(): bot.send_message(uid, "❌ <b>Вы уже активировали этот промокод.</b>", parse_mode="HTML")
            elif promo[1] == 0: bot.send_message(uid, "❌ <b>Этот промокод закончился.</b>", parse_mode="HTML")
            else:
                reward = promo[0]; add_balance(uid, reward)
                local_cursor.execute("INSERT INTO promo_activations (code, user_id) VALUES (?, ?)", (promo_code, uid))
                if promo[1] != -1: local_cursor.execute("UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?", (promo_code,))
                bot.send_message(uid, f"✅ <b>Промокод успешно активирован!</b> Вам начислено <b>{reward} ⭐</b>.", parse_mode="HTML")
        bot.temp["promo_temp"].pop(uid, None)
        try: bot.delete_message(message.chat.id, message.message_id)
        except: pass
        show_profile_menu(u, message.chat.id)
        return

    if message.text and uid in bot.temp.get("transfer_mode", {}):
        try:
            recipient_id_str, amount_str = message.text.strip().split()
            recipient_id, amount = int(recipient_id_str), float(amount_str)
            if amount <= 0: return bot.send_message(uid, "❌ Сумма должна быть положительной.", parse_mode="HTML")
            if u['balance'] < amount: return bot.send_message(uid, f"❌ Недостаточно средств. У вас {u['balance']:.2f} ⭐", parse_mode="HTML")
            if not get_user(recipient_id): return bot.send_message(uid, "❌ Пользователь с таким ID не найден в боте.", parse_mode="HTML")
            if recipient_id == uid: return bot.send_message(uid, "❌ Нельзя перевести звёзды самому себе.", parse_mode="HTML")
            bot.temp['pending_transfer'][uid] = {'recipient': recipient_id, 'amount': amount}
            bot.send_message(uid, f"✅ Данные приняты: перевод <b>{amount} ⭐</b> пользователю <code>{recipient_id}</code>.\n\nНажмите 'Подтвердить' для выполнения перевода.", parse_mode="HTML")
        except (ValueError, IndexError):
            bot.send_message(uid, "❌ Неверный формат. Отправьте: <code>ID СУММА</code>", parse_mode="HTML")
        return

    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    cmd_start(message)

if __name__ == "__main__":
    print("Бот запущен...")
    bot.infinity_polling(timeout=60)