import os
import json
import sqlite3
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ============================================================
# PONDER WONDER CAFE — TELEGRAM ORDER BOT
# ============================================================

TZ = ZoneInfo("Asia/Singapore")
OPEN_TIME = time(7, 0)
CLOSE_TIME = time(22, 0)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_IDS = int(os.environ.get("ADMIN_CHAT_IDS", "0"))
DB_PATH = os.environ.get("DB_PATH", "orders.db")
QR_PATH = os.environ.get("QR_PATH", "paynow_qr.png")

# Menu from the latest customer-provided menu photo.
MENU = {
    "iced_matcha_latte": {
        "name": "Iced Matcha Latte", "price": 5.50,
        "sweetness": True, "milk": True,
    },
    "iced_earl_grey_matcha": {
        "name": "Iced Earl Grey Matcha Latte", "price": 6.00,
        "sweetness": True, "milk": True,
    },
    "iced_vanilla_matcha": {
        "name": "Iced Vanilla Matcha Latte", "price": 6.00,
        "sweetness": True, "milk": True,
    },
    "iced_banana_matcha": {
        "name": "Iced Banana Matcha Latte", "price": 6.50,
        "sweetness": False, "milk": False,
    },
    "iced_strawberry_matcha": {
        "name": "Iced Strawberry Matcha Latte", "price": 6.50,
        "sweetness": False, "milk": False,
    },
    "iced_earl_grey_latte": {
        "name": "Iced Earl Grey Latte", "price": 5.50,
        "sweetness": True, "milk": True,
    },
    "iced_vanilla_latte": {
        "name": "Iced Vanilla Latte", "price": 5.50,
        "sweetness": True, "milk": True,
    },
    "iced_banana_latte": {
        "name": "Iced Banana Latte (Kids Friendly)", "price": 6.00,
        "sweetness": False, "milk": False,
    },
    "iced_strawberry_latte": {
        "name": "Iced Strawberry Latte (Kids Friendly)", "price": 6.00,
        "sweetness": False, "milk": False,
    },
}

# Photo specifies sweetness only for menu 1, 2, 3, 6, 7.
SWEETNESS_OPTIONS = {
    "0": "0% sugar",
    "50": "50% sugar",
    "100": "100% sugar",
}

MILK_OPTIONS = {
    "dairy": ("Dairy milk", 0.00),
    "oat": ("Oat milk", 0.50),
}

# Cold foam is available for every drink.
FOAM_OPTIONS = {
    "none": ("No cold foam", 0.00),
    "lavender": ("Lavender cold foam", 1.00),
    "vanilla": ("Vanilla cold foam", 1.00),
}

