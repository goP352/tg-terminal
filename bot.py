import json
import logging
import sqlite3
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = "8615677092:AAEjzlE92bqxxMc5990exTja9m6MumAaHFI"
ADMIN_USER_ID = 7605916395
ADMIN_CHAT_ID = -1003769693834
DATABASE = "bot_data.db"
WEBAPP_URL = "https://gop352.github.io/tg-terminal/"

ASSETS = ["USDT", "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "TON", "LTC", "MATIC", "DOT", "AVAX", "LINK", "BCH"]
MAX_SUPPORT_LEN = 1000
MAX_WALLET_LEN = 128

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def db():
    return sqlite3.connect(DATABASE)


def now():
    return datetime.utcnow().isoformat()


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID


def init_db():
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                registered_at TEXT,
                is_blocked INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                asset TEXT,
                free REAL DEFAULT 0,
                locked REAL DEFAULT 0,
                updated_at TEXT,
                UNIQUE(user_id, asset)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                symbol TEXT,
                side TEXT,
                order_type TEXT,
                price REAL,
                amount REAL,
                filled REAL DEFAULT 0,
                status TEXT DEFAULT 'filled',
                take_profit REAL,
                stop_loss REAL,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                symbol TEXT,
                side TEXT,
                size REAL,
                entry_price REAL,
                mark_price REAL,
                pnl REAL DEFAULT 0,
                status TEXT DEFAULT 'open',
                created_at TEXT,
                updated_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                order_id INTEGER,
                symbol TEXT,
                side TEXT,
                price REAL,
                amount REAL,
                fee REAL DEFAULT 0,
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                asset TEXT,
                amount REAL,
                method TEXT,
                wallet TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                processed_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message TEXT,
                status TEXT DEFAULT 'open',
                created_at TEXT
            )
        """)
        conn.commit()


def create_user(user_id: int, username: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (user_id, username, registered_at) VALUES (?, ?, ?)",
                (user_id, username, now()),
            )
            for asset in ASSETS:
                default_free = 10000.0 if asset == "USDT" else 0.0
                cur.execute(
                    "INSERT OR IGNORE INTO balances (user_id, asset, free, locked, updated_at) VALUES (?, ?, ?, 0, ?)",
                    (user_id, asset, default_free, now()),
                )
            conn.commit()


def get_balance_rows(user_id: int):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT asset, free, locked FROM balances WHERE user_id = ? ORDER BY asset",
            (user_id,),
        )
        return cur.fetchall()


def get_asset_balance(user_id: int, asset: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT free, locked FROM balances WHERE user_id = ? AND asset = ?",
            (user_id, asset),
        )
        row = cur.fetchone()
    return row if row else (0.0, 0.0)


def update_asset_balance(user_id: int, asset: str, delta_free: float = 0.0, delta_locked: float = 0.0):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO balances (user_id, asset, free, locked, updated_at) VALUES (?, ?, 0, 0, ?)",
            (user_id, asset, now()),
        )
        cur.execute(
            """
            UPDATE balances
            SET free = free + ?, locked = locked + ?, updated_at = ?
            WHERE user_id = ? AND asset = ?
            """,
            (delta_free, delta_locked, now(), user_id, asset),
        )
        conn.commit()


def create_request(user_id: int, req_type: str, asset: str, amount: float, method: str = "", wallet: str = ""):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO requests (user_id, type, asset, amount, method, wallet, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (user_id, req_type, asset, amount, method, wallet, now()),
        )
        conn.commit()
        return cur.lastrowid


def get_request(request_id: int):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, user_id, type, asset, amount, method, wallet, status FROM requests WHERE id = ?",
            (request_id,),
        )
        return cur.fetchone()


def get_pending_requests():
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, user_id, type, asset, amount, method, wallet, created_at
            FROM requests
            WHERE status = 'pending'
            ORDER BY id ASC
            """
        )
        return cur.fetchall()


def set_request_status(request_id: int, status: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE requests SET status = ?, processed_at = ? WHERE id = ?",
            (status, now(), request_id),
        )
        conn.commit()


