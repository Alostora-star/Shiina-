import logging
import os
from dotenv import load_dotenv
import uuid
from datetime import datetime
import sqlite3
from flask import Flask
import threading
import time
import requests
import os


from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes, ApplicationBuilder
from telegram.error import BadRequest

from config import WEBSITE_NAME, WEBSITE_SLOGAN, WEBSITE_DESCRIPTION, WEBSITE_MESSAGE, INSTAGRAM_USERNAME, ADMIN_USER_ID, GROUP_ID, GROUP_JOIN_LINK
from data import PRODUCTS_DATA, find_item_by_id, get_product_price
from keyboards import (
    get_main_menu_keyboard,
    get_categories_keyboard,
    get_subcategories_keyboard,
    get_products_keyboard,
    get_product_actions_keyboard,
    get_back_to_main_keyboard,
    get_wallet_keyboard,
    get_servers_keyboard
)

# استيراد دوال قاعدة البيانات
from database import (
    init_db,
    get_user_wallet_db,
    update_user_wallet_db,
    add_pending_payment_db,
    add_purchase_history_db,
    get_user_purchases_history_db,
    update_purchase_status_db,
    get_purchase_by_details_db,
    get_total_users_db,
    get_new_users_today_db,
    get_active_users_last_24_hours_db,
    update_user_activity_db,
    get_all_user_ids_db
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
flask_app = Flask(__name__)

# المسار الرئيسي للتحقق من حالة الخدمة
@flask_app.route("/")
def home():
    return "✅ Bot is running and alive!"

# تشغيل Flask على المنفذ الذي تحدده Render
def run_flask():
    port = int(os.environ.get("PORT", 5000))  # ضروري استخدام المتغير البيئي PORT
    flask_app.run(host="0.0.0.0", port=port)

# بدء السيرفر في Thread منفصل
threading.Thread(target=run_flask).start()

# إرسال طلبات ping دورية للحفاظ على الخدمة نشطة
def keep_alive_ping():
    while True:
        try:
            requests.get("https://shiina-hvtp.onrender.com")  # غيّر الرابط حسب نطاق موقعك
            print("✅ Sent keep-alive ping to Render")
        except Exception as e:
            print(f"⚠️ Ping failed: {e}")
        time.sleep(300)  # كل 5 دقائق

threading.Thread(target=keep_alive_ping, daemon=True).start()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- المتغيرات العامة وحالات ConversationHandler ---
user_carts = {}

# تعريف حالات ConversationHandler في الأعلى
AMOUNT, TRANSACTION_ID = range(2)
SYRIATEL_CASH_AMOUNT, SYRIATEL_CASH_TRANSACTION_ID = range(2, 4)
ASK_GAME_ID = 4
BROADCAST_MESSAGE = 5


# --- دوال المحفظة والتخزين (تفاعل مع قاعدة البيانات) ---

async def get_user_wallet(user_id: int) -> float:
    """يجلب رصيد محفظة المستخدم من قاعدة البيانات."""
    return await get_user_wallet_db(user_id)

async def update_user_wallet(user_id: int, amount: float, username: str = None):
    """يحدث رصيد محفظة المستخدم في قاعدة البيانات."""
    await update_user_wallet_db(user_id, amount, username)

async def add_pending_payment(user_id: int, username: str, amount: float, transaction_id: str, payment_method: str = "Unknown", context: ContextTypes.DEFAULT_TYPE = None):
    """يضيف طلب دفع معلق إلى قاعدة البيانات."""
    payment_id = await add_pending_payment_db(user_id, username, amount, transaction_id, payment_method)

    logger.info(f"Pending payment added for user {user_id}: {payment_id} via {payment_method} (Database)")

    if context and ADMIN_USER_ID:
        admin_notification_message = (
            f"🔔 طلب إيداع جديد!\n\n"
            f"المستخدم: {username} (ID: {user_id})\n"
            f"المبلغ: ${amount:.2f}\n"
            f"رقم العملية: `{transaction_id}`\n"
            f"الطريقة: {payment_method}\n"
            f"للتأكيد (يدوياً): استخدم الأمر `/admin_confirm_deposit {user_id} {amount:.2f}`" 
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_notification_message, parse_mode='Markdown')
            logger.info(f"Admin {ADMIN_USER_ID} notified about new pending payment {payment_id}.")
        except Exception as e:
            logger.error(f"Failed to send admin notification for payment {payment_id}: {str(e)}")

    return payment_id

# --- دوال المساعدة العامة ---

def escape_markdown(text: str) -> str:
    """دالة مساعدة لتهريب الأحرف الخاصة في MarkdownV2."""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

async def send_channel_join_message(update: Update, user_id: int, first_name: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يرسل رسالة توجيهية للمستخدم للانضمام إلى القناة."""
    if GROUP_ID and GROUP_JOIN_LINK: 
        await context.bot.send_message(
            chat_id=user_id,
            text=f"مرحباً {first_name}!\n\n"
                 f"لاستخدام البوت والاستفادة من خدماتنا، يرجى الانضمام إلى قناتنا على تليجرام.\n"
                 f"الرجاء الانضمام من خلال هذا الرابط: {GROUP_JOIN_LINK}\n\n"
                 f"بعد الانضمام، يمكنك الاستمرار في استخدام البوت."
        )
        context.user_data['channel_join_message_sent'] = True 
    else:
        logger.error("GROUP_ID or GROUP_JOIN_LINK is not set in config.py. Cannot send channel join message.")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"مرحباً {first_name}!\n\n"
                 f"لاستخدام البوت، يجب عليك الانضمام إلى قناتنا على تليجرام. عذراً، لا يمكنني توفير الرابط الآن."
        )

# --- دوال عرض المعلومات والمنتجات (show_*) ---

async def show_about_us(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض معلومات عن المتجر."""
    about_message = f"""
ℹ️ معلومات عن {WEBSITE_NAME}

🎯 رؤيتنا:
{WEBSITE_DESCRIPTION}

⭐ قيمنا:
{WEBSITE_SLOGAN}

📝 رسالتنا:
{WEBSITE_MESSAGE}

🔹 نحن متخصصون في توفير جميع أنواع الخدمات الرقمية
🔹 أسعار تنافسية وجودة عالية
🔹 خدمة عملاء متميزة على مدار الساعة
🔹 تسليم فوري للطلبات

تابعنا على انستغرام: {INSTAGRAM_USERNAME}
    """
    if update.message: 
        await update.message.reply_text(
            about_message,
            reply_markup=get_back_to_main_keyboard()
        )
    elif update.callback_query: 
        await update.callback_query.message.reply_text(
            about_message,
            reply_markup=get_back_to_main_keyboard()
        )
        try:
            await update.callback_query.delete_message()
        except BadRequest:
            pass


async def show_contact_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض معلومات التواصل مع المتجر."""
    contact_message = f"""
📞 معلومات التواصل

🔹 للاستفسارات والدعم الفني:
📧 البريد الإلكتروني: alostorayazan@gmail.acm
📱 انستغرام: {INSTAGRAM_USERNAME}

🔹 أوقات العمل:
🕐 24/7 خدمة متواصلة

🔹 طرق الدفع المتاحة:
💳 فيزا - ماستر كارد
💰 محافظ إلكترونية
🏦 تحويل بنكي
    """
    if update.message:
        await update.message.reply_text(
            contact_message,
            reply_markup=get_back_to_main_keyboard()
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            contact_message,
            reply_markup=get_back_to_main_keyboard()
        )
        try:
            await update.callback_query.delete_message()
        except BadRequest:
            pass

async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض محتويات سلة المشتريات للمستخدم."""
    user_id = update.effective_user.id
    cart = user_carts.get(user_id, {})

    keyboard_buttons = []
    message = ""

    if not cart:
        message = "🛒 سلة المشتريات فارغة\n\nابدأ بتصفح المنتجات وإضافة ما تريد!"
    else:
        message = "🛒 سلة المشتريات:\n\n"
        total = 0
        for item_name, details in cart.items():
            price = details['price'] 
            product_id = details['id'] 
            total += price
            message += f"• {item_name}\n💰 السعر: ${price:.2f}\n"
            keyboard_buttons.append([InlineKeyboardButton(f"💳 شراء الآن: {item_name}", callback_data=f"buy_cart_item_{product_id}")])
            message += "\n"

        message += f"💵 المجموع الكلي: ${total:.2f}\n\n"

    keyboard_buttons.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")])

    if update.message:
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard_buttons)
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard_buttons)
        )
        try:
            await update.callback_query.delete_message()
        except BadRequest:
            pass

async def show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض الطلبات السابقة للمستخدم."""
    user_id = update.effective_user.id
    orders = await get_user_purchases_history_db(user_id)

    if not orders:
        message = """
📋 طلباتي

لا توجد طلبات سابقة حتى الآن.

عند إتمام أول عملية شراء، ستظهر طلباتك هنا.
        """
    else:
        message = "📋 طلباتي السابقة:\n\n"
        for i, order in enumerate(orders):
            message += (
                f"**الطلب رقم {i+1}:**\n"
                f"  المنتج: {escape_markdown(order.get('product_name', 'N/A'))}\n"
                f"  المبلغ: ${order.get('price', 0.0):.2f}\n"
                f"  معرف اللعبة: `{escape_markdown(order.get('game_id', 'N/A'))}`\n"
                f"  الحالة: {escape_markdown(order.get('status', 'N/A'))}\n"
                f"  التاريخ: {escape_markdown(order.get('timestamp', 'N/A'))}\n\n"
            )

    if update.message:
        await update.message.reply_text(
            message,
            parse_mode='Markdown', # تأكد أن هذا الوضع هو MarkdownV2
            reply_markup=get_back_to_main_keyboard()
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            message,
            parse_mode='Markdown', # تأكد أن هذا الوضع هو MarkdownV2
            reply_markup=get_back_to_main_keyboard()
        )
        try:
            await update.callback_query.delete_message()
        except BadRequest:
            pass

async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض الفئات الرئيسية للمنتجات."""
    message = "🛍️ اختر الفئة التي تريد تصفحها:"

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=get_categories_keyboard()
            )
        except BadRequest as e:
            logger.warning(f"Error editing message in show_categories: {e}. Sending new message instead.")
            await update.callback_query.message.reply_text(
                message,
                reply_markup=get_categories_keyboard()
            )
    elif update.message:
        await update.message.reply_text(
            message,
            reply_markup=get_categories_keyboard()
        )

async def show_subcategories(update: Update, context: ContextTypes.DEFAULT_TYPE, category_id: str) -> None: 
    """يعرض الفئات الفرعية ضمن فئة معينة."""
    category_data = find_item_by_id(category_id)
    if not category_data or category_data.get("type") != "category":
        logger.error(f"Category with ID '{category_id}' not found.")
        await update.callback_query.message.reply_text("عذراً، لم يتم العثور على هذه الفئة.", reply_markup=get_main_menu_keyboard())
        return

    message = f"📂 {category_data['name']}\n\nاختر الفئة الفرعية:"

    await update.callback_query.message.reply_text(
        message,
        reply_markup=get_subcategories_keyboard(category_id)
    )
    try:
        await update.callback_query.delete_message()
    except BadRequest:
        pass

