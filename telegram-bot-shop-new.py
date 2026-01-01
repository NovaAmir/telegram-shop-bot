from telegram import (Update , InlineKeyboardButton , InlineKeyboardMarkup , ReplyKeyboardMarkup , ReplyKeyboardRemove, InputMediaPhoto)
from telegram.ext import (ApplicationBuilder , CommandHandler , ContextTypes , CallbackQueryHandler , Application , MessageHandler , filters , ConversationHandler)
import logging
import os
import json
import uuid
import re
from datetime import datetime, timezone, timedelta
from collections import Counter
from typing import Dict,List,Optional,Tuple
import emoji
import requests
import asyncio
import threading
from flask import Flask, request
import jdatetime
from collections import Counter



CUSTOMER_NAME, CUSTOMER_PHONE, CUSTOMER_ADDRESS, CUSTOMER_POSTAL = range(4)

logging.basicConfig(level=logging.INFO,format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN","").strip()
if not BOT_TOKEN :
    logger.warning("⚠️ متغییر محیطی BOT_TOKEN تنظیم نشده است . قبل از اجرا آن را ست کنید .")

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID" , "").strip() or None

# Manual card payment settings
CARDS = [{"holder":"امیرمهدی پیری" , "number": "6104338705632277"} , {"holder":"امیرمهدی پیری" , "number": "5859831211429799"}]
ADMIN_USERNAME = "@Amirmehdi_84_11"


def _safe_callback(val):
    import re
    val = str(val)
    val = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF\-_]', '', val)
    return val[:15]  # حداکثر 15 کاراکتر برای کاهش احتمال Button_data_invalid (قبلاً 40 بود)

def _unsafe_color(safe_color: str, product_variants: Dict) -> Optional[str]:
    for color in product_variants.keys():
        safe_color_test = _safe_callback(color)
        logger.info(f"Comparing: '{safe_color}' with '{safe_color_test}' from original '{color}'")
        if safe_color_test == safe_color:
            return color
    return None


#      storge(json)
DB_FILE = os.getenv("SHOP_DB_FILE" , "shop_db.json")

def _atomic_write(path:str , data:dict):
    tmp = path + ".tmp"
    with open(tmp , "w" , encoding="utf_8") as f:
        json.dump(data , f , ensure_ascii=False , indent=2)
    os.replace(tmp , path)

class Storge:
    def __init__(self , path=DB_FILE):
        self.path = path
        self.data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path , "r" , encoding="utf_8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}
    
    def save(self):
        _atomic_write(self.path , self.data)

    def get_catalog(self , default_catalog:dict) -> dict:
        if "catalog" not in self.data:
            self.data["catalog"] = default_catalog
            self.save()
        return self.data["catalog"]
    
    def set_catalog(self , catalog:dict):
        self.data["catalog"] = catalog
        self.save()
    
    def add_order(self , order:dict):
        self.data.setdefault("orders" , [])
        self.data["orders"].append(order)
        self.save()
    
    def find_order(self , order_id:str) -> Optional[dict]:
        for o in self.data.get("orders" , []):
            if o.get("order_id") == order_id:
                return o
        return None
    
    def update_order(self , order_id:str , **updates):
        arr = self.data.get("orders" , [])
        for i , o in enumerate(arr):
            if o.get("order_id") == order_id:
                arr[i].update(updates)
                self.save()
                return arr[i]
        return None

STORE = Storge()

# ------------------ Discount codes (Coupons) ------------------
def _ensure_discount_storage():
    """Initialize discount-related keys in shop_db.json (non-destructive)."""
    try:
        STORE.data.setdefault("discount_codes", {})
        STORE.data.setdefault("discount_redemptions", {})
        STORE.data.setdefault("recovery_coupon_issued", {})
        STORE.save()
    except Exception:
        pass

_ensure_discount_storage()
# ------------------ end Discount codes ------------------


# If admin chat id not set via env, try loading from storage
if not ADMIN_CHAT_ID:
    try:
        ADMIN_CHAT_ID = STORE.data.get("admin_chat_id") or None
    except Exception:
        ADMIN_CHAT_ID = None



#        catalog
CATALOG: Dict[str,Dict[str,List[Dict]]] = {
    "men":{
        "کفش":[
            {"id": "men-shoe-running-hobi-gs8226" , 
             "name":"کفش رانینگ هابی مدل GS8226" , 
             "thumbnail" : "https://res.cloudinary.com/dkzhxotve/image/upload/v1766765624/men-shoe-running-hobi-gs8226_ysltf6.webp" ,
             "variants": {
                 "مشکی" : {
                     "photo" : "https://res.cloudinary.com/dkzhxotve/image/upload/v1766765624/men-shoe-running-hobi-gs8226_ysltf6.webp" ,
                     "price" : 1_500_000 ,
                     "buy_price" : 1_300_000 ,
                     "sizes" : {"40":3 , "41":1 , "42":4 , "43":3 ,  "44":2}
                    },
                 "سفید" : {
                     "photo" : "https://res.cloudinary.com/dkzhxotve/image/upload/v1766765777/men-shoe-running-hobi-gs8226-white_omgvwk.webp" ,
                     "price" : 1_300_000 ,
                     "buy_price" : 1_100_000 , 
                     "sizes" : {"40":2 , "41":0 , "42":3 , "43":2 , "44":1}
                 }
                }    
            },
            # FIX: شناسه محصول حاوی فاصله برای Air Force 1
            {"id":"men-shoe-Air-Force-1-WH-1990" , 
             "name":"کفش پیاده روی مردانه مدل Air Force 1 WH 1990" ,
             "thumbnail":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766765980/men-shoe-Air-Force-1-WH-1990_j4fbuc.webp" , 
             "variants":{
                 "مشکی" : {
                     "photo" : "https://res.cloudinary.com/dkzhxotve/image/upload/v1766766101/men-shoe-Air-Force-1-WH-1990Black_yn6bny.webp" , 
                     "price" : 650_000 ,
                     "buy_price" : 500_000 ,  
                     "sizes" : {"39":3 , "40":5 , "42":2 , "43":1}
                 },
                 "سفید" : {
                     "photo" : "https://res.cloudinary.com/dkzhxotve/image/upload/v1766765980/men-shoe-Air-Force-1-WH-1990_j4fbuc.webp" ,
                     "price" : 650_000 , 
                     "buy_price" : 500_000 , 
                     "sizes" : {"40":3 , "41":2 , "43":3} 
                 }
             } 

             }
        ],
        "پیراهن" : [
            # FIX: شناسه محصول حاوی فاصله برای MDSS-CG3719
            {"id":"men-shirt-MDSS-CG3719" , 
             "name":"پیراهن آستین بلند مردانه مدل MDSS-CG3719" , 
             "thumbnail": "https://res.cloudinary.com/dkzhxotve/image/upload/v1766766209/men-shirt-MDSS-CG3719_jh4u0w.webp" ,
             "price" : 3_000_000 ,
             "buy_price" : 2_000_000 , 
             "sizes":{"L":4 , "XL":5 , "XXL":3}
             },
             {"id":"men-shirt-SB-SS-4513" , 
              "name":"پیراهن آستین بلند مردانه مدل SB-SS-4513" , 
              "thumbnail":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766766299/men-shirt-SB-SS-4513_rrqpuv.webp" , 
              "price": 2_500_000 ,
              "buy_price" : 2_000_000 , 
              "sizes":{"L":3 , "XL":4 , "XXL":2}
              }
        ],
        "تی شرت" : [
            {"id":"men-Tshirt-model TS63 B" , 
             "name":"تی شرت اورسایز مردانه نوزده نودیک مدل TS63 B" , 
             "thumbnail":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766766391/men-Tshirt-model_TS63_B_aleauo.webp" , 
             "price" : 900_000 ,
             "buy_price" : 750_000 , 
             "sizes":{"L":3 , "XL":4 , "XXL":4}
             },
             {"id":"men-Tshirt-model TS1962 B" , 
              "name":"تی شرت ورزشی مردانه نوزده نودیک مدل TS1962 B" ,
              "thumbnail":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766766520/men-Tshirt-model_TS1962_B_bwvbs0.webp" , 
              "variants":{
                  "مشکی":{
                      "photo":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766766705/men-Tshirt-model_TS1962_Black_2_yohqzw.webp" , 
                      "price":550_000 , 
                      "buy_price" : 400_000 , 
                      "sizes":{"L":2 , "XL":2 , "XXL":2}

                  },
                  "سفید":{
                      "photo":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766766876/men-Tshirt-model_TS63_white_binvpk.webp" , 
                      "price":550_000 ,
                      "buy_price" : 400_000 ,  
                      "sizes":{"L":2 , "XL":3 , "XXL":2}
                  }
              }
              }
        ]
    },
    "women" : {
        "کفش":[
            {"id":"women-shoe-charm" , 
             "name": "کفش روزمره زنانه چرم درسا مدل 49569" , 
             "thumbnail": "https://res.cloudinary.com/dkzhxotve/image/upload/v1766767007/women-shoe-charm_gbhjjh.webp" , 
             "price": 9_100_000 , 
             "buy_price" : 8_500_000 , 
             "sizes" : {"40":2 , "41":0 , "42":3 , "43":2 , "44":1}
             },
             {"id":"women-shoe-3Fashion M.D" , 
              "name":"کفش روزمره زنانه مدل Fashion سه چسب M.D" , 
              "thumbnail": "https://res.cloudinary.com/dkzhxotve/image/upload/v1766767092/women-shoe-3Fashion_M.D_so7q56.webp" , 
              "variants":{
                  "مشکی":{
                      "photo":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766767290/women-shoe-charm-B_zqdqlh.webp" , 
                      "price":520_000 , 
                      "buy_price" : 400_000 , 
                      "sizes":{"40":3 , "41":2 , "43":3}
                  },
                  "سفید":{
                      "photo":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766767092/women-shoe-3Fashion_M.D_so7q56.webp" , 
                      "price":540_000 ,
                      "buy_price" : 400_000 ,  
                      "sizes":{"40":3 , "41":2 , "43":2 , "44":3}
                  }
              }
                 
             }
        ],
        "شلوار":[
             {"id":"women-pants-bag-lenin" , 
              "name":"شلوار زنانه مدل بگ لینن کنفی" , 
              "thumbnail":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766767361/women-pants-bag-lenin_czquax.webp" , 
              "price":800_000 , 
              "buy_price" : 500_000 , 
              "sizes":{"44":6 , "46":5 , "50":3 , "52":4}
              } , 
            {"id":"women-pants-rita-m-kerm" , # شناسه کوتاه شده برای جلوگیری از Button_data_invalid
             "name":"شلوار زنانه مدل ریتا مازراتی راسته رنگ کرم روشن" ,
             "thumbnail":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766767424/20251112222400589692652_pwel0m.jpg" , 
             "price":560_000 ,
             "buy_price" : 480_000 ,  
             "sizes":{"44":3 , "46":3 , "50":2 , "52":4}
            }
        ]
    }
}

CATALOG = STORE.get_catalog(CATALOG)

CATEGORY_MAP = {}
for gender in CATALOG:
    for cat in CATALOG[gender]:
        CATEGORY_MAP[_safe_callback(cat)] = cat
logger.info(f"CATEGORY_MAP contents: {CATEGORY_MAP}")

PAY_STATUS_FA = {
    "awaiting_receipt": "⏳ در انتظار ارسال رسید",
    "receipt_sent": "📨 رسید ارسال شد (در انتظار بررسی)",
    "paid_confirmed": "✅ پرداخت تایید شد",
    "paid_rejected": "❌ پرداخت رد شد",
    "cancelled": "لغو شد",
}

SHIP_STATUS_FA = {
    "pending": "⏳ هنوز ارسال نشده",
    "packed": "📦 بسته‌بندی شد",
    "shipped": "🚚 تحویل پست شد / ارسال شد",
    "delivered": "✅ تحویل شد",
}




#     منوها

