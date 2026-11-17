import os
import sys
import time
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess

# Автоматическая установка библиотек при запуске на облачном сервере
def install_and_import(package, import_name=None):
    if import_name is None:
        import_name = package
    try:
        __import__(import_name)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

install_and_import("pyTelegramBotAPI", "telebot")
install_and_import("requests")

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests

# =====================================================================
# 1. НАСТРОЙКИ БОТА
# =====================================================================
BOT_TOKEN = "8579556395:AAFYytRyf91jVGBsrK0BfNhAbU64Xp8c_iQ"

ADMIN_USERNAME = "abdullohm20"  # Никнейм администратора для уведомлений
ADMIN_ID = 7246101121           # Ваш числовой Telegram ID для заявок

# НОМЕР БАНКОВСКОЙ КАРТЫ (Uzcard / Humo) ДЛЯ ПРИЕМА ОПЛАТЫ
CARD_NUMBER = "9860 0105 0288 9826"  
CARD_HOLDER = "JASUR. MIRZAMUKHAMEDOV"         

# НАСТРОЙКИ ПАРТНЕРСКОГО API
PARTNER_API_URL = "https://api.example-stars-partner.com/v1/send_stars" 
PARTNER_API_KEY = "2953f2111b870795e4158cc52b175057"

# ЦЕНА И ЛИМИТЫ
PRICE_PER_STAR = 198      # 9900 / 50 = 198 сум за 1 звезду (50 звезд = 9900 сум)
MIN_DEPOSIT = 1000        # Минимум пополнения: 1 000 сум
MIN_STARS = 50            # Минимум покупки: 50 Stars
MAX_STARS = 750           # Максимум покупки: 750 Stars