async def show_servers(update: Update, context: ContextTypes.DEFAULT_TYPE, subcategory_id: str) -> None:
    """يعرض السيرفرات ضمن فئة فرعية وسيطة."""
    logger.info(f"show_servers called with subcategory_id: '{subcategory_id}'")

    subcategory_data = find_item_by_id(subcategory_id)
    if not subcategory_data or subcategory_data.get("type") != "subcategory" or "servers" not in subcategory_data.get("data", {}):
        logger.error(f"Subcategory with ID '{subcategory_id}' not found or has no servers.")
        await update.callback_query.message.reply_text("عذراً، لم يتم العثور على سيرفرات لهذه الفئة الفرعية.", reply_markup=get_main_menu_keyboard())
        return

    message = f"🎮 {subcategory_data['name']}\n\nاختر السيرفر الذي تريده:"

    reply_markup_to_send = get_servers_keyboard(subcategory_id)
    logger.info(f"Keyboard generated for servers: {reply_markup_to_send.inline_keyboard}")

    if update.callback_query:
        try:
            await update.callback_query.message.reply_text(
                message,
                reply_markup=reply_markup_to_send
            )
            try:
                await update.callback_query.delete_message()
            except BadRequest:
                pass
        except BadRequest as e:
            logger.warning(f"BadRequest error in show_servers for subcategory_id '{subcategory_id}': {e}. Sending new message instead.")
            await update.callback_query.message.reply_text(
                message,
                reply_markup=reply_markup_to_send
            )
    elif update.message:
        await update.message.reply_text(
            message,
            reply_markup=reply_markup_to_send
        )


async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE, item_id: str) -> None: 
    """يعرض المنتجات ضمن سيرفر أو فئة فرعية معينة."""
    logger.info(f"show_products called with item_id: '{item_id}'")

    item_data = find_item_by_id(item_id)
    if not item_data or (item_data.get("type") not in ["server", "subcategory"] and "products" not in item_data.get("data", {})):
        logger.error(f"Item with ID '{item_id}' not found or does not contain products.")
        await update.callback_query.message.reply_text("عذراً، لم يتم العثور على منتجات لهذه القائمة.", reply_markup=get_main_menu_keyboard())
        return

    # بناء الرسالة بشكل ديناميكي
    message_path = item_data['name']
    if item_data.get("server_id"): 
        server_name = item_data['name']
        subcategory_name_obj = find_item_by_id(item_data['subcategory_id']) 
        if subcategory_name_obj and subcategory_name_obj.get('name'):
            subcategory_name = subcategory_name_obj['name']
            message_path = f"{subcategory_name} > {server_name}"
        else:
            message_path = server_name 
    elif item_data.get("subcategory_id"): 
        message_path = item_data['name'] 

    message = f"🛍️ {message_path}\n\nاختر المنتج الذي تريده:"

    reply_markup_to_send = get_products_keyboard(item_id) 
    logger.info(f"Keyboard generated: {reply_markup_to_send.inline_keyboard}")

    if update.callback_query:
        try:
            await update.callback_query.message.reply_text(
                message,
                reply_markup=reply_markup_to_send
            )
            try:
                await update.callback_query.delete_message()
            except BadRequest:
                pass 
        except BadRequest as e:
            logger.warning(f"BadRequest error in show_products for item_id '{item_id}': {e}. Sending new message instead.")
            await update.callback_query.message.reply_text(
                message,
                reply_markup=reply_markup_to_send
            )
    elif update.message:
        await update.message.reply_text(
            message,
            reply_markup=reply_markup_to_send
        )


async def show_product_details(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: str) -> None:
    """يعرض تفاصيل منتج معين."""
    product_details = find_item_by_id(product_id)
    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found for details.")
        await update.callback_query.message.reply_text("عذراً، لم يتم العثور على تفاصيل هذا المنتج.", reply_markup=get_main_menu_keyboard())
        return

    category_name = product_details.get('category_name')
    subcategory_name = product_details.get('subcategory_name') 
    server_name = product_details.get('server_name') 
    product_name = product_details['name']
    final_price = product_details['price'] 

    full_path_display = f"{category_name}" if category_name else ""
    if subcategory_name:
        if full_path_display: full_path_display += " > "
        full_path_display += subcategory_name
    if server_name:
        if full_path_display: full_path_display += " > "
        full_path_display += server_name 

    message = f"""
🛍️ {product_name}

📂 الفئة: {full_path_display}

💰 السعر: ${final_price:.2f}

✅ متوفر للشراء الفوري
🚀 تسليم خلال دقائق
🔒 ضمان الجودة

ماذا تريد أن تفعل؟
    """
    context.user_data['purchase_product_category_name'] = category_name
    context.user_data['purchase_product_subcategory_name'] = subcategory_name
    context.user_data['purchase_product_server_name'] = server_name
    context.user_data['purchase_product_name'] = product_name
    context.user_data['purchase_product_price'] = final_price 
    context.user_data['purchase_product_id'] = product_id 

    # إضافة حالة التوفر الزمني هنا
    availability_message = ""
    server_id = product_details.get("server_id")
    if server_id:
        server_data = find_item_by_id(server_id)
        if server_data and server_data.get("availability_window"):
            now = datetime.now()
            current_hour = now.hour
            start_hour = server_data["availability_window"]["start_hour"]
            end_hour = server_data["availability_window"]["end_hour"]

            if current_hour >= end_hour: # بعد وقت الانتهاء (8 مساءً فصاعداً)
                availability_message = "\n\nغير متوفر للساعة 7 مساءً ❌"
            elif current_hour < start_hour: # قبل وقت البدء (قبل 7 مساءً)
                availability_message = f"\n\nمتاح بدءاً من الساعة {start_hour}:00 مساءً"
            # else: متاح حالياً، لا داعي لرسالة إضافية

    message += availability_message

    await update.callback_query.message.reply_text(
        message,
        reply_markup=get_product_actions_keyboard(product_id) 
    )
    try:
        await update.callback_query.delete_message()
    except BadRequest:
        pass


async def add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: str) -> None: 
    """يضيف منتجاً إلى سلة المشتريات."""
    user_id = update.effective_user.id
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found for cart.")
        await update.callback_query.message.reply_text("عذراً، لم يتم العثور على هذا المنتج لإضافته للسلة.", reply_markup=get_main_menu_keyboard())
        return

    # تحقق من التوفر الزمني قبل الإضافة للسلة
    server_id = product_details.get("server_id")
    if server_id:
        server_data = find_item_by_id(server_id)
        if server_data and server_data.get("availability_window"):
            now = datetime.now()
            current_hour = now.hour
            start_hour = server_data["availability_window"]["start_hour"]
            end_hour = server_data["availability_window"]["end_hour"]

            if not (start_hour <= current_hour < end_hour):
                await update.callback_query.message.reply_text(
                    f"عذراً، منتج {product_details['name']} غير متاح للشراء في هذا الوقت. "
                    f"يتوفر فقط من الساعة {start_hour}:00 وحتى {end_hour}:00 مساءً. "
                    f"غير متوفر للساعة 7 مساءً ❌", # الرسالة المطلوبة
                    reply_markup=get_main_menu_keyboard()
                )
                return


    product_name = product_details['name']
    category = product_details.get('category_name')
    subcategory = product_details.get('subcategory_name')
    server = product_details.get('server_name')
    original_price = product_details['price']

    full_path_display = f"{category}" if category else ""
    if subcategory:
        if full_path_display: full_path_display += " > "
        full_path_display += subcategory
    if server:
        if full_path_display: full_path_display += " > "
        full_path_display += server

    if user_id not in user_carts:
        user_carts[user_id] = {}

    user_carts[user_id][product_name] = { 
        'category_name': category,
        'subcategory_name': subcategory, 
        'server_name': server,
        'price': original_price,
        'id': product_id 
    }

    final_price = original_price 

    message = f"""
✅ تم إضافة المنتج للسلة بنجاح!

🛍️ {product_name}
💰 السعر: ${final_price:.2f}

يمكنك متابعة التسوق أو الذهاب لسلة المشتريات لإتمام الطلب.
    """

    await update.callback_query.message.reply_text(
        message,
        reply_markup=get_back_to_main_keyboard()
    )
    try:
        await update.callback_query.delete_message()
    except BadRequest:
        pass


# --- دوال المحفظة والإيداع (wallet, syriatel_cash_deposit_*, deposit_*) ---

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض رصيد المحفظة للمستخدم وخيارات الإيداع."""
    user_id = update.effective_user.id
    balance = await get_user_wallet_db(user_id)

    message = f"💰 رصيد محفظتك الحالي هو: ${balance:.2f}\n\n" \
              "اختر طريقة الإيداع:"

    if update.message: 
        await update.message.reply_text(message, reply_markup=get_wallet_keyboard())
    elif update.callback_query: 
        await update.callback_query.message.reply_text(message, reply_markup=get_wallet_keyboard())
        try:
            await update.callback_query.delete_message()
        except BadRequest:
            pass


async def syriatel_cash_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ عملية إيداع سيرياتيل كاش: يعرض رسالة التحويل ويطلب المبلغ."""
    syriatel_message = """
رقم التحويل: `69643514`

لست مسؤول عن تحويل رصيد
يرجى بعث رقم عملية التحويل 
Zenetsu Shop ⚡️🇸🇾⚡️

يرجى إدخال المبلغ الذي قمت بتحويله (بالدولار):
    """
    await update.callback_query.message.reply_text(syriatel_message, parse_mode='Markdown')
    return SYRIATEL_CASH_AMOUNT