def create_market_order(user_id: int, symbol: str, side: str, amount: float, price: float, tp=None, sl=None):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (user_id, symbol, side, order_type, price, amount, filled, status, take_profit, stop_loss, created_at, updated_at)
            VALUES (?, ?, ?, 'market', ?, ?, ?, 'filled', ?, ?, ?, ?)
            """,
            (user_id, symbol, side, price, amount, amount, tp, sl, now(), now()),
        )
        order_id = cur.lastrowid
        fee = round(amount * price * 0.001, 8)
        cur.execute(
            """
            INSERT INTO trades (user_id, order_id, symbol, side, price, amount, fee, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, order_id, symbol, side, price, amount, fee, now()),
        )
        cur.execute(
            """
            INSERT INTO positions (user_id, symbol, side, size, entry_price, mark_price, pnl, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, 'open', ?, ?)
            """,
            (user_id, symbol, side, amount, price, price, now(), now()),
        )
        conn.commit()
        return order_id, fee


def get_open_positions(user_id: int):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, symbol, side, size, entry_price, mark_price, pnl
            FROM positions
            WHERE user_id = ? AND status = 'open'
            ORDER BY id DESC
            """,
            (user_id,),
        )
        return cur.fetchall()


def get_recent_orders(user_id: int, limit: int = 5):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, symbol, side, order_type, price, amount, status, created_at
            FROM orders
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return cur.fetchall()


def add_support_message(user_id: int, text: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO support_messages (user_id, message, status, created_at) VALUES (?, ?, 'open', ?)",
            (user_id, text, now()),
        )
        conn.commit()


def parse_positive_number(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return round(num, 8) if num > 0 else None


def format_request(row):
    req_id, user_id, req_type, asset, amount, method, wallet, created_at = row
    lines = [
        f"Заявка #{req_id}",
        f"Пользователь: {user_id}",
        f"Тип: {req_type}",
        f"Актив: {asset}",
        f"Сумма: {amount:.8f}",
        f"Создана: {created_at}",
    ]
    if method:
        lines.append(f"Метод: {method}")
    if wallet:
        lines.append(f"Кошелек: {wallet}")
    return "\n".join(lines)


def request_markup(request_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Подтвердить", callback_data=f"approve:{request_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"reject:{request_id}"),
        ]
    ])


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Торговать", callback_data="trade"), InlineKeyboardButton("Портфель", callback_data="portfolio")],
        [InlineKeyboardButton("Депозит", callback_data="deposit"), InlineKeyboardButton("Вывод", callback_data="withdraw")],
        [InlineKeyboardButton("Реквизиты", callback_data="requisites"), InlineKeyboardButton("Техподдержка", callback_data="support")],
    ])


def webapp_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("Открыть миниапп", web_app=WebAppInfo(url=WEBAPP_URL))], ["Главное меню"]],
        resize_keyboard=True,
    )


async def notify_group(context: ContextTypes.DEFAULT_TYPE, text: str, markup=None):
    try:
        await context.bot.send_message(ADMIN_CHAT_ID, text, reply_markup=markup)
    except Exception:
        logger.exception("Failed to send message to group")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username or user.full_name)
    await update.message.reply_text("Открой миниапп кнопкой ниже или используй меню.", reply_markup=webapp_keyboard())


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username or user.full_name)
    await update.message.reply_text("Главное меню:", reply_markup=main_menu())


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет доступа.")
        return
    rows = get_pending_requests()
    if not rows:
        await update.message.reply_text("Нет заявок в ожидании.")
        return
    for row in rows:
        await update.message.reply_text(format_request(row), reply_markup=request_markup(row[0]))


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"chat_id: {update.effective_chat.id}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in {"/start", "меню", "главное меню"}:
        await menu(update, context)
        return
    if text in {"/web", "миниапп", "открыть миниапп"}:
        await start(update, context)
        return
    await update.message.reply_text("Используй кнопки меню или /web.")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    create_user(user.id, user.username or user.full_name)

    if data == "trade":
        await query.message.reply_text("Открой миниапп для торговли.", reply_markup=webapp_keyboard())
        return

    if data == "portfolio":
        rows = get_balance_rows(user.id)
        positions = get_open_positions(user.id)
        orders = get_recent_orders(user.id, 5)

        balance_lines = []
        for asset, free, locked in rows:
            balance_lines.append(
                f"{asset}\n"
                f"Свободно: {free:.8f}\n"
                f"Заблокировано: {locked:.8f}"
            )

        position_lines = []
        for pos_id, symbol, side, size, entry_price, mark_price, pnl in positions:
            position_lines.append(
                f"{symbol}\n"
                f"Сторона: {side}\n"
                f"Размер: {size:.8f}\n"
                f"Вход: {entry_price:.8f}\n"
                f"Текущая цена: {mark_price:.8f}\n"
                f"PnL: {pnl:.8f}"
            )

        order_lines = []
        for order_id, symbol, side, order_type, price, amount, status, created_at in orders:
            order_lines.append(
                f"Ордер #{order_id}\n"
                f"Пара: {symbol}\n"
                f"Сторона: {side}\n"
                f"Тип: {order_type}\n"
                f"Цена: {price:.8f}\n"
                f"Количество: {amount:.8f}\n"
                f"Статус: {status}"
            )

        text = "Портфель\n\n"
        text += "Балансы:\n"
        text += "\n\n".join(balance_lines) if balance_lines else "Нет данных"
        text += "\n\nПозиции:\n"
        text += "\n\n".join(position_lines) if position_lines else "Нет открытых позиций"
        text += "\n\nПоследние ордера:\n"
        text += "\n\n".join(order_lines) if order_lines else "Нет ордеров"

        await query.message.reply_text(text)
        return

    if data == "deposit":
        await query.message.reply_text("Открой миниапп, чтобы создать заявку на пополнение.", reply_markup=webapp_keyboard())
        return

    if data == "withdraw":
        await query.message.reply_text("Открой миниапп, чтобы создать заявку на вывод.", reply_markup=webapp_keyboard())
        return

    if data == "requisites":
        await query.message.reply_text("Реквизиты можно добавить позже через базу или админку.")
        return

    if data == "support":
        await query.message.reply_text("Открой миниапп, чтобы написать в поддержку.", reply_markup=webapp_keyboard())
        return

    if data.startswith("approve:") or data.startswith("reject:"):
        if not is_admin(user.id):
            await query.message.reply_text("У вас нет доступа.")
            return
        action, request_id_raw = data.split(":", 1)
        try:
            request_id = int(request_id_raw)
        except ValueError:
            await query.message.reply_text("Некорректный ID заявки.")
            return

        row = get_request(request_id)
        if not row:
            await query.message.reply_text("Заявка не найдена.")
            return

        req_id, target_user_id, req_type, asset, amount, method, wallet, status = row
        if status != "pending":
            await query.message.reply_text("Эта заявка уже обработана.")
            return

        if action == "approve":
            if req_type == "deposit":
                update_asset_balance(target_user_id, asset, delta_free=amount)
                set_request_status(req_id, "approved")
                await context.bot.send_message(target_user_id, f"Пополнение #{req_id} подтверждено: {amount:.8f} {asset}")
                await query.message.reply_text(f"Заявка #{req_id} подтверждена.")
                return

            if req_type == "withdraw":
                free_balance, _ = get_asset_balance(target_user_id, asset)
                if free_balance < amount:
                    set_request_status(req_id, "rejected")
                    await context.bot.send_message(target_user_id, f"Вывод #{req_id} отклонен: недостаточно {asset}.")
                    await query.message.reply_text(f"Заявка #{req_id} отклонена: недостаточно средств.")
                    return
                update_asset_balance(target_user_id, asset, delta_free=-amount)
                set_request_status(req_id, "approved")
                await context.bot.send_message(target_user_id, f"Вывод #{req_id} подтвержден: {amount:.8f} {asset}")
                await query.message.reply_text(f"Заявка #{req_id} подтверждена.")
                return

        if action == "reject":
            set_request_status(req_id, "rejected")
            await context.bot.send_message(target_user_id, f"Заявка #{req_id} отклонена.")
            await query.message.reply_text(f"Заявка #{req_id} отклонена.")
            return


async def webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    web_app_data = getattr(message, "web_app_data", None)
    if not web_app_data:
        return

    user = update.effective_user
    create_user(user.id, user.username or user.full_name)

    try:
        payload = json.loads(web_app_data.data)
    except json.JSONDecodeError:
        await message.reply_text("Ошибка чтения данных миниаппа.")
        return

    action = payload.get("action")

    if action == "portfolio":
        rows = get_balance_rows(user.id)
        positions = get_open_positions(user.id)
        orders = get_recent_orders(user.id, 5)

        balance_lines = []
        for asset, free, locked in rows:
            balance_lines.append(
                f"{asset}\n"
                f"Свободно: {free:.8f}\n"
                f"Заблокировано: {locked:.8f}"
            )

        position_lines = []
        for pos_id, symbol, side, size, entry_price, mark_price, pnl in positions:
            position_lines.append(
                f"{symbol}\n"
                f"Сторона: {side}\n"
                f"Размер: {size:.8f}\n"
                f"Вход: {entry_price:.8f}\n"
                f"Текущая цена: {mark_price:.8f}\n"
                f"PnL: {pnl:.8f}"
            )

        order_lines = []
        for order_id, symbol, side, order_type, price, amount, status, created_at in orders:
            order_lines.append(
                f"Ордер #{order_id}\n"
                f"Пара: {symbol}\n"
                f"Сторона: {side}\n"
                f"Тип: {order_type}\n"
                f"Цена: {price:.8f}\n"
                f"Количество: {amount:.8f}\n"
                f"Статус: {status}"
            )

        text = "Портфель\n\n"
        text += "Балансы:\n"
        text += "\n\n".join(balance_lines) if balance_lines else "Нет данных"
        text += "\n\nПозиции:\n"
        text += "\n\n".join(position_lines) if position_lines else "Нет открытых позиций"
        text += "\n\nПоследние ордера:\n"
        text += "\n\n".join(order_lines) if order_lines else "Нет ордеров"

        await message.reply_text(text)
        return

    if action == "trade":
        coin = str(payload.get("coin", "")).upper()
        direction = str(payload.get("direction", "")).lower()
        amount = parse_positive_number(payload.get("amount"))
        price = parse_positive_number(payload.get("price"))
        tp = parse_positive_number(payload.get("take_profit")) if payload.get("take_profit") else None
        sl = parse_positive_number(payload.get("stop_loss")) if payload.get("stop_loss") else None

        if coin not in ASSETS or coin == "USDT":
            await message.reply_text("Недопустимая торговая монета.")
            return
        if direction not in {"long", "short"}:
            await message.reply_text("Недопустимое направление.")
            return
        if amount is None or price is None:
            await message.reply_text("Введите корректные сумму и цену.")
            return

        cost = round(amount * price, 8)
        fee_balance, _ = get_asset_balance(user.id, "USDT")
        if fee_balance < cost:
            await message.reply_text("Недостаточно USDT для открытия сделки.")
            return

        update_asset_balance(user.id, "USDT", delta_free=-cost)
        order_id, fee = create_market_order(user.id, f"{coin}/USDT", direction, amount, price, tp, sl)

        if direction == "long":
            update_asset_balance(user.id, coin, delta_free=amount)

        await message.reply_text(f"Сделка открыта. Ордер #{order_id}. Комиссия: {fee:.8f} USDT")
        return

    if action == "deposit":
        asset = str(payload.get("currency", "")).upper()
        amount = parse_positive_number(payload.get("amount"))
        method = str(payload.get("method", "")).lower()

        if asset not in ASSETS:
            await message.reply_text("Недопустимая валюта пополнения.")
            return
        if amount is None:
            await message.reply_text("Введите корректную сумму.")
            return
        if method not in {"crypto", "card"}:
            await message.reply_text("Недопустимый способ пополнения.")
            return

        request_id = create_request(user.id, "deposit", asset, amount, method=method)
        await message.reply_text(f"Заявка на пополнение #{request_id} создана.")
        row = (request_id, user.id, "deposit", asset, amount, method, "", now())
        await notify_group(context, format_request(row), request_markup(request_id))
        return

    if action == "withdraw":
        asset = str(payload.get("currency", "")).upper()
        amount = parse_positive_number(payload.get("amount"))
        wallet = str(payload.get("wallet", "")).strip()

        if asset not in ASSETS:
            await message.reply_text("Недопустимая валюта вывода.")
            return
        if amount is None or not wallet:
            await message.reply_text("Введите корректные данные.")
            return
        if len(wallet) > MAX_WALLET_LEN:
            await message.reply_text("Кошелек слишком длинный.")
            return

        request_id = create_request(user.id, "withdraw", asset, amount, wallet=wallet)
        await message.reply_text(f"Заявка на вывод #{request_id} создана.")
        row = (request_id, user.id, "withdraw", asset, amount, "", wallet, now())
        await notify_group(context, format_request(row), request_markup(request_id))
        return

    if action == "support":
        text = str(payload.get("message", "")).strip()
        if not text:
            await message.reply_text("Напишите сообщение.")
            return
        if len(text) > MAX_SUPPORT_LEN:
            await message.reply_text("Сообщение слишком длинное.")
            return
        add_support_message(user.id, text)
        await message.reply_text("Сообщение отправлено.")
        await notify_group(context, f"Техподдержка от {user.id}:\n{text}")
        return

    await message.reply_text("Неизвестное действие.")


def main():
    if not TOKEN or TOKEN == "ВСТАВЬ_СЮДА_ТОКЕН":
        raise RuntimeError("Вставь токен в TOKEN.")
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("web", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_data))
    app.run_polling()


if __name__ == "__main__":
    main()