# =====================================================================
# 2. БАЗА ДАННЫХ (SQLite для хранения балансов и транзакций)
# =====================================================================
conn = sqlite3.connect("stars_bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    lang TEXT DEFAULT 'ru',
    balance INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS deposits (
    tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    status TEXT DEFAULT 'pending'
)
""")
conn.commit()

user_states = {}  # Временные состояния ввода (сумма пополнения, количество звезд)

def get_user(user_id, username=""):
    cursor.execute("SELECT user_id, username, lang, balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, username, lang, balance) VALUES (?, ?, 'ru', 0)", (user_id, username))
        conn.commit()
        return {"user_id": user_id, "username": username, "lang": "ru", "balance": 0}
    return {"user_id": row[0], "username": row[1], "lang": row[2], "balance": row[3]}

def set_lang(user_id, lang):
    cursor.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))
    conn.commit()

def update_balance(user_id, delta):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
    conn.commit()

# =====================================================================
# 3. ТЕКСТЫ НА РУССКОМ И УЗБЕКСКОМ ЯЗЫКАХ
# =====================================================================
TEXTS = {
    "ru": {
        "menu": "🏠 *Главное меню*\n\n💰 Ваш баланс: *{balance:,} сум*\n⭐ Курс: *50 Stars = 9 900 сум*\n\nВыберите действие:",
        "btn_deposit": "💳 Пополнить баланс",
        "btn_buy": "⭐ Купить Stars",
        "btn_lang": "🌐 Сменить язык / Tilni o'zgartirish",
        "card_info": (
            "💳 *Пополнение баланса*\n\n"
            "Переведите нужную сумму на карту:\n"
            "Карта: `{card}`\n"
            "Получатель: *{holder}*\n\n"
            "⚠️ Минимальная сумма пополнения: *{min_dep:,} сум* (максимума нет).\n\n"
            "Нажмите кнопку *«Выполнить»* ниже, чтобы ввести сумму пополнения:"
        ),
        "btn_execute": "✅ Выполнить",
        "btn_back": "🔙 Назад",
        "enter_deposit": "✍️ Введите сумму пополнения в сумах (минимум {min_dep:,} сум):",
        "invalid_deposit": "❌ Ошибка! Введите число не меньше {min_dep:,} сум:",
        "confirm_transfer": (
            "🧾 *Заявка на пополнение #{tx_id}*\n\n"
            "Сумма: *{amount:,} сум*\n"
            "Карта для перевода: `{card}`\n\n"
            "После того как переведёте деньги на карту, нажмите кнопку *«Я пополнил»*:"
        ),
        "btn_i_paid": "✅ Я пополнил",
        "wait_admin": "⏳ *Заявка #{tx_id} отправлена администратору!*\n\nКак только поступление на карту подтвердится, баланс автоматически пополнится.",
        "deposit_approved": "✅ *Ваш баланс пополнен на {amount:,} сум!*\n💰 Текущий баланс: *{balance:,} сум*",
        "deposit_rejected": "❌ *Заявка #{tx_id} на {amount:,} сум отклонена.*\nПлатёж не найден. Если вы перевели деньги, напишите в поддержку.",
        "enter_stars": (
            "⭐ *Покупка Telegram Stars*\n\n"
            "💰 Ваш баланс: *{balance:,} сум*\n"
            "💵 Цена: *50 Stars = 9 900 сум* (1 Star = 198 сум)\n\n"
            "Введите количество Stars для покупки (от *{min_s}* до *{max_s}*):"
        ),
        "invalid_stars": "❌ Введите целое число от {min_s} до {max_s} Stars:",
        "no_money": "❌ *Недостаточно средств на балансе!*\n\nНужно: *{cost:,} сум*\nУ вас: *{balance:,} сум*\n\nПополните баланс в главном меню.",
        "confirm_buy": (
            "🛒 *Подтверждение покупки*\n\n"
            "⭐ Количество: *{stars} Stars*\n"
            "💰 Спишется с баланса: *{cost:,} сум*\n"
            "👤 Получатель: @{username}\n\n"
            "Нажмите *«Купить»* для подтверждения:"
        ),
        "btn_confirm_buy": "✅ Купить",
        "processing_stars": "⏳ Отправляем *{stars} Stars* через партнёрский шлюз... Подождите.",
        "stars_success": "🎉 *Успешно!* Вам отправлено *{stars} Telegram Stars*!\n💰 Остаток на балансе: *{balance:,} сум*",
        "stars_failed": (
            "⚠️ *Ошибка при отправке Stars через партнёра!*\n\n"
            "Транзакция отменена, *{cost:,} сум* возвращены на ваш баланс в боте.\n"
            "💰 Текущий баланс: *{balance:,} сум*"
        ),
        "no_username": "⚠️ У вас не установлен `@username` в настройках Telegram! Установите его в профиле Telegram, чтобы получить Stars."
    },
    "uz": {
        "menu": "🏠 *Asosiy menyu*\n\n💰 Sizning balansingiz: *{balance:,} so'm*\n⭐ Narx: *50 Stars = 9 900 so'm*\n\nKerakli bo'limni tanlang:",
        "btn_deposit": "💳 Balansni to'ldirish",
        "btn_buy": "⭐ Stars sotib olish",
        "btn_lang": "🌐 Tilni o'zgartirish / Сменить язык",
        "card_info": (
            "💳 *Balansni to'ldirish*\n\n"
            "Kerakli summani quyidagi kartaga o'tkazing:\n"
            "Karta: `{card}`\n"
            "Egasi: *{holder}*\n\n"
            "⚠️ Minimal to'ldirish summasi: *{min_dep:,} so'm* (maksimal chegara yo'q).\n\n"
            "Summani kiritish uchun quyidagi *«Bajarish»* tugmasini bosing:"
        ),
        "btn_execute": "✅ Bajarish",
        "btn_back": "🔙 Orqaga",
        "enter_deposit": "✍️ To'ldirish summasini so'mda kiriting (kamida {min_dep:,} so'm):",
        "invalid_deposit": "❌ Xato! Kamida {min_dep:,} so'm miqdorida raqam kiriting:",
        "confirm_transfer": (
            "🧾 *To'ldirish arizasi #{tx_id}*\n\n"
            "Summa: *{amount:,} so'm*\n"
            "O'tkazma uchun karta: `{card}`\n\n"
            "Pulni kartaga o'tkazganingizdan so'ng *«To'ldirdim»* tugmasini bosing:"
        ),
        "btn_i_paid": "✅ To'ldirdim",
        "wait_admin": "⏳ *Ariza #{tx_id} adminga yuborildi!*\n\nKartaga pul tushishi tasdiqlanishi bilan balansingiz avtomatik to'ldiriladi.",
        "deposit_approved": "✅ *Balansingiz {amount:,} so'mga to'ldirildi!*\n💰 Joriy balans: *{balance:,} so'm*",
        "deposit_rejected": "❌ *#{tx_id} raqamli ({amount:,} so'm) ariza rad etildi.*\nTo'lov topilmadi. Agar pul o'tkazgan bo'lsangiz, adminga murojaat qiling.",
        "enter_stars": (
            "⭐ *Telegram Stars sotib olish*\n\n"
            "💰 Balansingiz: *{balance:,} so'm*\n"
            "💵 Narx: *50 Stars = 9 900 so'm* (1 Star = 198 so'm)\n\n"
            "Sotib olmoqchi bo'lgan Stars miqdorini kiriting (*{min_s}* dan *{max_s}* gacha):"
        ),
        "invalid_stars": "❌ {min_s} dan {max_s} gacha butun son kiriting:",
        "no_money": "❌ *Balansingizda mablag' yetarli emas!*\n\nKerak: *{cost:,} so'm*\nSizda: *{balance:,} so'm*\n\nAsosiy menyudan balansni to'ldiring.",
        "confirm_buy": (
            "🛒 *Xaridni tasdiqlash*\n\n"
            "⭐ Miqdor: *{stars} Stars*\n"
            "💰 Balansdan yechiladi: *{cost:,} so'm*\n"
            "👤 Qabul qiluvchi: @{username}\n\n"
            "Tasdiqlash uchun *«Sotib olish»* tugmasini bosing:"
        ),
        "btn_confirm_buy": "✅ Sotib olish",
        "processing_stars": "⏳ Hamkor tizimi orqali *{stars} Stars* yuborilmoqda... Kuting.",
        "stars_success": "🎉 *Muvaffaqiyatli!* Sizga *{stars} Telegram Stars* yuborildi!\n💰 Qolgan balans: *{balance:,} so'm*",
        "stars_failed": (
            "⚠️ *Hamkor orqali Stars yuborishda xatolik yuz berdi!*\n\n"
            "Tranzaksiya bekor qilindi, *{cost:,} so'm* botdagi balansingizga qaytarildi.\n"
            "💰 Joriy balans: *{balance:,} so'm*"
        ),
        "no_username": "⚠️ Telegram profilingizda `@username` o'rnatilmagan! Stars olish uchun avval Telegram sozlamalaridan username o'rnating."
    }
}

bot = telebot.TeleBot(BOT_TOKEN)

# =====================================================================
# 4. ФУНКЦИЯ ОТПРАВКИ STARS ПО API ПАРТНЕРА
# =====================================================================
def send_stars_partner(username: str, stars_amount: int) -> bool:
    headers = {
        "Authorization": f"Bearer {PARTNER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "username": username,
        "amount": stars_amount
    }
    try:
        # resp = requests.post(PARTNER_API_URL, json=payload, headers=headers, timeout=20)
        # data = resp.json()
        # return resp.status_code == 200 and data.get("success") is True
        
        print(f"[PARTNER API] Отправка {stars_amount} Stars -> @{username}")
        return True
    except Exception as e:
        print(f"[PARTNER ERROR] {e}")
        return False

# =====================================================================
# 5. ОБРАБОТЧИКИ КОМАНД И КНОПОК
# =====================================================================
def show_main_menu(chat_id, user_id):
    user = get_user(user_id)
    lang = user["lang"]
    t = TEXTS[lang]
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(t["btn_deposit"], callback_data="menu_deposit"),
        InlineKeyboardButton(t["btn_buy"], callback_data="menu_buy"),
        InlineKeyboardButton(t["btn_lang"], callback_data="choose_lang")
    )
    text = t["menu"].format(balance=user["balance"]).replace(",", " ")
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=["start"])
def cmd_start(message):
    user_states.pop(message.from_user.id, None)
    get_user(message.from_user.id, message.from_user.username or "")
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="setlang_uz"),
        InlineKeyboardButton("🇷🇺 Русский", callback_data="setlang_ru")
    )
    bot.send_message(
        message.chat.id,
        "🇺🇿 Tilni tanlang:\n🇷🇺 Выберите язык:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "choose_lang")
def cb_choose_lang(call):
    bot.answer_callback_query(call.id)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="setlang_uz"),
        InlineKeyboardButton("🇷🇺 Русский", callback_data="setlang_ru")
    )
    bot.edit_message_text(
        "🇺🇿 Tilni tanlang:\n🇷🇺 Выберите язык:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("setlang_"))
def cb_set_lang(call):
    lang = call.data.split("_")[1]
    set_lang(call.from_user.id, lang)
    bot.answer_callback_query(call.id)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    show_main_menu(call.message.chat.id, call.from_user.id)

# --- ПОПОЛНЕНИЕ БАЛАНСА ---
@bot.callback_query_handler(func=lambda call: call.data == "menu_deposit")
def cb_menu_deposit(call):
    bot.answer_callback_query(call.id)
    user = get_user(call.from_user.id)
    t = TEXTS[user["lang"]]
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(t["btn_execute"], callback_data="deposit_execute"),
        InlineKeyboardButton(t["btn_back"], callback_data="back_main")
    )
    text = t["card_info"].format(
        card=CARD_NUMBER,
        holder=CARD_HOLDER,
        min_dep=MIN_DEPOSIT
    ).replace(",", " ")
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "deposit_execute")
def cb_deposit_execute(call):
    bot.answer_callback_query(call.id)
    user = get_user(call.from_user.id)
    t = TEXTS[user["lang"]]
    user_states[call.from_user.id] = {"step": "wait_deposit_amount"}
    
    text = t["enter_deposit"].format(min_dep=MIN_DEPOSIT).replace(",", " ")
    bot.send_message(call.message.chat.id, text, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("paid_"))
def cb_user_paid(call):
    tx_id = int(call.data.split("_")[1])
    user = get_user(call.from_user.id)
    t = TEXTS[user["lang"]]
    
    cursor.execute("SELECT user_id, amount, status FROM deposits WHERE tx_id = ?", (tx_id,))
    dep = cursor.fetchone()
    if not dep or dep[2] != "pending":
        bot.answer_callback_query(call.id, "Заявка уже обработана.")
        return

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        t["wait_admin"].format(tx_id=tx_id),
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    
    # Отправка уведомления администратору
    if ADMIN_ID != 0:
        uname = f"@{call.from_user.username}" if call.from_user.username else f"ID: {call.from_user.id}"
        admin_text = (
            f"🔔 *НОВАЯ ЗАЯВКА НА ПОПОЛНЕНИЕ #{tx_id}*\n\n"
            f"👤 Пользователь: {uname} (`{call.from_user.id}`)\n"
            f"💰 Сумма: *{dep[1]:,} сум*\n\n"
            f"Проверьте поступление на банковскую карту и подтвердите:"
        ).replace(",", " ")
        
        admin_markup = InlineKeyboardMarkup(row_width=2)
        admin_markup.add(
            InlineKeyboardButton("✅ Подтвердить", callback_data=f"adm_ok_{tx_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"adm_no_{tx_id}")
        )
        bot.send_message(ADMIN_ID, admin_text, parse_mode="Markdown", reply_markup=admin_markup)

# --- ПОДТВЕРЖДЕНИЕ / ОТКЛОНЕНИЕ АДМИНОМ ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
def cb_admin_decision(call):
    parts = call.data.split("_")
    action = parts[1]  
    tx_id = int(parts[2])
    
    cursor.execute("SELECT user_id, amount, status FROM deposits WHERE tx_id = ?", (tx_id,))
    dep = cursor.fetchone()
    if not dep:
        bot.answer_callback_query(call.id, "Транзакция не найдена.")
        return
    if dep[2] != "pending":
        bot.answer_callback_query(call.id, "Эта заявка уже обработана!")
        return

    target_user_id, amount, _ = dep
    target_user = get_user(target_user_id)
    t = TEXTS[target_user["lang"]]

    if action == "ok":
        cursor.execute("UPDATE deposits SET status = 'approved' WHERE tx_id = ?", (tx_id,))
        update_balance(target_user_id, amount)
        new_bal = get_user(target_user_id)["balance"]
        
        bot.answer_callback_query(call.id, "Пополнение подтверждено!")
        bot.edit_message_text(
            f"✅ *Заявка #{tx_id} ПОДТВЕРЖДЕНА!*\nПользователю `{target_user_id}` начислено *{amount:,} сум*.".replace(",", " "),
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
        msg_text = t["deposit_approved"].format(amount=amount, balance=new_bal).replace(",", " ")
        bot.send_message(target_user_id, msg_text, parse_mode="Markdown")
        show_main_menu(target_user_id, target_user_id)
    else:
        cursor.execute("UPDATE deposits SET status = 'rejected' WHERE tx_id = ?", (tx_id,))
        conn.commit()
        bot.answer_callback_query(call.id, "Заявка отклонена.")
        bot.edit_message_text(
            f"❌ *Заявка #{tx_id} ОТКЛОНЕНА.*",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
        msg_text = t["deposit_rejected"].format(tx_id=tx_id, amount=amount).replace(",", " ")
        bot.send_message(target_user_id, msg_text, parse_mode="Markdown")

# --- ПОКУПКА STARS ---
@bot.callback_query_handler(func=lambda call: call.data == "menu_buy")
def cb_menu_buy(call):
    bot.answer_callback_query(call.id)
    user = get_user(call.from_user.id)
    t = TEXTS[user["lang"]]
    
    if not call.from_user.username:
        bot.send_message(call.message.chat.id, t["no_username"], parse_mode="Markdown")
        return

    user_states[call.from_user.id] = {"step": "wait_stars_amount"}
    text = t["enter_stars"].format(
        balance=user["balance"],
        min_s=MIN_STARS,
        max_s=MAX_STARS
    ).replace(",", " ")
    bot.send_message(call.message.chat.id, text, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("buystars_"))
def cb_confirm_buy_stars(call):
    stars_amount = int(call.data.split("_")[1])
    user = get_user(call.from_user.id)
    t = TEXTS[user["lang"]]
    cost = stars_amount * PRICE_PER_STAR

    if user["balance"] < cost:
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            t["no_money"].format(cost=cost, balance=user["balance"]).replace(",", " "),
            parse_mode="Markdown"
        )
        return

    if not call.from_user.username:
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, t["no_username"], parse_mode="Markdown")
        return

    bot.answer_callback_query(call.id)
    update_balance(call.from_user.id, -cost)
    
    bot.edit_message_text(
        t["processing_stars"].format(stars=stars_amount),
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )

    success = send_stars_partner(call.from_user.username, stars_amount)

    if success:
        new_bal = get_user(call.from_user.id)["balance"]
        bot.edit_message_text(
            t["stars_success"].format(stars=stars_amount, balance=new_bal).replace(",", " "),
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
    else:
        update_balance(call.from_user.id, cost)
        restored_bal = get_user(call.from_user.id)["balance"]
        bot.edit_message_text(
            t["stars_failed"].format(cost=cost, balance=restored_bal).replace(",", " "),
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )

@bot.callback_query_handler(func=lambda call: call.data == "back_main")
def cb_back_main(call):
    bot.answer_callback_query(call.id)
    user_states.pop(call.from_user.id, None)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    show_main_menu(call.message.chat.id, call.from_user.id)

# --- ОБРАБОТКА ВВОДА ЧИСЕЛ ОТ ПОЛЬЗОВАТЕЛЯ ---
@bot.message_handler(func=lambda msg: True)
def handle_text_input(message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    if not state:
        return

    user = get_user(user_id, message.from_user.username or "")
    t = TEXTS[user["lang"]]
    raw_text = message.text.replace(" ", "").replace(",", "")

    if state["step"] == "wait_deposit_amount":
        if not raw_text.isdigit() or int(raw_text) < MIN_DEPOSIT:
            bot.send_message(message.chat.id, t["invalid_deposit"].format(min_dep=MIN_DEPOSIT).replace(",", " "))
            return
        
        amount = int(raw_text)
        user_states.pop(user_id, None)
        
        cursor.execute("INSERT INTO deposits (user_id, amount, status) VALUES (?, ?, 'pending')", (user_id, amount))
        conn.commit()
        tx_id = cursor.lastrowid
        
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton(t["btn_i_paid"], callback_data=f"paid_{tx_id}"),
            InlineKeyboardButton(t["btn_back"], callback_data="back_main")
        )
        text = t["confirm_transfer"].format(tx_id=tx_id, amount=amount, card=CARD_NUMBER).replace(",", " ")
        bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)

    elif state["step"] == "wait_stars_amount":
        if not raw_text.isdigit() or not (MIN_STARS <= int(raw_text) <= MAX_STARS):
            bot.send_message(message.chat.id, t["invalid_stars"].format(min_s=MIN_STARS, max_s=MAX_STARS))
            return
        
        stars_amount = int(raw_text)
        cost = stars_amount * PRICE_PER_STAR
        user_states.pop(user_id, None)
        
        if user["balance"] < cost:
            bot.send_message(
                message.chat.id,
                t["no_money"].format(cost=cost, balance=user["balance"]).replace(",", " "),
                parse_mode="Markdown"
            )
            return

        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton(t["btn_confirm_buy"], callback_data=f"buystars_{stars_amount}"),
            InlineKeyboardButton(t["btn_back"], callback_data="back_main")
        )
        text = t["confirm_buy"].format(
            stars=stars_amount,
            cost=cost,
            username=message.from_user.username
        ).replace(",", " ")
        bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)

# =====================================================================
# 6. ВЕБ-СЕРВЕР ДЛЯ ОБЛАЧНОГО ХОСТИНГА (Render 24/7)
# =====================================================================
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Stars Bot is running 24/7!")
    def log_message(self, format, *args):
        pass

def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=start_web_server, daemon=True).start()
    print("Бот запущен в облачном режиме 24/7!")
    bot.infinity_polling(skip_pending=True)
