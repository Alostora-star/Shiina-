# data.py
import uuid
from datetime import datetime

# قاموس لتخزين بيانات المنتجات
# هيكل: الفئة -> بيانات الفئة (id, subcategories)
# الفئة الفرعية -> بيانات الفئة الفرعية (id, products OR servers)
# السيرفر -> بيانات السيرفر (id, products, availability_window)
# المنتج -> بيانات المنتج (price, id)
PRODUCTS_DATA = {
    "ألعاب": { # Category ID: games
        "id": "games",
        "subcategories": {
            "فري فاير 💎": { # Subcategory ID: freefire_main
                "id": "freefire_main",
                "servers": { # ليس منتجات مباشرة، بل سيرفرات
                    "فري فاير سيرفر 1": { # Server ID: ffs1
                        "id": "ffs1",
                        # نافذة التوفر: متاح من 7 مساءً (19:00) حتى 8 مساءً (20:00)
                        "availability_window": {"start_hour": 19, "end_hour": 20},
                        "products": {
                            "100 💎": {"price": 0.9, "id": "ffs1_100_gems"},
                            "210 💎": {"price": 1.8, "id": "ffs1_210_gems"},
                            "520 💎": {"price": 4.5, "id": "ffs1_520_gems"},
                            "1080 💎": {"price": 8.5, "id": "ffs1_1080_gems"},
                            "العضوية الأسبوعية 💎": {"price": 2.0, "id": "ffs1_weekly_mem"},
                            "العضوية الشهرية 💎": {"price": 6.0, "id": "ffs1_monthly_mem"},
                        }
                    },
                    "فري فاير سيرفر 2": { # Server ID: ffs2
                        "id": "ffs2",
                        "products": {
                            "100 💎": {"price": 1.0, "id": "ffs2_100_gems"}, # منتجات جديدة
                            "210 💎": {"price": 2.0, "id": "ffs2_210_gems"},
                            "520 💎": {"price": 5.0, "id": "ffs2_520_gems"},
                            "1080 💎": {"price": 9.8, "id": "ffs2_1080_gems"},
                        }
                    },
                }
            },
            "ببجي 🎮": { # Subcategory ID: pubg_main
                "id": "pubg_main",
                "products": {
                    "60 🪙": {"price": 0.95, "id": "pubg_60_uc"}, # منتجات جديدة
                    "120 🪙": {"price": 1.90, "id": "pubg_120_uc"},
                    "180 🪙": {"price": 2.85, "id": "pubg_180_uc"},
                    "325 🪙": {"price": 4.7, "id": "pubg_325_uc"},
                    "660 🪙": {"price": 9.3, "id": "pubg_660_uc"}, # تم تعديل السعر والاسم
                    "1800 🪙": {"price": 24.0, "id": "pubg_1800_uc"}, # تم تعديل السعر والاسم
                }
            }
        }
    },
    "خدمات اجتماعية": { # Category ID: social_services
        "id": "social_services",
        "subcategories": {
            "انستغرام": { # Subcategory ID: instagram
                "id": "instagram",
                "products": {
                    "1000 متابع انستغرام": {"price": 5.0, "id": "insta_1000_followers"},
                    "5000 لايك انستغرام": {"price": 8.0, "id": "insta_5000_likes"},
                }
            },
            "تيك توك": { # Subcategory ID: tiktok
                "id": "tiktok",
                "products": {
                    "1000 متابع تيك توك": {"price": 4.0, "id": "tiktok_1000_followers"},
                    "10000 مشاهدة تيك توك": {"price": 6.0, "id": "tiktok_10000_views"},
                }
            }
        }
    }
}

def find_item_by_id(item_id: str):
    """يبحث عن عنصر (فئة، فئة فرعية، سيرفر، منتج) بناءً على الـ ID الخاص به."""
    for category_name, category_data in PRODUCTS_DATA.items():
        if category_data.get("id") == item_id:
            return {"type": "category", "name": category_name, "id": item_id, "data": category_data}
        
        for subcategory_name, subcategory_data in category_data.get("subcategories", {}).items():
            if subcategory_data.get("id") == item_id:
                return {"type": "subcategory", "name": subcategory_name, "id": item_id, 
                        "category_name": category_name, "category_id": category_data.get("id"), 
                        "data": subcategory_data}
            
            # Check for servers (if applicable)
            if "servers" in subcategory_data:
                for server_name, server_data in subcategory_data["servers"].items():
                    if server_data.get("id") == item_id:
                        return {"type": "server", "name": server_name, "id": item_id, 
                                "category_name": category_name, "category_id": category_data.get("id"), 
                                "subcategory_name": subcategory_name, "subcategory_id": subcategory_data.get("id"), 
                                "availability_window": server_data.get("availability_window"), # إضافة نافذة التوفر
                                "data": server_data}
                    
                    # Check for products within servers
                    for product_name, product_details in server_data.get("products", {}).items():
                        if product_details.get("id") == item_id:
                            return {
                                "type": "product", "name": product_name, "id": item_id,
                                "category_name": category_name, "category_id": category_data.get("id"), 
                                "subcategory_name": subcategory_name, "subcategory_id": subcategory_data.get("id"), 
                                "server_name": server_name, "server_id": server_data.get("id"), 
                                "availability_window": server_data.get("availability_window"), # إضافة نافذة التوفر من السيرفر
                                "price": product_details["price"]
                            }
            # Check for products directly under subcategories (if no servers)
            elif "products" in subcategory_data:
                for product_name, product_details in subcategory_data["products"].items():
                    if product_details.get("id") == item_id:
                        return {
                            "type": "product", "name": product_name, "id": item_id,
                            "category_name": category_name, "category_id": category_data.get("id"), 
                            "subcategory_name": subcategory_name, "subcategory_id": subcategory_data.get("id"), 
                            "server_name": None, "server_id": None, 
                            "availability_window": None, # لا يوجد نافذة توفر لهذه المنتجات
                            "price": product_details["price"]
                        }
    return None

def get_product_price(product_id: str) -> float:
    """يحصل على السعر الأساسي للمنتج باستخدام الـ ID."""
    product_data = find_item_by_id(product_id)
    if product_data and product_data.get("type") == "product":
        return product_data.get("price", 0.0)
    return 0.0

def calculate_price_with_increase(base_price: float, percentage_increase: float) -> float:
    """يحسب السعر بعد إضافة نسبة الزيادة."""
    return base_price * (1 + percentage_increase)