async def syriatel_cash_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل مبلغ سيرياتيل كاش ويطلب رقم العملية."""
    try:
        amount = float(update.message.text)
        if amount <= 0:
            await update.message.reply_text("المبلغ يجب أن يكون رقماً موجباً. يرجى إدخال المبلغ الصحيح:")
            return SYRIATEL_CASH_AMOUNT
        context.user_data['syriatel_cash_amount'] = amount
        await update.message.reply_text("الآن، يرجى إدخال رقم العملية (Transaction ID) من سيرياتيل كاش:")
        return SYRIATEL_CASH_TRANSACTION_ID
    except ValueError:
        await update.message.reply_text("المبلغ غير صالح. يرجى إدخال رقم صحيح للمبلغ:")
        return SYRIATEL_CASH_AMOUNT 

async def deposit_transaction_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل رقم العملية ويضيف المعاملة المعلقة."""
    transaction_id = update.message.text.strip()
    amount = context.user_data['deposit_amount']
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    payment_id = await add_pending_payment(user_id, username, amount, transaction_id, payment_method="General Deposit", context=context)

    await update.message.reply_text(
        f"✅ تم استلام طلب إيداعك بمبلغ ${amount:.2f} ورقم عملية {transaction_id}.\n"
        f"طلبك برقم {payment_id} في انتظار المراجعة من قبل الإدارة. سيتم تحديث رصيدك بعد التأكيد.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

async def cancel_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يلغي عملية الإيداع."""
    await update.message.reply_text("تم إلغاء عملية الإيداع.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# --- دوال الشراء (request_game_id, receive_game_id) ---

async def request_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دالة لطلب الـ Game ID من المستخدم."""
    product_id = context.user_data.get('purchase_product_id')
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found for purchase request.")
        await update.callback_query.message.reply_text("عذراً، لم يتم العثور على هذا المنتج لإتمام عملية الشراء.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    # تحقق من التوفر الزمني هنا
    server_id = product_details.get("server_id")
    if server_id:
        server_data = find_item_by_id(server_id)
        if server_data and server_data.get("availability_window"):
            now = datetime.now()
            current_hour = now.hour
            start_hour = server_data["availability_window"]["start_hour"]
            end_hour = server_data["availability_window"]["end_hour"]

            if not (start_hour <= current_hour < end_hour):
                await update.callback_query.message.reply_text(
                    f"عذراً، منتج {product_details['name']} غير متاح للشراء في هذا الوقت. "
                    f"يتوفر فقط من الساعة {start_hour}:00 وحتى {end_hour}:00 مساءً. "
                    f"غير متوفر للساعة 7 مساءً ❌", # الرسالة المطلوبة
                    reply_markup=get_main_menu_keyboard()
                )
                return ConversationHandler.END


    product_name = product_details['name']
    product_price = product_details['price']
    user_id = update.effective_user.id

    current_balance = await get_user_wallet_db(user_id)

    if current_balance < product_price:
        await update.callback_query.message.reply_text(
            f"😔 رصيدك غير كافٍ لشراء {product_name}.\n"
            f"رصيدك الحالي: ${current_balance:.2f}.\n"
            f"السعر المطلوب: ${product_price:.2f}.\n"
            f"يرجى شحن محفظتك أولاً.",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END 
    else:
        await update.callback_query.message.reply_text(
            f"لشراء {product_name}، يرجى إدخال معرف اللعبة (Game ID) الخاص بك:"
        )
        return ASK_GAME_ID

async def receive_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل الـ Game ID ويرسل طلب الشراء للمسؤول."""
    game_id = update.message.text.strip()
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    product_id = context.user_data.get('purchase_product_id')
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found during game ID reception.")
        await update.message.reply_text("عذراً، حدث خطأ في معالجة طلبك. يرجى المحاولة مرة أخرى.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    product_name = product_details['name']
    final_price = product_details['price'] 

    if not game_id.isdigit():
        await update.message.reply_text("معرف اللعبة يجب أن يحتوي على أرقام فقط. يرجى إدخال معرف اللعبة الصحيح:")
        return ASK_GAME_ID 

    await update_user_wallet_db(user_id, -final_price) 
    new_balance = await get_user_wallet_db(user_id) 

    purchase_id = await add_purchase_history_db(user_id, username, product_name, game_id, final_price)

    if ADMIN_USER_ID:
        admin_notification_message = (
            f"🔔 طلب شراء جديد!\n\n"
            f"المستخدم: {username} (ID: {user_id})\n"
            f"المنتج: {product_name} (ID: {product_id})\n" 
            f"المبلغ: ${final_price:.2f} (تم الخصم من المحفظة)\n"
            f"رصيد المستخدم بعد الخصم: ${new_balance:.2f}\n"
            f"معرف اللعبة (Game ID): `{game_id}`\n"
            f"رقم الطلب: `{purchase_id}`\n\n"
            f"للتأكيد بعد الشحن: `/admin_confirm_shipped {purchase_id}`" 
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_notification_message, parse_mode='Markdown')
            logger.info(f"Admin {ADMIN_USER_ID} notified about new purchase request {purchase_id}.")
        except Exception as e:
            logger.error(f"Failed to send admin notification for purchase {purchase_id}: {str(e)}")

    await update.message.reply_text(
        f"✅ تم استلام طلب شراء {product_name} الخاص بك.\n"
        f"معرف اللعبة: `{game_id}`.\n"
        f"تم خصم ${final_price:.2f} من محفظتك. رصيدك الحالي: ${new_balance:.2f}.\n"
        f"طلبك برقم {purchase_id} في انتظار الشحن. سيتم إعلامك عند اكتمال العملية.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# --- دوال المسؤول (admin_confirm_deposit, admin_confirm_shipped) ---

async def admin_confirm_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يؤكد طلب إيداع و يحدث رصيد المستخدم."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    try:
        user_id_str = context.args[0]
        amount_str = context.args[1]
        user_id = int(user_id_str)
        amount = float(amount_str)
    except (IndexError, ValueError):
        await update.message.reply_text("الاستخدام: `/admin_confirm_deposit <معرف_المستخدم> <المبلغ>`")
        return

    new_balance = await update_user_wallet_db(user_id, amount) 

    await update.message.reply_text(
        f"✅ تم إضافة ${amount:.2f} إلى محفظة المستخدم {user_id}.\n"
        f"رصيده الجديد: ${new_balance:.2f} (تم الحفظ في قاعدة البيانات).",
        reply_markup=get_back_to_main_keyboard()
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=f"🎉 تم تأكيد إيداعك بمبلغ ${amount:.2f} في محفظتك! رصيدك الحالي: ${new_balance:.2f}")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about confirmed payment: {str(e)}")

async def admin_confirm_shipped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يؤكد عملية الشحن و يرسل إشعار للمستخدم."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    try:
        purchase_id = context.args[0]
    except (IndexError):
        await update.message.reply_text("الاستخدام: `/admin_confirm_shipped <معرف_الطلب>`")
        return

    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, product_name FROM purchases_history WHERE purchase_id = ?", (purchase_id,))
        purchase_details = cursor.fetchone()

    if not purchase_details:
        await update.message.reply_text(f"❌ لم يتم العثور على طلب بالمعرف: `{purchase_id}`.")
        return

    user_id, product_name = purchase_details

    await update_purchase_status_db(purchase_id, 'shipped', datetime.now().isoformat())
    logger.info(f"Purchase {purchase_id} for user {user_id}, product {product_name} marked as shipped in DB.")

    message_to_user = f"🎉 تم عملية الشحن بنجاح ✅ لمنتج: {product_name}!"
    try:
        await context.bot.send_message(chat_id=user_id, text=message_to_user)
        await update.message.reply_text(f"✅ تم إرسال إشعار الشحن بنجاح للمستخدم {user_id} لمنتج {product_name} (رقم الطلب: `{purchase_id}`).", reply_markup=get_back_to_main_keyboard())
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about shipped purchase {purchase_id}: {str(e)}")
        await update.message.reply_text(f"❌ فشل إرسال إشعار الشحن للمستخدم {user_id}.", reply_markup=get_back_to_main_keyboard())


# --- دوال المحفظة والإيداع (wallet, syriatel_cash_deposit_*, deposit_*) ---

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض رصيد المحفظة للمستخدم وخيارات الإيداع."""
    user_id = update.effective_user.id
    balance = await get_user_wallet_db(user_id)

    message = f"💰 رصيد محفظتك الحالي هو: ${balance:.2f}\n\n" \
              "اختر طريقة الإيداع:"

    if update.message: 
        await update.message.reply_text(message, reply_markup=get_wallet_keyboard())
    elif update.callback_query: 
        await update.callback_query.message.reply_text(message, reply_markup=get_wallet_keyboard())
        try:
            await update.callback_query.delete_message()
        except BadRequest:
            pass


async def syriatel_cash_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ عملية إيداع سيرياتيل كاش: يعرض رسالة التحويل و يطلب المبلغ."""
    syriatel_message = """
رقم التحويل: `69643514`

لست مسؤول عن تحويل رصيد
يرجى بعث رقم عملية التحويل 
Zenetsu Shop ⚡️🇸🇾⚡️

يرجى إدخال المبلغ الذي قمت بتحويله (بالدولار):
    """
    await update.callback_query.message.reply_text(syriatel_message, parse_mode='Markdown')
    return SYRIATEL_CASH_AMOUNT

async def syriatel_cash_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل مبلغ سيرياتيل كاش و يطلب رقم العملية."""
    try:
        amount = float(update.message.text)
        if amount <= 0:
            await update.message.reply_text("المبلغ يجب أن يكون رقماً موجباً. يرجى إدخال المبلغ الصحيح:")
            return SYRIATEL_CASH_AMOUNT
        context.user_data['syriatel_cash_amount'] = amount
        await update.message.reply_text("الآن، يرجى إدخال رقم العملية (Transaction ID) من سيرياتيل كاش:")
        return SYRIATEL_CASH_TRANSACTION_ID
    except ValueError:
        await update.message.reply_text("المبلغ غير صالح. يرجى إدخال رقم صحيح للمبلغ:")
        return SYRIATEL_CASH_AMOUNT 

async def syriatel_cash_deposit_transaction_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل رقم عملية سيرياتيل كاش و يضيف المعاملة المعلقة."""
    transaction_id = update.message.text.strip()
    amount = context.user_data['syriatel_cash_amount']
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    payment_id = await add_pending_payment(user_id, username, amount, transaction_id, payment_method="General Deposit", context=context)

    await update.message.reply_text(
        f"✅ تم استلام طلب إيداعك بمبلغ ${amount:.2f} ورقم عملية {transaction_id}.\n"
        f"طلبك برقم {payment_id} في انتظار المراجعة من قبل الإدارة. سيتم تحديث رصيدك بعد التأكيد.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

async def deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ عملية الإيداع العامة (يمكن استخدامها لأوامر /deposit مباشرة)."""
    await update.message.reply_text("💳 لإيداع مبلغ في محفظتك، يرجى إدخال المبلغ الذي قمت بتحويله (بالدولار):")
    return AMOUNT

async def deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل المبلغ و يطلب رقم العملية (للايداع العام)."""
    try:
        amount = float(update.message.text)
        if amount <= 0:
            await update.message.reply_text("المبلغ يجب أن يكون رقماً موجباً. يرجى إدخال المبلغ الصحيح:")
            return AMOUNT
        context.user_data['deposit_amount'] = amount
        await update.message.reply_text("الآن، يرجى إدخال رقم العملية (Transaction ID):")
        return TRANSACTION_ID
    except ValueError:
        await update.message.reply_text("المبلغ غير صالح. يرجى إدخال رقم صحيح للمبلغ:")
        return AMOUNT 

async def deposit_transaction_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل رقم العملية و يضيف المعاملة المعلقة (للايداع العام)."""
    transaction_id = update.message.text.strip()
    amount = context.user_data['deposit_amount']
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    payment_id = await add_pending_payment(user_id, username, amount, transaction_id, payment_method="General Deposit", context=context)

    await update.message.reply_text(
        f"✅ تم استلام طلب إيداعك بمبلغ ${amount:.2f} ورقم عملية {transaction_id}.\n"
        f"طلبك برقم {payment_id} في انتظار المراجعة من قبل الإدارة. سيتم تحديث رصيدك بعد التأكيد.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

async def cancel_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يلغي عملية الإيداع."""
    await update.message.reply_text("تم إلغاء عملية الإيداع.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# --- دوال الشراء (request_game_id, receive_game_id) ---

async def request_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دالة لطلب الـ Game ID من المستخدم."""
    product_id = context.user_data.get('purchase_product_id')
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found for purchase request.")
        await update.callback_query.message.reply_text("عذراً، لم يتم العثور على هذا المنتج لإتمام عملية الشراء.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    # تحقق من التوفر الزمني هنا
    server_id = product_details.get("server_id")
    if server_id:
        server_data = find_item_by_id(server_id)
        if server_data and server_data.get("availability_window"):
            now = datetime.now()
            current_hour = now.hour
            start_hour = server_data["availability_window"]["start_hour"]
            end_hour = server_data["availability_window"]["end_hour"]

            if not (start_hour <= current_hour < end_hour):
                await update.callback_query.message.reply_text(
                    f"عذراً، منتج {product_details['name']} غير متاح للشراء في هذا الوقت. "
                    f"يتوفر فقط من الساعة {start_hour}:00 وحتى {end_hour}:00 مساءً. "
                    f"غير متوفر للساعة 7 مساءً ❌", # الرسالة المطلوبة
                    reply_markup=get_main_menu_keyboard()
                )
                return ConversationHandler.END


    product_name = product_details['name']
    product_price = product_details['price']
    user_id = update.effective_user.id

    current_balance = await get_user_wallet_db(user_id)

    if current_balance < product_price:
        await update.callback_query.message.reply_text(
            f"😔 رصيدك غير كافٍ لشراء {product_name}.\n"
            f"رصيدك الحالي: ${current_balance:.2f}.\n"
            f"السعر المطلوب: ${product_price:.2f}.\n"
            f"يرجى شحن محفظتك أولاً.",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END 
    else:
        await update.callback_query.message.reply_text(
            f"لشراء {product_name}، يرجى إدخال معرف اللعبة (Game ID) الخاص بك:"
        )
        return ASK_GAME_ID

async def receive_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل الـ Game ID ويرسل طلب الشراء للمسؤول."""
    game_id = update.message.text.strip()
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    product_id = context.user_data.get('purchase_product_id')
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found during game ID reception.")
        await update.message.reply_text("عذراً، حدث خطأ في معالجة طلبك. يرجى المحاولة مرة أخرى.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    product_name = product_details['name']
    final_price = product_details['price'] 

    if not game_id.isdigit():
        await update.message.reply_text("معرف اللعبة يجب أن يحتوي على أرقام فقط. يرجى إدخال معرف اللعبة الصحيح:")
        return ASK_GAME_ID 

    await update_user_wallet_db(user_id, -final_price) 
    new_balance = await get_user_wallet_db(user_id) 

    purchase_id = await add_purchase_history_db(user_id, username, product_name, game_id, final_price)

    if ADMIN_USER_ID:
        admin_notification_message = (
            f"🔔 طلب شراء جديد!\n\n"
            f"المستخدم: {username} (ID: {user_id})\n"
            f"المنتج: {product_name} (ID: {product_id})\n" 
            f"المبلغ: ${final_price:.2f} (تم الخصم من المحفظة)\n"
            f"رصيد المستخدم بعد الخصم: ${new_balance:.2f}\n"
            f"معرف اللعبة (Game ID): `{game_id}`\n"
            f"رقم الطلب: `{purchase_id}`\n\n"
            f"للتأكيد بعد الشحن: `/admin_confirm_shipped {purchase_id}`" 
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_notification_message, parse_mode='Markdown')
            logger.info(f"Admin {ADMIN_USER_ID} notified about new purchase request {purchase_id}.")
        except Exception as e:
            logger.error(f"Failed to send admin notification for purchase {purchase_id}: {str(e)}")

    await update.message.reply_text(
        f"✅ تم استلام طلب شراء {product_name} الخاص بك.\n"
        f"معرف اللعبة: `{game_id}`.\n"
        f"تم خصم ${final_price:.2f} من محفظتك. رصيدك الحالي: ${new_balance:.2f}.\n"
        f"طلبك برقم {purchase_id} في انتظار الشحن. سيتم إعلامك عند اكتمال العملية.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# --- دوال المسؤول (admin_confirm_deposit, admin_confirm_shipped) ---

async def admin_confirm_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يؤكد طلب إيداع و يحدث رصيد المستخدم."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    try:
        user_id_str = context.args[0]
        amount_str = context.args[1]
        user_id = int(user_id_str)
        amount = float(amount_str)
    except (IndexError, ValueError):
        await update.message.reply_text("الاستخدام: `/admin_confirm_deposit <معرف_المستخدم> <المبلغ>`")
        return

    new_balance = await update_user_wallet_db(user_id, amount) 

    await update.message.reply_text(
        f"✅ تم إضافة ${amount:.2f} إلى محفظة المستخدم {user_id}.\n"
        f"رصيده الجديد: ${new_balance:.2f} (تم الحفظ في قاعدة البيانات).",
        reply_markup=get_back_to_main_keyboard()
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=f"🎉 تم تأكيد إيداعك بمبلغ ${amount:.2f} في محفظتك! رصيدك الحالي: ${new_balance:.2f}")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about confirmed payment: {str(e)}")

async def admin_confirm_shipped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يؤكد عملية الشحن و يرسل إشعار للمستخدم."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    try:
        purchase_id = context.args[0]
    except (IndexError):
        await update.message.reply_text("الاستخدام: `/admin_confirm_shipped <معرف_الطلب>`")
        return

    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, product_name FROM purchases_history WHERE purchase_id = ?", (purchase_id,))
        purchase_details = cursor.fetchone()

    if not purchase_details:
        await update.message.reply_text(f"❌ لم يتم العثور على طلب بالمعرف: `{purchase_id}`.")
        return

    user_id, product_name = purchase_details

    await update_purchase_status_db(purchase_id, 'shipped', datetime.now().isoformat())
    logger.info(f"Purchase {purchase_id} for user {user_id}, product {product_name} marked as shipped in DB.")

    message_to_user = f"🎉 تم عملية الشحن بنجاح ✅ لمنتج: {product_name}!"
    try:
        await context.bot.send_message(chat_id=user_id, text=message_to_user)
        await update.message.reply_text(f"✅ تم إرسال إشعار الشحن بنجاح للمستخدم {user_id} لمنتج {product_name} (رقم الطلب: `{purchase_id}`).", reply_markup=get_back_to_main_keyboard())
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about shipped purchase {purchase_id}: {str(e)}")
        await update.message.reply_text(f"❌ فشل إرسال إشعار الشحن للمستخدم {user_id}.", reply_markup=get_back_to_main_keyboard())


# --- دوال المحفظة والإيداع (wallet, syriatel_cash_deposit_*, deposit_*) ---

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض رصيد المحفظة للمستخدم وخيارات الإيداع."""
    user_id = update.effective_user.id
    balance = await get_user_wallet_db(user_id)

    message = f"💰 رصيد محفظتك الحالي هو: ${balance:.2f}\n\n" \
              "اختر طريقة الإيداع:"

    if update.message: 
        await update.message.reply_text(message, reply_markup=get_wallet_keyboard())
    elif update.callback_query: 
        await update.callback_query.message.reply_text(message, reply_markup=get_wallet_keyboard())
        try:
            await update.callback_query.delete_message()
        except BadRequest:
            pass


async def syriatel_cash_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ عملية إيداع سيرياتيل كاش: يعرض رسالة التحويل و يطلب المبلغ."""
    syriatel_message = """
رقم التحويل: `69643514`

لست مسؤول عن تحويل رصيد
يرجى بعث رقم عملية التحويل 
Zenetsu Shop ⚡️🇸🇾⚡️

يرجى إدخال المبلغ الذي قمت بتحويله (بالدولار):
    """
    await update.callback_query.message.reply_text(syriatel_message, parse_mode='Markdown')
    return SYRIATEL_CASH_AMOUNT

async def syriatel_cash_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل مبلغ سيرياتيل كاش و يطلب رقم العملية."""
    try:
        amount = float(update.message.text)
        if amount <= 0:
            await update.message.reply_text("المبلغ يجب أن يكون رقماً موجباً. يرجى إدخال المبلغ الصحيح:")
            return SYRIATEL_CASH_AMOUNT
        context.user_data['syriatel_cash_amount'] = amount
        await update.message.reply_text("الآن، يرجى إدخال رقم العملية (Transaction ID) من سيرياتيل كاش:")
        return SYRIATEL_CASH_TRANSACTION_ID
    except ValueError:
        await update.message.reply_text("المبلغ غير صالح. يرجى إدخال رقم صحيح للمبلغ:")
        return SYRIATEL_CASH_AMOUNT 

async def deposit_transaction_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل رقم العملية و يضيف المعاملة المعلقة (للايداع العام)."""
    transaction_id = update.message.text.strip()
    amount = context.user_data['deposit_amount']
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    payment_id = await add_pending_payment(user_id, username, amount, transaction_id, payment_method="General Deposit", context=context)

    await update.message.reply_text(
        f"✅ تم استلام طلب إيداعك بمبلغ ${amount:.2f} ورقم عملية {transaction_id}.\n"
        f"طلبك برقم {payment_id} في انتظار المراجعة من قبل الإدارة. سيتم تحديث رصيدك بعد التأكيد.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

async def cancel_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يلغي عملية الإيداع."""
    await update.message.reply_text("تم إلغاء عملية الإيداع.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# --- دوال الشراء (request_game_id, receive_game_id) ---

async def request_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دالة لطلب الـ Game ID من المستخدم."""
    product_id = context.user_data.get('purchase_product_id')
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found for purchase request.")
        await update.callback_query.message.reply_text("عذراً، لم يتم العثور على هذا المنتج لإتمام عملية الشراء.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    # تحقق من التوفر الزمني هنا
    server_id = product_details.get("server_id")
    if server_id:
        server_data = find_item_by_id(server_id)
        if server_data and server_data.get("availability_window"):
            now = datetime.now()
            current_hour = now.hour
            start_hour = server_data["availability_window"]["start_hour"]
            end_hour = server_data["availability_window"]["end_hour"]

            if not (start_hour <= current_hour < end_hour):
                await update.callback_query.message.reply_text(
                    f"عذراً، منتج {product_details['name']} غير متاح للشراء في هذا الوقت. "
                    f"يتوفر فقط من الساعة {start_hour}:00 وحتى {end_hour}:00 مساءً. "
                    f"غير متوفر للساعة 7 مساءً ❌", # الرسالة المطلوبة
                    reply_markup=get_main_menu_keyboard()
                )
                return ConversationHandler.END


    product_name = product_details['name']
    product_price = product_details['price']
    user_id = update.effective_user.id

    current_balance = await get_user_wallet_db(user_id)

    if current_balance < product_price:
        await update.callback_query.message.reply_text(
            f"😔 رصيدك غير كافٍ لشراء {product_name}.\n"
            f"رصيدك الحالي: ${current_balance:.2f}.\n"
            f"السعر المطلوب: ${product_price:.2f}.\n"
            f"يرجى شحن محفظتك أولاً.",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END 
    else:
        await update.callback_query.message.reply_text(
            f"لشراء {product_name}، يرجى إدخال معرف اللعبة (Game ID) الخاص بك:"
        )
        return ASK_GAME_ID

async def receive_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل الـ Game ID ويرسل طلب الشراء للمسؤول."""
    game_id = update.message.text.strip()
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    product_id = context.user_data.get('purchase_product_id')
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found during game ID reception.")
        await update.message.reply_text("عذراً، حدث خطأ في معالجة طلبك. يرجى المحاولة مرة أخرى.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    product_name = product_details['name']
    final_price = product_details['price'] 

    if not game_id.isdigit():
        await update.message.reply_text("معرف اللعبة يجب أن يحتوي على أرقام فقط. يرجى إدخال معرف اللعبة الصحيح:")
        return ASK_GAME_ID 

    await update_user_wallet_db(user_id, -final_price) 
    new_balance = await get_user_wallet_db(user_id) 

    purchase_id = await add_purchase_history_db(user_id, username, product_name, game_id, final_price)

    if ADMIN_USER_ID:
        admin_notification_message = (
            f"🔔 طلب شراء جديد!\n\n"
            f"المستخدم: {username} (ID: {user_id})\n"
            f"المنتج: {product_name} (ID: {product_id})\n" 
            f"المبلغ: ${final_price:.2f} (تم الخصم من المحفظة)\n"
            f"رصيد المستخدم بعد الخصم: ${new_balance:.2f}\n"
            f"معرف اللعبة (Game ID): `{game_id}`\n"
            f"رقم الطلب: `{purchase_id}`\n\n"
            f"للتأكيد بعد الشحن: `/admin_confirm_shipped {purchase_id}`" 
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_notification_message, parse_mode='Markdown')
            logger.info(f"Admin {ADMIN_USER_ID} notified about new purchase request {purchase_id}.")
        except Exception as e:
            logger.error(f"Failed to send admin notification for purchase {purchase_id}: {str(e)}")

    await update.message.reply_text(
        f"✅ تم استلام طلب شراء {product_name} الخاص بك.\n"
        f"معرف اللعبة: `{game_id}`.\n"
        f"تم خصم ${final_price:.2f} من محفظتك. رصيدك الحالي: ${new_balance:.2f}.\n"
        f"طلبك برقم {purchase_id} في انتظار الشحن. سيتم إعلامك عند اكتمال العملية.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# --- دوال المسؤول (admin_confirm_deposit, admin_confirm_shipped) ---

async def admin_confirm_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يؤكد طلب إيداع و يحدث رصيد المستخدم."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    try:
        user_id_str = context.args[0]
        amount_str = context.args[1]
        user_id = int(user_id_str)
        amount = float(amount_str)
    except (IndexError, ValueError):
        await update.message.reply_text("الاستخدام: `/admin_confirm_deposit <معرف_المستخدم> <المبلغ>`")
        return

    new_balance = await update_user_wallet_db(user_id, amount) 

    await update.message.reply_text(
        f"✅ تم إضافة ${amount:.2f} إلى محفظة المستخدم {user_id}.\n"
        f"رصيده الجديد: ${new_balance:.2f} (تم الحفظ في قاعدة البيانات).",
        reply_markup=get_back_to_main_keyboard()
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=f"🎉 تم تأكيد إيداعك بمبلغ ${amount:.2f} في محفظتك! رصيدك الحالي: ${new_balance:.2f}")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about confirmed payment: {str(e)}")

async def admin_confirm_shipped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يؤكد عملية الشحن و يرسل إشعار للمستخدم."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    try:
        purchase_id = context.args[0]
    except (IndexError):
        await update.message.reply_text("الاستخدام: `/admin_confirm_shipped <معرف_الطلب>`")
        return

    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, product_name FROM purchases_history WHERE purchase_id = ?", (purchase_id,))
        purchase_details = cursor.fetchone()

    if not purchase_details:
        await update.message.reply_text(f"❌ لم يتم العثور على طلب بالمعرف: `{purchase_id}`.")
        return

    user_id, product_name = purchase_details

    await update_purchase_status_db(purchase_id, 'shipped', datetime.now().isoformat())
    logger.info(f"Purchase {purchase_id} for user {user_id}, product {product_name} marked as shipped in DB.")

    message_to_user = f"🎉 تم عملية الشحن بنجاح ✅ لمنتج: {product_name}!"
    try:
        await context.bot.send_message(chat_id=user_id, text=message_to_user)
        await update.message.reply_text(f"✅ تم إرسال إشعار الشحن بنجاح للمستخدم {user_id} لمنتج {product_name} (رقم الطلب: `{purchase_id}`).", reply_markup=get_back_to_main_keyboard())
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about shipped purchase {purchase_id}: {str(e)}")
        await update.message.reply_text(f"❌ فشل إرسال إشعار الشحن للمستخدم {user_id}.", reply_markup=get_back_to_main_keyboard())


# --- دوال المحفظة والإيداع (wallet, syriatel_cash_deposit_*, deposit_*) ---

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض رصيد المحفظة للمستخدم وخيارات الإيداع."""
    user_id = update.effective_user.id
    balance = await get_user_wallet_db(user_id)

    message = f"💰 رصيد محفظتك الحالي هو: ${balance:.2f}\n\n" \
              "اختر طريقة الإيداع:"

    if update.message: 
        await update.message.reply_text(message, reply_markup=get_wallet_keyboard())
    elif update.callback_query: 
        await update.callback_query.message.reply_text(message, reply_markup=get_wallet_keyboard())
        try:
            await update.callback_query.delete_message()
        except BadRequest:
            pass


async def syriatel_cash_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ عملية إيداع سيرياتيل كاش: يعرض رسالة التحويل و يطلب المبلغ."""
    syriatel_message = """
رقم التحويل: `69643514`

لست مسؤول عن تحويل رصيد
يرجى بعث رقم عملية التحويل 
Zenetsu Shop ⚡️🇸🇾⚡️

يرجى إدخال المبلغ الذي قمت بتحويله (بالدولار):
    """
    await update.callback_query.message.reply_text(syriatel_message, parse_mode='Markdown')
    return SYRIATEL_CASH_AMOUNT

async def syriatel_cash_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل مبلغ سيرياتيل كاش و يطلب رقم العملية."""
    try:
        amount = float(update.message.text)
        if amount <= 0:
            await update.message.reply_text("المبلغ يجب أن يكون رقماً موجباً. يرجى إدخال المبلغ الصحيح:")
            return SYRIATEL_CASH_AMOUNT
        context.user_data['syriatel_cash_amount'] = amount
        await update.message.reply_text("الآن، يرجى إدخال رقم العملية (Transaction ID) من سيرياتيل كاش:")
        return SYRIATEL_CASH_TRANSACTION_ID
    except ValueError:
        await update.message.reply_text("المبلغ غير صالح. يرجى إدخال رقم صحيح للمبلغ:")
        return SYRIATEL_CASH_AMOUNT 

async def deposit_transaction_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل رقم العملية و يضيف المعاملة المعلقة (للايداع العام)."""
    transaction_id = update.message.text.strip()
    amount = context.user_data['deposit_amount']
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    payment_id = await add_pending_payment(user_id, username, amount, transaction_id, payment_method="General Deposit", context=context)

    await update.message.reply_text(
        f"✅ تم استلام طلب إيداعك بمبلغ ${amount:.2f} ورقم عملية {transaction_id}.\n"
        f"طلبك برقم {payment_id} في انتظار المراجعة من قبل الإدارة. سيتم تحديث رصيدك بعد التأكيد.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

async def cancel_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يلغي عملية الإيداع."""
    await update.message.reply_text("تم إلغاء عملية الإيداع.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# --- دوال الشراء (request_game_id, receive_game_id) ---

async def request_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دالة لطلب الـ Game ID من المستخدم."""
    product_id = context.user_data.get('purchase_product_id')
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found for purchase request.")
        await update.callback_query.message.reply_text("عذراً، لم يتم العثور على هذا المنتج لإتمام عملية الشراء.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    # تحقق من التوفر الزمني هنا
    server_id = product_details.get("server_id")
    if server_id:
        server_data = find_item_by_id(server_id)
        if server_data and server_data.get("availability_window"):
            now = datetime.now()
            current_hour = now.hour
            start_hour = server_data["availability_window"]["start_hour"]
            end_hour = server_data["availability_window"]["end_hour"]

            if not (start_hour <= current_hour < end_hour):
                await update.callback_query.message.reply_text(
                    f"عذراً، منتج {product_details['name']} غير متاح للشراء في هذا الوقت. "
                    f"يتوفر فقط من الساعة {start_hour}:00 وحتى {end_hour}:00 مساءً. "
                    f"غير متوفر للساعة 7 مساءً ❌", # الرسالة المطلوبة
                    reply_markup=get_main_menu_keyboard()
                )
                return ConversationHandler.END


    product_name = product_details['name']
    product_price = product_details['price']
    user_id = update.effective_user.id

    current_balance = await get_user_wallet_db(user_id)

    if current_balance < product_price:
        await update.callback_query.message.reply_text(
            f"😔 رصيدك غير كافٍ لشراء {product_name}.\n"
            f"رصيدك الحالي: ${current_balance:.2f}.\n"
            f"السعر المطلوب: ${product_price:.2f}.\n"
            f"يرجى شحن محفظتك أولاً.",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END 
    else:
        await update.callback_query.message.reply_text(
            f"لشراء {product_name}، يرجى إدخال معرف اللعبة (Game ID) الخاص بك:"
        )
        return ASK_GAME_ID

async def receive_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل الـ Game ID ويرسل طلب الشراء للمسؤول."""
    game_id = update.message.text.strip()
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    product_id = context.user_data.get('purchase_product_id')
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found during game ID reception.")
        await update.message.reply_text("عذراً، حدث خطأ في معالجة طلبك. يرجى المحاولة مرة أخرى.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    product_name = product_details['name']
    final_price = product_details['price'] 

    if not game_id.isdigit():
        await update.message.reply_text("معرف اللعبة يجب أن يحتوي على أرقام فقط. يرجى إدخال معرف اللعبة الصحيح:")
        return ASK_GAME_ID 

    await update_user_wallet_db(user_id, -final_price) 
    new_balance = await get_user_wallet_db(user_id) 

    purchase_id = await add_purchase_history_db(user_id, username, product_name, game_id, final_price)

    if ADMIN_USER_ID:
        admin_notification_message = (
            f"🔔 طلب شراء جديد!\n\n"
            f"المستخدم: {username} (ID: {user_id})\n"
            f"المنتج: {product_name} (ID: {product_id})\n" 
            f"المبلغ: ${final_price:.2f} (تم الخصم من المحفظة)\n"
            f"رصيد المستخدم بعد الخصم: ${new_balance:.2f}\n"
            f"معرف اللعبة (Game ID): `{game_id}`\n"
            f"رقم الطلب: `{purchase_id}`\n\n"
            f"للتأكيد بعد الشحن: `/admin_confirm_shipped {purchase_id}`" 
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_notification_message, parse_mode='Markdown')
            logger.info(f"Admin {ADMIN_USER_ID} notified about new purchase request {purchase_id}.")
        except Exception as e:
            logger.error(f"Failed to send admin notification for purchase {purchase_id}: {str(e)}")

    await update.message.reply_text(
        f"✅ تم استلام طلب شراء {product_name} الخاص بك.\n"
        f"معرف اللعبة: `{game_id}`.\n"
        f"تم خصم ${final_price:.2f} من محفظتك. رصيدك الحالي: ${new_balance:.2f}.\n"
        f"طلبك برقم {purchase_id} في انتظار الشحن. سيتم إعلامك عند اكتمال العملية.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# --- دوال المسؤول (admin_confirm_deposit, admin_confirm_shipped) ---

async def admin_confirm_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يؤكد طلب إيداع و يحدث رصيد المستخدم."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    try:
        user_id_str = context.args[0]
        amount_str = context.args[1]
        user_id = int(user_id_str)
        amount = float(amount_str)
    except (IndexError, ValueError):
        await update.message.reply_text("الاستخدام: `/admin_confirm_deposit <معرف_المستخدم> <المبلغ>`")
        return

    new_balance = await update_user_wallet_db(user_id, amount) 

    await update.message.reply_text(
        f"✅ تم إضافة ${amount:.2f} إلى محفظة المستخدم {user_id}.\n"
        f"رصيده الجديد: ${new_balance:.2f} (تم الحفظ في قاعدة البيانات).",
        reply_markup=get_back_to_main_keyboard()
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=f"🎉 تم تأكيد إيداعك بمبلغ ${amount:.2f} في محفظتك! رصيدك الحالي: ${new_balance:.2f}")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about confirmed payment: {str(e)}")

async def admin_confirm_shipped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يؤكد عملية الشحن و يرسل إشعار للمستخدم."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    try:
        purchase_id = context.args[0]
    except (IndexError):
        await update.message.reply_text("الاستخدام: `/admin_confirm_shipped <معرف_الطلب>`")
        return

    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, product_name FROM purchases_history WHERE purchase_id = ?", (purchase_id,))
        purchase_details = cursor.fetchone()

    if not purchase_details:
        await update.message.reply_text(f"❌ لم يتم العثور على طلب بالمعرف: `{purchase_id}`.")
        return

    user_id, product_name = purchase_details

    await update_purchase_status_db(purchase_id, 'shipped', datetime.now().isoformat())
    logger.info(f"Purchase {purchase_id} for user {user_id}, product {product_name} marked as shipped in DB.")

    message_to_user = f"🎉 تم عملية الشحن بنجاح ✅ لمنتج: {product_name}!"
    try:
        await context.bot.send_message(chat_id=user_id, text=message_to_user)
        await update.message.reply_text(f"✅ تم إرسال إشعار الشحن بنجاح للمستخدم {user_id} لمنتج {product_name} (رقم الطلب: `{purchase_id}`).", reply_markup=get_back_to_main_keyboard())
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about shipped purchase {purchase_id}: {str(e)}")
        await update.message.reply_text(f"❌ فشل إرسال إشعار الشحن للمستخدم {user_id}.", reply_markup=get_back_to_main_keyboard())


# --- دوال المحفظة والإيداع (wallet, syriatel_cash_deposit_*, deposit_*) ---

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض رصيد المحفظة للمستخدم وخيارات الإيداع."""
    user_id = update.effective_user.id
    balance = await get_user_wallet_db(user_id)

    message = f"💰 رصيد محفظتك الحالي هو: ${balance:.2f}\n\n" \
              "اختر طريقة الإيداع:"

    if update.message: 
        await update.message.reply_text(message, reply_markup=get_wallet_keyboard())
    elif update.callback_query: 
        await update.callback_query.message.reply_text(message, reply_markup=get_wallet_keyboard())
        try:
            await update.callback_query.delete_message()
        except BadRequest:
            pass


async def syriatel_cash_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ عملية إيداع سيرياتيل كاش: يعرض رسالة التحويل و يطلب المبلغ."""
    syriatel_message = """
رقم التحويل: `69643514`

لست مسؤول عن تحويل رصيد
يرجى بعث رقم عملية التحويل 
Zenetsu Shop ⚡️🇸🇾⚡️

يرجى إدخال المبلغ الذي قمت بتحويله (بالدولار):
    """
    await update.callback_query.message.reply_text(syriatel_message, parse_mode='Markdown')
    return SYRIATEL_CASH_AMOUNT

async def syriatel_cash_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل مبلغ سيرياتيل كاش و يطلب رقم العملية."""
    try:
        amount = float(update.message.text)
        if amount <= 0:
            await update.message.reply_text("المبلغ يجب أن يكون رقماً موجباً. يرجى إدخال المبلغ الصحيح:")
            return SYRIATEL_CASH_AMOUNT
        context.user_data['syriatel_cash_amount'] = amount
        await update.message.reply_text("الآن، يرجى إدخال رقم العملية (Transaction ID) من سيرياتيل كاش:")
        return SYRIATEL_CASH_TRANSACTION_ID
    except ValueError:
        await update.message.reply_text("المبلغ غير صالح. يرجى إدخال رقم صحيح للمبلغ:")
        return SYRIATEL_CASH_AMOUNT 

async def deposit_transaction_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل رقم العملية و يضيف المعاملة المعلقة (للايداع العام)."""
    transaction_id = update.message.text.strip()
    amount = context.user_data['deposit_amount']
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    payment_id = await add_pending_payment(user_id, username, amount, transaction_id, payment_method="General Deposit", context=context)

    await update.message.reply_text(
        f"✅ تم استلام طلب إيداعك بمبلغ ${amount:.2f} ورقم عملية {transaction_id}.\n"
        f"طلبك برقم {payment_id} في انتظار المراجعة من قبل الإدارة. سيتم تحديث رصيدك بعد التأكيد.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

async def cancel_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يلغي عملية الإيداع."""
    await update.message.reply_text("تم إلغاء عملية الإيداع.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# --- دوال الشراء (request_game_id, receive_game_id) ---

async def request_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دالة لطلب الـ Game ID من المستخدم."""
    product_id = context.user_data.get('purchase_product_id')
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found for purchase request.")
        await update.callback_query.message.reply_text("عذراً، لم يتم العثور على هذا المنتج لإتمام عملية الشراء.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    # تحقق من التوفر الزمني هنا
    server_id = product_details.get("server_id")
    if server_id:
        server_data = find_item_by_id(server_id)
        if server_data and server_data.get("availability_window"):
            now = datetime.now()
            current_hour = now.hour
            start_hour = server_data["availability_window"]["start_hour"]
            end_hour = server_data["availability_window"]["end_hour"]

            if not (start_hour <= current_hour < end_hour):
                await update.callback_query.message.reply_text(
                    f"عذراً، منتج {product_details['name']} غير متاح للشراء في هذا الوقت. "
                    f"يتوفر فقط من الساعة {start_hour}:00 وحتى {end_hour}:00 مساءً. "
                    f"غير متوفر للساعة 7 مساءً ❌", # الرسالة المطلوبة
                    reply_markup=get_main_menu_keyboard()
                )
                return ConversationHandler.END


    product_name = product_details['name']
    product_price = product_details['price']
    user_id = update.effective_user.id

    current_balance = await get_user_wallet_db(user_id)

    if current_balance < product_price:
        await update.callback_query.message.reply_text(
            f"😔 رصيدك غير كافٍ لشراء {product_name}.\n"
            f"رصيدك الحالي: ${current_balance:.2f}.\n"
            f"السعر المطلوب: ${product_price:.2f}.\n"
            f"يرجى شحن محفظتك أولاً.",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END 
    else:
        await update.callback_query.message.reply_text(
            f"لشراء {product_name}، يرجى إدخال معرف اللعبة (Game ID) الخاص بك:"
        )
        return ASK_GAME_ID

async def receive_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل الـ Game ID ويرسل طلب الشراء للمسؤول."""
    game_id = update.message.text.strip()
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    product_id = context.user_data.get('purchase_product_id')
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found during game ID reception.")
        await update.message.reply_text("عذراً، حدث خطأ في معالجة طلبك. يرجى المحاولة مرة أخرى.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    product_name = product_details['name']
    final_price = product_details['price'] 

    if not game_id.isdigit():
        await update.message.reply_text("معرف اللعبة يجب أن يحتوي على أرقام فقط. يرجى إدخال معرف اللعبة الصحيح:")
        return ASK_GAME_ID 

    await update_user_wallet_db(user_id, -final_price) 
    new_balance = await get_user_wallet_db(user_id) 

    purchase_id = await add_purchase_history_db(user_id, username, product_name, game_id, final_price)

    if ADMIN_USER_ID:
        admin_notification_message = (
            f"🔔 طلب شراء جديد!\n\n"
            f"المستخدم: {username} (ID: {user_id})\n"
            f"المنتج: {product_name} (ID: {product_id})\n" 
            f"المبلغ: ${final_price:.2f} (تم الخصم من المحفظة)\n"
            f"رصيد المستخدم بعد الخصم: ${new_balance:.2f}\n"
            f"معرف اللعبة (Game ID): `{game_id}`\n"
            f"رقم الطلب: `{purchase_id}`\n\n"
            f"للتأكيد بعد الشحن: `/admin_confirm_shipped {purchase_id}`" 
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_notification_message, parse_mode='Markdown')
            logger.info(f"Admin {ADMIN_USER_ID} notified about new purchase request {purchase_id}.")
        except Exception as e:
            logger.error(f"Failed to send admin notification for purchase {purchase_id}: {str(e)}")

    await update.message.reply_text(
        f"✅ تم استلام طلب شراء {product_name} الخاص بك.\n"
        f"معرف اللعبة: `{game_id}`.\n"
        f"تم خصم ${final_price:.2f} من محفظتك. رصيدك الحالي: ${new_balance:.2f}.\n"
        f"طلبك برقم {purchase_id} في انتظار الشحن. سيتم إعلامك عند اكتمال العملية.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# --- دوال المسؤول (admin_confirm_deposit, admin_confirm_shipped) ---

async def admin_confirm_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يؤكد طلب إيداع و يحدث رصيد المستخدم."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    try:
        user_id_str = context.args[0]
        amount_str = context.args[1]
        user_id = int(user_id_str)
        amount = float(amount_str)
    except (IndexError, ValueError):
        await update.message.reply_text("الاستخدام: `/admin_confirm_deposit <معرف_المستخدم> <المبلغ>`")
        return

    new_balance = await update_user_wallet_db(user_id, amount) 

    await update.message.reply_text(
        f"✅ تم إضافة ${amount:.2f} إلى محفظة المستخدم {user_id}.\n"
        f"رصيده الجديد: ${new_balance:.2f} (تم الحفظ في قاعدة البيانات).",
        reply_markup=get_back_to_main_keyboard()
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=f"🎉 تم تأكيد إيداعك بمبلغ ${amount:.2f} في محفظتك! رصيدك الحالي: ${new_balance:.2f}")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about confirmed payment: {str(e)}")

async def admin_confirm_shipped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يؤكد عملية الشحن و يرسل إشعار للمستخدم."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    try:
        purchase_id = context.args[0]
    except (IndexError):
        await update.message.reply_text("الاستخدام: `/admin_confirm_shipped <معرف_الطلب>`")
        return

    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, product_name FROM purchases_history WHERE purchase_id = ?", (purchase_id,))
        purchase_details = cursor.fetchone()

    if not purchase_details:
        await update.message.reply_text(f"❌ لم يتم العثور على طلب بالمعرف: `{purchase_id}`.")
        return

    user_id, product_name = purchase_details

    await update_purchase_status_db(purchase_id, 'shipped', datetime.now().isoformat())
    logger.info(f"Purchase {purchase_id} for user {user_id}, product {product_name} marked as shipped in DB.")

    message_to_user = f"🎉 تم عملية الشحن بنجاح ✅ لمنتج: {product_name}!"
    try:
        await context.bot.send_message(chat_id=user_id, text=message_to_user)
        await update.message.reply_text(f"✅ تم إرسال إشعار الشحن بنجاح للمستخدم {user_id} لمنتج {product_name} (رقم الطلب: `{purchase_id}`).", reply_markup=get_back_to_main_keyboard())
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about shipped purchase {purchase_id}: {str(e)}")
        await update.message.reply_text(f"❌ فشل إرسال إشعار الشحن للمستخدم {user_id}.", reply_markup=get_back_to_main_keyboard())


# --- دوال المحفظة والإيداع (wallet, syriatel_cash_deposit_*, deposit_*) ---

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض رصيد المحفظة للمستخدم وخيارات الإيداع."""
    user_id = update.effective_user.id
    balance = await get_user_wallet_db(user_id)

    message = f"💰 رصيد محفظتك الحالي هو: ${balance:.2f}\n\n" \
              "اختر طريقة الإيداع:"

    if update.message: 
        await update.message.reply_text(message, reply_markup=get_wallet_keyboard())
    elif update.callback_query: 
        await update.callback_query.message.reply_text(message, reply_markup=get_wallet_keyboard())
        try:
            await update.callback_query.delete_message()
        except BadRequest:
            pass


async def syriatel_cash_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ عملية إيداع سيرياتيل كاش: يعرض رسالة التحويل و يطلب المبلغ."""
    syriatel_message = """
رقم التحويل: `69643514`

لست مسؤول عن تحويل رصيد
يرجى بعث رقم عملية التحويل 
Zenetsu Shop ⚡️🇸🇾⚡️

يرجى إدخال المبلغ الذي قمت بتحويله (بالدولار):
    """
    await update.callback_query.message.reply_text(syriatel_message, parse_mode='Markdown')
    return SYRIATEL_CASH_AMOUNT

async def syriatel_cash_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل مبلغ سيرياتيل كاش و يطلب رقم العملية."""
    try:
        amount = float(update.message.text)
        if amount <= 0:
            await update.message.reply_text("المبلغ يجب أن يكون رقماً موجباً. يرجى إدخال المبلغ الصحيح:")
            return SYRIATEL_CASH_AMOUNT
        context.user_data['syriatel_cash_amount'] = amount
        await update.message.reply_text("الآن، يرجى إدخال رقم العملية (Transaction ID) من سيرياتيل كاش:")
        return SYRIATEL_CASH_TRANSACTION_ID
    except ValueError:
        await update.message.reply_text("المبلغ غير صالح. يرجى إدخال رقم صحيح للمبلغ:")
        return SYRIATEL_CASH_AMOUNT 

async def deposit_transaction_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل رقم العملية و يضيف المعاملة المعلقة (للايداع العام)."""
    transaction_id = update.message.text.strip()
    amount = context.user_data['deposit_amount']
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    payment_id = await add_pending_payment(user_id, username, amount, transaction_id, payment_method="General Deposit", context=context)

    await update.message.reply_text(
        f"✅ تم استلام طلب إيداعك بمبلغ ${amount:.2f} ورقم عملية {transaction_id}.\n"
        f"طلبك برقم {payment_id} في انتظار المراجعة من قبل الإدارة. سيتم تحديث رصيدك بعد التأكيد.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

async def cancel_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يلغي عملية الإيداع."""
    await update.message.reply_text("تم إلغاء عملية الإيداع.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# --- دوال الشراء (request_game_id, receive_game_id) ---

async def request_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دالة لطلب الـ Game ID من المستخدم."""
    product_id = context.user_data.get('purchase_product_id')
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found for purchase request.")
        await update.callback_query.message.reply_text("عذراً، لم يتم العثور على هذا المنتج لإتمام عملية الشراء.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    # تحقق من التوفر الزمني هنا
    server_id = product_details.get("server_id")
    if server_id:
        server_data = find_item_by_id(server_id)
        if server_data and server_data.get("availability_window"):
            now = datetime.now()
            current_hour = now.hour
            start_hour = server_data["availability_window"]["start_hour"]
            end_hour = server_data["availability_window"]["end_hour"]

            if not (start_hour <= current_hour < end_hour):
                await update.callback_query.message.reply_text(
                    f"عذراً، منتج {product_details['name']} غير متاح للشراء في هذا الوقت. "
                    f"يتوفر فقط من الساعة {start_hour}:00 وحتى {end_hour}:00 مساءً. "
                    f"غير متوفر للساعة 7 مساءً ❌", # الرسالة المطلوبة
                    reply_markup=get_main_menu_keyboard()
                )
                return ConversationHandler.END


    product_name = product_details['name']
    product_price = product_details['price']
    user_id = update.effective_user.id

    current_balance = await get_user_wallet_db(user_id)

    if current_balance < product_price:
        await update.callback_query.message.reply_text(
            f"😔 رصيدك غير كافٍ لشراء {product_name}.\n"
            f"رصيدك الحالي: ${current_balance:.2f}.\n"
            f"السعر المطلوب: ${product_price:.2f}.\n"
            f"يرجى شحن محفظتك أولاً.",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END 
    else:
        await update.callback_query.message.reply_text(
            f"لشراء {product_name}، يرجى إدخال معرف اللعبة (Game ID) الخاص بك:"
        )
        return ASK_GAME_ID

async def receive_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل الـ Game ID ويرسل طلب الشراء للمسؤول."""
    game_id = update.message.text.strip()
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    product_id = context.user_data.get('purchase_product_id')
    product_details = find_item_by_id(product_id)

    if not product_details or product_details.get("type") != "product":
        logger.error(f"Product with ID '{product_id}' not found during game ID reception.")
        await update.message.reply_text("عذراً، حدث خطأ في معالجة طلبك. يرجى المحاولة مرة أخرى.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    product_name = product_details['name']
    final_price = product_details['price'] 

    if not game_id.isdigit():
        await update.message.reply_text("معرف اللعبة يجب أن يحتوي على أرقام فقط. يرجى إدخال معرف اللعبة الصحيح:")
        return ASK_GAME_ID 

    await update_user_wallet_db(user_id, -final_price) 
    new_balance = await get_user_wallet_db(user_id) 

    purchase_id = await add_purchase_history_db(user_id, username, product_name, game_id, final_price)

    if ADMIN_USER_ID:
        admin_notification_message = (
            f"🔔 طلب شراء جديد!\n\n"
            f"المستخدم: {username} (ID: {user_id})\n"
            f"المنتج: {product_name} (ID: {product_id})\n" 
            f"المبلغ: ${final_price:.2f} (تم الخصم من المحفظة)\n"
            f"رصيد المستخدم بعد الخصم: ${new_balance:.2f}\n"
            f"معرف اللعبة (Game ID): `{game_id}`\n"
            f"رقم الطلب: `{purchase_id}`\n\n"
            f"للتأكيد بعد الشحن: `/admin_confirm_shipped {purchase_id}`" 
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_notification_message, parse_mode='Markdown')
            logger.info(f"Admin {ADMIN_USER_ID} notified about new purchase request {purchase_id}.")
        except Exception as e:
            logger.error(f"Failed to send admin notification for purchase {purchase_id}: {str(e)}")

    await update.message.reply_text(
        f"✅ تم استلام طلب شراء {product_name} الخاص بك.\n"
        f"معرف اللعبة: `{game_id}`.\n"
        f"تم خصم ${final_price:.2f} من محفظتك. رصيدك الحالي: ${new_balance:.2f}.\n"
        f"طلبك برقم {purchase_id} في انتظار الشحن. سيتم إعلامك عند اكتمال العملية.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# --- دوال المسؤول (admin_confirm_deposit, admin_confirm_shipped) ---

async def admin_confirm_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يؤكد طلب إيداع و يحدث رصيد المستخدم."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    try:
        user_id_str = context.args[0]
        amount_str = context.args[1]
        user_id = int(user_id_str)
        amount = float(amount_str)
    except (IndexError, ValueError):
        await update.message.reply_text("الاستخدام: `/admin_confirm_deposit <معرف_المستخدم> <المبلغ>`")
        return

    new_balance = await update_user_wallet_db(user_id, amount) 

    await update.message.reply_text(
        f"✅ تم إضافة ${amount:.2f} إلى محفظة المستخدم {user_id}.\n"
        f"رصيده الجديد: ${new_balance:.2f} (تم الحفظ في قاعدة البيانات).",
        reply_markup=get_back_to_main_keyboard()
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=f"🎉 تم تأكيد إيداعك بمبلغ ${amount:.2f} في محفظتك! رصيدك الحالي: ${new_balance:.2f}")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about confirmed payment: {str(e)}")

async def admin_confirm_shipped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يؤكد عملية الشحن و يرسل إشعار للمستخدم."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    try:
        purchase_id = context.args[0]
    except (IndexError):
        await update.message.reply_text("الاستخدام: `/admin_confirm_shipped <معرف_الطلب>`")
        return

    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, product_name FROM purchases_history WHERE purchase_id = ?", (purchase_id,))
        purchase_details = cursor.fetchone()

    if not purchase_details:
        await update.message.reply_text(f"❌ لم يتم العثور على طلب بالمعرف: `{purchase_id}`.")
        return

    user_id, product_name = purchase_details

    await update_purchase_status_db(purchase_id, 'shipped', datetime.now().isoformat())
    logger.info(f"Purchase {purchase_id} for user {user_id}, product {product_name} marked as shipped in DB.")

    message_to_user = f"🎉 تم عملية الشحن بنجاح ✅ لمنتج: {product_name}!"
    try:
        await context.bot.send_message(chat_id=user_id, text=message_to_user)
        await update.message.reply_text(f"✅ تم إرسال إشعار الشحن بنجاح للمستخدم {user_id} لمنتج {product_name} (رقم الطلب: `{purchase_id}`).", reply_markup=get_back_to_main_keyboard())
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about shipped purchase {purchase_id}: {str(e)}")
        await update.message.reply_text(f"❌ فشل إرسال إشعار الشحن للمستخدم {user_id}.", reply_markup=get_back_to_main_keyboard())


# --- دوال المحفظة والإيداع (wallet, syriatel_cash_deposit_*, deposit_*) ---

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض رصيد المحفظة للمستخدم وخيارات الإيداع."""
    user_id = update.effective_user.id
    balance = await get_user_wallet_db(user_id)

    message = f"💰 رصيد محفظتك الحالي هو: ${balance:.2f}\n\n" \
              "اختر طريقة الإيداع:"

    if update.message: 
        await update.message.reply_text(message, reply_markup=get_wallet_keyboard())
    elif update.callback_query: 
        await update.callback_query.message.reply_text(message, reply_markup=get_wallet_keyboard())
        try:
            await update.callback_query.delete_message()
        except BadRequest:
            pass


async def syriatel_cash_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ عملية إيداع سيرياتيل كاش: يعرض رسالة التحويل و يطلب المبلغ."""
    syriatel_message = """
رقم التحويل: `69643514`

لست مسؤول عن تحويل رصيد
يرجى بعث رقم عملية التحويل 
Zenetsu Shop ⚡️🇸🇾⚡️

يرجى إدخال المبلغ الذي قمت بتحويله (بالدولار):
    """
    await update.callback_query.message.reply_text(syriatel_message, parse_mode='Markdown')
    return SYRIATEL_CASH_AMOUNT

async def syriatel_cash_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل مبلغ سيرياتيل كاش و يطلب رقم العملية."""
    try:
        amount = float(update.message.text)
        if amount <= 0:
            await update.message.reply_text("المبلغ يجب أن يكون رقماً موجباً. يرجى إدخال المبلغ الصحيح:")
            return SYRIATEL_CASH_AMOUNT
        context.user_data['syriatel_cash_amount'] = amount
        await update.message.reply_text("الآن، يرجى إدخال رقم العملية (Transaction ID) من سيرياتيل كاش:")
        return SYRIATEL_CASH_TRANSACTION_ID
    except ValueError:
        await update.message.reply_text("المبلغ غير صالح. يرجى إدخال رقم صحيح للمبلغ:")
        return SYRIATEL_CASH_AMOUNT 

async def deposit_transaction_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل رقم العملية و يضيف المعاملة المعلقة (للايداع العام)."""
    transaction_id = update.message.text.strip()
    amount = context.user_data['deposit_amount']
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name

    payment_id = await add_pending_payment(user_id, username, amount, transaction_id, payment_method="General Deposit", context=context)

    await update.message.reply_text(
        f"✅ تم استلام طلب إيداعك بمبلغ ${amount:.2f} ورقم عملية {transaction_id}.\n"
        f"طلبك برقم {payment_id} في انتظار المراجعة من قبل الإدارة. سيتم تحديث رصيدك بعد التأكيد.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

async def cancel_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يلغي عملية الإيداع."""
    await update.message.reply_text("تم إلغاء عملية الإيداع.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# --- دوال الإحصائيات (الجديدة) ---
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض إحصائيات المستخدمين للمسؤول."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return

    total_users = await get_total_users_db()
    new_users_today = await get_new_users_today_db()
    active_users_24h = await get_active_users_last_24_hours_db()

    stats_message = (
        f"📊 إحصائيات المستخدمين:\n\n"
        f"👤 العدد الكلي للمستخدمين: {total_users}\n"
        f"🆕 سجلوا اليوم: {new_users_today}\n"
        f"🟢 نشطون آخر 24 ساعة: {active_users_24h}\n\n"
        f"تاريخ ووقت الإحصائية: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await update.message.reply_text(stats_message, reply_markup=get_back_to_main_keyboard())

# --- دوال البث (Broadcast) ---

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ عملية إرسال رسالة جماعية للمسؤول."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return ConversationHandler.END

    await update.message.reply_text("يرجى إرسال الرسالة التي تود بثها لجميع المستخدمين. اكتب /cancel للإلغاء.")
    return BROADCAST_MESSAGE

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل رسالة البث و يرسلها لجميع المستخدمين."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لهذا الأمر.")
        return ConversationHandler.END

    message_text = update.message.text
    all_user_ids = await get_all_user_ids_db() # جلب جميع معرفات المستخدمين

    sent_count = 0
    blocked_count = 0

    await update.message.reply_text(f"جاري إرسال الرسالة لـ {len(all_user_ids)} مستخدم...", disable_notification=True)

    for user_id in all_user_ids:
        try:
            # تجنب إرسال الرسالة إلى المسؤول نفسه مرة أخرى (إذا كان يرغب)
            if user_id == ADMIN_USER_ID:
                continue
            await context.bot.send_message(chat_id=user_id, text=message_text)
            sent_count += 1
        except Exception as e:
            logger.warning(f"Failed to send broadcast message to user {user_id}: {e}")
            # التعامل مع المستخدمين الذين حظروا البوت
            if "blocked by the user" in str(e) or "user is deactivated" in str(e):
                blocked_count += 1
            # يمكن هنا إضافة منطق لحذف المستخدمين الذين حظروا البوت من قاعدة البيانات إذا أردت
            # ولكن كن حذراً عند حذف البيانات.

    await update.message.reply_text(
        f"✅ تم الانتهاء من البث!\n"
        f"تم الإرسال بنجاح إلى: {sent_count} مستخدم.\n"
        f"فشل الإرسال (ربما حظروا البوت): {blocked_count} مستخدم."
    )
    return ConversationHandler.END # إنهاء المحادثة بعد البث

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يلغي عملية البث."""
    await update.message.reply_text("تم إلغاء عملية البث.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END


# --- الدوال المعالجة الرئيسية (start, handle_message, handle_callback_query) ---
# هذه الدوال يجب أن تأتي في النهاية، قبل دالة main() مباشرة
# هذا هو الترتيب الذي يجب أن يحل جميع NameErrors المتعلقة بالتعريف

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يبدأ البوت ويعرض القائمة الرئيسية."""
    user = update.effective_user

    # تحديث last_activity عند كل تفاعل مع /start
    await update_user_activity_db(user.id)

    if GROUP_ID and GROUP_JOIN_LINK and not context.user_data.get('channel_join_message_sent', False):
        await send_channel_join_message(update, user.id, user.first_name, context)

    await update_user_wallet_db(user.id, 0.0, user.username if user.username else user.first_name)

    welcome_message = f"""
🌟 أهلاً بك يا {user.first_name} في {WEBSITE_NAME} 🌟

{WEBSITE_SLOGAN}
{WEBSITE_DESCRIPTION}

{WEBSITE_MESSAGE}

اختر من القائمة أدناه ما تريد:
    """

    await update.message.reply_text(
        welcome_message,
        reply_markup=get_main_menu_keyboard()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعالج الرسائل النصية الواردة من المستخدمين."""
    user = update.effective_user
    # تحديث last_activity عند كل تفاعل مع رسالة نصية
    await update_user_activity_db(user.id)

    text = update.message.text

    if text == "🛍️ تصفح المنتجات":
        await show_categories(update, context)
    elif text == "ℹ️ معلومات عنا":
        await show_about_us(update, context)
    elif text == "📞 التواصل معنا":
        await show_contact_info(update, context)
    elif text == "🛒 سلة المشتريات":
        await show_cart(update, context)
    elif text == "📋 طلباتي":
        await show_orders(update, context)
    elif text == "💰 محفظتي":
        await wallet(update, context)
    elif text == "🏠 القائمة الرئيسية":
        await start(update, context)
    else:
        await update.message.reply_text(
            "عذراً، لم أفهم طلبك. يرجى استخدام الأزرار المتاحة.",
            reply_markup=get_main_menu_keyboard()
        )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعالج ضغطات الأزرار (Callback Queries) الواردة من المستخدمين."""
    query = update.callback_query
    user = update.effective_user
    # تحديث last_activity عند كل تفاعل مع CallbackQuery
    await update_user_activity_db(user.id)

    await query.answer()

    data = query.data

    try:
        if data == "main_menu":
            await start(update, context)
            try:
                await query.delete_message()
            except BadRequest:
                pass
        elif data == "categories":
            await show_categories(update, context)
        elif data.startswith("cat_"):
            category_id = data[4:]
            await show_subcategories(update, context, category_id)
        elif data.startswith("subcat_"):
            subcategory_id = data[7:]
            sub_item_data = find_item_by_id(subcategory_id)
            if sub_item_data and "servers" in sub_item_data["data"]:
                await show_servers(update, context, subcategory_id)
            else:
                await show_products(update, context, subcategory_id)
        elif data.startswith("server_"):
            server_id = data[7:]
            await show_products(update, context, server_id)
        elif data.startswith("product_"):
            product_id = data[8:]
            await show_product_details(update, context, product_id)

        elif data.startswith("add_cart_"):
            product_id = data[9:]
            await add_to_cart(update, context, product_id)
        elif data.startswith("buy_now_"):
            product_id = data[8:]
            context.user_data['purchase_product_id'] = product_id
            await request_game_id(update, context)
        elif data.startswith("buy_cart_item_"):
            product_id = data[len("buy_cart_item_"):]
            context.user_data['purchase_product_id'] = product_id
            await request_game_id(update, context)

        elif data == "syriatel_cash_deposit":
            await syriatel_cash_deposit_start(update, context)
        elif data == "show_products_main":
            await show_categories(update, context)
        elif data == "show_cart_main":
            await show_cart(update, context)
        elif data == "show_orders_main":
            await show_orders(update, context)
        elif data == "show_about_us_main":
            await show_about_us(update, context)
        elif data == "show_contact_info_main":
            await show_contact_info(update, context)
        elif data == "show_wallet_main":
            await wallet(update, context)
    except BadRequest as e:
        logger.warning(f"BadRequest error in handle_callback_query for data '{data}': {e}. Sending new message instead.")
        await query.message.reply_text(
            "عذراً، حدث خطأ. يرجى البدء من جديد باستخدام القائمة الرئيسية.",
            reply_markup=get_main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"An unexpected error occurred in handle_callback_query for data '{data}': {e}", exc_info=True)
        await query.message.reply_text(
            "عذراً، حدث خطأ غير متوقع. يرجى المحاولة لاحقاً.",
            reply_markup=get_main_menu_keyboard()
        )


def main() -> None:
    """الدالة الرئيسية لتشغيل البوت."""
    init_db()

    if not BOT_TOKEN:
        print("خطأ: لم يتم العثور على 'BOT_TOKEN' في ملف .env.")
        print("تأكد أنك قمت بإنشاء ملف .env في نفس مجلد bot.py،")
        print("وأن BOT_TOKEN='YOUR_ACTUAL_BOT_TOKEN_HERE' (مع التوكن الحقيقي) موجود فيه.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # يجب انتظار initialize() لأنها coroutine
    application.bot.initialize()

    # --- معالجات ConversationHandler ---
    syriatel_cash_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(syriatel_cash_deposit_start, pattern='^syriatel_cash_deposit$')],
        states={
            SYRIATEL_CASH_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, syriatel_cash_deposit_amount)],
            SYRIATEL_CASH_TRANSACTION_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, syriatel_cash_deposit_transaction_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel_deposit)],
    )
    application.add_handler(syriatel_cash_conv_handler)

    deposit_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("deposit", deposit_start)],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount)],
            TRANSACTION_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_transaction_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel_deposit)],
    )
    application.add_handler(deposit_conv_handler)

    buy_now_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(request_game_id, pattern='^buy_now_')],
        states={
            ASK_GAME_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_game_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel_deposit)],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END
        }
    )
    application.add_handler(buy_now_conv_handler)

    # ConversationHandler للبث
    broadcast_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_message)],
        },
        fallbacks=[CommandHandler("cancel", cancel_broadcast)],
    )
    application.add_handler(broadcast_conv_handler)

    # --- معالجات الأوامر والرسائل العادية ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # --- أوامر المسؤول ---
    application.add_handler(CommandHandler("admin_confirm_deposit", admin_confirm_deposit))
    application.add_handler(CommandHandler("admin_confirm_shipped", admin_confirm_shipped))
    application.add_handler(CommandHandler("stats", stats))
    # الأمر /broadcast تم إضافته بالفعل كجزء من entry_points في ConversationHandler

    print(f"🤖 تم تشغيل بوت {WEBSITE_NAME} بنجاح! يتم تخزين البيانات بشكل دائم.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


# تشغيل البوت الخاص بك (تأكد أن 'application' معرف مسبقًا في كود آخر)
if __name__ == '__main__':
    print("🚀 Starting Telegram bot...")
    application.run_polling()