COLLECTION_OPTIONS = {
    "now": "Immediate",
    "15": "15 mins",
    "30": "30 mins",
    "60": "1 hour",
}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# -------------------- DATABASE --------------------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            username TEXT,
            customer_name TEXT,
            items TEXT NOT NULL,
            total REAL NOT NULL,
            collection TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PAYMENT_PENDING',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def create_order(user, items, total, collection):
    conn = db()
    cur = conn.execute("""
        INSERT INTO orders
        (telegram_user_id, username, customer_name, items, total, collection, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user.id,
        user.username or "",
        user.full_name,
        json.dumps(items),
        total,
        collection,
        datetime.now(TZ).isoformat(timespec="seconds"),
    ))
    order_id = cur.lastrowid
    conn.commit()
    conn.close()
    return order_id


def update_order_status(order_id, status):
    conn = db()
    conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    conn.commit()
    conn.close()


def get_order(order_id):
    conn = db()
    row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    conn.close()
    return row


# -------------------- ADMIN ORDER VIEWS --------------------

ACTIVE_STATUSES = (
    "PAYMENT_PENDING",
    "PAYMENT_REPORTED",
    "PAYMENT_SCREENSHOT_RECEIVED",
    "PAYMENT_CONFIRMED",
    "PREPARING",
    "READY",
)

STATUS_LABELS = {
    "PAYMENT_PENDING": "💳 Payment pending",
    "PAYMENT_REPORTED": "⚠️ Payment reported",
    "PAYMENT_SCREENSHOT_RECEIVED": "📸 Screenshot received",
    "PAYMENT_CONFIRMED": "💰 Payment confirmed",
    "PREPARING": "🍵 Preparing",
    "READY": "📦 Ready for collection",
    "COLLECTED": "✅ Collected / completed",
    "CANCELLED": "❌ Cancelled",
}


def get_active_orders():
    conn = db()
    rows = conn.execute(
        "SELECT * FROM orders WHERE status IN ({}) ORDER BY id ASC".format(
            ",".join("?" for _ in ACTIVE_STATUSES)
        ),
        ACTIVE_STATUSES,
    ).fetchall()
    conn.close()
    return rows


def get_completed_orders():
    conn = db()
    rows = conn.execute(
        "SELECT * FROM orders WHERE status='COLLECTED' ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return rows


def format_order_summary(order):
    items = json.loads(order["items"])
    item_text = ", ".join(f"{x['qty']}× {x['name']}" for x in items)
    status = STATUS_LABELS.get(order["status"], order["status"])
    return (
        f"<b>#{order['id']}</b> — {status}\n"
        f"👤 {order['customer_name']}\n"
        f"🍵 {item_text}\n"
        f"💰 ${order['total']:.2f} · 🏠 {order['collection']}\n"
        f"🕐 {order['created_at'].replace('T', ' ')}"
    )


def admin_dashboard_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 New Orders", callback_data="admin:view:new"),
            InlineKeyboardButton("📦 Completed", callback_data="admin:view:completed"),
        ],
        [InlineKeyboardButton("📊 Order Counts", callback_data="admin:view:counts")],
        [
            InlineKeyboardButton("🔒 Close Shop", callback_data="admin_close"),
            InlineKeyboardButton("🔓 Open Shop", callback_data="admin_open"),
        ],
    ])


def admin_orders_text(kind):
    if kind == "new":
        rows = get_active_orders()
        title = "📋 <b>NEW / ACTIVE ORDERS</b>"
        empty = "There are no new or active orders."
    else:
        rows = get_completed_orders()
        title = "📦 <b>COMPLETED ORDERS</b>"
        empty = "There are no completed orders yet."

    if not rows:
        return title + "\n\n" + empty

    lines = [title, "", "Orders are shown oldest first.", ""]
    for order in rows:
        lines.append(format_order_summary(order))
        lines.append("────────────────")
    return "\n".join(lines).rstrip("\n─")


def admin_counts_text():
    conn = db()
    active = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status IN ({})".format(
            ",".join("?" for _ in ACTIVE_STATUSES)
        ), ACTIVE_STATUSES
    ).fetchone()[0]
    completed = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status='COLLECTED'"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    conn.close()

    return (
        "📊 <b>ORDER COUNTS</b>\n\n"
        f"📋 New / active orders: <b>{active}</b>\n"
        f"📦 Completed orders: <b>{completed}</b>\n"
        f"🧾 Total orders: <b>{total}</b>"
    )


# -------------------- SHOP STATUS --------------------

def is_open(context):
    if context.bot_data.get("manually_closed", False):
        return False
    now = datetime.now(TZ).time()
    return OPEN_TIME <= now < CLOSE_TIME


def closed_message():
    return (
        "🔒 <b>Ponder Wonder Cafe is currently closed.</b>\n\n"
        "We're not taking orders right now.\n"
        "Opening hours: <b>7:00am – 10:00pm</b>\n\n"
        "Please come back during opening hours. 🍵"
    )


# -------------------- UI --------------------

def main_keyboard(is_admin=False):
    buttons = [[InlineKeyboardButton("🍵 View Menu", callback_data="menu")]]
    if is_admin:
        buttons.append([
            InlineKeyboardButton("📋 New Orders", callback_data="admin:view:new"),
            InlineKeyboardButton("📦 Completed", callback_data="admin:view:completed"),
        ])
        buttons.append([InlineKeyboardButton("📊 Order Counts", callback_data="admin:view:counts")])
        buttons.append([
            InlineKeyboardButton("🔒 Close Shop", callback_data="admin_close"),
            InlineKeyboardButton("🔓 Open Shop", callback_data="admin_open"),
        ])
    return InlineKeyboardMarkup(buttons)


def menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1. Iced Matcha Latte — $5.50", callback_data="add:iced_matcha_latte")],
        [InlineKeyboardButton("2. Iced Earl Grey Matcha Latte — $6", callback_data="add:iced_earl_grey_matcha")],
        [InlineKeyboardButton("3. Iced Vanilla Matcha Latte — $6", callback_data="add:iced_vanilla_matcha")],
        [InlineKeyboardButton("4. Iced Banana Matcha Latte — $6.50", callback_data="add:iced_banana_matcha")],
        [InlineKeyboardButton("5. Iced Strawberry Matcha Latte — $6.50", callback_data="add:iced_strawberry_matcha")],
        [InlineKeyboardButton("6. Iced Earl Grey Latte — $5.50", callback_data="add:iced_earl_grey_latte")],
        [InlineKeyboardButton("7. Iced Vanilla Latte — $5.50", callback_data="add:iced_vanilla_latte")],
        [InlineKeyboardButton("8. Iced Banana Latte — $6 (Kids Friendly)", callback_data="add:iced_banana_latte")],
        [InlineKeyboardButton("9. Iced Strawberry Latte — $6 (Kids Friendly)", callback_data="add:iced_strawberry_latte")],
        [InlineKeyboardButton("🛒 View Cart", callback_data="cart")],
        [InlineKeyboardButton("🏠 Home", callback_data="home")],
    ])


def menu_text(cart):
    lines = [
        "🍵 <b>Ponder Wonder Cafe Menu</b>",
        "",
        "Choose your drink:",
        "",
        "1. Iced Matcha Latte — $5.50",
        "2. Iced Earl Grey Matcha Latte — $6",
        "3. Iced Vanilla Matcha Latte — $6",
        "4. Iced Banana Matcha Latte — $6.50",
        "5. Iced Strawberry Matcha Latte — $6.50",
        "6. Iced Earl Grey Latte — $5.50",
        "7. Iced Vanilla Latte — $5.50",
        "8. Iced Banana Latte — $6 (Kids Friendly)",
        "9. Iced Strawberry Latte — $6 (Kids Friendly)",
    ]
    if cart:
        lines.extend(["", "🛒 <b>Current cart</b>"])
        for entry in cart:
            lines.append(format_cart_entry(entry))
        lines.append(f"<b>Cart total: ${cart_total(cart):.2f}</b>")
    else:
        lines.extend(["", "🛒 Your cart is currently empty."])
    return "\n".join(lines)


def cart_keyboard(cart):
    buttons = []
    for i, entry in enumerate(cart):
        short_name = entry["name"]
        if len(short_name) > 22:
            short_name = short_name[:21] + "…"
        buttons.append([
            InlineKeyboardButton(f"➖ {short_name}", callback_data=f"dec:{i}"),
            InlineKeyboardButton(f"{entry['qty']} ×", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"inc:{i}"),
        ])

    if cart:
        buttons.append([InlineKeyboardButton("✅ Checkout", callback_data="checkout")])
        buttons.append([InlineKeyboardButton("🗑 Clear Cart", callback_data="clear")])
    buttons.append([InlineKeyboardButton("🍵 Add More", callback_data="menu")])
    buttons.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
    return InlineKeyboardMarkup(buttons)


def collection_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Immediate", callback_data="collect:now")],
        [InlineKeyboardButton("🕐 15 mins", callback_data="collect:15")],
        [InlineKeyboardButton("🕐 30 mins", callback_data="collect:30")],
        [InlineKeyboardButton("🕐 1 hour", callback_data="collect:60")],
        [InlineKeyboardButton("✏️ Edit Cart", callback_data="edit_cart")],
    ])


def payment_keyboard(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 I've Paid", callback_data=f"paid:{order_id}")],
        [InlineKeyboardButton("🏠 Back to Home", callback_data="home")],
    ])


def admin_order_keyboard(order_id, status="PAYMENT_PENDING"):
    if status in ("PAYMENT_PENDING", "PAYMENT_REPORTED", "PAYMENT_SCREENSHOT_RECEIVED"):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Payment Received", callback_data=f"admin:paid:{order_id}")],
        ])
    if status == "PAYMENT_CONFIRMED":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🍵 Preparing", callback_data=f"admin:prep:{order_id}")],
        ])
    if status == "PREPARING":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Ready", callback_data=f"admin:ready:{order_id}")],
        ])
    if status == "READY":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Collected", callback_data=f"admin:collected:{order_id}")],
        ])
    return InlineKeyboardMarkup([])


# -------------------- CART / CUSTOMISATION HELPERS --------------------

def get_cart(context):
    # New cart format: a list of customised line items.
    cart = context.user_data.setdefault("cart", [])
    if isinstance(cart, dict):
        # Migrate any old in-memory cart format gracefully.
        migrated = []
        for key, qty in cart.items():
            item = MENU.get(key)
            if item:
                migrated.append({
                    "key": key,
                    "name": item["name"],
                    "base_price": item["price"],
                    "unit_price": item["price"],
                    "qty": qty,
                    "sweetness": None,
                    "milk": None,
                    "foam": "No cold foam",
                })
        context.user_data["cart"] = migrated
        cart = migrated
    return cart


def cart_total(cart):
    return round(sum(entry["unit_price"] * entry["qty"] for entry in cart), 2)


def format_cart_entry(entry):
    custom = []
    if entry.get("sweetness"):
        custom.append(entry["sweetness"])
    if entry.get("milk"):
        custom.append(entry["milk"])
    foam = entry.get("foam")
    if foam and foam != "No cold foam":
        custom.append(foam)
    detail = f" ({', '.join(custom)})" if custom else ""
    subtotal = entry["unit_price"] * entry["qty"]
    return f"• {entry['qty']} × {entry['name']}{detail} — ${subtotal:.2f}"


def cart_text(cart):
    if not cart:
        return "🛒 <b>Your cart is empty.</b>"
    lines = ["🛒 <b>Your Order</b>", ""]
    for entry in cart:
        lines.append(format_cart_entry(entry))
    lines.append(f"\n<b>Total: ${cart_total(cart):.2f}</b>")
    return "\n".join(lines)


def add_or_merge_cart_item(cart, item_data):
    # Merge only when the drink and all selected options match.
    for entry in cart:
        if all(entry.get(k) == item_data.get(k) for k in ("key", "sweetness", "milk", "foam")):
            entry["qty"] += 1
            return
    cart.append(item_data)


def customization_start_keyboard(key):
    item = MENU[key]
    if item["sweetness"]:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("0% sugar", callback_data="sweet:0")],
            [InlineKeyboardButton("50% sugar", callback_data="sweet:50")],
            [InlineKeyboardButton("100% sugar", callback_data="sweet:100")],
            [InlineKeyboardButton("✕ Cancel", callback_data="custom_cancel")],
        ])
    return foam_keyboard()


def milk_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🥛 Dairy milk", callback_data="milk:dairy")],
        [InlineKeyboardButton("🌾 Oat milk +$0.50", callback_data="milk:oat")],
        [InlineKeyboardButton("✕ Cancel", callback_data="custom_cancel")],
    ])


def foam_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("No cold foam", callback_data="foam:none")],
        [InlineKeyboardButton("💜 Lavender cold foam +$1", callback_data="foam:lavender")],
        [InlineKeyboardButton("🤍 Vanilla cold foam +$1", callback_data="foam:vanilla")],
        [InlineKeyboardButton("✕ Cancel", callback_data="custom_cancel")],
    ])


def customization_summary(draft):
    item = MENU[draft["key"]]
    price = item["price"]
    if draft.get("milk") == "Oat milk":
        price += 0.50
    if draft.get("foam") in ("Lavender cold foam", "Vanilla cold foam"):
        price += 1.00
    lines = [
        f"🍵 <b>{item['name']}</b>",
        f"Base price: ${item['price']:.2f}",
    ]
    if item["sweetness"]:
        lines.append(f"Sweetness: <b>{draft.get('sweetness', 'Not selected')}</b>")
        lines.append(f"Milk: <b>{draft.get('milk', 'Not selected')}</b>")
    lines.append(f"Cold foam: <b>{draft.get('foam', 'Not selected')}</b>")
    lines.append(f"\nPrice for this drink: <b>${price:.2f}</b>")
    return "\n".join(lines)


def finalise_draft_price(draft):
    item = MENU[draft["key"]]
    price = item["price"]
    if draft.get("milk") == "Oat milk":
        price += 0.50
    if draft.get("foam") in ("Lavender cold foam", "Vanilla cold foam"):
        price += 1.00
    draft["base_price"] = item["price"]
    draft["unit_price"] = round(price, 2)
    draft["qty"] = 1
    draft["name"] = item["name"]
    return draft


def customization_prompt(context):
    draft = context.user_data.get("customizing")
    if not draft:
        return None
    item = MENU[draft["key"]]
    if item["sweetness"] and not draft.get("sweetness"):
        return (
            f"🍵 <b>{item['name']}</b>\n\n"
            "Choose your sweetness level:",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("0% sugar", callback_data="sweet:0")],
                [InlineKeyboardButton("50% sugar", callback_data="sweet:50")],
                [InlineKeyboardButton("100% sugar", callback_data="sweet:100")],
                [InlineKeyboardButton("✕ Cancel", callback_data="custom_cancel")],
            ])
        )
    if item["milk"] and not draft.get("milk"):
        return (
            f"🍵 <b>{item['name']}</b>\n\n"
            f"Sweetness: <b>{draft['sweetness']}</b>\n\n"
            "Choose your milk:",
            milk_keyboard()
        )
    if not draft.get("foam"):
        return (
            f"🍵 <b>{item['name']}</b>\n\n"
            + (f"Sweetness: <b>{draft['sweetness']}</b>\nMilk: <b>{draft['milk']}</b>\n\n" if item["milk"] else "")
            + "Choose your cold foam:",
            foam_keyboard()
        )
    return None


# -------------------- ORDER DISPLAY --------------------

def order_text(order):
    items = json.loads(order["items"])
    lines = [
        f"🔔 <b>NEW ORDER #{order['id']}</b>",
        "",
        f"👤 {order['customer_name']}",
        f"💬 @{order['username']}" if order["username"] else "💬 Telegram username: not set",
        "",
    ]
    for item in items:
        details = []
        for field in ("sweetness", "milk", "foam"):
            value = item.get(field)
            if value and value != "No cold foam":
                details.append(value)
            elif field == "foam" and value == "No cold foam":
                details.append(value)
        detail_text = f" ({', '.join(details)})" if details else ""
        lines.append(f"• {item['qty']} × {item['name']}{detail_text} — ${item['subtotal']:.2f}")
    lines.extend([
        "",
        f"💰 <b>Total: ${order['total']:.2f}</b>",
        f"🏠 Collection: {order['collection']}",
        "💳 Payment: Pending",
        "",
        "Collection point:",
        "Blk 322, Lift B, Level 3, Unit 03-253",
    ])
    return "\n".join(lines)


# -------------------- CUSTOMER COMMANDS --------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = update.effective_user.id == ADMIN_CHAT_ID
    context.user_data.setdefault("cart", [])
    context.user_data.pop("customizing", None)

    if not is_open(context) and not is_admin:
        await update.message.reply_text(closed_message(), parse_mode="HTML")
        return

    await update.message.reply_text(
        "🍵 <b>Welcome to Ponder Wonder Cafe!</b>\n\n"
        "Fresh matcha drinks, made for collection.\n\n"
        "🕖 Opening hours: 7:00am – 10:00pm\n"
        "🏠 Yishun Central Blk 322 #03-253\n\n",
        parse_mode="HTML",
        reply_markup=main_keyboard(is_admin),
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Your Telegram user/chat ID is:\n<code>{update.effective_user.id}</code>",
        parse_mode="HTML",
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_open(context):
        await update.message.reply_text(
            "🟢 <b>OPEN</b>\n\nOrders are currently being accepted.\nOpening hours: 7:00am – 10:00pm",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(closed_message(), parse_mode="HTML")


# -------------------- CALLBACKS --------------------

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    is_admin = user.id == ADMIN_CHAT_ID

    # Home. If this is the payment QR screen, reset the pending order/cart.
    if data == "home":
        current_order_id = context.user_data.get("current_order_id")
        current_order = get_order(current_order_id) if current_order_id else None
        if current_order and current_order["telegram_user_id"] == user.id:
            if current_order["status"] in ("PAYMENT_PENDING",):
                update_order_status(current_order_id, "CANCELLED")
            context.user_data.pop("current_order_id", None)
            context.user_data["cart"] = []
        context.user_data.pop("customizing", None)

        if not is_open(context) and not is_admin:
            if query.message and query.message.photo:
                await query.edit_message_caption(
                    caption=closed_message(), parse_mode="HTML",
                    reply_markup=main_keyboard(is_admin),
                )
            else:
                await query.edit_message_text(closed_message(), parse_mode="HTML")
            return

        home_text = "🍵 <b>Ponder Wonder Cafe</b>\n\nWhat would you like to do?"
        if query.message and query.message.photo:
            await query.edit_message_caption(
                caption=home_text, parse_mode="HTML",
                reply_markup=main_keyboard(is_admin),
            )
        else:
            await query.edit_message_text(
                home_text, parse_mode="HTML",
                reply_markup=main_keyboard(is_admin),
            )
        return

    # Menu
    if data == "menu":
        if not is_open(context) and not is_admin:
            await query.edit_message_text(closed_message(), parse_mode="HTML")
            return
        await query.edit_message_text(
            menu_text(get_cart(context)), parse_mode="HTML", reply_markup=menu_keyboard()
        )
        return

    # Start drink customisation.
    if data.startswith("add:"):
        if not is_open(context) and not is_admin:
            await query.edit_message_text(closed_message(), parse_mode="HTML")
            return
        key = data.split(":", 1)[1]
        if key not in MENU:
            await query.answer("Drink not found.", show_alert=True)
            return
        context.user_data["customizing"] = {
            "key": key,
            "sweetness": None,
            "milk": None,
            "foam": None,
        }
        prompt = customization_prompt(context)
        if prompt:
            text, keyboard = prompt
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        return

    # Sweetness choice.
    if data.startswith("sweet:"):
        draft = context.user_data.get("customizing")
        if not draft:
            await query.answer("Please choose a drink first.", show_alert=True)
            return
        draft["sweetness"] = SWEETNESS_OPTIONS[data.split(":", 1)[1]]
        prompt = customization_prompt(context)
        text, keyboard = prompt
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        return

    # Milk choice.
    if data.startswith("milk:"):
        draft = context.user_data.get("customizing")
        if not draft:
            await query.answer("Please choose a drink first.", show_alert=True)
            return
        code = data.split(":", 1)[1]
        draft["milk"] = MILK_OPTIONS[code][0]
        prompt = customization_prompt(context)
        text, keyboard = prompt
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        return

    # Cold foam choice. This completes the drink.
    if data.startswith("foam:"):
        draft = context.user_data.get("customizing")
        if not draft:
            await query.answer("Please choose a drink first.", show_alert=True)
            return
        code = data.split(":", 1)[1]
        draft["foam"] = FOAM_OPTIONS[code][0]
        finalise_draft_price(draft)
        cart = get_cart(context)
        add_or_merge_cart_item(cart, draft)
        context.user_data.pop("customizing", None)
        await query.edit_message_text(
            f"✅ Added to cart!\n\n{cart_text(cart)}",
            parse_mode="HTML",
            reply_markup=cart_keyboard(cart),
        )
        return

    if data == "custom_cancel":
        context.user_data.pop("customizing", None)
        await query.edit_message_text(
            menu_text(get_cart(context)), parse_mode="HTML", reply_markup=menu_keyboard()
        )
        return

    # Cart
    if data == "cart":
        await query.edit_message_text(
            cart_text(get_cart(context)), parse_mode="HTML",
            reply_markup=cart_keyboard(get_cart(context))
        )
        return

    # Increase/decrease a customised cart line.
    if data.startswith("inc:") or data.startswith("dec:"):
        try:
            index = int(data.split(":", 1)[1])
            cart = get_cart(context)
            entry = cart[index]
        except (ValueError, IndexError):
            await query.answer("Cart item not found.", show_alert=True)
            return

        if data.startswith("inc:"):
            entry["qty"] += 1
        else:
            entry["qty"] -= 1
            if entry["qty"] <= 0:
                cart.pop(index)

        await query.edit_message_text(
            cart_text(cart), parse_mode="HTML", reply_markup=cart_keyboard(cart)
        )
        return

    if data == "clear":
        context.user_data["cart"] = []
        context.user_data.pop("current_order_id", None)
        context.user_data.pop("customizing", None)
        await query.edit_message_text(
            menu_text(get_cart(context)), parse_mode="HTML", reply_markup=menu_keyboard()
        )
        return

    if data == "edit_cart":
        if not is_open(context) and not is_admin:
            await query.edit_message_text(closed_message(), parse_mode="HTML")
            return
        await query.edit_message_text(
            menu_text(get_cart(context)), parse_mode="HTML", reply_markup=menu_keyboard()
        )
        return

    if data == "checkout":
        if not get_cart(context):
            await query.answer("Your cart is empty.", show_alert=True)
            return
        if not is_open(context) and not is_admin:
            await query.edit_message_text(closed_message(), parse_mode="HTML")
            return
        await query.edit_message_text(
            "🏠 <b>Collection time</b>\n\n"
            "Choose when you'd like to collect your order.\n"
            "The timing starts when payment is received.",
            parse_mode="HTML", reply_markup=collection_keyboard()
        )
        return

    if data.startswith("collect:"):
        option = data.split(":", 1)[1]
        collection = COLLECTION_OPTIONS[option]
        cart = get_cart(context)

        if not cart:
            await query.answer("Your cart is empty.", show_alert=True)
            return

        items = []
        for entry in cart:
            items.append({
                "name": entry["name"],
                "qty": entry["qty"],
                "subtotal": round(entry["unit_price"] * entry["qty"], 2),
                "unit_price": entry["unit_price"],
                "sweetness": entry.get("sweetness"),
                "milk": entry.get("milk"),
                "foam": entry.get("foam"),
            })

        total = cart_total(cart)
        order_id = create_order(user, items, total, collection)
        context.user_data["cart"] = []
        context.user_data["current_order_id"] = order_id

        payment_text = (
            f"💳 <b>Payment for Order #{order_id}</b>\n\n"
            f"Total: <b>${total:.2f}</b>\n"
            f"Collection: <b>{collection}</b>\n\n"
            "Please scan the PayNow QR code and send your payment screenshot in this chat."
        )

        if os.path.exists(QR_PATH):
            with open(QR_PATH, "rb") as photo:
                await query.message.reply_photo(
                    photo=photo, caption=payment_text, parse_mode="HTML",
                    reply_markup=payment_keyboard(order_id)
                )
            await query.delete_message()
        else:
            await query.edit_message_text(
                payment_text + "\n\n⚠️ <i>PayNow QR has not been uploaded to the bot yet.</i>",
                parse_mode="HTML", reply_markup=payment_keyboard(order_id)
            )
        return

    if data.startswith("paid:"):
        order_id = int(data.split(":", 1)[1])
        order = get_order(order_id)
        if not order or order["telegram_user_id"] != user.id:
            await query.answer("Order not found.", show_alert=True)
            return
        update_order_status(order_id, "PAYMENT_REPORTED")
        await query.edit_message_text(
            f"✅ <b>Payment reported for Order #{order_id}</b>\n\n"
            "Your order is now awaiting payment confirmation.\n"
            "We'll send you an update once it has been confirmed.\n\n"
            "🍵 Ponder Wonder Cafe",
            parse_mode="HTML"
        )
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                ADMIN_CHAT_ID,
                order_text(order) + "\n\n⚠️ Customer says payment has been made.",
                parse_mode="HTML", reply_markup=admin_order_keyboard(order_id, "PAYMENT_REPORTED")
            )
        return

    # Admin order views
    if data.startswith("admin:view:"):
        if not is_admin:
            await query.answer("Admin only.", show_alert=True)
            return
        view = data.split(":", 2)[2]
        if view == "new":
            text = admin_orders_text("new")
        elif view == "completed":
            text = admin_orders_text("completed")
        elif view == "counts":
            text = admin_counts_text()
        else:
            await query.answer("Unknown admin view.", show_alert=True)
            return
        await query.edit_message_text(
            text, parse_mode="HTML", reply_markup=admin_dashboard_keyboard()
        )
        return

    # Admin controls
    if data in ("admin_close", "admin_open"):
        if not is_admin:
            await query.answer("Admin only.", show_alert=True)
            return
        context.bot_data["manually_closed"] = (data == "admin_close")
        if data == "admin_close":
            await query.edit_message_text(
                "🔒 <b>Shop closed.</b>\n\nCustomers will automatically receive the closed-shop message and won't be able to place orders.",
                parse_mode="HTML", reply_markup=main_keyboard(True)
            )
        else:
            await query.edit_message_text(
                "🔓 <b>Shop opened.</b>\n\nCustomers can now place orders, subject to normal opening hours.",
                parse_mode="HTML", reply_markup=main_keyboard(True)
            )
        return

    # Admin order status
    if data.startswith("admin:"):
        if not is_admin:
            await query.answer("Admin only.", show_alert=True)
            return
        _, action, order_id_str = data.split(":")
        order_id = int(order_id_str)
        order = get_order(order_id)
        if not order:
            await query.answer("Order not found.", show_alert=True)
            return

        status_map = {
            "paid": ("PAYMENT_CONFIRMED", "💰 Payment confirmed"),
            "prep": ("PREPARING", "🍵 Order is being prepared"),
            "ready": ("READY", "📦 Order is ready for collection"),
            "collected": ("COLLECTED", "✅ Order collected — completed"),
        }
        if action not in status_map:
            await query.answer("Unknown order action.", show_alert=True)
            return
        new_status, label = status_map[action]
        update_order_status(order_id, new_status)
        await query.edit_message_reply_markup(
            reply_markup=admin_order_keyboard(order_id, new_status)
        )

        if action == "ready":
            customer_message = (
                f"{label} — <b>Order #{order_id}</b>\n\n"
                "Please proceed to Blk 322, Lift B, Level 3, Unit 03-253 for collection. 🍵"
            )
        elif action == "collected":
            customer_message = (
                "<b>Thank you for your support! 🍵💚</b>\n\n"
                f"Order #{order_id} has been collected and is now completed.\n\n"
                "We hope you enjoyed your drink! If you enjoyed it, tag us on social media "
                "<b>@powderwondercafe</b>. We'd love to see it! ✨"
            )
        else:
            customer_message = f"{label} — <b>Order #{order_id}</b>\n\nWe'll keep you updated."

        await context.bot.send_message(order["telegram_user_id"], customer_message, parse_mode="HTML")
        await query.answer(label)
        return

    if data == "noop":
        await query.answer()
        return


# -------------------- PAYMENT SCREENSHOT --------------------

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    order_id = context.user_data.get("current_order_id")
    if not order_id:
        await update.message.reply_text(
            "Please place an order first, then send your payment screenshot here."
        )
        return
    order = get_order(order_id)
    if not order or order["telegram_user_id"] != update.effective_user.id:
        return
    update_order_status(order_id, "PAYMENT_SCREENSHOT_RECEIVED")
    if ADMIN_CHAT_ID:
        caption = (
            f"📸 <b>Payment screenshot — Order #{order_id}</b>\n\n"
            f"Customer: {order['customer_name']}\n"
            f"Total: ${order['total']:.2f}\n"
            f"Collection: {order['collection']}"
        )
        photo = update.message.photo[-1]
        await context.bot.send_photo(
            ADMIN_CHAT_ID, photo=photo.file_id, caption=caption,
            parse_mode="HTML",
            reply_markup=admin_order_keyboard(order_id, "PAYMENT_SCREENSHOT_RECEIVED")
        )
    await update.message.reply_text(
        f"📸 Payment screenshot received for <b>Order #{order_id}</b>.\n\n"
        "We'll confirm your payment shortly. 🍵", parse_mode="HTML"
    )


# -------------------- ADMIN COMMANDS --------------------

async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    await update.message.reply_text(
        admin_orders_text("new"), parse_mode="HTML",
        reply_markup=admin_dashboard_keyboard()
    )


async def counts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    await update.message.reply_text(
        admin_counts_text(), parse_mode="HTML",
        reply_markup=admin_dashboard_keyboard()
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    await update.message.reply_text(
        "🛠 <b>Admin Dashboard</b>", parse_mode="HTML",
        reply_markup=admin_dashboard_keyboard()
    )


async def close_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    context.bot_data["manually_closed"] = True
    await update.message.reply_text(
        "🔒 Shop is now CLOSED.\n\nCustomers attempting to order will receive the closed-shop message."
    )


async def open_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    context.bot_data["manually_closed"] = False
    await update.message.reply_text(
        "🔓 Shop is now OPEN (during normal 7am–10pm operating hours)."
    )


# -------------------- MAIN --------------------

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing.")
    if not ADMIN_CHAT_ID:
        raise RuntimeError("ADMIN_CHAT_ID environment variable is missing.")

    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("close", close_shop))
    app.add_handler(CommandHandler("open", open_shop))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("counts", counts_command))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, photo_handler))
    logger.info("Ponder Wonder Cafe bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