def main_menu_reply() -> ReplyKeyboardMarkup:
    """ساخت کیبورد Reply برای منو اصلی (پایین صفحه)"""
    keyboard = [
        ["🛍️ لیست محصولات", "🧺 سبد خرید"],
        ["💛 امتیاز من", "📦 وضعیت سفارش من"],
        ["🆘 پشتیبانی"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def form_keyboard() -> ReplyKeyboardMarkup:
    """کیبورد ساده مخصوص فرم (فقط انصراف). منوی اصلی را موقتاً جایگزین می‌کند."""
    keyboard = [["❌ انصراف"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


# **[تغییر]** تعریف تابع main_menu برای استفاده از Inline Keyboard در Callback Query ها
def main_menu() -> InlineKeyboardMarkup:
    """ساخت کیبورد Inline برای منو اصلی در محیط Callback (بعد از اتمام کار)"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ لیست محصولات", callback_data="menu:products")],
        [InlineKeyboardButton("🧺 سبد خرید", callback_data="menu:cart")],
        [InlineKeyboardButton("💛 امتیاز من", callback_data="menu:loyalty")],
        [InlineKeyboardButton("🆘 پشتیبانی", callback_data="menu:support")],
    ])


def gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👨 مردانه" , callback_data="catalog:gender:men"),
            InlineKeyboardButton("👩 زنانه" , callback_data="catalog:gender:women"),
        ],
        [InlineKeyboardButton("🏠 بازگشت به منو" , callback_data="menu:back_home")],
    ])


def category_keyboard(gender : str) -> InlineKeyboardMarkup:
    cats = list(CATALOG.get(gender , {}).keys())
    rows = []
    for i in range(0 , len(cats) , 2):
        chunk = cats[i:i+2]
        rows.append([InlineKeyboardButton(c , callback_data=f"catalog:category:{gender}:{_safe_callback(c)}")for c in chunk])
    rows.append([
        InlineKeyboardButton("⬅️ تغییر جنسیت" , callback_data="menu:products"),
        InlineKeyboardButton("🏠 منو اصلی" , callback_data="menu:back_home"),
    ])
    return InlineKeyboardMarkup(rows)

def admin_panel_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 بسته‌بندی شد", callback_data=f"ship:packed:{order_id}")],
        [InlineKeyboardButton("🚚 تحویل پست شد + کد رهگیری", callback_data=f"ship:need_track:{order_id}")],
        [InlineKeyboardButton("✅ تحویل شد", callback_data=f"ship:delivered:{order_id}")],
        [InlineKeyboardButton("✉️ پیام به مشتری", callback_data=f"admin:msg:{order_id}")],
    ])





# ------------------ Shipping methods ------------------
# روش‌های ارسال (فعلاً هزینه ثابت/صفر؛ بعداً می‌توانید برای هر روش مبلغ تعیین کنید)
SHIPPING_METHODS = {
    "post": {"label": "📮 پست","cost": 60000, "payer": "customer"},
    "tipax": {"label": "🚚 تیپاکس", "cost": 90000, "payer": "customer"},
    "courier": {"label": "🛵 پیک (درون‌شهری)"},
}

SHIPPING_INFO = {
    "post": "📮 پست: هزینه ارسال بر عهده مشتری است (پس‌کرایه/پرداخت هنگام تحویل یا طبق فاکتور پست).",
    "tipax": "🚚 تیپاکس: هزینه ارسال بر عهده مشتری است و هنگام ارسال/تحویل محاسبه و دریافت می‌شود.",
    "courier": "🛵 پیک درون‌شهری: هزینه ارسال بر عهده مشتری است و قبل از ارسال هماهنگ می‌شود.",
}


def shipping_methods_keyboard(selected: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    for key, info in SHIPPING_METHODS.items():
        prefix = "✅ " if selected == key else ""
        rows.append([InlineKeyboardButton(f"{prefix}{info['label']}", callback_data=f"shipmethod:set:{key}")])
    rows.append([InlineKeyboardButton("⬅️ بازگشت به خلاصه سفارش", callback_data="shipmethod:back")])
    return InlineKeyboardMarkup(rows)
# ------------------ end shipping methods ------------------

def colors_keyboard(gender:str, category:str, product_id:str) -> InlineKeyboardMarkup:
    product = _find_product(gender, category, product_id)
    assert product and "variants" in product
    colors = list(product["variants"].keys())
    rows = []
    for i, color in enumerate(colors):
        available_sizes = [sz for sz, qty in product["variants"][color]["sizes"].items() if qty > 0]
        # در اینجا منطق انتخاب رنگ و سایز ترکیب شده بود، که در تابع ask_color_and_size مجدداً بازنویسی شده است.
        # این تابع در واقع هیچ استفاده‌ای در روال فعلی ربات شما ندارد و باعث تکرار می‌شود.
        # اما برای حفظ ساختار اصلی، آن را نگه می‌دارم، هرچند که بهتر است حذف شود.
        for sz in available_sizes:
            btn_text = f"{color} | سایز {sz}"
            # این خطوط در واقع کارایی تابع ask_color_and_size را در context:choose انجام می‌دهند.
            rows.append([InlineKeyboardButton(
                btn_text,
                callback_data=f"catalog:choose:{gender}:{_safe_callback(category)}:{product_id}:{i}:{sz}"
            )])
    rows.append([InlineKeyboardButton("⬅️ انتخاب محصول دیگر", callback_data=f"catalog:category:{gender}:{_safe_callback(category)}")])
    return InlineKeyboardMarkup(rows)


def sizes_keyboard(sizes:Dict[str , int]) -> InlineKeyboardMarkup:
    available = [s for s,qty in sizes.items() if qty and qty > 0]
    rows = []
    for i in range(0 , len(available) , 3):
        chunk = available[i:i+3]
        rows.append([InlineKeyboardButton(sz , callback_data=f"catalog:size:{_safe_callback(sz)}") for sz in chunk])
    rows.append([InlineKeyboardButton("❌ انصراف" , callback_data="flow:cancel")])
    return InlineKeyboardMarkup(rows)


def qty_keyboard(qty:int , max_qty:int) -> InlineKeyboardMarkup:
    if qty < 1:
        qty = 1
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➖" , callback_data="qty:dec") , 
            InlineKeyboardButton(f"تعداد: {qty}/{max_qty}" , callback_data="qty:noop") , 
            InlineKeyboardButton("➕" , callback_data="qty:inc"),
        ],
        [InlineKeyboardButton("🧺 افزودن به سبد خرید" , callback_data="qty:add")],
        [InlineKeyboardButton("❌ انصراف" , callback_data="flow:cancel")],
    ])


#     Helpers

# --- (NEW) Product list message tracking (for cleanup on selection) ---
def _track_product_list_msg(context: ContextTypes.DEFAULT_TYPE, message_id: int):
    context.user_data.setdefault("product_list_msg_ids", [])
    context.user_data["product_list_msg_ids"].append(int(message_id))

async def _clear_product_list_msgs(update: Update, context: ContextTypes.DEFAULT_TYPE, keep_message_id: int | None = None):
    chat_id = update.effective_chat.id
    ids = context.user_data.get("product_list_msg_ids", [])
    for mid in ids:
        if keep_message_id is not None and int(mid) == int(keep_message_id):
            continue
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=int(mid))
        except Exception:
            pass
    context.user_data["product_list_msg_ids"] = []
# --- end tracking helpers ---



def _find_product(gender:str , category:str , product_id:str) -> Optional[Dict]:
    for p in CATALOG.get(gender , {}).get(category , []):
        if p.get("id") == product_id:
            return p 
    return None

def format_card_number(card_number: str) -> str:
    return " ".join(card_number[i:i+4] for i in range(0, len(card_number), 4))


def _product_photo_for_list(p:Dict) -> Optional[str]:
    if not isinstance(p , dict):
        return None
    if p.get("thumbnail"):
        return p["thumbnail"]
    if p.get("photo"):
        return p["photo"]
    if "variants" in p and p["variants"]:
        first_color = next(iter(p["variants"].values()))
        if isinstance(first_color , dict):
            return first_color.get("photo")
    return None

def _admin_receipt_kb(order: dict, order_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("✅ تایید پرداخت", callback_data=f"admin:approve:{order_id}")],
        [InlineKeyboardButton("❌ مشکل دارد", callback_data=f"admin:reject:{order_id}")],
        [
            InlineKeyboardButton("🚚 ارسال با مشتری", callback_data=f"admin:shippayer:customer:{order_id}"),
            InlineKeyboardButton("🚚 ارسال با ادمین", callback_data=f"admin:shippayer:admin:{order_id}"),
        ],
    ]

    # اگر ارسال با ادمین باشد، دکمه ثبت هزینه ارسال را نشان بده
    if (order.get("shipping_payer") or "customer") == "admin":
        buttons.append([InlineKeyboardButton("💰 ثبت هزینه ارسال", callback_data=f"admin:shipcost:{order_id}")])

    return InlineKeyboardMarkup(buttons)


def _unit_price_and_sizes(p:Dict , color:Optional[str]) -> Tuple[int , Dict[str,int]]:
    if "variants" in p and color :
        v = p["variants"][color]
        return v["price"] , v["sizes"]
    if "price" in p and "sizes" in p:
        return p["price"] , p["sizes"]
    return 0 , {}


def _order_log(order_id: str, by: str, text: str):
    order = STORE.find_order(order_id)
    if not order:
        return
    hist = order.get("history", [])
    hist.append({"at": datetime.utcnow().isoformat() + "Z", "by": by, "text": text})
    STORE.update_order(order_id, history=hist)



def _format_order_history_md(order: dict, limit: int = 10) -> str:
    """Format last `limit` history events for admin/user display (Markdown-safe enough for our use)."""
    hist = order.get("history") or []
    if not hist:
        return "—"
    tail = hist[-limit:]
    lines = []
    for h in tail:
        at = str(h.get("at") or "")
        by = str(h.get("by") or "")
        txt = str(h.get("text") or "")
        # keep it simple; avoid heavy Markdown that might break on special chars
        lines.append(f"- {at} | {by} | {txt}")
    return "\n".join(lines)

def _with_history_section_md(base_text: str, order: dict, limit: int = 10) -> str:
    """Remove existing history section (if any) and append a fresh one."""
    if base_text is None:
        base_text = ""
    marker = "\n\n🕓 تاریخچه تغییرات:"
    if marker in base_text:
        base_text = base_text.split(marker)[0]
    return base_text.rstrip() + "\n\n🕓 تاریخچه تغییرات:\n" + _format_order_history_md(order, limit=limit)
def _update_order_with_log(order_id: str, by: str, note: str = "", **updates):
    before = STORE.find_order(order_id) or {}
    after = STORE.update_order(order_id, **updates)
    if not after:
        return None

    changes = []
    for k, v in updates.items():
        old = before.get(k)
        new = after.get(k)
        if old != new:
            changes.append(f"{k}: {old} → {new}")

    # متن لاگ
    text_parts = []
    if note:
        text_parts.append(note)
    if changes:
        text_parts.append(" | ".join(changes))

    if text_parts:
        _order_log(order_id, by, " / ".join(text_parts))

    return after


def _photo_for_selection(p:Dict , color:Optional[str]) -> Optional[str]:
    if color and "variants" in p:
        return p["variants"][color].get("photo") or p.get("thumbnail") or p.get("photo")
    return p.get("photo") or p.get("thumbnail")


def _ftm_toman(n:int) -> str :
    try:
        return f"{n:,} تومان"
    except Exception:
        return f"{n} تومان"


def _calc_cart_total(cart:List[dict]) -> int:
    return sum(it["qty"] * it["price"] for it in cart)

def _calc_items_cost(items: list[dict]) -> int:
    return sum(int(it.get("qty") or 0) * int(it.get("buy_price") or 0) for it in (items or []))

def _calc_shipping_admin_cost(order: dict) -> int:
    if (order.get("shipping_payer") or "customer") != "admin":
        return 0
    return int(order.get("shipping_cost_actual") or 0)



def _calc_estimated_profit(order: dict) -> dict:
    subtotal = int(order.get("subtotal") or 0)
    discount = int(order.get("discount_amount") or 0)
    total = int(order.get("total") or max(0, subtotal - discount))
    items_cost = _calc_items_cost(order.get("items") or [])
    ship_admin = _calc_shipping_admin_cost(order)
    profit = total - items_cost - ship_admin
    return {
        "subtotal": subtotal,
        "discount": discount,
        "total": total,
        "items_cost": items_cost,
        "ship_admin": ship_admin,
        "profit": profit,
    }

def _is_shipping_paid_by_admin(order: dict) -> bool:
    return (order.get("shipping_payer") or "customer") == "admin"






# ------------------ Coupon helpers ------------------
def _get_discount_maps():
    STORE.data.setdefault("discount_codes", {})
    STORE.data.setdefault("discount_redemptions", {})
    STORE.data.setdefault("recovery_coupon_issued", {})
    return STORE.data["discount_codes"], STORE.data["discount_redemptions"], STORE.data["recovery_coupon_issued"]

def _normalize_code(code: str) -> str:
    return (code or "").strip().upper()

def _is_code_valid_for_user(code: str, chat_id: int, cart_total: int):
    code = _normalize_code(code)
    codes, redemptions, _ = _get_discount_maps()
    c = codes.get(code)
    if not c or not c.get("active", True):
        return False, "کد تخفیف معتبر نیست.", None

    exp = _parse_dt_utc_z(c.get("expires_at"))
    if exp and _now_utc() >= exp:
        return False, "این کد تخفیف منقضی شده است.", None

    if c.get("max_uses_total") is not None:
        if int(c.get("used_total") or 0) >= int(c.get("max_uses_total") or 0):
            return False, "سقف استفاده از این کد تکمیل شده است.", None

    max_u = c.get("max_uses_per_user")
    if max_u is not None:
        used = redemptions.get(str(int(chat_id)), [])
        if used.count(code) >= int(max_u):
            return False, "شما قبلاً از این کد استفاده کرده‌اید.", None

    if int(cart_total or 0) <= 0:
        return False, "سبد خرید خالی است.", None

    return True, "کد تخفیف اعمال شد ✅", c

def _calc_discount_amount(cart_total: int, code_obj: dict | None) -> int:
    t = int(cart_total or 0)
    if t <= 0 or not code_obj:
        return 0
    typ = (code_obj.get("type") or "").lower()
    val = int(code_obj.get("value") or 0)
    if typ == "percent":
        pct = max(0, min(100, val))
        return int(t * pct / 100)
    if typ == "amount":
        return max(0, min(t, val))
    return 0

def _calc_payable_with_coupon(cart_total: int, coupon_code: str | None):
    if not coupon_code:
        return int(cart_total or 0), 0, None
    code = _normalize_code(coupon_code)
    codes, _, _ = _get_discount_maps()
    cobj = codes.get(code)
    disc = _calc_discount_amount(int(cart_total or 0), cobj) if cobj else 0
    payable = max(0, int(cart_total or 0) - disc)
    return payable, disc, (code if cobj else None)

def _redeem_discount(code: str, chat_id: int):
    code = _normalize_code(code)
    codes, redemptions, _ = _get_discount_maps()
    c = codes.get(code)
    if not c:
        return
    c["used_total"] = int(c.get("used_total") or 0) + 1
    redemptions.setdefault(str(int(chat_id)), [])
    redemptions[str(int(chat_id))].append(code)
    STORE.save()

def _maybe_issue_recovery_coupon(chat_id: int, now: datetime) -> str | None:
    """Issue a small one-time coupon for abandoned cart VIP stage (only once per user)."""
    codes, _, issued = _get_discount_maps()
    key = str(int(chat_id))
    if issued.get(key):
        return None
    # create unique-ish code
    new_code = f"RCV{chat_id % 10000:04d}{int(now.timestamp()) % 10000:04d}"
    new_code = _normalize_code(new_code)
    exp = now + timedelta(hours=48)
    codes[new_code] = {
        "type": "percent",
        "value": 5,
        "active": True,
        "max_uses_total": None,
        "used_total": 0,
        "max_uses_per_user": 1,
        "expires_at": _iso_z(exp),
        "note": "abandoned_cart_vip",
    }
    issued[key] = True
    STORE.save()
    return new_code
# ------------------ end Coupon helpers ------------------


# ------------------ Loyalty points (Points Wallet) ------------------
# هدف: امتیازدهی روی subtotal (جمع اقلام) + امکان مصرف محدود امتیاز برای کاهش مبلغ پرداختی
# همچنین: Tier بندی احساسی (Bronze/Silver/Gold) + بونوس‌های مناسبتی/رفتاری با سقف هزینه

def _ensure_loyalty_storage():
    """Initialize loyalty-related keys in shop_db.json (non-destructive)."""
    try:
        STORE.data.setdefault("loyalty", {})
        loy = STORE.data["loyalty"]
        loy.setdefault("users", {})
        loy.setdefault("ledger", [])
        loy.setdefault("rules", {
            # امتیازدهی پایه
            "earn_per_10000": 1,                 # هر 10,000 تومان -> 1 امتیاز
            "burn_value_per_point": 500,         # ارزش هر امتیاز برای خرج کردن (تومان)
            "max_burn_percent": 20,              # سقف مصرف اعتبار در هر سفارش (% از subtotal)
            "points_expire_days": 180,           # انقضا (اختیاری) - فعلاً فقط در ledger ثبت می‌شود

            # Tier ها (بر اساس مجموع امتیازهای کسب‌شده در طول زمان)
            "tiers": [
                {"key": "bronze", "label": "برنزی", "min_lifetime_earned": 0, "earn_multiplier": 1.00},
                {"key": "silver", "label": "نقره‌ای", "min_lifetime_earned": 500, "earn_multiplier": 1.05},
                {"key": "gold",   "label": "طلایی",  "min_lifetime_earned": 1500, "earn_multiplier": 1.10},
            ],

            # بونوس‌های رفتاری/مناسبتی (کم‌هزینه)
            "bonuses": {
                # خرید دوم (فقط یک بار)
                "second_purchase_points": 20,

                # بازگشت بعد از مدت طولانی
                "comeback_after_days": 30,
                "comeback_points": 30,
                "comeback_cooldown_days": 90,  # هر 90 روز یکبار

                # مناسبت‌های شمسی (کم‌هزینه و قابل تنظیم)
                # فرمت تاریخ‌ها: "MM-DD" در تقویم شمسی
                # نکته: روز پدر/مادر در ایران قمری است و هر سال تغییر می‌کند؛
                # برای جلوگیری از خطا، این دو مورد را خالی می‌گذاریم تا دستی در DB تنظیم شوند.
                "special_days": {
                    "nowruz": {"label": "عید نوروز", "range": ["01-01", "01-04"], "points": 30, "once_per_year": True},
                    "yalda":  {"label": "شب یلدا",   "days": ["09-30"],            "points": 20, "once_per_year": True},
                    "mother": {"label": "روز مادر",  "days": [],                  "points": 25, "once_per_year": True},
                    "father": {"label": "روز پدر",   "days": [],                  "points": 25, "once_per_year": True},
                },

                # سقف بونوس در هر سفارش برای کنترل هزینه
                "max_bonus_points_per_order": 60,
            }
        })
        STORE.save()
    except Exception:
        pass

_ensure_loyalty_storage()

def _loy_map() -> dict:
    STORE.data.setdefault("loyalty", {})
    return STORE.data["loyalty"]

def _loy_users() -> dict:
    loy = _loy_map()
    loy.setdefault("users", {})
    return loy["users"]

def _loy_ledger() -> list:
    loy = _loy_map()
    loy.setdefault("ledger", [])
    return loy["ledger"]

def _loy_rules() -> dict:
    loy = _loy_map()
    loy.setdefault("rules", {})
    return loy["rules"]

def _loy_tz():
    # ایران پیش‌فرض: +03:30 (210 دقیقه)
    try:
        off = int(os.getenv("TZ_OFFSET_MINUTES", "210"))
    except Exception:
        off = 210
    return timezone(timedelta(minutes=off))

def _loy_now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone(_loy_tz())

def _loy_user(chat_id: int) -> dict:
    users = _loy_users()
    key = str(int(chat_id))
    users.setdefault(key, {})
    u = users[key]
    u.setdefault("balance", 0)
    u.setdefault("tier", "bronze")
    u.setdefault("joined_at", datetime.utcnow().isoformat() + "Z")
    u.setdefault("last_earned_at", None)
    u.setdefault("last_burn_at", None)
    u.setdefault("lifetime_earned", 0)      # مجموع امتیازهای کسب‌شده
    u.setdefault("orders_paid_count", 0)    # تعداد خریدهای پرداخت‌شده
    u.setdefault("last_paid_at", None)      # آخرین زمان پرداخت (UTC isoZ)
    u.setdefault("bonus_log", {})           # برای cooldown / once-per-year
    return u

def loyalty_balance(chat_id: int) -> int:
    u = _loy_user(chat_id)
    try:
        return int(u.get("balance") or 0)
    except Exception:
        return 0

def _tier_table() -> list:
    tiers = _loy_rules().get("tiers") or []
    # مرتب‌سازی بر اساس min
    try:
        tiers = sorted(tiers, key=lambda x: int(x.get("min_lifetime_earned") or 0))
    except Exception:
        pass
    return tiers

def _calc_tier_by_lifetime(lifetime_earned: int) -> dict:
    lt = int(lifetime_earned or 0)
    chosen = {"key": "bronze", "label": "برنزی", "min_lifetime_earned": 0, "earn_multiplier": 1.0}
    for t in _tier_table():
        try:
            if lt >= int(t.get("min_lifetime_earned") or 0):
                chosen = t
        except Exception:
            continue
    return chosen

def _tier_label(tier_key: str) -> str:
    for t in _tier_table():
        if (t.get("key") or "").strip() == (tier_key or "").strip():
            return t.get("label") or tier_key
    return tier_key or "—"

def _tier_multiplier(tier_key: str) -> float:
    for t in _tier_table():
        if (t.get("key") or "").strip() == (tier_key or "").strip():
            try:
                return float(t.get("earn_multiplier") or 1.0)
            except Exception:
                return 1.0
    return 1.0

def _loy_special_day_hits(now_local: datetime) -> list:
    """Return list of special-day keys that match today (jalali MM-DD)."""
    rules = _loy_rules()
    b = (rules.get("bonuses") or {}).get("special_days") or {}
    try:
        j = jdatetime.date.fromgregorian(date=now_local.date())
        mmdd = f"{int(j.month):02d}-{int(j.day):02d}"
    except Exception:
        return []
    hits = []
    for key, cfg in b.items():
        if not isinstance(cfg, dict):
            continue
        days = cfg.get("days") or []
        r = cfg.get("range") or None
        if r and isinstance(r, list) and len(r) == 2:
            if r[0] <= mmdd <= r[1]:
                hits.append(key)
        elif mmdd in days:
            hits.append(key)
    return hits

def _loy_bonus_allowed(u: dict, bonus_key: str, now_local: datetime, once_per_year: bool = False, cooldown_days: int | None = None) -> bool:
    log = u.get("bonus_log") or {}
    last = log.get(bonus_key)
    if not last:
        return True
    last_dt = _parse_dt_utc_z(last) if isinstance(last, str) else None
    if once_per_year:
        try:
            # سال شمسی جاری
            jnow = jdatetime.date.fromgregorian(date=now_local.date())
            # کلید سالانه را خارج از این تابع مدیریت می‌کنیم، پس اگر last وجود دارد یعنی امسال خورده
            # ولی اگر last_dt در سال قبل بود هم ok
            if last_dt:
                jlast = jdatetime.date.fromgregorian(date=last_dt.astimezone(_loy_tz()).date())
                if jlast.year == jnow.year:
                    return False
        except Exception:
            pass
        return True
    if cooldown_days is not None and last_dt:
        try:
            return (now_local.astimezone(timezone.utc) - last_dt) >= timedelta(days=int(cooldown_days))
        except Exception:
            return True
    return True

def _loy_mark_bonus(u: dict, bonus_key: str):
    log = u.get("bonus_log") or {}
    log[bonus_key] = datetime.utcnow().isoformat() + "Z"
    u["bonus_log"] = log

def loyalty_apply(subtotal: int, chat_id: int, use_points: bool) -> tuple[int, int, int]:
    """Apply loyalty points (burn) on checkout summary. Returns payable, burn_points, burn_value."""
    subtotal = int(subtotal or 0)
    if subtotal <= 0 or not use_points:
        return subtotal, 0, 0

    rules = _loy_rules()
    max_pct = int(rules.get("max_burn_percent") or 0)
    burn_value_per_point = int(rules.get("burn_value_per_point") or 0)
    if max_pct <= 0 or burn_value_per_point <= 0:
        return subtotal, 0, 0

    max_discount_value = int(subtotal * max_pct / 100)
    bal = loyalty_balance(chat_id)
    possible_value = bal * burn_value_per_point
    burn_value = max(0, min(max_discount_value, possible_value))
    burn_points = int(burn_value / burn_value_per_point) if burn_value_per_point else 0
    burn_value = burn_points * burn_value_per_point

    payable = max(0, subtotal - burn_value)
    return payable, burn_points, burn_value

def loyalty_burn(chat_id: int, points: int, order_id: str | None = None) -> bool:
    u = _loy_user(chat_id)
    pts = max(0, int(points or 0))
    bal = int(u.get("balance") or 0)
    if pts <= 0 or bal < pts:
        return False

    u["balance"] = bal - pts
    u["last_burn_at"] = datetime.utcnow().isoformat() + "Z"

    # ledger
    _loy_ledger().append({
        "id": f"LP-{uuid.uuid4()}",
        "chat_id": int(chat_id),
        "type": "burn",
        "points": pts,
        "reason": "order_checkout",
        "order_id": order_id,
        "at": datetime.utcnow().isoformat() + "Z",
    })
    STORE.save()
    return True

def loyalty_earn(chat_id: int, subtotal: int, order_id: str | None = None) -> dict:
    """Earn points after payment confirmation. Earn is based on subtotal."""
    rules = _loy_rules()
    earn_per_10000 = int(rules.get("earn_per_10000") or 0)
    subtotal = int(subtotal or 0)
    if subtotal <= 0 or earn_per_10000 <= 0:
        return {"earned": 0, "bonus": 0, "tier_before": None, "tier_after": None, "tier_upgraded": False, "messages": []}

    u = _loy_user(chat_id)
    now_local = _loy_now_local()

    # tier before
    tier_before = (u.get("tier") or "bronze")
    tier_info_before = _calc_tier_by_lifetime(int(u.get("lifetime_earned") or 0))
    # sync stored tier if out-of-date
    if tier_info_before.get("key") and tier_info_before.get("key") != tier_before:
        tier_before = tier_info_before.get("key")
        u["tier"] = tier_before

    # base points
    base_units = int(subtotal / 10000)
    base_points = base_units * earn_per_10000
    mult = _tier_multiplier(tier_before)
    base_points = int(round(base_points * mult))

    # behavioral bonuses (low-cost)
    bonuses_cfg = (rules.get("bonuses") or {})
    bonus_points = 0
    bonus_msgs = []

    # second purchase bonus: if this order makes paid_count == 2
    paid_count = int(u.get("orders_paid_count") or 0)
    if paid_count == 1:
        pts = int(bonuses_cfg.get("second_purchase_points") or 0)
        if pts > 0 and _loy_bonus_allowed(u, "second_purchase", now_local, once_per_year=False, cooldown_days=None):
            bonus_points += pts
            bonus_msgs.append("🎉 به پاس «خرید دوم»، یه هدیه کوچیک امتیازی برات فعال شد.")
            _loy_mark_bonus(u, "second_purchase")

    # comeback bonus: if last_paid_at older than comeback_after_days
    comeback_after = int(bonuses_cfg.get("comeback_after_days") or 0)
    comeback_pts = int(bonuses_cfg.get("comeback_points") or 0)
    cooldown = int(bonuses_cfg.get("comeback_cooldown_days") or 0)
    last_paid = _parse_dt_utc_z(u.get("last_paid_at"))
    if comeback_after > 0 and comeback_pts > 0 and last_paid:
        try:
            last_local = last_paid.astimezone(_loy_tz())
            if (now_local - last_local) >= timedelta(days=comeback_after):
                if _loy_bonus_allowed(u, "comeback", now_local, once_per_year=False, cooldown_days=cooldown):
                    bonus_points += comeback_pts
                    bonus_msgs.append("✨ دلمون برات تنگ شده بود! بابت برگشتنت یه امتیاز هدیه داریم.")
                    _loy_mark_bonus(u, "comeback")
        except Exception:
            pass

    # special day bonuses (jalali)
    special_cfg = bonuses_cfg.get("special_days") or {}
    for skey in _loy_special_day_hits(now_local):
        cfg = special_cfg.get(skey) or {}
        pts = int(cfg.get("points") or 0)
        if pts <= 0:
            continue
        once_per_year = bool(cfg.get("once_per_year", True))
        # کلید سالانه: مثلا nowruz_1405
        try:
            jnow = jdatetime.date.fromgregorian(date=now_local.date())
            year_key = f"{skey}_{jnow.year}"
        except Exception:
            year_key = f"{skey}"
        if _loy_bonus_allowed(u, year_key, now_local, once_per_year=once_per_year, cooldown_days=None):
            bonus_points += pts
            bonus_msgs.append(f"🎁 {cfg.get('label') or 'مناسبت ویژه'} مبارک! یه هدیه امتیازی برات اضافه شد.")
            _loy_mark_bonus(u, year_key)

    # cap bonus per order
    max_bonus = int(bonuses_cfg.get("max_bonus_points_per_order") or 0)
    if max_bonus > 0 and bonus_points > max_bonus:
        bonus_points = max_bonus

    total_earned = max(0, int(base_points + bonus_points))
    if total_earned <= 0:
        return {"earned": 0, "bonus": 0, "tier_before": tier_before, "tier_after": tier_before, "tier_upgraded": False, "messages": []}

    # update balances and lifetime
    u["balance"] = int(u.get("balance") or 0) + total_earned
    u["lifetime_earned"] = int(u.get("lifetime_earned") or 0) + total_earned
    u["last_earned_at"] = datetime.utcnow().isoformat() + "Z"
    u["orders_paid_count"] = int(u.get("orders_paid_count") or 0) + 1
    u["last_paid_at"] = datetime.utcnow().isoformat() + "Z"

    # tier after (may upgrade)
    tier_info_after = _calc_tier_by_lifetime(int(u.get("lifetime_earned") or 0))
    tier_after = tier_info_after.get("key") or tier_before
    tier_upgraded = (tier_after != tier_before)
    u["tier"] = tier_after

    # ledger record
    expires_days = int(rules.get("points_expire_days") or 0)
    expires_at = None
    if expires_days > 0:
        try:
            exp = datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(days=expires_days)
            expires_at = _iso_z(exp)
        except Exception:
            expires_at = None

    _loy_ledger().append({
        "id": f"LP-{uuid.uuid4()}",
        "chat_id": int(chat_id),
        "type": "earn",
        "points": int(total_earned),
        "reason": "order_paid",
        "order_id": order_id,
        "amount_base": int(subtotal),
        "at": datetime.utcnow().isoformat() + "Z",
        "expires_at": expires_at,
        "tier": tier_after,
        "base_points": int(base_points),
        "bonus_points": int(bonus_points),
    })

    STORE.save()

    messages = []
    # احساس‌محور: پیام Tier
    if tier_upgraded:
        messages.append(f"🌟 تبریک! سطح وفاداری‌ت ارتقا پیدا کرد: *{_tier_label(tier_after)}*")
    # بونوس‌ها
    messages.extend(bonus_msgs)

    return {
        "earned": int(total_earned),
        "bonus": int(bonus_points),
        "tier_before": tier_before,
        "tier_after": tier_after,
        "tier_upgraded": bool(tier_upgraded),
        "messages": messages,
    }

def loyalty_user_summary(chat_id: int) -> dict:
    u = _loy_user(chat_id)
    rules = _loy_rules()
    tier_key = u.get("tier") or "bronze"
    return {
        "balance": int(u.get("balance") or 0),
        "tier_key": tier_key,
        "tier_label": _tier_label(tier_key),
        "multiplier": _tier_multiplier(tier_key),
        "burn_value_per_point": int(rules.get("burn_value_per_point") or 0),
        "max_burn_percent": int(rules.get("max_burn_percent") or 0),
    }

def loyalty_point_value() -> int:
    r = _loy_rules()
    return int(r.get("burn_value_per_point") or 0)

async def show_loyalty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = None
    if update.effective_user:
        chat_id = int(update.effective_user.id)

    if not chat_id:
        return

    s = loyalty_user_summary(chat_id)
    bal = int(s.get("balance") or 0)
    pv = int(s.get("burn_value_per_point") or 0)
    tier_label = s.get("tier_label") or "—"
    mult = float(s.get("multiplier") or 1.0)
    max_pct = int(s.get("max_burn_percent") or 0)

    value = bal * pv
    # برای حس پیشرفت: تا سطح بعدی چند امتیاز مانده؟
    u = _loy_user(chat_id)
    lifetime = int(u.get("lifetime_earned") or 0)
    tiers = _tier_table()
    next_t = None
    for t in tiers:
        try:
            if int(t.get("min_lifetime_earned") or 0) > lifetime:
                next_t = t
                break
        except Exception:
            continue
    next_line = ""
    if next_t:
        try:
            need = int(next_t.get("min_lifetime_earned") or 0) - lifetime
            next_line = f"\n\n🔜 تا سطح *{next_t.get('label') or _tier_label(next_t.get('key'))}* فقط *{max(0, need)}* امتیاز دیگه مونده."
        except Exception:
            pass

    text = (
        "💛 *باشگاه وفاداری*\n\n"
        f"🏅 سطح فعلی: *{tier_label}* (×{mult:.2f} امتیاز)\n"
        f"✨ موجودی امتیاز: *{bal}*\n"
        f"💰 ارزش تقریبی اعتبار: *{value:,}* تومان\n"
        f"🧾 سقف مصرف در هر خرید: *{max_pct}%* از subtotal"
        f"{next_line}\n\n"
        "🫶 امتیازها فقط تخفیف نیستن؛ یعنی «ما یادت هستیم». 💛"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 مشاهده سبد خرید", callback_data="cart:view")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")],
    ])

    if update.callback_query:
        q = update.callback_query
        await q.answer()
        try:
            if q.message.caption:
                await q.edit_message_caption(caption=text, parse_mode="Markdown", reply_markup=kb)
            else:
                await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=kb)
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=kb)

# ------------------ end Loyalty points ------------------





# ------------------ Recovery campaigns (Abandoned cart / Missing receipt) ------------------
# ایده کلی:
# - سبد خرید رهاشده: cart در STORE.data["user_states"] ذخیره می‌شود + timestamp آخرین تغییر
# - رسید ارسال نشده: روی orders با status=awaiting_receipt زمان‌محور پیام یادآوری می‌فرستیم
# ضد اسپم:
# - برای هر کمپین، حداکثر ۱ پیام در ۲۴ ساعت به هر کاربر
# - برای هر سفارش، حداکثر ۳ یادآوری رسید (Friendly / Urgent / VIP)

RECOVERY_MIN_GAP = timedelta(hours=24)

# آستانه‌های زمانی (قابل تنظیم)
ABANDONED_CART_THRESHOLDS = [
    (timedelta(hours=1), "friendly"),
    (timedelta(hours=6), "urgent"),
    (timedelta(hours=24), "vip"),
]
MISSING_RECEIPT_THRESHOLDS = [
    (timedelta(hours=2), "friendly"),
    (timedelta(hours=8), "urgent"),
    (timedelta(hours=24), "vip"),
]

def _now_utc() -> datetime:
    return datetime.utcnow().replace(tzinfo=timezone.utc)

def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"

def _get_user_states_map() -> dict:
    STORE.data.setdefault("user_states", {})
    return STORE.data["user_states"]

def _get_recovery_log_map() -> dict:
    STORE.data.setdefault("recovery_logs", {})
    return STORE.data["recovery_logs"]

def _user_state(chat_id: int) -> dict:
    states = _get_user_states_map()
    key = str(int(chat_id))
    states.setdefault(key, {})
    return states[key]

def _log_can_send(chat_id: int, campaign_key: str) -> bool:
    logs = _get_recovery_log_map()
    ukey = str(int(chat_id))
    logs.setdefault(ukey, {})
    last = logs[ukey].get(campaign_key)
    last_dt = _parse_dt_utc_z(last) if last else None
    if not last_dt:
        return True
    return (_now_utc() - last_dt) >= RECOVERY_MIN_GAP

def _log_mark_sent(chat_id: int, campaign_key: str):
    logs = _get_recovery_log_map()
    ukey = str(int(chat_id))
    logs.setdefault(ukey, {})
    logs[ukey][campaign_key] = _iso_z(_now_utc())
    STORE.save()

def _sync_cart_state(chat_id: int, cart: List[dict]):
    st = _user_state(chat_id)
    st["cart"] = cart or []
    st["cart_total"] = int(_calc_cart_total(cart or []))
    st["cart_updated_at"] = _iso_z(_now_utc())
    STORE.save()

def _clear_cart_state(chat_id: int):
    st = _user_state(chat_id)
    st["cart"] = []
    st["cart_total"] = 0
    st["cart_updated_at"] = _iso_z(_now_utc())
    STORE.save()

def _active_order_for_user(chat_id: int) -> Optional[dict]:
    # سفارش‌های فعال: هنوز پرداخت/تایید نشده و لغو نشده
    orders = STORE.data.get("orders", []) or []
    mine = [o for o in orders if int(o.get("user_chat_id", 0)) == int(chat_id)]
    if not mine:
        return None
    # آخرین سفارش فعال
    mine = sorted(mine, key=lambda x: x.get("created_at", ""), reverse=True)
    for o in mine:
        st = (o.get("status") or "").strip()
        if st in {"awaiting_receipt", "receipt_submitted", "receipt_rejected"}:
            return o
    return None

def _cart_recovery_text(style: str, cart_total: int) -> str:
    price = _ftm_toman(cart_total)
    if style == "urgent":
        return (
            "⏰ *یادآوری سریع!*\n\n"
            "چندتا آیتم توی سبدت مونده و ممکنه موجودی‌شون محدود باشه.\n"
            f"💰 مجموع فعلی سبد: *{price}*\n\n"
            "اگه قصد خرید داری همین الان تکمیلش کن 👇"
        )
    if style == "vip":
        return (
            "🌟 *برای شما یک یادآوری VIP*\n\n"
            "سبدت هنوز آماده‌ی ثبت سفارشه. اگه سوال یا نیاز به راهنمایی داری، همینجا پیام بده تا سریع کمکت کنیم.\n"
            f"🧺 مجموع سبد: *{price}*\n\n"
            "برای ادامه، سبد خرید رو باز کن 👇"
        )
    # friendly
    return (
        "😊 سلام! یه یادآوری کوچیک\n\n"
        "به نظر میاد چندتا کالا توی سبدت گذاشتی ولی خریدت کامل نشده.\n"
        f"🧺 مجموع سبد: *{price}*\n\n"
        "هر وقت آماده بودی، از اینجا ادامه بده 👇"
    )

def _receipt_recovery_text(style: str, order_id: str, total: int) -> str:
    price = _ftm_toman(int(total or 0))
    if style == "urgent":
        return (
            "⏰ *یادآوری مهم پرداخت*\n\n"
            f"برای سفارش `{order_id}` هنوز *رسید پرداخت* دریافت نشده.\n"
            f"💰 مبلغ سفارش: *{price}*\n\n"
            "برای اینکه سفارشت سریع‌تر پردازش بشه، لطفاً رسید رو همین الان ارسال کن 👇"
        )
    if style == "vip":
        return (
            "🌟 *پیگیری VIP سفارش شما*\n\n"
            f"سفارش `{order_id}` آماده‌ی بررسیه؛ فقط ارسال رسید پرداخت مونده.\n"
            f"💰 مبلغ: *{price}*\n\n"
            "به محض ارسال رسید، بررسی و پردازش سریع انجام می‌شه 👇"
        )
    # friendly
    return (
        "😊 سلام! یادآوری دوستانه\n\n"
        f"برای سفارش `{order_id}` هنوز رسید پرداخت ارسال نشده.\n"
        f"💰 مبلغ سفارش: *{price}*\n\n"
        "اگر پرداخت انجام دادی، لطفاً رسید رو اینجا بفرست 👇"
    )

def _choose_style_by_stage(stage: int) -> str:
    # 0->friendly, 1->urgent, 2->vip
    return ["friendly", "urgent", "vip"][max(0, min(2, stage))]

async def recovery_campaigns_job(context: ContextTypes.DEFAULT_TYPE):
    """Periodic job: sends recovery messages (anti-spam protected)."""
    now = _now_utc()

    # 1) Abandoned cart
    states = _get_user_states_map()
    for ukey, st in list((states or {}).items()):
        try:
            chat_id = int(ukey)
        except Exception:
            continue
        cart = st.get("cart") or []
        if not cart:
            continue

        # اگر سفارش فعال برای کاربر هست، سبد رهاشده ارسال نکن
        if _active_order_for_user(chat_id):
            continue

        updated_dt = _parse_dt_utc_z(st.get("cart_updated_at"))
        if not updated_dt:
            continue
        elapsed = now - updated_dt
        # تعیین stage بر اساس thresholds
        stage = None
        for i, (thr, _) in enumerate(ABANDONED_CART_THRESHOLDS):
            if elapsed >= thr:
                stage = i
        if stage is None:
            continue

        # هر مرحله یک کلید جداگانه تا در طول زمان سه پیام (حداکثر) ارسال شود
        campaign_key = f"abandoned_cart_stage_{stage}"
        if not _log_can_send(chat_id, campaign_key):
            continue

        style = _choose_style_by_stage(stage)
        text = _cart_recovery_text(style, int(st.get("cart_total") or 0))

        # 🎟️ VIP stage: issue a small one-time coupon (only once per user)
        if stage == 2:
            try:
                c = _maybe_issue_recovery_coupon(chat_id, now)
                if c:
                    text += "\n\n🎁 *کد تخفیف ویژه شما:* `" + c + "`\n(فقط یک‌بار قابل استفاده و تا ۴۸ ساعت معتبر است)"
            except Exception:
                pass
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧺 باز کردن سبد خرید", callback_data="menu:cart")],
            [InlineKeyboardButton("🛍️ ادامه خرید", callback_data="menu:products")],
        ])
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=kb)
            _log_mark_sent(chat_id, campaign_key)
        except Exception as e:
            logger.error("Recovery abandoned_cart send failed to %s: %s", chat_id, e)

    # 2) Missing receipt
    orders = STORE.data.get("orders", []) or []
    for o in (orders or []):
        try:
            chat_id = int(o.get("user_chat_id"))
        except Exception:
            continue
        if (o.get("status") or "") != "awaiting_receipt":
            continue

        created_dt = _parse_dt_utc_z(o.get("created_at"))
        if not created_dt:
            continue

        elapsed = now - created_dt
        stage = None
        for i, (thr, _) in enumerate(MISSING_RECEIPT_THRESHOLDS):
            if elapsed >= thr:
                stage = i
        if stage is None:
            continue

        rec = o.get("recovery") or {}
        sent_stages = set(rec.get("receipt_reminders_sent") or [])
        # حداکثر سه پیام
        if stage in sent_stages:
            continue

        campaign_key = f"missing_receipt_{o.get('order_id')}_stage_{stage}"
        if not _log_can_send(chat_id, campaign_key):
            continue

        style = _choose_style_by_stage(stage)
        text = _receipt_recovery_text(style, o.get("order_id"), int(o.get("total") or 0))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 ارسال رسید", callback_data=f"receipt:start:{o.get('order_id')}")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")],
        ])
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=kb)
            # مارک stage ارسال شده
            sent = sorted(set(list(sent_stages) + [stage]))
            rec["receipt_reminders_sent"] = sent
            rec["receipt_last_sent_at"] = _iso_z(now)
            STORE.update_order(o.get("order_id"), recovery=rec)
            _log_mark_sent(chat_id, campaign_key)
        except Exception as e:
            logger.error("Recovery missing_receipt send failed order=%s chat=%s: %s", o.get("order_id"), chat_id, e)

# ------------------ end recovery campaigns ------------------


# ------------------ Sales dashboard helpers ------------------
# فروش را بر اساس «زمان پرداخت» حساب می‌کنیم:
# - پرداخت آنلاین: paid_at
# - پرداخت کارت‌به‌کارت: confirmed_at (پس از تایید ادمین)
# - در نهایت fallback به created_at
PAID_STATUSES = {"paid", "paid_confirmed", "fulfilled"}

# ------------------ Customer Segmentation (VIP / New / Churn) ------------------
# Segmentation is computed only from REAL purchases: orders with status in PAID_STATUSES.
# Default thresholds (tweakable, designed to be safe for profitability):
SEG_NEW_DAYS = 30              # user is "new" if their first purchase is within last 30 days (and lifetime_orders <= 1)
SEG_VIP_RECENT_DAYS = 30       # VIP must have purchased within last 30 days
SEG_VIP_WINDOW_DAYS = 90       # consider the last 90 days for VIP scoring
SEG_VIP_MIN_ORDERS_90D = 3     # or
SEG_VIP_MIN_SPENT_90D = 3_000_000  # Tomans (based on subtotal)
SEG_CHURN_RISK_DAYS = 45       # "at risk" if no purchase for 45+ days
SEG_CHURNED_DAYS = 60          # "churned" if no purchase for 60+ days

def _ensure_customer_profiles_storage():
    """Initialize customer_profiles in shop_db.json (non-destructive)."""
    try:
        STORE.data.setdefault("customer_profiles", {})
    except Exception:
        STORE.data["customer_profiles"] = {}
    STORE.save()

def _parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # accept both ...Z and timezone-aware strings
        if isinstance(s, str) and s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def _order_paid_dt(order: Dict) -> Optional[datetime]:
    # Prefer explicit paid timestamps; fall back cautiously.
    for k in ("paid_at", "confirmed_at", "paid_confirmed_at", "created_at"):
        dt = _parse_iso_dt(order.get(k))
        if dt:
            return dt
    return None

def compute_customer_profiles(now: Optional[datetime] = None) -> Dict[str, Dict]:
    """Compute per-customer metrics + segment label from STORE.data['orders'].

    Returns profiles dict keyed by chat_id as string.
    Segment labels:
      - vip
      - new
      - churn_risk
      - churned
      - active (fallback for paying customers not in other segments)
    """
    _ensure_customer_profiles_storage()
    if not now:
        now = datetime.now(timezone.utc)

    orders = STORE.data.get("orders", []) or []
    by_user: Dict[str, List[Dict]] = {}
    for o in orders:
        try:
            status = (o.get("status") or "").strip()
            if status not in PAID_STATUSES:
                continue
            chat_id = o.get("chat_id") or o.get("user_chat_id") or o.get("customer_chat_id")
            if chat_id is None:
                continue
            uid = str(chat_id)
            by_user.setdefault(uid, []).append(o)
        except Exception:
            continue

    profiles: Dict[str, Dict] = {}
    vip_count = new_count = churn_count = risk_count = active_count = 0

    vip_window_start = now - timedelta(days=SEG_VIP_WINDOW_DAYS)

    for uid, u_orders in by_user.items():
        paid_dts = []
        lifetime_spent = 0
        lifetime_orders = 0

        spent_90d = 0
        orders_90d = 0

        for o in u_orders:
            dt = _order_paid_dt(o)
            if not dt:
                continue
            paid_dts.append(dt)
            lifetime_orders += 1
            # Use subtotal for segmentation (matches loyalty earn base)
            lifetime_spent += int(o.get("subtotal") or 0)

            if dt >= vip_window_start:
                orders_90d += 1
                spent_90d += int(o.get("subtotal") or 0)

        if lifetime_orders == 0 or not paid_dts:
            continue

        last_paid = max(paid_dts)
        days_since = (now - last_paid).days

        # Segment rules
        segment = "active"
        detail = ""

        # new: first-time buyer recently
        if lifetime_orders <= 1 and days_since <= SEG_NEW_DAYS:
            segment = "new"
        # churned / risk
        elif days_since >= SEG_CHURNED_DAYS:
            segment = "churned"
        elif days_since >= SEG_CHURN_RISK_DAYS:
            segment = "churn_risk"
        # vip: frequent/high spend in last window and recent
        elif days_since <= SEG_VIP_RECENT_DAYS and (orders_90d >= SEG_VIP_MIN_ORDERS_90D or spent_90d >= SEG_VIP_MIN_SPENT_90D):
            segment = "vip"

        # aggregate counts
        if segment == "vip":
            vip_count += 1
        elif segment == "new":
            new_count += 1
        elif segment == "churned":
            churn_count += 1
        elif segment == "churn_risk":
            risk_count += 1
        else:
            active_count += 1

        profiles[uid] = {
            "segment": segment,
            "last_paid_at": last_paid.isoformat().replace("+00:00", "Z"),
            "days_since_last_purchase": days_since,
            "lifetime_orders": lifetime_orders,
            "lifetime_spent_subtotal": lifetime_spent,
            "orders_90d": orders_90d,
            "spent_90d_subtotal": spent_90d,
            "updated_at": now.isoformat().replace("+00:00", "Z"),
        }

    # persist
    STORE.data["customer_profiles"] = profiles
    STORE.data.setdefault("segments_summary", {})
    STORE.data["segments_summary"] = {
        "vip": vip_count,
        "new": new_count,
        "churned": churn_count,
        "churn_risk": risk_count,
        "active": active_count,
        "updated_at": (now.isoformat().replace("+00:00", "Z")),
    }
    STORE.save()
    return profiles

async def admin_segments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /segments - show segmentation summary + a few samples."""
    if not ADMIN_CHAT_ID or str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return

    now = datetime.now(timezone.utc)
    profiles = compute_customer_profiles(now=now)
    summary = STORE.data.get("segments_summary", {}) or {}

    # Prepare sample lists
    def _top(filter_seg: str, key: str, n: int = 5, reverse: bool = True):
        rows = [(uid, p) for uid, p in profiles.items() if p.get("segment") == filter_seg]
        rows.sort(key=lambda r: r[1].get(key, 0), reverse=reverse)
        return rows[:n]

    top_vip = _top("vip", "spent_90d_subtotal", 5, True)
    top_churn = _top("churned", "days_since_last_purchase", 5, True)
    top_risk = _top("churn_risk", "days_since_last_purchase", 5, True)
    top_new = _top("new", "last_paid_at", 5, True)

    lines = []
    lines.append("📌 گزارش سگمنت مشتری‌ها")
    lines.append(f"VIP: {summary.get('vip',0)} نفر")
    lines.append(f"مشتری جدید: {summary.get('new',0)} نفر")
    lines.append(f"ریزش‌یافته: {summary.get('churned',0)} نفر")
    lines.append(f"در خطر ریزش: {summary.get('churn_risk',0)} نفر")
    lines.append(f"فعال: {summary.get('active',0)} نفر")
    lines.append("")

    if top_vip:
        lines.append("⭐️ نمونه VIP (Top 5 بر اساس خرید ۹۰ روز اخیر):")
        for uid, p in top_vip:
            lines.append(f" - {uid} | سفارش۹۰روز: {p.get('orders_90d')} | هزینه۹۰روز: {p.get('spent_90d_subtotal'):,} | آخرین خرید: {p.get('days_since_last_purchase')} روز پیش")
        lines.append("")
    if top_new:
        lines.append("🆕 نمونه مشتری جدید:")
        for uid, p in top_new:
            lines.append(f" - {uid} | اولین/تنها خرید | {p.get('days_since_last_purchase')} روز پیش | مبلغ کل: {p.get('lifetime_spent_subtotal'):,}")
        lines.append("")
    if top_risk:
        lines.append("⚠️ در خطر ریزش:")
        for uid, p in top_risk:
            lines.append(f" - {uid} | {p.get('days_since_last_purchase')} روز بدون خرید | سفارش کل: {p.get('lifetime_orders')}")
        lines.append("")
    if top_churn:
        lines.append("🧊 ریزش‌یافته:")
        for uid, p in top_churn:
            lines.append(f" - {uid} | {p.get('days_since_last_purchase')} روز بدون خرید | سفارش کل: {p.get('lifetime_orders')}")
        lines.append("")

    await update.message.reply_text("\n".join(lines))





# ------------------ Automated messaging & campaigns ------------------
def _ensure_automation_storage():
    try:
        STORE.data.setdefault("automations", {})
        STORE.data["automations"].setdefault("order_followups", {})  # order_id -> {"followup_sent_at":..,"feedback_sent_at":..}
        STORE.data["automations"].setdefault("campaigns", [])         # list of campaigns
        STORE.data["automations"].setdefault("campaign_redemptions", {})  # campaign_id -> {chat_id: iso_z}
        STORE.save()
    except Exception:
        pass

_ensure_automation_storage()

# Default automation delays (tune here)
FOLLOWUP_DELAY_HOURS = int(os.getenv("FOLLOWUP_DELAY_HOURS", "24"))   # پیگیری سفارش
FEEDBACK_AFTER_DELIVERY_HOURS = int(os.getenv("FEEDBACK_AFTER_DELIVERY_HOURS", "24"))   # نظرخواهی (بعد از تحویل)
AUTO_MSG_SCAN_INTERVAL_SEC = int(os.getenv("AUTO_MSG_SCAN_INTERVAL_SEC", "600"))

# Campaign defaults (small, capped)
CAMPAIGN_DEFAULT_GIFT_POINTS = int(os.getenv("CAMPAIGN_DEFAULT_GIFT_POINTS", "15"))  # هدیه امتیازی کوچک
CAMPAIGN_MAX_USERS_DEFAULT = int(os.getenv("CAMPAIGN_MAX_USERS_DEFAULT", "300"))
CAMPAIGN_USER_COOLDOWN_DAYS = int(os.getenv("CAMPAIGN_USER_COOLDOWN_DAYS", "90"))   # هر کاربر هر ۹۰ روز یکبار
CAMPAIGN_MAX_POINTS_PER_USER = int(os.getenv("CAMPAIGN_MAX_POINTS_PER_USER", "30")) # سقف هدیه در یک کمپین
CAMPAIGN_TOTAL_POINTS_CAP = int(os.getenv("CAMPAIGN_TOTAL_POINTS_CAP", "6000"))     # سقف کل هزینه (امتیاز) برای یک کمپین

def _now_iso_z():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _parse_iso_z(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Accept Z or naive
        if s.endswith("Z"):
            s2 = s.replace("Z", "+00:00")
        else:
            s2 = s
        return datetime.fromisoformat(s2)
    except Exception:
        return None

def _mark_order_automation_due(order_id: str, paid_dt: Optional[datetime] = None):
    """Set followup/feedback due timestamps on the order (idempotent)."""
    order = STORE.find_order(order_id)
    if not order:
        return
    if not paid_dt:
        paid_dt = _order_paid_dt(order) or datetime.now(timezone.utc)
    # if already set, keep
    if not order.get("followup_due_at"):
        order["followup_due_at"] = (paid_dt + timedelta(hours=FOLLOWUP_DELAY_HOURS)).isoformat().replace("+00:00", "Z")
    if not order.get("feedback_due_at"):
        order["feedback_due_at"] = (paid_dt + timedelta(hours=FEEDBACK_AFTER_DELIVERY_HOURS)).isoformat().replace("+00:00", "Z")
    STORE.update_order(order_id, **order)

def _automation_already_sent(order_id: str, kind: str) -> bool:
    _ensure_automation_storage()
    rec = STORE.data.get("automations", {}).get("order_followups", {}).get(order_id, {}) or {}
    return bool(rec.get(f"{kind}_sent_at"))

def _automation_mark_sent(order_id: str, kind: str):
    _ensure_automation_storage()
    STORE.data["automations"]["order_followups"].setdefault(order_id, {})
    STORE.data["automations"]["order_followups"][order_id][f"{kind}_sent_at"] = _now_iso_z()
    STORE.save()
def _profile_key(chat_id: int | str) -> str:
    return str(chat_id)

def _get_customer_profile(chat_id: int) -> dict:
    return (STORE.data.get("customer_profiles", {}) or {}).get(_profile_key(chat_id), {}) or {}

def _get_customer_segment(chat_id: int) -> str:
    p = _get_customer_profile(chat_id)
    return (p.get("segment") or "active").strip()

def _followup_text(segment: str, order_id: str) -> str:
    if segment == "vip":
        return (
            "سلام رفیقِ ویژه 💛\n"
            f"فقط خواستم یه چک کنم همه‌چی رو به راهه 😊\n"
            f"سفارش `{order_id}` الان تو مرحله‌ی آماده‌سازی/ارساله.\n"
            "اگه هر چیزی خواستی (تغییر آدرس/سایز/سؤال) همینجا بهمون بگو ✨"
        )
    return (
        "سلام 😊\n"
        f"یه پیام کوتاه برای پیگیری سفارش‌ت بود.\n"
        f"سفارش `{order_id}` الان تو مرحله‌ی آماده‌سازی/ارساله 📦\n"
        "اگه چیزی لازم داشتی همینجا پیام بده 💛"
    )

def _feedback_text(segment: str, order_id: str) -> str:
    if segment == "vip":
        return (
            "رفیقِ ویژه‌مون 💛\n"
            f"امیدوارم سفارشت `{order_id}` به سلامت رسیده باشه.\n"
            "اگه ۱۰ ثانیه وقت داری، یه ستاره بده تا بدونیم چی رو بهتر کنیم ✨"
        )
    return (
        "امیدوارم سفارشت به سلامت رسیده باشه 💛\n"
        f"برای سفارش `{order_id}` یه امتیاز کوچیک می‌دی؟ (ستاره‌ها رو بزن) ⭐️"
    )

def _campaign_text(segment_label: str, points: int) -> str:
    # segment_label: churn | vip | new | active
    if segment_label == "vip":
        return (
            "رفیقِ VIP 🌟\n"
            f"به پاس همراهی‌ت، *{points} امتیاز هدیه* برات شارژ کردیم 💛\n"
            "هر وقت خواستی از «💛 امتیاز من» استفاده‌ش کن 😉"
        )
    if segment_label == "new":
        return (
            "خوش اومدی به جمع‌مون 😍\n"
            f"برای شروعِ رفاقت، *{points} امتیاز هدیه* برات فعال کردیم 💛\n"
            "از «💛 امتیاز من» می‌تونی ببینی و تو خرید بعدی استفاده کنی."
        )
    if segment_label == "active":
        return (
            "سلام رفیق ✨\n"
            f"یه هدیه کوچیک: *{points} امتیاز* برات فعال کردیم 💛\n"
            "دمتون گرم که همراهی 🙏"
        )
    # churn
    return (
        "سلام رفیق 😊\n"
        "دلمون برات تنگ شده بود!\n"
        f"برای اینکه برگشتن برات راحت‌تر بشه، *{points} امتیاز هدیه* برات فعال کردیم 💛\n"
        "هر وقت آماده بودی، از داخل «💛 امتیاز من» می‌تونی ببینی."
    )


async def auto_messages_job(context: ContextTypes.DEFAULT_TYPE):
    """Periodic scanner: sends followup/feedback messages when due."""
    try:
        orders = STORE.data.get("orders", []) or []
        now = datetime.now(timezone.utc)
        for o in orders:
            try:
                oid = o.get("order_id")
                if not oid:
                    continue
                status = (o.get("status") or "").strip()
                if status not in PAID_STATUSES:
                    continue
                uid = o.get("chat_id") or o.get("user_chat_id") or o.get("customer_chat_id")
                if uid is None:
                    continue
                uid = int(uid)

                # FOLLOWUP
                f_due = _parse_iso_z(o.get("followup_due_at") or "")
                if f_due and now >= f_due and not _automation_already_sent(oid, "followup"):
                    txt = (
                        f"📦 سلام! فقط خواستم پیگیری کنم 😊\n"
                        f"سفارش `{oid}` در حال پردازش/ارسال است.\n"
                        "اگر سوالی داری یا نیاز به تغییر آدرس/سایز هست همینجا پیام بده 💛"
                    )
                    try:
                        await context.bot.send_message(chat_id=uid, text=txt, parse_mode="Markdown")
                        _automation_mark_sent(oid, "followup")
                    except Exception:
                        pass

                # FEEDBACK (only after delivery)
                if not o.get("delivered_at"):
                    continue
                fb_due = _parse_iso_z(o.get("feedback_due_at") or "")
                if fb_due and now >= fb_due and not _automation_already_sent(oid, "feedback"):
                    kb = InlineKeyboardMarkup([[
                        InlineKeyboardButton("⭐️⭐️⭐️⭐️⭐️", callback_data=f"fb:{oid}:5"),
                        InlineKeyboardButton("⭐️⭐️⭐️⭐️", callback_data=f"fb:{oid}:4"),
                        InlineKeyboardButton("⭐️⭐️⭐️", callback_data=f"fb:{oid}:3"),
                    ],[
                        InlineKeyboardButton("⭐️⭐️", callback_data=f"fb:{oid}:2"),
                        InlineKeyboardButton("⭐️", callback_data=f"fb:{oid}:1"),
                    ]])
                    txt = (
                        f"📝 نظرت برامون خیلی مهمه 💛\n"
                        f"اگر سفارش `{oid}` به دستت رسیده، به تجربه‌ات چند ستاره می‌دی؟"
                    )
                    try:
                        await context.bot.send_message(chat_id=uid, text=txt, parse_mode="Markdown", reply_markup=kb)
                        _automation_mark_sent(oid, "feedback")
                    except Exception:
                        pass
            except Exception:
                continue
    except Exception as e:
        logger.error("auto_messages_job failed: %s", e)


async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    m = re.match(r"^fb:([^:]+):(\d)$", data)
    if not m:
        return
    order_id = m.group(1)
    rating = int(m.group(2))
    order = STORE.find_order(order_id)
    if order:
        order.setdefault("feedback", {})
        order["feedback"].update({
            "rating": rating,
            "at": _now_iso_z(),
            "from_chat_id": str(update.effective_chat.id),
        })
        STORE.update_order(order_id, **order)
    try:
        await q.edit_message_text(f"🙏 ممنون! امتیاز شما ثبت شد: {rating}⭐️")
    except Exception:
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🙏 ممنون! امتیاز شما ثبت شد: {rating}⭐️")
        except Exception:
            pass


def loyalty_gift_points(chat_id: int, points: int, reason: str, meta: Optional[dict] = None) -> bool:
    """Grant points not tied to an order (non-cashable), with ledger for audit."""
    if points <= 0:
        return False
    _ensure_loyalty_storage()
    _ensure_automation_storage()
    uid = str(chat_id)
    STORE.data["loyalty"]["users"].setdefault(uid, {"balance": 0, "tier": "bronze", "joined_at": _now_iso_z()})
    STORE.data["loyalty"]["users"][uid]["balance"] = int(STORE.data["loyalty"]["users"][uid].get("balance") or 0) + int(points)
    entry = {
        "id": f"LP-{uuid.uuid4().hex[:10]}",
        "chat_id": chat_id,
        "type": "earn",
        "points": int(points),
        "reason": reason,
        "order_id": None,
        "amount_base": 0,
        "at": _now_iso_z(),
        "expires_at": None,
        "meta": meta or {},
    }
    STORE.data["loyalty"].setdefault("ledger", [])
    STORE.data["loyalty"]["ledger"].append(entry)
    STORE.save()
    return True


def _campaign_recent_gift_points(chat_id: int, cooldown_days: int = CAMPAIGN_USER_COOLDOWN_DAYS) -> int:
    """Sum of campaign gifts within cooldown window."""
    _ensure_loyalty_storage()
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=cooldown_days)
    total = 0
    for e in (STORE.data.get("loyalty", {}).get("ledger", []) or []):
        try:
            if int(e.get("chat_id") or 0) != int(chat_id):
                continue
            if str(e.get("reason") or "") != "campaign_gift":
                continue
            dt = _parse_iso_z(e.get("at") or "")
            if dt and dt >= since:
                total += int(e.get("points") or 0)
        except Exception:
            continue
    return total



async def _run_campaign(seg_in: str, points: int, max_users: int, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run a targeted campaign to a segment with small, capped gift points.
    seg_in: churn|vip|new|active|risk|churned
    """
    admin_id = _ensure_admin_chat_id()
    if not admin_id or str(update.effective_chat.id) != str(admin_id):
        return

    points = max(1, min(int(points), CAMPAIGN_MAX_POINTS_PER_USER))
    max_users = max(1, min(int(max_users), 2000))

    # recompute segments (fresh)
    profiles = compute_customer_profiles()

    # map segment keywords
    seg_in = (seg_in or "").lower().strip()
    target_segments = set()
    if seg_in in ("churn", "churned"):
        target_segments = {"churned", "churn_risk"}
        seg_label = "churn"
    elif seg_in in ("risk", "churn_risk"):
        target_segments = {"churn_risk"}
        seg_label = "risk"
    elif seg_in in ("vip", "new", "active"):
        target_segments = {seg_in}
        seg_label = seg_in
    else:
        msg = "سگمنت نامعتبره. از churn/vip/new/active استفاده کن."
        if update.callback_query:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    # choose targets
    targets = [(uid, p) for uid, p in profiles.items() if p.get("segment") in target_segments]

    # prioritize: most inactive first for churn, most valuable first for vip
    if seg_label == "churn":
        targets.sort(key=lambda x: x[1].get("days_since_last_purchase", 0), reverse=True)
    elif seg_label == "vip":
        targets.sort(key=lambda x: x[1].get("spent_90d", 0), reverse=True)

    sent = 0
    gifted = 0
    skipped = 0
    total_points = 0

    for chat_id, prof in targets:
        if sent >= max_users:
            break

        chat_id = int(chat_id)

        # total cap
        if total_points + points > CAMPAIGN_TOTAL_POINTS_CAP:
            break

        # per-user cooldown
        if campaign_user_recently_gifted(chat_id, within_days=CAMPAIGN_USER_COOLDOWN_DAYS):
            skipped += 1
            continue

        msg = _campaign_text(seg_label, points)

        try:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        except Exception:
            skipped += 1
            continue

        ok = loyalty_gift_points(chat_id, points, reason="campaign_gift")
        if not ok:
            skipped += 1
            continue

        campaign_mark_user_gifted(chat_id)
        sent += 1
        gifted += 1
        total_points += points

    report = (
        f"✅ کمپین انجام شد\n"
        f"• سگمنت: `{seg_in}`\n"
        f"• ارسال‌شده: `{sent}`\n"
        f"• هدیه‌ثبت‌شده: `{gifted}`\n"
        f"• رد شده/ناموفق: `{skipped}`\n"
        f"• جمع امتیاز خرج‌شده: `{total_points}`"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(report, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ برگشت به داشبورد", callback_data="admin:dashboard")]
        ]))
    else:
        await update.message.reply_text(report, parse_mode="Markdown")


async def admin_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command:
    /campaign <segment> [points] [max_users]
    segments: churn | churned | risk | vip | new | active
    """
    if not ADMIN_CHAT_ID or str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "📣 کمپین پیام هدفمند\n"
            "فرمت: /campaign <segment> [points] [max_users]\n"
            "مثال: /campaign churn 15 200"
        )
        return

    seg_in = (args[0] or "").lower().strip()
    points = int(args[1]) if len(args) > 1 and str(args[1]).isdigit() else CAMPAIGN_DEFAULT_GIFT_POINTS
    max_users = int(args[2]) if len(args) > 2 and str(args[2]).isdigit() else CAMPAIGN_MAX_USERS_DEFAULT

    await _run_campaign(seg_in, points, max_users, update, context)
    return

    points = max(1, min(points, CAMPAIGN_MAX_POINTS_PER_USER))
    max_users = max(1, min(max_users, 2000))

    # recompute segments (fresh)
    profiles = compute_customer_profiles()

    # map segment keywords
    target_segments = set()
    if seg_in in ("churn", "churned"):
        target_segments = {"churned", "churn_risk"}  # هر دو را هدف می‌گیریم
        seg_label = "churn"
    elif seg_in in ("risk", "churn_risk"):
        target_segments = {"churn_risk"}
        seg_label = "risk"
    elif seg_in in ("vip", "new", "active"):
        target_segments = {seg_in}
        seg_label = seg_in
    else:
        await update.message.reply_text("سگمنت نامعتبر است. از churn/vip/new/active استفاده کن.")
        return

    # choose targets
    targets = [(uid, p) for uid, p in profiles.items() if p.get("segment") in target_segments]
    # prioritize: most inactive first for churn, most valuable first for vip
    if seg_label == "churn":
        targets.sort(key=lambda x: x[1].get("days_since_last_purchase", 0), reverse=True)
    elif seg_label == "vip":
        targets.sort(key=lambda x: x[1].get("spent_90d_subtotal", 0), reverse=True)
    else:
        targets.sort(key=lambda x: x[1].get("updated_at", ""), reverse=True)

    # Apply caps
    total_points_budget = CAMPAIGN_TOTAL_POINTS_CAP
    sent = 0
    gifted_total = 0
    campaign_id = f"CMP-{uuid.uuid4().hex[:8]}"
    _ensure_automation_storage()
    STORE.data["automations"]["campaigns"].append({
        "id": campaign_id,
        "segment": seg_label,
        "target_segments": list(target_segments),
        "points": points,
        "max_users": max_users,
        "total_points_cap": total_points_budget,
        "created_at": _now_iso_z(),
    })
    STORE.data["automations"]["campaign_redemptions"].setdefault(campaign_id, {})
    STORE.save()

    for uid, prof in targets:
        if sent >= max_users:
            break
        try:
            chat_id = int(uid)
        except Exception:
            continue

        # cooldown: if user already got campaign gifts recently, skip
        recent = _campaign_recent_gift_points(chat_id, CAMPAIGN_USER_COOLDOWN_DAYS)
        if recent >= CAMPAIGN_MAX_POINTS_PER_USER:
            continue

        # budget cap
        if gifted_total + points > total_points_budget:
            break

        # send message
        msg = _campaign_text(seg_label, points)
        try:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        except Exception:
            # if can't message, skip granting points
            continue

        # grant points
        ok = loyalty_gift_points(chat_id, points, reason="campaign_gift", meta={"campaign_id": campaign_id, "segment": seg_label})
        if not ok:
            continue

        # record redemption
        STORE.data["automations"]["campaign_redemptions"][campaign_id][str(chat_id)] = _now_iso_z()
        STORE.save()

        sent += 1
        gifted_total += points

    await update.message.reply_text(
        f"✅ کمپین ارسال شد.\n"
        f"کمپین: `{campaign_id}`\n"
        f"سگمنت: `{seg_label}`\n"
        f"ارسال‌شده: {sent} نفر\n"
        f"هدیه کل: {gifted_total} امتیاز",
        parse_mode="Markdown"
    )

# ------------------ end automated messaging & campaigns ------------------

# منطقه زمانی پیش‌فرض: ایران (+03:30). اگر نیاز داری عوضش کنی، env زیر را ست کن:
# TZ_OFFSET_MINUTES=210
try:
    TZ_OFFSET_MINUTES = int(os.getenv("TZ_OFFSET_MINUTES", "210"))
except Exception:
    TZ_OFFSET_MINUTES = 210
LOCAL_TZ = timezone(timedelta(minutes=TZ_OFFSET_MINUTES))

def _parse_dt_utc_z(s: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime strings saved like 2025-01-01T12:34:56.123Z (UTC)."""
    if not s:
        return None
    try:
        ss = str(s).strip()
        if ss.endswith("Z"):
            ss = ss[:-1]
        dt = datetime.fromisoformat(ss)
        # our storage uses utc time but without tzinfo -> set UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def _order_paid_dt_local(order: dict) -> Optional[datetime]:
    dt = _parse_dt_utc_z(order.get("paid_at") or order.get("confirmed_at") or order.get("created_at"))
    if not dt:
        return None
    return dt.astimezone(LOCAL_TZ)

def _product_name_by_id(pid: str) -> str:
    try:
        for gender, cats in CATALOG.items():
            for cat, products in (cats or {}).items():
                for p in (products or []):
                    if p.get("id") == pid:
                        return p.get("name") or pid
    except Exception:
        pass
    return pid

def _sales_agg(orders: List[dict], start: datetime, end: datetime) -> Dict[str, object]:
    count = 0
    amount = 0
    items = Counter()
    for o in (orders or []):
        if o.get("status") not in PAID_STATUSES:
            continue
        dt = _order_paid_dt_local(o)
        if not dt:
            continue
        if start <= dt < end:
            count += 1
            amount += int(o.get("total") or 0)
            for it in (o.get("items") or []):
                key = it.get("product_id") or it.get("id") or it.get("name") or "unknown"
                try:
                    items[key] += int(it.get("qty") or 0)
                except Exception:
                    items[key] += 0
    avg = int(amount / count) if count else 0
    return {"count": count, "amount": amount, "avg": avg, "items": items}

def _pct_change(curr: int, prev: int) -> Optional[float]:
    if prev == 0:
        if curr == 0:
            return None
        return 100.0
    return (curr - prev) / prev * 100.0

def _format_pct(p: Optional[float]) -> str:
    if p is None:
        return "—"
    sign = "+" if p > 0 else ""
    try:
        return f"{sign}{p:.0f}%"
    except Exception:
        return "—"

def _top_items_text(counter: Counter, n: int = 5) -> str:
    if not counter:
        return "—"
    parts = []
    for pid, qty in counter.most_common(n):
        parts.append(f"• {_product_name_by_id(pid)} × {qty}")
    return "\n".join(parts) if parts else "—"

from collections import Counter

def format_top(counter: Counter, title: str, limit=5):
    if not counter:
        return f"{title}:\n—"

    lines = [f"🏆 {title}:"]
    for k, v in counter.most_common(limit):
        lines.append(f"• {k} × {v}")

    return "\n".join(lines)


def best_sellers(orders):
    product_counter = Counter()
    color_counter = Counter()
    size_counter = Counter()

    for o in orders:
        if o.get("status") not in {"paid", "paid_confirmed", "fulfilled"}:
            continue

        for it in o.get("items", []):
            qty = int(it.get("qty", 0))

            product_counter[it.get("product_id")] += qty

            if it.get("color"):
                color_counter[it["color"]] += qty

            if it.get("size"):
                size_counter[it["size"]] += qty

    return {
        "products": product_counter,
        "colors": color_counter,
        "sizes": size_counter,
    }

# ------------------ end sales dashboard helpers ------------------


# **[تغییر]** توابع کمکی برای مدیریت سبد خرید (حذف/کم و زیاد کردن)
def _update_cart_item_qty(cart: List[dict], item_index: int, delta: int) -> bool:
    """تغییر تعداد یک آیتم در سبد خرید. اگر تعداد به صفر برسد، آیتم حذف می‌شود."""
    if 0 <= item_index < len(cart):
        item = cart[item_index]
        new_qty = item["qty"] + delta
        if new_qty > 0:
            item["qty"] = new_qty
            return True
        elif new_qty == 0:
            cart.pop(item_index)
            return True
    return False

def _delete_cart_item(cart: List[dict], item_index: int) -> bool:
    """حذف یک آیتم از سبد خرید"""
    if 0 <= item_index < len(cart):
        cart.pop(item_index)
        return True
    return False

# ⭐️ (جدید) تابع کمکی برای استخراج موجودی کالا از CATALOG ⭐️
def _get_item_inventory(item: Dict) -> int:
    """موجودی یک آیتم خاص در انبار را از CATALOG پیدا می کند."""
    p = _find_product(item["gender"], item["category"], item["product_id"])
    if not p:
        return 0
    
    color = item.get("color")
    size = item.get("size")
    
    # محصول دارای وریانت (رنگ) است
    if "variants" in p and color:
        variant = p["variants"].get(color)
        if variant and size:
            # موجودی به صورت int ذخیره شده است
            return int(variant["sizes"].get(size, 0))
    # محصول بدون وریانت (رنگ) است
    elif "sizes" in p and size:
        # موجودی به صورت int ذخیره شده است
        return int(p["sizes"].get(size, 0))
    
    return 0
# ----------------------------------


# تابع کمکی برای تبدیل ارقام فارسی به انگلیسی
def _to_english_digits(text: str) -> str:
    mapping = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    return text.translate(mapping)


def _merge_cart_item(cart:List[dict] , new_item : dict):
    for it in cart:
        if(
            it["product_id"] == new_item["product_id"] and
            it.get("color") == new_item.get("color") and 
            it.get("size") == new_item.get("size") and
            it.get("gender") == new_item.get("gender") and
            it.get("category") == new_item.get("category")
        ):
            it["qty"] += new_item["qty"]
            return 
    cart.append(new_item)

def _decrement_inventory(item:dict, context: ContextTypes.DEFAULT_TYPE = None):
    p = _find_product(item["gender"] , item["category"] , item["product_id"])
    if not p:
        return False

    color = item.get("color")
    size = item.get("size")
    qty = item["qty"]

    if "variants" in p and color:
        sizes = p["variants"][color]["sizes"]
    else:
        sizes = p["sizes"]

    cur = int(sizes.get(size , 0))
    if cur < qty:
        return False

    new_remaining = cur - qty
    sizes[size] = new_remaining
    STORE.set_catalog(CATALOG)

    # ✅ بعد از بروزرسانی موجودی، هشدار کمبود موجودی
    if context is not None:
        try:
            asyncio.run_coroutine_threadsafe(
                _check_low_stock_and_alert(context, item, new_remaining),
                LOOP
            )
        except Exception as e:
            logger.error("Failed to schedule low stock alert: %s", e)

    return True



#   /start

async def start(update:Update , context:ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        # پاکسازی اطلاعات موقت فقط در صورت شروع از /start
        context.user_data.pop("cart", None)
        try:
            _clear_cart_state(update.effective_chat.id)
        except Exception:
            pass
        context.user_data.pop("customer", None)
    context.user_data.pop("pending", None)
    context.user_data.pop("awaiting", None)
    text = emoji.emojize("سلام:waving_hand:\n به ربات فروشگاه ... خوش آمدید . \n لطفا یکی از گزینه های زیر را انتخاب کنید")
    
    # ⭐️ اصلاح: سازگار کردن با CallbackQuery ⭐️
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        # ویرایش پیام قبلی با دکمه‌های Inline به متن ساده
        try:
             await q.edit_message_text(text) 
        except Exception:
             await context.bot.send_message(update.effective_chat.id, text)
             
        # ارسال یک پیام جدید با Reply Keyboard
        await q.message.reply_text(text , reply_markup=main_menu_reply())
    else:
        await update.message.reply_text(text , reply_markup=main_menu_reply())


#     نمایش مراحل


# --- Admin registration helpers ---
async def admin_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register current chat as admin chat. Run this from the admin account in a private chat with the bot."""
    global ADMIN_CHAT_ID
    chat_id = update.effective_chat.id
    ADMIN_CHAT_ID = str(chat_id)
    try:
        STORE.data["admin_chat_id"] = str(chat_id)
        STORE.save()
    except Exception:
        pass
    await update.message.reply_text(
        f"✅ ادمین ثبت شد. از این به بعد رسیدها به این چت ارسال می‌شوند.\nAdminChatID: {chat_id}",
        reply_markup=main_menu_reply()
    )



async def admin_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to manage discount codes (coupons).

    Examples:
      /coupon list
      /coupon OFF20 percent 20 168 1
      /coupon T10 amount 10000 72 1
      /coupon disable OFF20
    """
    admin_id = _ensure_admin_chat_id()
    if not admin_id or update.effective_chat.id != admin_id:
        await update.message.reply_text("⛔️ دسترسی ندارید.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "🎟 مدیریت کد تخفیف\n\n"
            "لیست: /coupon list\n"
            "ثبت: /coupon <CODE> <percent|amount> <VALUE> [HOURS_VALID=168] [MAX_PER_USER=1] [MAX_TOTAL= ]\n"
            "غیرفعال: /coupon disable <CODE>\n\n"
            "مثال: /coupon OFF20 percent 20 168 1\n"
            "مثال: /coupon T10 amount 10000 72 1"
        )
        return

    sub = args[0].lower()
    codes, _, _ = _get_discount_maps()

    if sub == "list":
        if not codes:
            await update.message.reply_text("هیچ کد تخفیفی ثبت نشده است.")
            return
        lines = []
        for code, c in sorted(codes.items()):
            exp = c.get("expires_at") or "—"
            typ = c.get("type")
            val = c.get("value")
            active = "✅" if c.get("active", True) else "⛔️"
            used = int(c.get("used_total") or 0)
            lines.append(f"{active} `{code}` | {typ}={val} | used={used} | exp={exp}")
        await update.message.reply_text("🎟 لیست کدها:\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return

    if sub == "disable" and len(args) >= 2:
        code = _normalize_code(args[1])
        if code in codes:
            codes[code]["active"] = False
            STORE.save()
            await update.message.reply_text(f"کد `{code}` غیرفعال شد.", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("این کد وجود ندارد.")
        return

    # otherwise: create/update code
    try:
        code = _normalize_code(args[0])
        typ = (args[1] if len(args) > 1 else "").lower()
        value = int(args[2]) if len(args) > 2 else 0
        hours_valid = int(args[3]) if len(args) > 3 else 168
        max_per_user = int(args[4]) if len(args) > 4 else 1
        max_total = int(args[5]) if len(args) > 5 else None
        if typ not in ("percent", "amount"):
            raise ValueError("type")
        if typ == "percent" and not (1 <= value <= 100):
            raise ValueError("value")
        if typ == "amount" and value <= 0:
            raise ValueError("value")
    except Exception:
        await update.message.reply_text("فرمت دستور اشتباه است. برای راهنما: /coupon")
        return

    exp = _now_utc() + timedelta(hours=hours_valid)
    codes[code] = {
        "type": typ,
        "value": value,
        "active": True,
        "max_uses_total": max_total,
        "used_total": int(codes.get(code, {}).get("used_total") or 0),
        "max_uses_per_user": max_per_user,
        "expires_at": _iso_z(exp),
        "note": "admin_created",
    }
    STORE.save()
    await update.message.reply_text(
        f"✅ کد `{code}` ثبت شد.\n"
        f"type={typ} value={value} exp={_iso_z(exp)} max_per_user={max_per_user}",
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_shipcost_start(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str) -> None:
    q = update.callback_query
    await q.answer()

    admin_id = _ensure_admin_chat_id()
    if not admin_id or q.message.chat_id != admin_id:
        await q.answer("دسترسی ندارید.", show_alert=True)
        return

    order = STORE.find_order(order_id)
    if not order:
        await q.edit_message_text("❌ سفارش پیدا نشد.")
        return

    # حالت انتظار برای دریافت عدد
    context.bot_data["admin_pending_shipcost"] = {"order_id": order_id}

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "🚚 لطفاً *عدد هزینه ارسال* را فقط به صورت عدد بفرستید.\n"
            "مثال: 75000\n\n"
            "اگر هزینه ارسال صفر است: 0"
        ),
        parse_mode="Markdown"
    )



async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """داشبورد فروش روزانه/هفتگی/ماهیانه (فقط ادمین)."""
    admin_id = _ensure_admin_chat_id()
    if not admin_id or update.effective_chat.id != admin_id:
        if update.message:
            await update.message.reply_text("⛔️ دسترسی ندارید.", reply_markup=main_menu_reply())
        elif update.callback_query:
            await update.callback_query.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return

    orders = STORE.data.get("orders", []) or []
    best = best_sellers(orders)


    now_local = datetime.now(timezone.utc).astimezone(LOCAL_TZ)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    # امروز
    today = _sales_agg(orders, today_start, tomorrow_start)
    yesterday = _sales_agg(orders, today_start - timedelta(days=1), today_start)

    # ۷ روز اخیر (شامل امروز)
    week_start = today_start - timedelta(days=6)
    week_end = tomorrow_start
    week = _sales_agg(orders, week_start, week_end)
    prev_week = _sales_agg(orders, week_start - timedelta(days=7), week_start)

    # ۳۰ روز اخیر (شامل امروز)
    month_start = today_start - timedelta(days=29)
    month_end = tomorrow_start
    month = _sales_agg(orders, month_start, month_end)
    prev_month = _sales_agg(orders, month_start - timedelta(days=30), month_start)

    # وضعیت سفارش‌ها
    status_counts = Counter((o.get("status") or "unknown") for o in orders)

    # تاریخ شمسی برای نمایش
    try:
        j_now = jdatetime.datetime.fromgregorian(datetime=now_local.replace(tzinfo=None))
        jalali_label = j_now.strftime("%Y/%m/%d")
        greg_label = now_local.strftime("%Y-%m-%d")
        date_label = f"{jalali_label} ({greg_label})"
    except Exception:
        date_label = now_local.strftime("%Y-%m-%d")

    lines = []
    lines.append("📊 *داشبورد فروش*")
    lines.append(f"📅 تاریخ: `{date_label}`")
    lines.append(f"🕒 منطقه زمانی: `UTC{TZ_OFFSET_MINUTES/60:+.1f}`")
    lines.append("")
    lines.append("🗓 *امروز*")
    lines.append(f"• تعداد سفارش پرداخت‌شده: `{today['count']}`")
    lines.append(f"• مبلغ فروش: *{_ftm_toman(today['amount'])}*")
    lines.append(f"• میانگین سبد: `{_ftm_toman(today['avg'])}`")
    lines.append(f"• تغییر نسبت به دیروز (مبلغ): `{_format_pct(_pct_change(today['amount'], yesterday['amount']))}`")
    lines.append("")
    lines.append("📅 *۷ روز اخیر*")
    lines.append(f"• تعداد: `{week['count']}`")
    lines.append(f"• فروش: *{_ftm_toman(week['amount'])}*")
    lines.append(f"• میانگین: `{_ftm_toman(week['avg'])}`")
    lines.append(f"• تغییر نسبت به ۷ روز قبل (مبلغ): `{_format_pct(_pct_change(week['amount'], prev_week['amount']))}`")
    lines.append("• پرفروش‌ها:")
    lines.append(_top_items_text(week["items"]))
    lines.append("")
    lines.append("📆 *۳۰ روز اخیر*")
    lines.append(f"• تعداد: `{month['count']}`")
    lines.append(f"• فروش: *{_ftm_toman(month['amount'])}*")
    lines.append(f"• میانگین: `{_ftm_toman(month['avg'])}`")
    lines.append(f"• تغییر نسبت به ۳۰ روز قبل (مبلغ): `{_format_pct(_pct_change(month['amount'], prev_month['amount']))}`")
    lines.append("• پرفروش‌ها:")
    lines.append(_top_items_text(month["items"]))
    lines.append("")
    lines.append("📦 *وضعیت سفارش‌ها*")
    lines.append(f"• awaiting_receipt: `{status_counts.get('awaiting_receipt', 0)}`")
    lines.append(f"• receipt_submitted: `{status_counts.get('receipt_submitted', 0)}`")
    lines.append(f"• receipt_rejected: `{status_counts.get('receipt_rejected', 0)}`")
    lines.append(f"• paid: `{status_counts.get('paid', 0)}`")
    lines.append(f"• paid_confirmed: `{status_counts.get('paid_confirmed', 0)}`")
    lines.append(f"• fulfilled: `{status_counts.get('fulfilled', 0)}`")


    # سگمنت مشتری‌ها
    summary = STORE.data.get("segments_summary", {}) or {}
    lines.append("")
    lines.append("👥 *سگمنت مشتری‌ها*")
    lines.append(f"• VIP: `{summary.get('vip',0)}`")
    lines.append(f"• مشتری جدید: `{summary.get('new',0)}`")
    lines.append(f"• ریزش‌یافته: `{summary.get('churned',0)}`")
    lines.append(f"• در خطر ریزش: `{summary.get('churn_risk',0)}`")
    lines.append(f"• فعال: `{summary.get('active',0)}`")

    
    lines.append("")
    lines.append(format_top(best["products"], "محصولات پرفروش"))
    lines.append("")
    lines.append(format_top(best["colors"], "رنگ‌های پرفروش"))
    lines.append("")
    lines.append(format_top(best["sizes"], "سایزهای پرفروش"))

    msg = "\n".join(lines)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی داشبورد", callback_data="admin:dashboard")],
        [InlineKeyboardButton("🎯 کمپین ریزشی (+15)", callback_data="camp:prep:churn:15:200")],
        [InlineKeyboardButton("🌟 کمپین VIP (+10)", callback_data="camp:prep:vip:10:150")],
        [InlineKeyboardButton("🆕 کمپین مشتری جدید (+10)", callback_data="camp:prep:new:10:300")],
    ])

    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
    elif update.callback_query:
        q = update.callback_query
        await q.answer()
        try:
            await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="Markdown", reply_markup=kb)


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"ChatID شما: {update.effective_chat.id}")

# --- end admin helpers ---

async def show_gender(update:Update , context:ContextTypes.DEFAULT_TYPE) -> None:
    """
    نمایش کیبورد انتخاب جنسیت.
    سازگار شده برای دریافت Message (از Reply Keyboard) و CallbackQuery (از Inline Keyboard).
    """
    text = "جنسیت رو انتخاب کن :"
    reply_markup = gender_keyboard()

    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.edit_message_text(text , reply_markup=reply_markup)
    else:
        # اگر از Reply Keyboard (لیست محصولات) آمده است
        await update.message.reply_text(text , reply_markup=reply_markup)


async def show_categories(update:Update , context:ContextTypes.DEFAULT_TYPE , gender:str) -> None: # ⭐️ تغییر: پذیرش gender ⭐️
    """
    نمایش دسته‌بندی محصولات بر اساس جنسیت انتخاب شده.
    سازگار شده برای دریافت CallbackQuery (چون در این مرحله فقط از Inline Keyboard فراخوانی می‌شود).
    """
    text = "لطفا یک دسته‌بندی را انتخاب کنید."
    reply_markup = category_keyboard(gender) # ⭐️ تغییر: ارسال gender به category_keyboard ⭐️

    # در جریان عادی، این تابع همیشه از طریق CallbackQuery فراخوانی می‌شود،
    # اما منطق را برای اطمینان از سازگاری نگه می‌داریم.
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        # ویرایش پیام قبلی
        await q.edit_message_text(text , reply_markup=reply_markup)
    else:
        # حالت اضطراری - اگر از Reply Keyboard آمده بود (که نباید اینگونه باشد)
        await update.message.reply_text(text , reply_markup=reply_markup)
    
    return


async def show_products(update:Update, context:ContextTypes.DEFAULT_TYPE, gender:str, category:str) -> None:
    q = update.callback_query
    await q.answer()

    items = CATALOG.get(gender, {}).get(category, [])
    if not items:
        # اگر محصولی نیست، کاربر را به صفحه دسته‌ها برگردان
        try:
            await q.edit_message_text("فعلا محصولی در این دسته نیست", reply_markup=category_keyboard(gender))
        except Exception:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="فعلا محصولی در این دسته نیست",
                reply_markup=category_keyboard(gender)
            )
        return

    # --- reset and track list messages for this view ---
    context.user_data["product_list_msg_ids"] = []

    # هدر لیست
    title = f"👇 محصولات دسته «{category}» 👇"
    try:
        await q.edit_message_text(title)
        _track_product_list_msg(context, q.message.message_id)
    except Exception as e:
        logger.debug("Could not edit message for product list header: %s", e)
        m = await context.bot.send_message(chat_id=update.effective_chat.id, text=title)
        _track_product_list_msg(context, m.message_id)

    # ارسال هر محصول جداگانه — مقاوم در برابر خطا و با کمی تأخیر برای جلوگیری از flood
    for p in items:
        photo = _product_photo_for_list(p)
        caption = f"{p.get('name', 'بدون نام')}"
        # دکمه مناسب بسته به این که وریانت دارد یا نه
        if "variants" in p:
            btn = InlineKeyboardButton("انتخاب", callback_data=f"catalog:select:{gender}:{_safe_callback(category)}:{p['id']}")
        else:
            btn = InlineKeyboardButton("انتخاب", callback_data=f"catalog:sizeonly:{gender}:{_safe_callback(category)}:{p['id']}")
        keyboard = InlineKeyboardMarkup([[btn]])

        try:
            if photo:
                m = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=caption,
                    reply_markup=keyboard
                )
                _track_product_list_msg(context, m.message_id)
            else:
                m = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=caption,
                    reply_markup=keyboard
                )
                _track_product_list_msg(context, m.message_id)
        except Exception as e:
            logger.warning("Failed to send product %s (id=%s): %s. Falling back to text.", p.get("name"), p.get("id"), e)
            try:
                m = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"{caption}\n(⚠️ تصویر قابل نمایش نیست)",
                    reply_markup=keyboard
                )
                _track_product_list_msg(context, m.message_id)
            except Exception as e2:
                logger.error("Fallback send_message also failed for product %s: %s", p.get("id"), e2)

        try:
            await asyncio.sleep(0.08)
        except Exception:
            pass

    # پیام راهنما و دکمه بازگشت (در انتها) — این هم جزو لیست است و باید پاک شود
    try:
        m = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"دسته: {category}\nبرای انتخاب هر محصول روی دکمهٔ زیر عکس آن کلیک کن.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ انتخاب دسته دیگر", callback_data=f"catalog:gender:{gender}")],
                [InlineKeyboardButton("🏠 منو اصلی", callback_data="menu:back_home")],
            ])
        )
        _track_product_list_msg(context, m.message_id)
    except Exception as e:
        logger.debug("Failed to send category footer: %s", e)


async def ask_color_and_size(update:Update, context:ContextTypes.DEFAULT_TYPE, gender:str, category:str, product_id:str) -> None:
    q = update.callback_query
    await q.answer()

    # ✅ مرحله C: پاک کردن کل لیست محصولات (به جز همین پیام انتخاب‌شده)
    await _clear_product_list_msgs(update, context, keep_message_id=q.message.message_id)

    p = _find_product(gender, category, product_id)
    if not p or "variants" not in p:
        await q.edit_message_text("محصول یا رنگ‌ها پیدا نشد.", reply_markup=category_keyboard(gender))
        return

    rows = []
    for i, (color, v) in enumerate(p["variants"].items()):
        available_sizes = [sz for sz, qty in v["sizes"].items() if qty > 0]
        for sz in available_sizes:
            rows.append([InlineKeyboardButton(
                f"{color} | سایز {sz}",
                callback_data=f"catalog:choose:{gender}:{_safe_callback(category)}:{product_id}:{i}:{sz}"
            )])

    if not rows:
        await q.edit_message_text("هیچ رنگ و سایزی برای این محصول موجود نیست.", reply_markup=category_keyboard(gender))
        return

    rows.append([InlineKeyboardButton("⬅️ انتخاب محصول دیگر", callback_data=f"catalog:category:{gender}:{_safe_callback(category)}")])

    caption = f"✅ {p['name']}\nلطفاً رنگ و سایز را انتخاب کن:"
    thumb = _product_photo_for_list(p)

    # ✅ نمایش محصول انتخابی (عکس + دکمه‌ها) با Edit
    try:
        if thumb:
            await context.bot.edit_message_media(
                chat_id=update.effective_chat.id,
                message_id=q.message.message_id,
                media=InputMediaPhoto(media=thumb, caption=caption),
                reply_markup=InlineKeyboardMarkup(rows)
            )
        else:
            await q.edit_message_text(caption, reply_markup=InlineKeyboardMarkup(rows))
    except Exception:
        # fallback اگر پیام عکس‌دار باشد ولی edit_message_media شکست بخورد
        try:
            await q.edit_message_caption(caption=caption, reply_markup=InlineKeyboardMarkup(rows))
        except Exception:
            await q.edit_message_text(text=caption, reply_markup=InlineKeyboardMarkup(rows))


async def after_color_ask_size(update:Update , context:ContextTypes.DEFAULT_TYPE , gender:str , category:str , product_id:str , color:str) -> None:
    q = update.callback_query
    await q.answer()

    p = _find_product(gender , category , product_id)
    if not p or "variants" not in p or color not in p["variants"]:
        await q.message.reply_text("رنگ انتخابی معتبر نیست" , reply_markup = colors_keyboard(gender , category , product_id))
        return
    price , sizes = _unit_price_and_sizes(p , color=color)
    if not any(qty > 0 for qty in sizes.values()):
        await q.message.reply_text("این رنگ فعلا موجود نیست" , reply_markup = colors_keyboard(gender , category , product_id))
        return
    
    context.user_data["pending"] = {
        "gender": gender,
        "category": category,
        "product_id": product_id,
        "name": p["name"],
        "color": color,
        "size": size,
        "price": v["price"],
        "buy_price": int(v.get("buy_price") or 0),
        "available": available,
        "qty": 1,
    }

    photo = _photo_for_selection(p , color=color)
    if photo:
        await q.message.reply_photo(photo=photo, caption=f"{p['name']}\nرنگ: {color}")
    await q.message.reply_text(
        f"رنگ انتخاب شده: {color}\nحالا سایز مورد نظر را انتخاب کنید:",
        reply_markup=sizes_keyboard(sizes)
    )



async def ask_size_only(update: Update, context: ContextTypes.DEFAULT_TYPE, gender, category, product_id):
    q = update.callback_query
    await q.answer()

    # ✅ مرحله C: پاک کردن کل لیست محصولات (به جز همین پیام انتخاب‌شده)
    await _clear_product_list_msgs(update, context, keep_message_id=q.message.message_id)

    p = _find_product(gender, category, product_id)
    if not p or "sizes" not in p:
        await q.edit_message_text("محصول یا سایزها پیدا نشد.", reply_markup=category_keyboard(gender))
        return

    available_sizes = [sz for sz, qty in p["sizes"].items() if qty > 0]
    rows = [[InlineKeyboardButton(
        f"سایز {sz}",
        callback_data=f"catalog:chooseonly:{gender}:{_safe_callback(category)}:{product_id}:{sz}"
    )] for sz in available_sizes]

    rows.append([InlineKeyboardButton("⬅️ انتخاب محصول دیگر", callback_data=f"catalog:category:{gender}:{_safe_callback(category)}")])

    caption = f"✅ {p['name']}\nلطفاً سایز را انتخاب کن:"
    thumb = _product_photo_for_list(p)

    try:
        if thumb:
            await context.bot.edit_message_media(
                chat_id=update.effective_chat.id,
                message_id=q.message.message_id,
                media=InputMediaPhoto(media=thumb, caption=caption),
                reply_markup=InlineKeyboardMarkup(rows)
            )
        else:
            await q.edit_message_text(caption, reply_markup=InlineKeyboardMarkup(rows))
    except Exception:
        try:
            await q.edit_message_caption(caption=caption, reply_markup=InlineKeyboardMarkup(rows))
        except Exception:
            await q.edit_message_text(text=caption, reply_markup=InlineKeyboardMarkup(rows))

       
async def show_qty_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, chosen_size):
    q = update.callback_query
    await q.answer()

    pend = context.user_data.get("pending")
    if not pend:
        await q.edit_message_text("اطلاعات محصول ناقص است.", reply_markup=main_menu())
        return

    # برای محصولات بدون رنگ
    p = _find_product(pend["gender"], pend["category"], pend["product_id"])
    if not p:
        await q.edit_message_text("محصول پیدا نشد.", reply_markup=main_menu())
        return

    sizes = p.get("sizes")
    price = p.get("price")

    if "variants" in p and pend.get("color"):
        color_variant = p["variants"].get(pend["color"])
        if color_variant:
            sizes = color_variant.get("sizes")
            price = color_variant.get("price")

    if not sizes or chosen_size not in sizes:
        await q.edit_message_text("سایز انتخابی معتبر نیست.", reply_markup=main_menu())
        return

    available = int(sizes.get(chosen_size, 0))
    if available <= 0:
        await q.edit_message_text("این سایز موجود نیست.", reply_markup=main_menu())
        return

    pend["size"] = chosen_size
    pend["available"] = available
    pend["qty"] = 1
    pend["price"] = price
    pend["buy_price"] = int(p.get("buy_price") or 0)


    photo = _product_photo_for_list(p)
    cap = (
        f"{p['name']}\nسایز: {chosen_size}\n"
        f"موجودی: {available}\n"
        f"قیمت واحد: {_ftm_toman(price)}\n"
        f"قیمت نهایی: {_ftm_toman(price)}"
    )

    # ✅ مرحله D: به‌جای پیام جدید، همان پیام قبلی را ویرایش کن
    try:
        if photo:
            await context.bot.edit_message_media(
                chat_id=update.effective_chat.id,
                message_id=q.message.message_id,
                media=InputMediaPhoto(media=photo, caption=cap),
                reply_markup=qty_keyboard(1, available)
            )
        else:
            await q.edit_message_text(cap, reply_markup=qty_keyboard(1, available))
    except Exception as e:
        logger.error(f"Failed to edit message in qty picker for {p.get('id')}: {e}. Falling back to caption/text edit.")
        try:
            await q.edit_message_caption(caption=cap, reply_markup=qty_keyboard(1, available))
        except Exception:
            await q.edit_message_text(text=cap, reply_markup=qty_keyboard(1, available))



async def show_qty_picker_combined(update: Update, context: ContextTypes.DEFAULT_TYPE, gender, category, product_id, color, size):
    q = update.callback_query
    await q.answer()

    p = _find_product(gender, category, product_id)
    if not p or "variants" not in p:
        await q.edit_message_text("محصول یا رنگ انتخابی معتبر نیست.", reply_markup=main_menu())
        return

    v = p["variants"][color]
    available = int(v["sizes"].get(size, 0))
    if available <= 0:
        await q.edit_message_text("این سایز موجود نیست.", reply_markup=main_menu())
        return

    context.user_data["pending"] = {
        "gender": gender,
        "category": category,
        "product_id": product_id,
        "name": p["name"],
        "color": color,
        "size": size,
        "price": v["price"],
        "available": available,
        "qty": 1,
    }

    photo = v.get("photo") or _product_photo_for_list(p)
    cap = (
        f"{p['name']}\nرنگ: {color} | سایز: {size}\n"
        f"موجودی: {available}\n"
        f"قیمت واحد: {_ftm_toman(v['price'])}\n"
        f"قیمت نهایی: {_ftm_toman(v['price'])}"
    )

    # ✅ مرحله D: به‌جای پیام جدید، همان پیام قبلی را ویرایش کن
    try:
        if photo:
            await context.bot.edit_message_media(
                chat_id=update.effective_chat.id,
                message_id=q.message.message_id,
                media=InputMediaPhoto(media=photo, caption=cap),
                reply_markup=qty_keyboard(1, available)
            )
        else:
            await q.edit_message_text(cap, reply_markup=qty_keyboard(1, available))
    except Exception as e:
        logger.error(f"Failed to edit message in combined qty picker for {p.get('id')}: {e}. Falling back to caption/text edit.")
        try:
            await q.edit_message_caption(caption=cap, reply_markup=qty_keyboard(1, available))
        except Exception:
            await q.edit_message_text(text=cap, reply_markup=qty_keyboard(1, available))


#       cart / checkout
PHONE_REGEX = re.compile(r"^(\+98|0)?9\d{9}$") # اجازه می‌دهد که با +98 یا 0 یا بدون هیچکدام شروع شود.

async def show_cart(update:Update , context:ContextTypes.DEFAULT_TYPE) -> None:
    cart: List[Dict] = context.user_data.get("cart" , [])

    # 🔁 Sync cart state to persistent storage for recovery campaigns
    try:
        cid = update.effective_chat.id
        if cart:
            _sync_cart_state(cid, cart)
        else:
            _clear_cart_state(cid)
    except Exception:
        cid = update.effective_chat.id

    subtotal = sum(item['price'] * item['qty'] for item in cart)

    # Loyalty points (preferred over coupon codes)
    use_points = bool(context.user_data.get("use_points"))
    payable, burn_points, burn_value = loyalty_apply(subtotal, cid, use_points)

    text = ""
    reply_markup = None
    if not cart:
        # reset toggles
        context.user_data.pop("use_points", None)
        context.user_data.pop("coupon_code", None)
        text = emoji.emojize("سبد خرید شما خالی است :shopping_cart:")
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text , reply_markup=main_menu() , parse_mode="Markdown")
        else:
            await update.message.reply_text(text , reply_markup=main_menu_reply() , parse_mode="Markdown")
        return

    lines = ["🧺 *سبد خرید شما*\n"]
    for item in cart:
        lines.append(f"• {item.get('name','')} × {item.get('qty',1)} = {_ftm_toman(int(item.get('price',0))*int(item.get('qty',1)))}")

    lines.append("\n------------------")
    lines.append(f"جمع جزء (Subtotal): *{_ftm_toman(subtotal)}*")

    if use_points and burn_points > 0 and burn_value > 0:
        pv = loyalty_point_value()
        lines.append(f"💛 استفاده از امتیاز: *{burn_points}* امتیاز (≈ {_ftm_toman(burn_value)})")
        lines.append(f"مبلغ قابل پرداخت: *{_ftm_toman(payable)}*")
        lines.append(f"_هر ۱ امتیاز = {_ftm_toman(pv)} | سقف استفاده: {_loy_rules().get('max_burn_percent')}%_")
    else:
        bal = loyalty_balance(cid)
        pv = loyalty_point_value()
        lines.append(f"💛 امتیاز شما: *{bal}* (≈ {_ftm_toman(bal*pv)})")
        lines.append(f"مبلغ قابل پرداخت: *{_ftm_toman(payable)}*")

    text = "\n".join(lines)

    toggle_btn = InlineKeyboardButton(
        "❌ عدم استفاده از امتیاز" if use_points else "💛 استفاده از امتیاز",
        callback_data="loyalty:toggle"
    )

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ادامه و ثبت سفارش" , callback_data="checkout:start")],
        [toggle_btn],
        [InlineKeyboardButton("🧹 خالی کردن سبد" , callback_data="cart:clear")],
        [InlineKeyboardButton("🏠 منوی اصلی" , callback_data="menu:back_home")],
    ])

    # اگر از دکمه Inline آمده (CallbackQuery)
    if update.callback_query:
        await update.callback_query.answer()
        try:
            if update.callback_query.message.caption:
                await update.callback_query.edit_message_caption(caption=text, reply_markup=reply_markup , parse_mode="Markdown")
            else:
                await update.callback_query.edit_message_text(text , reply_markup=reply_markup , parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id=cid, text=text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        # اگر از دکمه Reply Keyboard آمده (Message)
        await update.message.reply_text(text , reply_markup=reply_markup , parse_mode="Markdown")
    return
async def show_my_order_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    orders = STORE.data.get("orders", [])

    mine = [o for o in orders if int(o.get("user_chat_id", 0)) == int(chat_id)]
    if not mine:
        await update.message.reply_text("هنوز سفارشی برای شما ثبت نشده است.", reply_markup=main_menu_reply())
        return

    # آخرین سفارش
    o = sorted(mine, key=lambda x: x.get("created_at", ""), reverse=True)[0]
    order_id = o.get("order_id")
    status = o.get("status")
    ship = o.get("shipping_status", "pending")
    track = o.get("tracking_code") or "ثبت نشده"

    text = (
        f"📦 وضعیت آخرین سفارش شما:\n\n"
        f"🧾 شماره سفارش: {order_id}\n"
        f"💳 وضعیت پرداخت: {PAY_STATUS_FA.get(status, '—')}\n"
        f"🚚 وضعیت ارسال: {SHIP_STATUS_FA.get(ship, '—')}\n"
        f"🔎 کد رهگیری: {track}\n"
    )

    # آخرین 3 رویداد
    last_event = (o.get("history") or [])[-1:]  # فقط آخرین آیتم
    if last_event:
        h = last_event[0]
        text += f"\nآخرین تغییر: {h.get('text')}"


    await update.message.reply_text(text, reply_markup=main_menu_reply())



async def menu_reply_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    روتر برای مدیریت پیام‌های متنی دریافتی از دکمه‌های Reply Keyboard (پایین صفحه).
    """
    text = update.message.text


    # 🎟️ دریافت کد تخفیف از کاربر (وقتی در حالت انتظار هستیم)
    if context.user_data.get("awaiting") == "coupon_code":
        raw = (text or "").strip()
        if raw == "❌ انصراف":
            context.user_data["awaiting"] = None
            await update.message.reply_text("❌ لغو شد.", reply_markup=main_menu_reply())
            await show_cart(update, context)
            return

        cart = context.user_data.get("cart", []) or []
        cart_total = _calc_cart_total(cart)
        ok, msg, _ = _is_code_valid_for_user(raw, update.effective_chat.id, cart_total)
        if ok:
            context.user_data["coupon_code"] = _normalize_code(raw)
            context.user_data["awaiting"] = None
            await update.message.reply_text(msg, reply_markup=main_menu_reply())
            await show_cart(update, context)
        else:
            await update.message.reply_text(f"❌ {msg}\n\nیک کد دیگر بفرست یا «❌ انصراف» را بزن.", reply_markup=form_keyboard())
        return

    
    if text == "🛍️ لیست محصولات":
        # هدایت به مرحله اول انتخاب محصولات (انتخاب جنسیت)
        await show_gender(update, context) 
    
    elif text == "🧺 سبد خرید":
        # تابع show_cart قبلاً اصلاح شد.
        await show_cart(update, context)
        
    elif text == "🆘 پشتیبانی":
        await update.message.reply_text("برای پشتیبانی با @amirmehdi_84_10 تماس بگیرید.")

    elif text == "💛 امتیاز من":
        await show_loyalty(update, context)

    elif text == "📦 وضعیت سفارش من":
        await show_my_order_status(update, context)


async def begin_customer_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if context.user_data.get("cart"):
        context.user_data["awaiting"] = "name"

        text = (
            "✍️ لطفاً نام و نام خانوادگی را وارد کن.\n\n"
            "❌ برای لغو فرم مشخصات می‌توانید گزینه «انصراف» را بزنید."
        )

        # 👇 فقط یک پیام ارسال می‌شود
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=form_keyboard()
        )
        return CUSTOMER_NAME
    else:
        await q.edit_message_text(
            "❌ سبد خرید شما خالی است.",
            reply_markup=main_menu()
        )
        return ConversationHandler.END



async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return 
    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        await menu_reply_router(update, context)
        return ConversationHandler.END
    
    text = update.message.text.strip()

    # ✅ لغو فرم از طریق Reply Keyboard
    if text == "❌ انصراف":
        context.user_data.pop("customer", None)
        context.user_data.pop("pending", None)
        context.user_data["awaiting"] = None
        await update.message.reply_text("❌ فرم لغو شد. از منوی پایین استفاده کن.", reply_markup=main_menu_reply())
        # بازگشت به سبد (اختیاری)
        await show_cart(update, context)
        return ConversationHandler.END

    if awaiting == "name":
        context.user_data.setdefault("customer", {})["name"] = text
        context.user_data["awaiting"] = "phone"
        kb = ReplyKeyboardMarkup(
            [[{"text": "📱 ارسال شماره من", "request_contact": True}], ["❌ انصراف"]],
            resize_keyboard=True, one_time_keyboard=False
        )
        await update.message.reply_text("شماره تماس خود را وارد کنید:", reply_markup=kb)
        return CUSTOMER_PHONE
    if awaiting == "phone":
        # 🟢 اصلاحات برای پذیرش ارقام فارسی و فرمت‌های +98/0
        phone = _to_english_digits(text) # تبدیل ارقام فارسی به انگلیسی
        phone = phone.replace(" ", "") # حذف فاصله‌ها
        
        if PHONE_REGEX.match(phone):
            # نرمال‌سازی شماره به فرمت استاندارد 09xxxxxxxxx برای ذخیره‌سازی
            if phone.startswith("+98"):
                phone = "0" + phone[3:] # حذف +98 و جایگزینی با 0
            elif not phone.startswith("0") and len(phone) == 10:
                phone = "0" + phone # اضافه کردن 0 اگر با 9 شروع شده باشد
            
            context.user_data["customer"]["phone"] = phone
            context.user_data["awaiting"] = "address"
            await update.message.reply_text("آدرس کامل و دقیق (شامل شهر، خیابان، پلاک):", reply_markup=form_keyboard())
            return CUSTOMER_ADDRESS
        else:
            await update.message.reply_text("شماره نامعتبر است. با قالب 09xxxxxxxxx (فارسی یا انگلیسی) وارد کن.")
        return CUSTOMER_PHONE
    if awaiting == "address":
        context.user_data["customer"]["address"] = text
        context.user_data["awaiting"] = "postal"
        await update.message.reply_text("کد پستی ۱۰ رقمی:")
        return CUSTOMER_POSTAL
    if awaiting == "postal":
        if re.fullmatch(r"\d{10}" , _to_english_digits(text)): # اعمال تبدیل برای کدپستی هم توصیه می‌شود
            context.user_data["customer"]["postal"] = _to_english_digits(text)
            context.user_data["awaiting"] = None
            # ⭐️ (اصلاح شده) فراخوانی با کل شیء update برای استخراج دقیق chat_id
            await show_checkout_summary(update, context) 
            return ConversationHandler.END
        else:
            await update.message.reply_text("کد پستی نامعتبر است. ۱۰ رقم (فارسی یا انگلیسی) وارد کنید.")
        return CUSTOMER_POSTAL


async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.contact:
        return
    awaiting = context.user_data.get("awaiting")
    if awaiting != "phone":
        return
        
    phone = update.message.contact.phone_number
    # 🟢 اصلاحات برای نرمال‌سازی شماره ارسالی از تلگرام
    phone = phone.replace("+98", "0").replace("98", "0").replace(" ", "")

    if PHONE_REGEX.match(phone):
        # اطمینان از اینکه شماره به 0 شروع شود (فرمت ذخیره‌سازی):
        if not phone.startswith("0"):
             phone = "0" + phone
             
        context.user_data["customer"]["phone"] = phone
        context.user_data["awaiting"] = "address"
        await update.message.reply_text("آدرس کامل و دقیق (شامل شهر، خیابان، پلاک):", reply_markup=form_keyboard())
        return CUSTOMER_ADDRESS
    else:
        await update.message.reply_text("شمارهٔ دریافتی نامعتبر بود. لطفاً دستی وارد کن.")
        return CUSTOMER_PHONE


async def show_checkout_summary(update_or_msg, context: ContextTypes.DEFAULT_TYPE):
    # ⭐️ اصلاح شده برای تعیین chat_id و send function ⭐️
    # این منطق تضمین می‌کند که حتی اگر Update.message یا Update.callback_query نداشته باشیم (مثلاً فقط Message object باشد)،
    # باز هم chat_id به درستی استخراج شود و از context.bot.send_message برای ارسال مطمئن استفاده شود.
    if isinstance(update_or_msg, Update):
        chat_id = update_or_msg.effective_chat.id
    else: # اگر مستقیماً یک Message object باشد (مثل update.message)
        chat_id = update_or_msg.chat.id
    
    send = context.bot.send_message
    
    cart = context.user_data.get("cart" , [])
    customer = context.user_data.get("customer" , {})
    total = _calc_cart_total(cart)
    coupon_code = context.user_data.get("coupon_code")
    payable, discount_amount, valid_code = _calc_payable_with_coupon(total, coupon_code)
    coupon_code = context.user_data.get("coupon_code")
    payable, discount_amount, valid_code = _calc_payable_with_coupon(total, coupon_code)
    
    # اگر اطلاعات مشتری کامل نیست (مثلاً اگر در میان فرآیند ConversationHandler خطا رخ دهد)
    if not all(k in customer for k in ["name", "phone", "address", "postal"]):
        await send(chat_id=chat_id, text="❌ خطایی در جمع‌آوری اطلاعات رخ داد. لطفاً دوباره تلاش کنید.", reply_markup=main_menu())
        return

    lines = []
    for i , it in enumerate(cart , 1):
        lines.append(
            f"{i}) {it['name']} | رنگ: {it.get('color') or '—'} | سایز: {it.get('size') or '—'} | "
            f"تعداد: {it['qty']} | {_ftm_toman(it['qty'] * it['price'])}"
        )
    
    joined_lines = "\n".join(lines)
    # 🎟️ جمع‌بندی مبلغ با کد تخفیف (در صورت وجود)
    if valid_code and discount_amount > 0:
        payment_details = (
            f"💳 **جمع کل سبد**: **{_ftm_toman(total)}**\n"
            f"🎟 **کد تخفیف**: `{valid_code}`\n"
            f"➖ **تخفیف**: **{_ftm_toman(discount_amount)}**\n"
            f"💰 **مبلغ قابل پرداخت**: **{_ftm_toman(payable)}**"
        )
    else:
        payment_details = f"💰 **مبلغ قابل پرداخت**: **{_ftm_toman(total)}**"
    # 🟢 نمایش خلاصه سفارش و اطلاعات مشتری با فرمت Markdown
    info = (
        "🧾 **خلاصه سفارش و مشخصات مشتری**:\n\n"
        "👤 **نام و نام خانوادگی**: `{name}`\n"
        "📞 **شماره موبایل**: `{phone}`\n"
        "🏠 **آدرس**: `{address}`\n"
        "📮 **کد پستی**: `{postal}`\n"
        "🚚 **روش ارسال**: `{ship}`\n\n"
        "🛍️ **محصولات سفارش داده شده**:\n"
        f"{joined_lines}\n\n"
        f"{payment_details}"
    ).format(
        name=customer.get('name', '—'),
        phone=customer.get('phone', '—'),
        address=customer.get('address', '—'),
        postal=customer.get('postal', '—'),
        ship=(SHIPPING_METHODS.get(customer.get('shipping_method'), {}).get('label') if customer.get('shipping_method') else 'انتخاب نشده')
    )
    
    # 🟢 دکمه‌های مورد درخواست کاربر
    kb = InlineKeyboardMarkup([
    [InlineKeyboardButton("🚚 انتخاب روش ارسال", callback_data="shipmethod:choose")],
    [InlineKeyboardButton("✏️ ویرایش مشخصات", callback_data="checkout:begin")],
    [InlineKeyboardButton("💳 اقدام به پرداخت نهایی", callback_data="checkout:pay")],
    [InlineKeyboardButton("❌ لغو سفارش", callback_data="checkout:cancel")],
    [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")]
])

    await send(chat_id=chat_id, text=info, reply_markup=kb, parse_mode="Markdown")
    # ✅ بازگرداندن منوی اصلی (Reply Keyboard) بعد از اتمام فرم
    m = await context.bot.send_message(
        chat_id=chat_id,
        text="✅فرم مشخصات تکمیل شد.",
        reply_markup=main_menu_reply(),
    )
    context.user_data["form_done_msg_id"] = m.message_id

def _build_checkout_summary_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    cart = context.user_data.get("cart", [])
    customer = context.user_data.get("customer", {})
    total = _calc_cart_total(cart)
    coupon_code = context.user_data.get("coupon_code")
    payable, discount_amount, valid_code = _calc_payable_with_coupon(total, coupon_code)

    lines = []
    for i, it in enumerate(cart, 1):
        lines.append(
            f"{i}) {it['name']} | رنگ: {it.get('color') or '—'} | سایز: {it.get('size') or '—'} | "
            f"تعداد: {it['qty']} | {_ftm_toman(it['qty'] * it['price'])}"
        )
    joined_lines = "\n".join(lines) if lines else "—"

    ship_label = SHIPPING_METHODS.get(customer.get("shipping_method"), {}).get("label") if customer.get("shipping_method") else "انتخاب نشده"

    # 🎟️ جمع‌بندی مبلغ با کد تخفیف (در صورت وجود)
    if valid_code and discount_amount > 0:
        payment_details = (
            f"💳 **جمع کل سبد**: **{_ftm_toman(total)}**\n"
            f"🎟 **کد تخفیف**: `{valid_code}`\n"
            f"➖ **تخفیف**: **{_ftm_toman(discount_amount)}**\n"
            f"💰 **مبلغ قابل پرداخت**: **{_ftm_toman(payable)}**"
        )
    else:
        payment_details = f"💰 **مبلغ قابل پرداخت**: **{_ftm_toman(total)}**"

    info = (
        "🧾 **خلاصه سفارش و مشخصات مشتری**:\n\n"
        "👤 **نام و نام خانوادگی**: `{name}`\n"
        "📞 **شماره موبایل**: `{phone}`\n"
        "🏠 **آدرس**: `{address}`\n"
        "📮 **کد پستی**: `{postal}`\n"
        "🚚 **روش ارسال**: `{ship}`\n\n"
        "🛍️ **محصولات سفارش داده شده**:\n"
        "{items}\n\n"
        "{payment}"
    ).format(
        name=customer.get('name', '—'),
        phone=customer.get('phone', '—'),
        address=customer.get('address', '—'),
        postal=customer.get('postal', '—'),
        ship=ship_label,
        payment=payment_details,
        items=joined_lines,
        total=_ftm_toman(total)
    )
    return info


# ------------------ Manual payment / receipt workflow ------------------

import jdatetime
def _make_order_id() -> str:
    today = jdatetime.date.today().strftime("%Y%m%d")

    seq_map = STORE.data.get("order_seq", {})
    last_seq = int(seq_map.get(today, 0))
    new_seq = last_seq + 1
    seq_map[today] = new_seq
    STORE.data["order_seq"] = seq_map
    STORE.save()

    return f"ORD-{today}-{new_seq:03d}"


def _ensure_admin_chat_id() -> Optional[int]:
    try:
        return int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else None
    except Exception:
        return None
    
# --- Low stock alert settings ---
LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "2"))  # آستانه هشدار (پیش‌فرض 2)

def _sku_key(item_or_parts: dict) -> str:
    """
    کلید یکتا برای هر SKU:
    product_id|gender|category|color|size
    """
    pid = item_or_parts.get("product_id") or item_or_parts.get("id") or ""
    gender = item_or_parts.get("gender") or ""
    category = item_or_parts.get("category") or ""
    color = item_or_parts.get("color") or "—"
    size = item_or_parts.get("size") or "—"
    return f"{pid}|{gender}|{category}|{color}|{size}"

def _get_low_stock_alerts_map() -> dict:
    STORE.data.setdefault("low_stock_alerts", {})
    return STORE.data["low_stock_alerts"]

async def _send_low_stock_alert(context: ContextTypes.DEFAULT_TYPE, item: dict, remaining: int):
    admin_id = _ensure_admin_chat_id()
    if not admin_id:
        return

    text = (
        "⚠️ *هشدار کمبود موجودی*\n\n"
        f"📦 محصول: *{item.get('name', item.get('product_id', '—'))}*\n"
        f"🎨 رنگ: `{item.get('color') or '—'}`\n"
        f"📏 سایز: `{item.get('size') or '—'}`\n"
        f"📂 دسته: `{item.get('category') or '—'}` | `{item.get('gender') or '—'}`\n"
        f"🔻 موجودی باقی‌مانده: *{remaining}* عدد\n\n"
        f"آستانه هشدار: {LOW_STOCK_THRESHOLD}"
    )

    try:
        await context.bot.send_message(chat_id=admin_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error("Failed to send low stock alert to admin: %s", e)

async def _check_low_stock_and_alert(context: ContextTypes.DEFAULT_TYPE, item: dict, remaining: int):
    """
    اگر remaining <= threshold و قبلاً برای این SKU هشدار نداده باشیم => هشدار بده
    اگر remaining > threshold و قبلاً هشدار داده بودیم => ریست کن تا دفعه بعد دوباره هشدار بده
    """
    alerts = _get_low_stock_alerts_map()
    key = _sku_key(item)

    if remaining <= LOW_STOCK_THRESHOLD:
        if not alerts.get(key):  # قبلاً هشدار نداده
            alerts[key] = {
                "at": datetime.utcnow().isoformat() + "Z",
                "remaining": remaining,
            }
            STORE.save()
            await _send_low_stock_alert(context, item, remaining)
    else:
        # اگر موجودی دوباره بالا رفت، ریست کنیم
        if key in alerts:
            alerts.pop(key, None)
            STORE.save()


def _create_order_from_current_cart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    """Create (or reuse) an order id for current user's cart+customer."""
    cart = context.user_data.get("cart", [])
    customer = context.user_data.get("customer", {})
    if not cart or not customer:
        return None

    existing = context.user_data.get("current_order_id")
    if existing and STORE.find_order(existing):
        # sync shipping method/customer with latest user_data
        order = STORE.find_order(existing)
        cust = dict(order.get("customer", {}))
        cust.update(customer)

        subtotal = _calc_cart_total(cart)

        # prefer loyalty points over coupons
        use_points = bool(context.user_data.get("use_points"))
        if use_points:
            payable, burn_points, burn_value = loyalty_apply(subtotal, update.effective_chat.id, True)
            coupon_code = None
            discount_amount = burn_value
        else:
            payable, discount_amount, coupon_code = _calc_payable_with_coupon(subtotal, context.user_data.get("coupon_code"))
            burn_points, burn_value = 0, 0

        STORE.update_order(
            existing,
            customer=cust,
            shipping_method=cust.get("shipping_method"),
            subtotal=subtotal,
            coupon_code=coupon_code,
            discount_amount=discount_amount,
            loyalty_points_used=burn_points,
            loyalty_discount_amount=burn_value,
            total=payable,
            items=cart,
            chat_id=update.effective_chat.id,
        )
        return existing

    order_id = _make_order_id()

    subtotal = _calc_cart_total(cart)

    # prefer loyalty points over coupons
    use_points = bool(context.user_data.get("use_points"))
    if use_points:
        payable, burn_points, burn_value = loyalty_apply(subtotal, update.effective_chat.id, True)
        coupon_code = None
        discount_amount = burn_value
    else:
        payable, discount_amount, coupon_code = _calc_payable_with_coupon(subtotal, context.user_data.get("coupon_code"))
        burn_points, burn_value = 0, 0

    order = {
        "order_id": order_id,
        "chat_id": update.effective_chat.id,
        "status": "awaiting_receipt",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "subtotal": subtotal,
        "coupon_code": coupon_code,
        "discount_amount": discount_amount,
        "total": payable,
        "loyalty_points_used": burn_points,
        "loyalty_discount_amount": burn_value,
        "items": cart,
        "customer": customer,
        "shipping_method": customer.get("shipping_method"),
        "shipping_status": "pending",
        "shipping_cost_actual": 0,
        "shipping_payer": "customer",
        "tracking_code": None,
        "history": [{"at": datetime.utcnow().isoformat() + "Z", "by": "system", "text": "سفارش ساخته شد و در انتظار رسید است."}],
        "user_chat_id": update.effective_chat.id,
    }

    STORE.add_order(order)
    context.user_data["current_order_id"] = order_id
    return order_id

async def manual_payment_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str) -> None:
    """Send card number (copyable) + request receipt."""
    total = 0
    order = STORE.find_order(order_id)
    if order:
        total = order.get("total", 0)
    
    cards_text = ""
    for i, card in enumerate(CARDS, start=1):
        cards_text += (f"{i}) 💳 `{format_card_number(card['number'])}`\n"f"👤 ({card['holder']})\n\n")
    
    shipping_method = (order.get("shipping_method") or order.get("customer", {}).get("shipping_method"))
    shipping_note = SHIPPING_INFO.get(shipping_method, "هزینه ارسال بر عهده مشتری است.")

    ship_label = SHIPPING_METHODS.get(shipping_method, {}).get("label", "انتخاب نشده")
    text = (
    "💳 **پرداخت کارت به کارت**\n\n"
    f"🔸 مبلغ قابل پرداخت: **{_ftm_toman(total)}**\n"
    f"🚚 روش ارسال: **{ship_label}**\n"
    f"{shipping_note}\n\n"
    "🔹 اطلاعات حساب‌های فروشگاه (برای کپی، روی شماره بزنید):\n\n"
    f"{cards_text}\n"
    "📸 بعد از پرداخت، روی دکمه زیر بزنید و *عکس رسید پرداخت* را ارسال کنید."
)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 ارسال عکس رسید پرداخت", callback_data=f"receipt:start:{order_id}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")],
    ])

    if update.callback_query:
        q = update.callback_query
        await q.answer()
        try:
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=kb, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=kb, parse_mode="Markdown")


