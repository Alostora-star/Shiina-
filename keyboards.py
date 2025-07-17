# keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from data import PRODUCTS_DATA, find_item_by_id 

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("🛍️ تصفح المنتجات"), KeyboardButton("🛒 سلة المشتريات")],
        [KeyboardButton("📋 طلباتي"), KeyboardButton("ℹ️ معلومات عنا"), KeyboardButton("📞 التواصل معنا")],
        [KeyboardButton("💰 محفظتي")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def get_back_to_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton("🏠 القائمة الرئيسية")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def get_wallet_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("سيرياتيل كاش 📞", callback_data="syriatel_cash_deposit")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(buttons)

def get_categories_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for category_name, category_data in PRODUCTS_DATA.items():
        category_id = category_data.get("id")
        if category_id:
            buttons.append([InlineKeyboardButton(category_name, callback_data=f"cat_{category_id}")])
    buttons.append([InlineKeyboardButton("⬅️ رجوع", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def get_subcategories_keyboard(category_id: str) -> InlineKeyboardMarkup: 
    buttons = []
    category_data = find_item_by_id(category_id)
    if not category_data or category_data.get("type") != "category":
        return InlineKeyboardMarkup([]) 

    for subcategory_name, subcategory_data in category_data.get("data", {}).get("subcategories", {}).items():
        subcategory_id = subcategory_data.get("id")
        if subcategory_id:
            buttons.append([InlineKeyboardButton(subcategory_name, callback_data=f"subcat_{subcategory_id}")])
    
    buttons.append([InlineKeyboardButton("⬅️ رجوع", callback_data="categories")])
    return InlineKeyboardMarkup(buttons)

def get_servers_keyboard(subcategory_id: str) -> InlineKeyboardMarkup:
    buttons = []
    subcategory_data = find_item_by_id(subcategory_id)
    if not subcategory_data or subcategory_data.get("type") != "subcategory" or "servers" not in subcategory_data.get("data", {}):
        return InlineKeyboardMarkup([])

    for server_name, server_data in subcategory_data["data"]["servers"].items():
        server_id = server_data.get("id")
        if server_id:
            buttons.append([InlineKeyboardButton(server_name, callback_data=f"server_{server_id}")])
    
    buttons.append([InlineKeyboardButton("⬅️ رجوع", callback_data=f"subcat_{subcategory_id}")]) 
    return InlineKeyboardMarkup(buttons)

def get_products_keyboard(item_id: str) -> InlineKeyboardMarkup: 
    buttons = []
    item_data = find_item_by_id(item_id) 
    
    products_to_show = {}
    if item_data and item_data.get("type") == "server":
        products_to_show = item_data.get("data", {}).get("products", {})
    elif item_data and item_data.get("type") == "subcategory" and "products" in item_data.get("data", {}):
        products_to_show = item_data.get("data", {}).get("products", {})
    
    for product_name, details in products_to_show.items():
        product_id = details.get("id")
        if product_id:
            buttons.append([InlineKeyboardButton(product_name, callback_data=f"product_{product_id}")])
    
    # تحديد زر الرجوع بناءً على نوع العنصر
    back_callback_data = "main_menu" # Fallback

    if item_data and item_data.get("type") == "server":
        back_callback_data = f"subcat_{item_data['subcategory_id']}" 
    elif item_data and item_data.get("type") == "subcategory":
        back_callback_data = f"cat_{item_data['category_id']}"
    
    buttons.append([InlineKeyboardButton("⬅️ رجوع", callback_data=back_callback_data)])
    return InlineKeyboardMarkup(buttons)

def get_product_actions_keyboard(product_id: str) -> InlineKeyboardMarkup:
    product_details = find_item_by_id(product_id)
    if not product_details or product_details.get("type") != "product":
        return InlineKeyboardMarkup([]) 

    back_callback_data = "main_menu" # Fallback

    if product_details.get("server_id"): 
        back_callback_data = f"server_{product_details['server_id']}"
    elif product_details.get("subcategory_id"): 
        back_callback_data = f"subcat_{product_details['subcategory_id']}"

    buttons = [
        [InlineKeyboardButton("🛒 إضافة للسلة", callback_data=f"add_cart_{product_id}")],
        [InlineKeyboardButton("💳 شراء الآن", callback_data=f"buy_now_{product_id}")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data=back_callback_data)]
    ]
    return InlineKeyboardMarkup(buttons)