async def receipt_start(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str) -> None:
    q = update.callback_query
    await q.answer()
    mid = context.user_data.pop("form_done_msg_id", None)
    if mid:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=int(mid))
        except Exception:
            pass
    order = STORE.find_order(order_id)
    if not order:
        await q.edit_message_text("❌ سفارش پیدا نشد.", reply_markup=main_menu())
        return

    # mark that we are waiting for a photo from this user
    context.user_data["awaiting_receipt"] = order_id

    text = (
        "📸 لطفاً *عکس رسید پرداخت* را همینجا ارسال کنید.\n\n"
        "اگر اشتباهی وارد این مرحله شدید، می‌توانید انصراف دهید."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ انصراف", callback_data="receipt:cancel")],
    ])
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=kb, parse_mode="Markdown")


async def receipt_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    context.user_data.pop("awaiting_receipt", None)
    await q.edit_message_text("انصراف داده شد. از منو می‌توانید ادامه دهید.", reply_markup=main_menu())


async def on_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user uploading receipt photo."""
    if not update.message or not update.message.photo:
        return

    order_id = context.user_data.get("awaiting_receipt")
    if not order_id:
        return  # not in receipt flow

    order = STORE.find_order(order_id)
    if not order:
        context.user_data.pop("awaiting_receipt", None)
        await update.message.reply_text("❌ سفارش پیدا نشد. لطفاً دوباره تلاش کنید.", reply_markup=main_menu_reply())
        return

    # take best quality
    photo = update.message.photo[-1]
    file_id = photo.file_id

    # update order
    STORE.update_order(order_id, status="receipt_submitted", receipt={"file_id": file_id, "submitted_at": datetime.utcnow().isoformat() + "Z"})
    context.user_data.pop("awaiting_receipt", None)

    await update.message.reply_text(
        "✅ رسید دریافت شد. پس از بررسی توسط ادمین، نتیجه به شما اطلاع داده می‌شود.",
        reply_markup=main_menu_reply()
    )

    admin_id = _ensure_admin_chat_id()
    if not admin_id:
        # admin not registered yet
        await update.message.reply_text(
            f"⚠️ ادمین هنوز در ربات ثبت نشده است. لطفاً به ادمین ({ADMIN_USERNAME}) اطلاع دهید داخل ربات دستور /admin را بزند.",
            reply_markup=main_menu_reply()
        )
        return

    # build order summary for admin
    lines = []
    for i, it in enumerate(order.get("items", []), 1):
        lines.append(
            f"{i}) {it['name']} | رنگ: {it.get('color') or '—'} | سایز: {it.get('size') or '—'} | "
            f"تعداد: {it['qty']} | {_ftm_toman(it['qty'] * it['price'])}"
        )

    p = _calc_estimated_profit(order)
    missing_buy = any(int(it.get("buy_price") or 0) <= 0 for it in (order.get("items") or []))
    warn = "\n⚠️ *هشدار:* قیمت خرید بعضی آیتم‌ها ثبت نشده؛ سود تقریبی دقیق نیست." if missing_buy else ""


    admin_text = (
    "🧾 **رسید پرداخت جدید**\n"
    f"OrderID: `{order_id}`\n"
    f"UserChatID: `{order.get('user_chat_id')}`\n"
    f"User: @{order.get('username') or '—'}\n"
    f"جمع کل: **{_ftm_toman(order.get('total', 0))}**\n\n"
    "📊 **محاسبه سود تقریبی**\n"
    f"فروش (subtotal): {_ftm_toman(p['subtotal'])}\n"
    f"تخفیف: {_ftm_toman(p['discount'])}\n"
    f"دریافتی (total): {_ftm_toman(p['total'])}\n"
    f"هزینه خرید کالاها: {_ftm_toman(p['items_cost'])}\n"
    f"هزینه ارسال (با ادمین): {_ftm_toman(p['ship_admin'])}\n"
    f"✅ سود تقریبی: **{_ftm_toman(p['profit'])}**"
    f"{warn}\n\n"
    "👤 مشتری:\n"
    f"نام: {order['customer'].get('name')}\n"
    f"موبایل: {order['customer'].get('phone')}\n"
    f"آدرس: {order['customer'].get('address')}\n"
    f"کدپستی: {order['customer'].get('postal')}\n\n"
    "اقلام:\n" + "\n".join(lines)
)

    admin_text = _with_history_section_md(admin_text, order, limit=10)


    buttons = [
        [InlineKeyboardButton("✅ تایید پرداخت", callback_data=f"admin:approve:{order_id}")],
        [InlineKeyboardButton("❌ مشکل دارد", callback_data=f"admin:reject:{order_id}")],
        [
        InlineKeyboardButton("🚚 ارسال با مشتری", callback_data=f"admin:shippayer:customer:{order_id}"),
        InlineKeyboardButton("🚚 ارسال با ادمین", callback_data=f"admin:shippayer:admin:{order_id}"),
        ],
    ]

    # فقط اگر ارسال با ادمین شد، دکمه ثبت هزینه ارسال را هم نشان بده
    if (order.get("shipping_payer") or "customer") == "admin":
        buttons.append([InlineKeyboardButton("💰 ثبت هزینه ارسال", callback_data=f"admin:shipcost:{order_id}")])

    admin_kb = _admin_receipt_kb(order, order_id)



    try:
        await context.bot.send_photo(
            chat_id=admin_id,
            photo=file_id,
            caption=admin_text,
            parse_mode="Markdown",
            reply_markup=admin_kb
        )
    except Exception as e:
        logger.error("Failed to send receipt to admin: %s", e)


async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str) -> None:
    q = update.callback_query
    await q.answer()

    admin_id = _ensure_admin_chat_id()
    if not admin_id or q.message.chat_id != admin_id:
        await q.answer("دسترسی ندارید.", show_alert=True)
        return

    order = STORE.find_order(order_id)
    if not order:
        await q.edit_message_text("❌ سفارش پیدا نشد.")
        return

    if order.get("status") == "paid_confirmed":
        await q.answer("قبلاً تایید شده.", show_alert=False)
        return

    # decrement inventory once confirmed
    for it in order.get("items", []):
        _decrement_inventory(it , context=context)

    _update_order_with_log(
        order_id,
        by="admin",
        note="✅ پرداخت تایید شد",
        status="paid_confirmed",
        confirmed_at=datetime.utcnow().isoformat() + "Z",
    )

    # 🕒 schedule followup/feedback automation timestamps
    try:
        _mark_order_automation_due(order_id)
    except Exception:
        pass
    # 🎟️ redeem coupon only after admin confirms payment
    try:
        ccode = order.get("coupon_code")
        if ccode:
            uid = int(order.get("chat_id") or 0)
            if uid:
                _redeem_discount(ccode, uid)
    except Exception:
        pass

    # 💛 loyalty burn/earn after payment confirmation (earn is based on subtotal)
    try:
        uid = int(order.get("chat_id") or 0)
        if uid:
            used = int(order.get("loyalty_points_used") or 0)
            if used > 0:
                loyalty_burn(uid, used, order_id)
            res = loyalty_earn(uid, int(order.get("subtotal") or 0), order_id)
            # update segments after a real purchase is recorded
            compute_customer_profiles()
            earned = int(res.get("earned") or 0)
            if earned > 0:
                bonus = int(res.get("bonus") or 0)
                msg_lines = [f"💛 بابت این خرید، *{earned}* امتیاز به حسابت اضافه شد. ممنون که برگشتی ✨"]
                if bonus > 0:
                    msg_lines.append(f"🎁 از این مقدار، *{bonus}* امتیاز هدیه/بونوس بود.")
                for mtxt in (res.get("messages") or []):
                    if mtxt:
                        msg_lines.append(str(mtxt))
                msg = "\n".join(msg_lines)
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=msg,
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
    except Exception:
        pass

    # پاکسازی سبد کاربر بعد از تایید پرداخت (برای کمپین بازیابی و ...)
    try:
        uid = int(order.get("chat_id") or 0)
        if uid:
            _clear_cart_state(uid)
    except Exception:
        pass

    _order_log(order_id, "admin", "پرداخت تایید شد. سفارش وارد مرحله پردازش شد.")

    admin_panel = admin_panel_keyboard(order_id)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🛠 کنترل سفارش `{order_id}`",
        parse_mode="Markdown",
        reply_markup=admin_panel
    )



    user_chat_id = order.get("user_chat_id")
    try:
        await context.bot.send_message(
            chat_id=int(user_chat_id),
            text=f"✅ پرداخت شما برای سفارش `{order_id}` تایید شد. سفارش شما در حال پردازش است.",
            parse_mode="Markdown",
            reply_markup=main_menu_reply()
        )
    except Exception as e:
        logger.error("Failed to notify user for approve: %s", e)

    
# refresh admin message (receipt) with latest history/status
order2 = STORE.find_order(order_id) or order
base = q.message.caption or q.message.text or ""
caption = _with_history_section_md(base + "\n\n✅ *پرداخت تایید شد.*", order2, limit=10)
try:
    await q.edit_message_caption(caption=caption, parse_mode="Markdown", reply_markup=None)
except Exception:
    try:
        await q.edit_message_text(text=caption, parse_mode="Markdown", reply_markup=None)
    except Exception:
        pass

async def admin_reject_start(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str) -> None:
    q = update.callback_query
    await q.answer()

    admin_id = _ensure_admin_chat_id()
    if not admin_id or q.message.chat_id != admin_id:
        await q.answer("دسترسی ندارید.", show_alert=True)
        return

    order = STORE.find_order(order_id)
    if not order:
        await q.edit_message_text("❌ سفارش پیدا نشد.")
        return

    # mark pending admin reply in bot_data (shared)
    context.bot_data["admin_pending_reply"] = {
        "order_id": order_id,
        "user_chat_id": order.get("user_chat_id"),
        "admin_chat_id": admin_id,
    }
    await q.edit_message_caption(
        caption=(q.message.caption or "") + "\n\n❌ *لطفاً دلیل/پیام را تایپ کنید تا برای مشتری ارسال شود.*",
        parse_mode="Markdown",
        reply_markup=q.message.reply_markup
    )


async def admin_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = _ensure_admin_chat_id()
    if not admin_id:
        return
    if update.effective_chat.id != admin_id:
        return

    """Admin types a message after pressing 'مشکل دارد' to send to user."""
    if not update.message:
        return
    
    pending_ship = context.bot_data.get("admin_pending_shipcost")
    if pending_ship:
        order_id = pending_ship["order_id"]
        order = STORE.find_order(order_id)
        if not order:
            await update.message.reply_text("❌ سفارش پیدا نشد.")
            context.bot_data.pop("admin_pending_shipcost", None)
            return

        raw = (update.message.text or "").strip()
        raw = _to_english_digits(raw)
        raw = raw.replace(",", "").replace("تومان", "").strip()

        if not raw.isdigit():
            await update.message.reply_text("❌ عدد معتبر نیست. فقط عدد بفرستید. مثال: 75000")
            return

        cost = int(raw)
        STORE.update_order(order_id, shipping_cost_actual=cost)
        _order_log(order_id, "admin", f"هزینه ارسال ثبت شد: {cost}")

        # سود جدید
        order2 = STORE.find_order(order_id)  # دوباره بخون
        p = _calc_estimated_profit(order2)

        await update.message.reply_text(
            "✅ هزینه ارسال ثبت شد.\n\n"
            f"🚚 هزینه ارسال (با ادمین): {_ftm_toman(cost)}\n"
            f"✅ سود تقریبی جدید: {_ftm_toman(p['profit'])}"
        )

        context.bot_data.pop("admin_pending_shipcost", None)
        return

    
    pending_track = context.bot_data.get("admin_pending_tracking")
    if pending_track:
        order_id = pending_track["order_id"]
        order = STORE.find_order(order_id)

        if not order:
            await update.message.reply_text("❌ سفارش پیدا نشد.")
            context.bot_data.pop("admin_pending_tracking", None)
            return

        track = update.message.text.strip()

        # ذخیره وضعیت ارسال
        STORE.update_order(order_id, shipping_status="shipped", tracking_code=track)
        _order_log(order_id, "admin", f"تحویل پست شد. کد رهگیری: {track}")

        # ✅ ارسال پیام به مشتری (بدون Markdown برای جلوگیری از خطا)
        try:
            await context.bot.send_message(
                chat_id=int(order["user_chat_id"]),
                text=(
                    "🚚 سفارش شما ارسال شد.\n"
                    f"🧾 شماره سفارش: {order_id}\n"
                    f"🔎 کد رهگیری: {track}"
                ),
                reply_markup=main_menu_reply()
            )
        except Exception as e:
            logger.error("Failed to send tracking to user: %s", e)
            await update.message.reply_text("❌ ارسال کد رهگیری به مشتری ناموفق بود.")
            context.bot_data.pop("admin_pending_tracking", None)
            return

        # ✅ پیام تایید به ادمین + نگه داشتن پنل
        await update.message.reply_text("✅ کد رهگیری برای مشتری ارسال شد.")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🛠 کنترل سفارش `{order_id}`",
            parse_mode="Markdown",
            reply_markup=admin_panel_keyboard(order_id)
        )

        context.bot_data.pop("admin_pending_tracking", None)
        return


    pending_msg = context.bot_data.get("admin_pending_msg")
    if pending_msg:
        order_id = pending_msg["order_id"]
        order = STORE.find_order(order_id)

        if not order:
            await update.message.reply_text("❌ سفارش پیدا نشد.")
            context.bot_data.pop("admin_pending_msg", None)
            return

        msg = update.message.text.strip()
        _order_log(order_id, "admin", f"پیام ادمین به مشتری: {msg}")

    # ✅ ارسال پیام واقعی به مشتری
        try:
            await context.bot.send_message(
                chat_id=int(order["user_chat_id"]),
                text=f"✉️ پیام پشتیبانی درباره سفارش {order_id}:\n{msg}",
                reply_markup=main_menu_reply()
            )
        except Exception as e:
            logger.error("Failed to send admin message to user: %s", e)
            await update.message.reply_text("❌ ارسال پیام به مشتری ناموفق بود (خطای تلگرام).")
            context.bot_data.pop("admin_pending_msg", None)
            return

    # ✅ تأیید به ادمین + نگه داشتن پنل
        await update.message.reply_text("✅ پیام برای مشتری ارسال شد.")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🛠 کنترل سفارش `{order_id}`",
            parse_mode="Markdown",
            reply_markup=admin_panel_keyboard(order_id)
        )

        context.bot_data.pop("admin_pending_msg", None)
        return


    pending = context.bot_data.get("admin_pending_reply")
    admin_id = _ensure_admin_chat_id()
    if not pending or not admin_id:
        return
    if update.effective_chat.id != admin_id:
        return

    msg = update.message.text.strip()
    order_id = pending.get("order_id")
    user_chat_id = pending.get("user_chat_id")
    if not (order_id and user_chat_id):
        context.bot_data.pop("admin_pending_reply", None)
        return

    # update order status
    _update_order_with_log(
        order_id,
        by="admin",
        note=f"❌ رسید رد شد. پیام ادمین: {msg}",
        status="receipt_rejected",
        rejected_at=datetime.utcnow().isoformat() + "Z",
        reject_message=msg,
    )

    try:
        kb = InlineKeyboardMarkup([
    [InlineKeyboardButton("📸 ارسال مجدد رسید", callback_data=f"receipt:start:{order_id}")],
    [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")],
])

        await context.bot.send_message(
    chat_id=int(user_chat_id),
    text=(
        f"❌ رسید پرداخت برای سفارش `{order_id}` تایید نشد.\n\n"
        f"پیام ادمین: {msg}\n\n"
        "لطفاً روی «ارسال مجدد رسید» بزن و دوباره عکس رسید را ارسال کن."
    ),
    parse_mode="Markdown",
    reply_markup=kb
)
    except Exception as e:
        logger.error("Failed to send reject message to user: %s", e)

    await update.message.reply_text("✅ پیام برای مشتری ارسال شد.")
    context.bot_data.pop("admin_pending_reply", None)

# ------------------ end manual payment / receipt workflow ------------------

#      payment_provider
class DummyProvider:
    def create_payment(self , order_id:str , amount: int, name: str, phone: str, desc: str, callback_url: Optional[str] = None):
        link = link = f"https://example.com/pay?order_id={order_id}&amount={amount}"
        return {"ok": True, "payment_id": f"dummy-{order_id}", "link": link, "raw": {"provider": "dummy"}}
    
    def verify_payment(self, order_id: str, payment_id: str):
        return {"ok": True, "status": "paid", "track_id": f"FAKE-{order_id}", "raw": {}}


class IdPayProvider:
    def __init__(self, api_key: str, sandbox: bool = True):
        self.api_key = api_key
        self.sandbox = sandbox
        self.create_url = "https://api.idpay.ir/v1.1/payment"
        self.verify_url = "https://api.idpay.ir/v1.1/payment/verify"

    def _headers(self):
        return {
            "X-API-KEY": self.api_key,
            "X-SANDBOX": "1" if self.sandbox else "0",
            "Content-Type": "application/json",
        }
    
    def create_payment(self, order_id: str, amount: int, name: str, phone: str, desc: str, callback_url: Optional[str] = None):
        payload = {
            "order_id": order_id,
            "amount": amount,
            "name": name,
            "phone": phone,
            "desc": desc[:200],
        }
        if callback_url:
            payload["callback"] = callback_url
        r = requests.post(self.create_url, headers=self._headers(), json=payload, timeout=20)
        try:
            j = r.json()
        except Exception:
            j = {"error": r.text}
        link = j.get("link")
        pid = j.get("id")
        ok = bool(link and pid)
        return {"ok": ok, "payment_id": pid, "link": link, "raw": j}
    
    def verify_payment(self, order_id: str, payment_id: str):
        payload = {"id": payment_id, "order_id": order_id}
        r = requests.post(self.verify_url, headers=self._headers(), json=payload, timeout=20)
        try:
            j = r.json()
        except Exception:
            j = {"error": r.text}
        status = j.get("status")
        ok = status in (100, 101)
        track_id = j.get("track_id") or j.get("payment", {}).get("track_id")
        return {"ok": ok, "status": status, "track_id": track_id, "raw": j}


def get_payment_provider():
    provider_name = (os.getenv("PAYMENT_PROVIDER", "idpay") or "idpay").lower()
    if provider_name == "idpay" and os.getenv("IDPAY_API_KEY", "").strip():
        return IdPayProvider(
            api_key=os.getenv("IDPAY_API_KEY").strip(),
            sandbox=(os.getenv("IDPAY_SANDBOX", "1").strip() == "1")
        )
    return DummyProvider()
PAY = get_payment_provider()
CALLBACK_URL = os.getenv("CALLBACK_URL", "").strip() or None


#      check out: pay/verify

async def checkout_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    customer = context.user_data.get("customer", {})
    if not customer or not customer.get("shipping_method"):
        # کاربر هنوز روش ارسال را انتخاب نکرده
        await q.answer("ابتدا روش ارسال را انتخاب کنید.", show_alert=True)
        text = _build_checkout_summary_text(context)
        try:
            await q.edit_message_text(text, reply_markup=shipping_methods_keyboard(None), parse_mode="Markdown")
        except Exception:
            pass
        return


    order_id = _create_order_from_current_cart(update, context)
    if not order_id:
        await q.edit_message_text("❌ سبد خرید یا مشخصات مشتری کامل نیست. لطفاً دوباره تلاش کنید.", reply_markup=main_menu())
        return

    await manual_payment_instructions(update, context, order_id)


async def checkout_verify(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    q = update.callback_query
    await q.answer()

    order = STORE.find_order(order_id)
    if not order:
        await q.edit_message_text("سفارش پیدا نشد.", reply_markup=main_menu())
        return
    if order.get("status") in ("paid", "fulfilled"):
        await q.edit_message_text("این سفارش قبلاً پرداخت/تایید شده است. 🙌", reply_markup=main_menu())
        return
    
    payment_id = order.get("payment", {}).get("payment_id")
    if not payment_id:
        await q.edit_message_text("شناسه پرداخت نامشخص است.", reply_markup=main_menu())
        return
    
    res = PAY.verify_payment(order_id, payment_id)
    if not res.get("ok"):
        await q.edit_message_text("پرداخت هنوز تایید نشده یا ناموفق بوده است.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 بررسی مجدد", callback_data=f"checkout:verify:{order_id}")],
            [InlineKeyboardButton("🏠 منو", callback_data="menu:back_home")],
        ]))
        logger.warning("Payment verify not ok: %s", res)
        return
    
    for it in order["items"]:
        ok = _decrement_inventory(it , context=context)
        if not ok:
            logger.error("Inventory not enough for %s", it)
    
    STORE.update_order(
        order_id,
        status="paid",
        paid_at=datetime.utcnow().isoformat() + "Z",
        payment={**order["payment"], "verify_raw": res.get("raw"), "track_id": res.get("track_id")}
    )

    # 🕒 schedule followup/feedback automation timestamps
    try:
        _mark_order_automation_due(order_id)
    except Exception:
        pass

    # 🎟️ redeem coupon (count usage) only after successful payment
    try:
        ccode = order.get("coupon_code")
        if ccode:
            _redeem_discount(ccode, update.effective_chat.id)
    except Exception:
        pass

    # 💛 loyalty burn/earn after payment confirmation (earn is based on subtotal)
    try:
        uid = int(order.get("chat_id") or update.effective_chat.id or 0)
        if uid:
            used = int(order.get("loyalty_points_used") or 0)
            if used > 0:
                loyalty_burn(uid, used, order_id)
            res = loyalty_earn(uid, int(order.get("subtotal") or 0), order_id)
            # update segments after a real purchase is recorded
            compute_customer_profiles()
            earned = int(res.get("earned") or 0)
            if earned > 0:
                bonus = int(res.get("bonus") or 0)
                msg_lines = [f"💛 بابت این خرید، *{earned}* امتیاز به حسابت اضافه شد. ممنون که برگشتی ✨"]
                if bonus > 0:
                    msg_lines.append(f"🎁 از این مقدار، *{bonus}* امتیاز هدیه/بونوس بود.")
                for mtxt in (res.get("messages") or []):
                    if mtxt:
                        msg_lines.append(str(mtxt))
                msg = "\n".join(msg_lines)
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=msg,
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
    except Exception:
        pass


    context.user_data["cart"] = []
    context.user_data.pop("coupon_code", None)
    try:
        _clear_cart_state(update.effective_chat.id)
    except Exception:
        pass

    await q.edit_message_text(
        f"🎉 پرداخت با موفقیت انجام شد!\nشماره سفارش: {order_id}\n"
        f"کد رهگیری پرداخت: {res.get('track_id') or '—'}\n"
        f"مبلغ: {_ftm_toman(order['total'])}\n\n"
        "سفارش شما برای پردازش به ادمین ارسال شد.",
        reply_markup=main_menu()
    )

    if ADMIN_CHAT_ID:
        lines = []
        for i, it in enumerate(order["items"], 1):
            lines.append(
                f"{i}) {it['name']} | رنگ: {it.get('color') or '—'} | سایز: {it.get('size') or '—'} | "
                f"تعداد: {it['qty']} | قیمت واحد: {_ftm_toman(it['price'])}"
            )
        
        msg = (
            f"📦 سفارش جدید پرداخت‌شده\n"
            f"OrderID: {order_id}\n"
            f"User: @{update.effective_user.username or update.effective_user.id}\n"
            f"جمع کل: {_ftm_toman(order['total'])}\n"
            f"رهگیری پرداخت: {res.get('track_id') or '—'}\n\n"
            "اقلام:\n" + "\n".join(lines) + "\n\n"
            "👤 مشتری:\n"
            f"نام: {order['customer'].get('name')}\n"
            f"موبایل: {order['customer'].get('phone')}\n"
            f"آدرس: {order['customer'].get('address')}\n"
            f"کدپستی: {order['customer'].get('postal')}\n"
        )
        try:
            msg = _with_history_section_md(msg, order, limit=10)
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=msg)
        except Exception as e:
            logger.error("Failed to notify admin: %s", e)
        
async def show_home_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = "🏠 منوی اصلی\nاز گزینه‌های زیر انتخاب کنید:"

    if update.callback_query:
        q = update.callback_query
        await q.answer()
        # پیام فعلی (Inline) را تبدیل به منو کن
        try:
            await q.edit_message_text(text, reply_markup=main_menu())
        except Exception:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=main_menu())

        # اگر می‌خوای کیبورد پایین صفحه (ReplyKeyboard) هم حتماً دیده بشه:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⬇️ از منوی پایین هم می‌تونی استفاده کنی.",
            reply_markup=main_menu_reply()
        )
    else:
        await update.message.reply_text(text, reply_markup=main_menu_reply())

#      روتر کلی دکمه ها 
async def menu_router(update:Update , context:ContextTypes.DEFAULT_TYPE) -> None :
    q = update.callback_query
    await q.answer() # پاسخ به کلیک اولیه برای حذف لودینگ
    data = (q.data or "").strip()

    if data == "admin:dashboard":
        await admin_dashboard(update, context)
        return
 
    # -------- Campaign buttons (from dashboard) --------
    if data.startswith("camp:prep:"):
        # camp:prep:<segment>:<points>:<max_users>
        try:
            _, _, seg, pts, mx = data.split(":", 4)
            pts_i = int(pts)
            mx_i = int(mx)
        except Exception:
            await q.answer("خطا در کمپین", show_alert=True)
            return

        confirm_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ بزن بریم", callback_data=f"camp:run:{seg}:{pts_i}:{mx_i}"),
            InlineKeyboardButton("❌ بیخیال", callback_data="camp:cancel"),
        ]])
        label = "ریزش" if seg == "churn" else ("VIP" if seg == "vip" else ("مشتری جدید" if seg == "new" else seg))
        await q.edit_message_text(
            f"📣 کمپین {label}\n"
            f"می‌خوای برای این گروه، *{pts_i} امتیاز هدیه* (تا {mx_i} نفر) ارسال بشه؟",
            parse_mode="Markdown",
            reply_markup=confirm_kb
        )
        return

    if data == "camp:cancel":
        await admin_dashboard(update, context)
        return

    if data.startswith("camp:run:"):
        try:
            _, _, seg, pts, mx = data.split(":", 4)
            pts_i = int(pts)
            mx_i = int(mx)
        except Exception:
            await q.answer("خطا در اجرای کمپین", show_alert=True)
            return

        await _run_campaign(seg, pts_i, mx_i, update, context)
        return
    # -------- end Campaign buttons --------



    logger.info(f"Received callback data: {data}")
    logger.info(f"CATEGORY_MAP: {CATEGORY_MAP}")

    if data == "menu:back_home":
        await show_home_menu(update, context)
        return
        
    if data == "menu:products":
        await show_gender(update , context) ; return
    
    if data == "menu:cart":
        await show_cart(update , context) ; return

    if data == "menu:loyalty":
        await show_loyalty(update, context)
        return

    if data == "loyalty:toggle":
        # prefer points over coupons; enforce mutual exclusivity
        context.user_data.pop("coupon_code", None)
        context.user_data["use_points"] = not bool(context.user_data.get("use_points"))
        await show_cart(update, context)
        return

    # ---- coupon callbacks ----
    if data == "coupon:enter":
        # prompt user to type coupon code (handled in menu_reply_router)
        context.user_data["awaiting"] = "coupon_code"
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🎟 لطفاً کد تخفیف را ارسال کن (مثال: OFF20)\n\nبرای لغو، «❌ انصراف» را بفرست.",
            reply_markup=form_keyboard()
        )
        return

    if data == "coupon:clear":
        context.user_data.pop("coupon_code", None)
        context.user_data["awaiting"] = None
        await q.answer("کد تخفیف حذف شد ✅", show_alert=False)
        await show_cart(update, context)
        return
    # ---- end coupon callbacks ----


    if data == "menu:support":
        await q.edit_message_text(" پشتیبانی: @amirmehdi_84_10", reply_markup=main_menu()) ; return
        
    

    
    # ---- shipping method callbacks ----
    if data == "shipmethod:choose":
        customer = context.user_data.get("customer", {})
        selected = customer.get("shipping_method")
        text = _build_checkout_summary_text(context)
        try:
            await q.edit_message_text(text, reply_markup=shipping_methods_keyboard(selected), parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=shipping_methods_keyboard(selected), parse_mode="Markdown")
        return
    
    if data.startswith("shipmethod:set:"):
        _, _, method = data.split(":", 2)
        if method not in SHIPPING_METHODS:
            await q.answer("روش ارسال نامعتبر است.", show_alert=True)
            return
        context.user_data.setdefault("customer", {})["shipping_method"] = method
        # ✅ اگر سفارش قبلاً ساخته شده، روش ارسال داخل ORDER هم آپدیت شود
        existing = context.user_data.get("current_order_id")
        if existing and STORE.find_order(existing):
            order = STORE.find_order(existing)
            new_customer = dict(order.get("customer", {}))
            new_customer["shipping_method"] = method
            STORE.update_order(existing, shipping_method=method, customer=new_customer)

        text = _build_checkout_summary_text(context)
        # برگشت به خلاصه سفارش با کیبورد اصلی همان مرحله
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚚 انتخاب روش ارسال", callback_data="shipmethod:choose")],
            [InlineKeyboardButton("✏️ ویرایش مشخصات", callback_data="checkout:begin")],
            [InlineKeyboardButton("💳 اقدام به پرداخت نهایی", callback_data="checkout:pay")],
            [InlineKeyboardButton("❌ لغو سفارش", callback_data="checkout:cancel")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")]
        ])
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        await q.answer("روش ارسال ثبت شد ✅", show_alert=False)
        info = SHIPPING_INFO.get(method, "هزینه ارسال بر عهده مشتری است.")
        await q.answer(info, show_alert=True)
        return
    
    if data == "shipmethod:back":
        text = _build_checkout_summary_text(context)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚚 انتخاب روش ارسال", callback_data="shipmethod:choose")],
            [InlineKeyboardButton("✏️ ویرایش مشخصات", callback_data="checkout:begin")],
            [InlineKeyboardButton("💳 اقدام به پرداخت نهایی", callback_data="checkout:pay")],
            [InlineKeyboardButton("❌ لغو سفارش", callback_data="checkout:cancel")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")]
        ])
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return
    # ---- end shipping method callbacks ----
    
# ---- manual payment / receipt callbacks ----
    if data.startswith("receipt:start:"):
        _, _, order_id = data.split(":", 2)
        await receipt_start(update, context, order_id)
        return

    if data == "receipt:cancel":
        await receipt_cancel(update, context)
        return

    if data.startswith("admin:approve:"):
        _, _, order_id = data.split(":", 2)
        await admin_approve(update, context, order_id)
        return

    if data.startswith("admin:reject:"):
        _, _, order_id = data.split(":", 2)
        await admin_reject_start(update, context, order_id)
        return
    
    if data.startswith("admin:shippayer:"):
        _, _, payer, order_id = data.split(":", 3)
        order = STORE.find_order(order_id)
        if not order:
            await q.answer("سفارش پیدا نشد.", show_alert=True)
            return

        prev_payer = (order.get("shipping_payer") or "customer")
        prev_cost = int(order.get("shipping_cost_actual") or 0)

        # اعمال تغییر
        STORE.update_order(order_id, shipping_payer=payer)
        if payer == "customer":
            STORE.update_order(order_id, shipping_cost_actual=0)

        # لاگ
        if payer != prev_payer:
            new_cost = 0 if payer == "customer" else int(STORE.find_order(order_id).get("shipping_cost_actual") or 0)
            _order_log(
                order_id,
                "admin",
                f"تغییر پرداخت‌کننده ارسال: {prev_payer} → {payer} | هزینه ارسال: {prev_cost} → {new_cost}"
            )

        
order2 = STORE.find_order(order_id) or order
kb = _admin_receipt_kb(order2, order_id)
base = q.message.caption or q.message.text or ""
new_text = _with_history_section_md(base, order2, limit=10)
try:
    await q.edit_message_caption(caption=new_text, parse_mode="Markdown", reply_markup=kb)
except Exception:
    try:
        await q.edit_message_text(text=new_text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        try:
            await q.edit_message_reply_markup(reply_markup=kb)
        except Exception:
            pass
        await q.answer("ثبت شد ✅", show_alert=False)
        return

    
    if data.startswith("admin:shipcost:"):
        _, _, order_id = data.split(":", 2)
        await admin_shipcost_start(update, context, order_id)
        return

    # ---- end manual payment / receipt callbacks ----


# **[تغییر]** شروع بخش هندلرهای سبد خرید
    # ------------------ مدیریت سبد خرید ------------------
    cart: List[Dict] = context.user_data.get("cart" , [])
    
    # ... هندلرهای cart:plus و cart:minus بدون تغییر نسبت به اصلاحیه قبلی ...

    if data.startswith("cart:plus:"):
        _, _, index_str = data.split(":", 2)
        try:
            index = int(index_str)
            if 0 <= index < len(cart):
                item = cart[index]
                # ⭐️ (جدید) بررسی موجودی ⭐️
                max_qty = _get_item_inventory(item)
                
                if item["qty"] + 1 <= max_qty:
                    if _update_cart_item_qty(cart, index, 1):
                        await show_cart(update, context)
                    else:
                        await q.answer("❌ خطای افزایش تعداد. (شاید آیتم پیدا نشد)", show_alert=True)
                else:
                    # ⭐️ (جدید) نمایش پیام محدودیت موجودی ⭐️
                    await q.answer(
                        f"❌ متأسفانه موجودی این کالا ({item['name']}) فقط {max_qty} عدد است و شما {item['qty']} عدد در سبد دارید.", 
                        show_alert=True
                    )
            else:
                await q.answer("❌ خطای افزایش تعداد. (آیتم نامعتبر)", show_alert=True)
        except Exception:
            await q.answer("❌ خطای افزایش تعداد.", show_alert=True)
        return
        
    if data.startswith("cart:minus:"):
        _, _, index_str = data.split(":", 2)
        try:
            index = int(index_str)
            # توجه: اگر تعداد صفر شود، آیتم به طور خودکار حذف می‌شود.
            if _update_cart_item_qty(cart, index, -1):
                await show_cart(update, context)
            else:
                await q.answer("❌ خطای کاهش تعداد. (شاید آیتم پیدا نشد)", show_alert=True)
        except Exception:
            await q.answer("❌ خطای کاهش تعداد.", show_alert=True)
        return
    
    if data == "none":
        await q.answer("این دکمه فقط تعداد فعلی/موجودی را نشان می‌دهد." , show_alert=False) ; return 
        
    # ------------------ پایان بخش هندلرهای سبد خرید ------------------
    
    if data.startswith("catalog:gender:"):
        _, _, gender = data.split(":" , 2)
        await show_categories(update , context , gender) ; return
        
    if data.startswith("catalog:category:"):
        parts = data.split(":" , 3)
        _, _, gender , category_safe = parts
        category = CATEGORY_MAP.get(category_safe , category_safe)
        await show_products(update , context , gender , category) ; return
    
    if data.startswith("catalog:select:"):
        _, _, gender, category_safe, product_id = data.split(":", 4)
        category = CATEGORY_MAP.get(category_safe , category_safe)
        product = _find_product(gender , category , product_id)
        if product and "variants" in product:
            await ask_color_and_size(update, context, gender, category, product_id)
        else:
            await ask_size_only(update , context , gender , category , product_id)
        return
        
    
    if data.startswith("catalog:sizeonly:"):
        _, _, gender, category_safe, product_id = data.split(":", 4)
        category = CATEGORY_MAP.get(category_safe , category_safe)
        await ask_size_only(update, context, gender, category, product_id) ; return
        
    
    if data.startswith("catalog:chooseonly:"):
        _, _, gender, category_safe , product_id, size = data.split(":", 5)
        category = CATEGORY_MAP.get(category_safe , category_safe)
        # برای محصولات بدون رنگ، باید قیمت و موجودی را از خود محصول بگیریم
        p = _find_product(gender, category, product_id)
        if not p:
            await q.edit_message_text("محصول پیدا نشد.", reply_markup=main_menu())
            return
            
        context.user_data["pending"] = {
            "gender": gender,
            "category": category,
            "product_id": product_id,
            "name": p["name"],
            "size": size,
            "price": p["price"],
        }
        await show_qty_picker(update, context, size) ; return


    if data.startswith("ship:packed:"):
        _, _, order_id = data.split(":", 2)
        order = STORE.find_order(order_id)
        if not order:
            await q.answer("سفارش پیدا نشد", show_alert=True)
            return

        STORE.update_order(order_id, shipping_status="packed")
        _order_log(order_id, "admin", "بسته‌بندی شد.")

    # پیام به مشتری
        await context.bot.send_message(
            chat_id=int(order["user_chat_id"]),
            text=f"📦 سفارش `{order_id}` بسته‌بندی شد و به‌زودی ارسال می‌شود.",
            parse_mode="Markdown",
            reply_markup=main_menu_reply()
        )

    # ✅ پیام به ادمین
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                f"✅ انجام شد.\n"
                f"سفارش `{order_id}` «بسته‌بندی شد» و پیام برای مشتری ارسال شد."
            ),
            parse_mode="Markdown",
            reply_markup=admin_panel_keyboard(order_id)
        )

        await q.answer("ثبت شد ✅")
        return

    
    
    if data.startswith("ship:delivered:"):
        _, _, order_id = data.split(":", 2)
        order = STORE.find_order(order_id)
        if not order:
            await q.answer("سفارش پیدا نشد", show_alert=True)
            return

        now = datetime.now(timezone.utc)
        # mark delivered + schedule feedback 24h after delivery (configurable)
        upd = {
            "shipping_status": "delivered",
            "delivered_at": now.isoformat().replace("+00:00", "Z"),
        }
        if not order.get("feedback_due_at"):
            upd["feedback_due_at"] = (now + timedelta(hours=FEEDBACK_AFTER_DELIVERY_HOURS)).isoformat().replace("+00:00", "Z")

        STORE.update_order(order_id, **upd)
        _order_log(order_id, "admin", "تحویل شد. زمان‌بندی نظرخواهی فعال شد.")

        # پیام به مشتری (خودمونی)
        try:
            await context.bot.send_message(
                chat_id=int(order["user_chat_id"]),
                text=(
                    f"✅ سفارشت `{order_id}` تحویل شد 😍\n"
                    "اگه مشکلی بود همینجا بهمون بگو، سریع پیگیری می‌کنیم 💛"
                ),
                parse_mode="Markdown",
                reply_markup=main_menu_reply()
            )
        except Exception:
            pass

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ ثبت شد: سفارش `{order_id}` «تحویل شد» و نظرخواهی برای ۲۴ ساعت بعد زمان‌بندی شد.",
            parse_mode="Markdown",
            reply_markup=admin_panel_keyboard(order_id)
        )
        await q.answer("تحویل ثبت شد ✅")
        return

    if data.startswith("ship:need_track:"):
        _, _, order_id = data.split(":", 2)
        context.bot_data["admin_pending_tracking"] = {"order_id": order_id}
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔎 لطفاً کد رهگیری پست را تایپ کنید:"
        )
        await q.answer("منتظر کد رهگیری…", show_alert=False)
        return

    
    if data.startswith("admin:msg:"):
        _, _, order_id = data.split(":", 2)
        context.bot_data["admin_pending_msg"] = {"order_id": order_id}
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✉️ لطفاً پیام را تایپ کنید تا برای مشتری ارسال شود:"
        )

        await q.answer("منتظر پیام…", show_alert=False)
        return

    
    
    if data.startswith("catalog:choose:"):
        parts = data.split(":", 6)
        if len(parts) != 7:
            await q.edit_message_text("داده انتخاب محصول ناقص است.", reply_markup=main_menu())
            return
        _, _, gender, category_safe, product_id, color_index_str, size = parts
        category = CATEGORY_MAP.get(category_safe, category_safe)
    
        p = _find_product(gender, category, product_id)
        if not p or "variants" not in p:
            await q.edit_message_text("محصول پیدا نشد.", reply_markup=main_menu())
            return
    
        try:
            color_index = int(color_index_str)
            colors = list(p["variants"].keys())
            if color_index < 0 or color_index >= len(colors):
                raise ValueError("Invalid color index")
            color = colors[color_index]
        except (ValueError, IndexError):
            await q.edit_message_text("رنگ انتخابی معتبر نیست.", reply_markup=main_menu())
            return
    
        await show_qty_picker_combined(update, context, gender, category, product_id, color, size)
        return
        
       
    # این بخش برای یک روال قدیمی‌تر است که در ask_color_and_size کنونی استفاده نمی‌شود
    if data.startswith("catalog:color:"):
        _, _, gender, category_safe, product_id, color_safe = data.split(":", 5)
        category = CATEGORY_MAP.get(category_safe, category_safe)
    
        p = _find_product(gender, category, product_id)
        if not p or "variants" not in p:
            await q.edit_message_text("محصول پیدا نشد.", reply_markup=main_menu())
            return
    
        color = _unsafe_color(color_safe, p["variants"])
        if not color:
            await q.edit_message_text("رنگ انتخابی معتبر نیست.", reply_markup=main_menu())
            return
    
        await after_color_ask_size(update, context, gender, category, product_id, color)
        return
        
    if data.startswith("catalog:size:"):
        _, _, chosen_size = data.split(":" , 2)
        await show_qty_picker(update, context, chosen_size) ; return
        
    

    if data == "qty:inc":
        pend = context.user_data.get("pending")
        if not pend:
            await q.answer("خطا در انجام عملیات" , show_alert=True)
            return
        if pend["qty"] < pend["available"]:
            pend["qty"] += 1
        else:
            await q.answer("به حداکثر موجودی فروشگاه رسیدی" , show_alert=False)
        
        cap = (
            f"{pend['name']}"
            f"\nرنگ:{pend.get('color') or '—'} | سایز : {pend['size']}"
            f"\nموجودی:{pend['available']}"
            f"\nقیمت واحد : {_ftm_toman(pend['price'])}"
            f"\nقیمت نهایی: {_ftm_toman(pend['price'] * pend['qty'])}"
        )
        try:
            # سعی در ویرایش کپشن (اگر پیام قبلی عکس‌دار باشد)
            await q.edit_message_caption(caption=cap, reply_markup=qty_keyboard(pend["qty"], pend["available"]))
        except Exception:
            # اگر نشد، پیام را به صورت متنی ویرایش کن
            await q.edit_message_text(text=cap, reply_markup=qty_keyboard(pend["qty"], pend["available"]))
        return
    
    
    if data == "qty:dec":
        pend = context.user_data.get("pending")
        if not pend:
            await q.answer("خطا در انجام عملیات" , show_alert=True) ; return
        if pend["qty"] > 1 :
            pend["qty"] -= 1
        else:
            await q.answer("حداقل تعداد 1 است ", show_alert=False)
        cap = (
            f"{pend['name']}"
            f"\nرنگ:{pend.get('color') or '—'} | سایز : {pend['size']}"
            f"\nموجودی:{pend['available']}"
            f"\nقیمت واحد:{_ftm_toman(pend['price'])}"
            f"\nقیمت نهایی:{_ftm_toman(pend['price'] * pend['qty'])}"
        )
        try:
            await q.edit_message_caption(caption=cap, reply_markup=qty_keyboard(pend["qty"], pend["available"]))
        except Exception:
            await q.edit_message_text(text=cap, reply_markup=qty_keyboard(pend["qty"], pend["available"]))
        return
    
    if data == "qty:add":
        pend = context.user_data.get("pending")
        if not pend:
            await q.answer("خطا در انجام عملیات" , show_alert=True) ; return
        item = {
            "product_id": pend["product_id"],
            "gender": pend["gender"],
            "category": pend["category"],
            "name": pend["name"],
            "color": pend.get("color"),
            "size": pend.get("size"),
            "qty": pend["qty"],
            "price": pend["price"],
            "buy_price": int(pend.get("buy_price") or 0),
        }

        cart = context.user_data.setdefault("cart" , [])
        _merge_cart_item(cart , item)
        context.user_data.pop("pending" , None)
# 🔁 Sync persisted cart for recovery campaigns
        try:
            _sync_cart_state(q.message.chat_id, cart)
        except Exception:
            pass

        # 🟢 تغییر: افزودن پیام هشدار (درخواستی کاربر)
        warning_message = (
            "✅ مشتری گرامی، **کالا مورد نظر به سبد خرید شما اضافه شده**.\n\n"
            "⚠️ **لطفاً توجه داشته باشید** که تا پرداخت نهایی، کالا متعلق به شما نمی‌باشد و "
            "اگر مشتری دیگری زودتر پرداخت را انجام دهد، متأسفانه کالا برای ایشان ثبت می‌شود و "
            "گاهی ممکن است همان لحظه موجودی فروشگاه تمام شود.\n\n"
            "با تشکر، مدیریت فروشگاه ..."
        )
        
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text=warning_message,
            parse_mode="Markdown"
        )
        # ----------------------------------------------------

        txt = "می‌تونی به خرید ادامه بدی یا سبد خرید رو مشاهده کنی"
        await q.message.reply_text(
            txt,
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 مشاهده سبد", callback_data="menu:cart")], 
                [InlineKeyboardButton("🛍️ ادامه خرید", callback_data="menu:products")],
            ])
        )
        return

    if data == "qty:noop":
        await q.answer("---" , show_alert=False) ; return
    

    
    if data == "flow:cancel":
        """
        انصراف از جریان انتخاب محصول (سایز/تعداد).
        خواستهٔ شما: پیام انتخاب محصول/تعداد (همین پیام فعلی) پاک شود و سپس صفحهٔ قبلی نمایش داده شود.
        """
        pend = context.user_data.get("pending") or {}
        gender = pend.get("gender")
        category = pend.get("category")

        # پاکسازی وضعیت انتخاب فعلی
        context.user_data.pop("pending", None)
        context.user_data["awaiting"] = None

        # ✅ پاک کردن پیام فعلی (پیام محصول/انتخاب سایز/تعداد)
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.callback_query.message.message_id)
        except Exception:
            pass

        # برگشت به مرحله مناسب
        if gender and category:
            await show_products(update, context, gender, category)
        else:
            await show_cart(update, context)
        return


    # checkout:begin توسط ConversationHandler در entry_points مدیریت می‌شود.
    # اگر این کد اجرا شود، یعنی ConversationHandler موفق به آغاز نشده است.
    if data == "checkout:begin":
        await q.answer("❌ خطا در اجرای فرم. لطفاً یک بار دیگر تلاش کنید.", show_alert=True)
        await show_cart(update, context)
        return
    

    if data == "checkout:pay":
        await checkout_pay(update , context) ; return
    
    # نیاز به هندلر برای لغو سفارش
    if data == "checkout:cancel":
        context.user_data.pop("cart" , None)
        try:
            _clear_cart_state(update.effective_chat.id)
        except Exception:
            pass
        context.user_data.pop("customer" , None)
        context.user_data.pop("pending" , None)
        context.user_data['awaiting'] = None
        await q.edit_message_text("❌ سفارش لغو شد. سبد خرید خالی شد.", reply_markup=main_menu())
        # ✅ بازگرداندن منوی اصلی (Reply Keyboard)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="از منوی پایین می‌تونی ادامه بدی.",
            reply_markup=main_menu_reply(),
        )
        return

    if data.startswith("checkout:verify:"):
        _, _, order_id = data.split(":", 2)
        await checkout_verify(update, context, order_id); return
    

    await q.edit_message_text("❌ گزینه نامعتبر.", reply_markup=main_menu())


#        /start و اجرای برنامه
# ساخت اپلیکیشن PTB
application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("admin", admin_register))
application.add_handler(CommandHandler("coupon", admin_coupon))
application.add_handler(CommandHandler("myid", my_id))
application.add_handler(CommandHandler("campaign", admin_campaign))
application.add_handler(CallbackQueryHandler(feedback_callback, pattern=r"^fb:"))
application.add_handler(CommandHandler("dashboard", admin_dashboard))
application.add_handler(CommandHandler("sales", admin_dashboard))
application.add_handler(CommandHandler("segments", admin_segments))

# Conversation Handler برای فرم مشتری
conv_handler = ConversationHandler(
    # ⭐️ (اصلاح) entry_points: شروع مکالمه با زدن دکمه "ثبت سفارش و پرداخت" یا "ویرایش مشخصات" ⭐️
    entry_points=[CallbackQueryHandler(begin_customer_form, pattern=r"^checkout:begin$")],
    states={
        CUSTOMER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],
        CUSTOMER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text), MessageHandler(filters.CONTACT, on_contact)],
        CUSTOMER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],
        CUSTOMER_POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],
    },
    # ⭐️ fallbacks: بازگشت به سبد خرید در صورت انصراف ⭐️
    fallbacks=[CallbackQueryHandler(menu_router, pattern=r"^flow:cancel$")]
)
application.add_handler(conv_handler)


# هندلرهای اصلی (بعد از Conversation Handler)
application.add_handler(CallbackQueryHandler(menu_router))

# Receipt photo handler (user uploads)
application.add_handler(MessageHandler(filters.PHOTO, on_receipt_photo))

# Admin text reply handler (when admin writes a reason for rejection)
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text_reply),group=1)

# هندلر برای Reply Keyboard (منوهای پایین صفحه)
menu_reply_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND,
    menu_reply_router
)
application.add_handler(menu_reply_handler)


# اجرای event loop در پس‌زمینه
LOOP = asyncio.new_event_loop()
def _run_loop_forever():
    asyncio.set_event_loop(LOOP)
    LOOP.run_forever()
threading.Thread(target=_run_loop_forever, daemon=True).start()

# ست کردن webhook
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
WEBHOOK_URL = f"https://{RENDER_HOST}/webhook/{BOT_TOKEN}"

async def _ptb_init_and_webhook():
    try:
        await application.initialize()
        await application.start()
        # ⏱ Recovery campaigns periodic job (every 30 min; first run after 5 min)
        try:
            application.job_queue.run_repeating(recovery_campaigns_job, interval=1800, first=300)
            # ⏱ Order followup & feedback scanner
            try:
                application.job_queue.run_repeating(auto_messages_job, interval=AUTO_MSG_SCAN_INTERVAL_SEC, first=120)
                logger.info("Auto messages job scheduled (interval=%ss).", AUTO_MSG_SCAN_INTERVAL_SEC)
            except Exception as e:
                logger.error("Failed to schedule auto_messages_job: %s", e)
            logger.info("Recovery campaigns job scheduled (interval=1800s).")
        except Exception as e:
            logger.error("Failed to schedule recovery campaigns job: %s", e)

        await application.bot.set_webhook(
            url=WEBHOOK_URL,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
        logger.info(f"Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        logger.error("Failed to set webhook: %s", e)
        
# اجرای تنظیمات PTB در لوپ اصلی
asyncio.run_coroutine_threadsafe(_ptb_init_and_webhook(), LOOP)

# Flask app
flask_app = Flask(__name__)

@flask_app.route("/", methods=["GET", "HEAD"])
def health():
    return "Bot is running", 200

@flask_app.post(f"/webhook/{BOT_TOKEN}")
def telegram_webhook():
    try:
        data = request.get_json(force=True)
        # استفاده از application.update_queue.put_nowait برای فرستادن آپدیت به لوپ PTB
        # تا از خطا در thread اصلی وب‌هو‌ک جلوگیری شود.
        logger.info("Received Update JSON: %s", data)
        update = Update.de_json(data, application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), LOOP) 
        return "OK", 200
    except Exception as e:
        logger.exception("webhook handler error: %s", e)
        return "ERROR", 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    # اگر در محیط رندر هستید، فلش اپ را با هاست 0.0.0.0 و پورت مشخص شده اجرا کنید
    # در غیر این صورت، می‌توانید برای تست لوکال از حالت debug=True استفاده کنید.
    flask_app.run(host="0.0.0.0", port=port, debug=False)
