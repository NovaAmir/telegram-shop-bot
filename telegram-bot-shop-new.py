from telegram import (Update , InlineKeyboardButton , InlineKeyboardMarkup , ReplyKeyboardMarkup , ReplyKeyboardRemove, InputMediaPhoto)
from telegram.ext import (ApplicationBuilder , CommandHandler , ContextTypes , CallbackQueryHandler , Application , MessageHandler , filters , ConversationHandler)
from telegram import MessageEntity
from telegram.constants import MessageEntityType

# --- One-tap copy support (Telegram copy button) ---
try:
    from telegram import CopyTextButton
    _HAS_COPY_BUTTON = True
except Exception:
    _HAS_COPY_BUTTON = False
# ---------------------------------------------------

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
from html import escape
import re



def _utf16_len(s: str) -> int:
    # Telegram offsets/lengths are in UTF-16 code units
    return len(s.encode("utf-16-le")) // 2

CUSTOMER_NAME, CUSTOMER_PHONE, CUSTOMER_ADDRESS, CUSTOMER_POSTAL, CUSTOMER_SHIPPING = range(5)

logging.basicConfig(level=logging.INFO,format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN","").strip()
if not BOT_TOKEN :
    logger.warning("⚠️ متغییر محیطی BOT_TOKEN تنظیم نشده است . قبل از اجرا آن را ست کنید .")

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID" , "").strip() or None

# Manual card payment settings
CARDS = [{"holder":"امیرمهدی پیری" , "number": "6104338705632277"} , {"holder":"امیرمهدی پیری" , "number": "5859831211429799"}]
ADMIN_USERNAME = "@Amirmehdi_84_11"

# ------------------ Admin access control ------------------
# فقط یوزرهایی که در این لیست هستند اجازه دارند /admin بزنند و به قابلیت‌های ادمین دسترسی داشته باشند.
# پیش‌فرض از مقدار ADMIN_USERNAME استفاده می‌شود. برای چند ادمین می‌توانید از env استفاده کنید:
#   ADMIN_USERNAMES="Amirmehdi_84_11,OtherUser"
#   ADMIN_USER_IDS="123456789,987654321"
# برای چند چت ادمین جهت دریافت رسید/هشدار هم می‌توانید env بدهید:
#   ADMIN_CHAT_IDS="11111111,22222222"
# اما ساده‌ترین روش این است که هر ادمین یک‌بار در چت خصوصی خودش /admin بزند.

def _normalize_username(u: Optional[str]) -> str:
    u = (u or "").strip()
    if u.startswith("@"):
        u = u[1:]
    return u.lower()

_allowed_admin_usernames = set()
if ADMIN_USERNAME:
    _allowed_admin_usernames.add(_normalize_username(ADMIN_USERNAME))

_env_admin_usernames = os.getenv("ADMIN_USERNAMES", "").strip()
if _env_admin_usernames:
    for _u in _env_admin_usernames.split(","):
        _u = _normalize_username(_u)
        if _u:
            _allowed_admin_usernames.add(_u)

_allowed_admin_user_ids = set()
_env_admin_user_ids = os.getenv("ADMIN_USER_IDS", "").strip()
if _env_admin_user_ids:
    for _x in _env_admin_user_ids.split(","):
        _x = _x.strip()
        if not _x:
            continue
        try:
            _allowed_admin_user_ids.add(int(_x))
        except Exception:
            pass

def _is_admin_user(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    if user.id in _allowed_admin_user_ids:
        return True
    uname = _normalize_username(getattr(user, "username", None))
    return bool(uname and uname in _allowed_admin_usernames)

def _is_admin_user_from_message(msg) -> bool:
    user = getattr(msg, "from_user", None)
    if not user:
        return False
    if user.id in _allowed_admin_user_ids:
        return True
    uname = _normalize_username(getattr(user, "username", None))
    return bool(uname and uname in _allowed_admin_usernames)


def _is_admin_activated(update: Update) -> bool:
    if not _is_admin_user(update):
        return False
    try:
        chat_id = int(update.effective_chat.id)
    except Exception:
        return False
    return chat_id in [int(x) for x in _get_admin_chat_ids()]


def _is_admin_activated_from_message(msg) -> bool:
    if not _is_admin_user_from_message(msg):
        return False
    try:
        chat_id = int(msg.chat.id)
    except Exception:
        return False
    return chat_id in [int(x) for x in _get_admin_chat_ids()]


# ----------------------------------------------------------



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

# If admin chat id not set via env, try loading from storage
if not ADMIN_CHAT_ID:
    try:
        ADMIN_CHAT_ID = STORE.data.get("admin_chat_id") or None
        # پشتیبانی از چند ادمین (لیست)
        if not ADMIN_CHAT_ID:
            _ids = STORE.data.get("admin_chat_ids") or []
            if isinstance(_ids, list) and _ids:
                ADMIN_CHAT_ID = str(_ids[0])
    except Exception:
        ADMIN_CHAT_ID = None




# ------------------ Admin chat receivers (multi-admin) ------------------
def _get_admin_chat_ids() -> List[int]:
    """
    لیست چت‌های ادمین که باید رسید/هشدارها به آنها ارسال شود.
    منابع:
      - env ADMIN_CHAT_ID (تک مقدار)
      - env ADMIN_CHAT_IDS (چند مقدار، جداشده با ,)
      - storage admin_chat_id (قدیمی)
      - storage admin_chat_ids (جدید: لیست)
    """
    ids = set()

    # env (multi)
    env_multi = os.getenv("ADMIN_CHAT_IDS", "").strip()
    if env_multi:
        for part in env_multi.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.add(int(part))
            except Exception:
                pass

    # storage
    try:
        single = STORE.data.get("admin_chat_id")
        if single:
            try:
                ids.add(int(single))
            except Exception:
                pass
        lst = STORE.data.get("admin_chat_ids") or []
        if isinstance(lst, list):
            for x in lst:
                try:
                    ids.add(int(x))
                except Exception:
                    pass
    except Exception:
        pass

    return sorted(ids)

def _has_admin_chat() -> bool:
    return len(_get_admin_chat_ids()) > 0

async def _broadcast_admin_message(context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs) -> None:
    for cid in _get_admin_chat_ids():
        try:
            await context.bot.send_message(chat_id=cid, text=text, **kwargs)
        except Exception as e:
            logger.error("Failed to notify admin chat %s: %s", cid, e)

async def _broadcast_admin_photo(context: ContextTypes.DEFAULT_TYPE, photo, **kwargs) -> None:
    for cid in _get_admin_chat_ids():
        try:
            await context.bot.send_photo(chat_id=cid, photo=photo, **kwargs)
        except Exception as e:
            logger.error("Failed to send photo to admin chat %s: %s", cid, e)

# ------------------------------------------------------------------------

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
                     "sizes" : {"40":3 , "41":1 , "42":4 , "43":3 ,  "44":2}
                    },
                 "سفید" : {
                     "photo" : "https://res.cloudinary.com/dkzhxotve/image/upload/v1766765777/men-shoe-running-hobi-gs8226-white_omgvwk.webp" ,
                     "price" : 1_300_000 ,
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
                     "sizes" : {"39":3 , "40":5 , "42":2 , "43":1}
                 },
                 "سفید" : {
                     "photo" : "https://res.cloudinary.com/dkzhxotve/image/upload/v1766765980/men-shoe-Air-Force-1-WH-1990_j4fbuc.webp" ,
                     "price" : 650_000 , 
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
             "sizes":{"L":4 , "XL":5 , "XXL":3}
             },
             {"id":"men-shirt-SB-SS-4513" , 
              "name":"پیراهن آستین بلند مردانه مدل SB-SS-4513" , 
              "thumbnail":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766766299/men-shirt-SB-SS-4513_rrqpuv.webp" , 
              "price": 2_500_000 ,
              "sizes":{"L":3 , "XL":4 , "XXL":2}
              }
        ],
        "تی شرت" : [
            {"id":"men-Tshirt-model TS63 B" , 
             "name":"تی شرت اورسایز مردانه نوزده نودیک مدل TS63 B" , 
             "thumbnail":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766766391/men-Tshirt-model_TS63_B_aleauo.webp" , 
             "price" : 900_000 ,
             "sizes":{"L":3 , "XL":4 , "XXL":4}
             },
             {"id":"men-Tshirt-model TS1962 B" , 
              "name":"تی شرت ورزشی مردانه نوزده نودیک مدل TS1962 B" ,
              "thumbnail":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766766520/men-Tshirt-model_TS1962_B_bwvbs0.webp" , 
              "variants":{
                  "مشکی":{
                      "photo":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766766705/men-Tshirt-model_TS1962_Black_2_yohqzw.webp" , 
                      "price":550_000 , 
                      "sizes":{"L":2 , "XL":2 , "XXL":2}

                  },
                  "سفید":{
                      "photo":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766766876/men-Tshirt-model_TS63_white_binvpk.webp" , 
                      "price":550_000 , 
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
             "sizes" : {"40":2 , "41":0 , "42":3 , "43":2 , "44":1}
             },
             {"id":"women-shoe-3Fashion M.D" , 
              "name":"کفش روزمره زنانه مدل Fashion سه چسب M.D" , 
              "thumbnail": "https://res.cloudinary.com/dkzhxotve/image/upload/v1766767092/women-shoe-3Fashion_M.D_so7q56.webp" , 
              "variants":{
                  "مشکی":{
                      "photo":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766767290/women-shoe-charm-B_zqdqlh.webp" , 
                      "price":520_000 , 
                      "sizes":{"40":3 , "41":2 , "43":3}
                  },
                  "سفید":{
                      "photo":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766767092/women-shoe-3Fashion_M.D_so7q56.webp" , 
                      "price":540_000 , 
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
              "sizes":{"44":6 , "46":5 , "50":3 , "52":4}
              } , 
            {"id":"women-pants-rita-m-kerm" , # شناسه کوتاه شده برای جلوگیری از Button_data_invalid
             "name":"شلوار زنانه مدل ریتا مازراتی راسته رنگ کرم روشن" ,
             "thumbnail":"https://res.cloudinary.com/dkzhxotve/image/upload/v1766767424/20251112222400589692652_pwel0m.jpg" , 
             "price":560_000 , 
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

ORDER_STATUS_FA = {
    "awaiting_receipt": "⏳ در انتظار ارسال رسید",
    "receipt_submitted": "📨 رسید ارسال شد",
    "receipt_rejected": "❌ رسید رد شد",
    "paid": "💳 درگاه پرداخت",
    "paid_confirmed": "✅ پرداخت تایید شد",
    "fulfilled": "📦 تکمیل و ارسال شده",
}





#     منوها

def main_menu_reply(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """ساخت کیبورد Reply برای منو اصلی (پایین صفحه)"""
    keyboard = [
        ["🛍️ لیست محصولات", "🧺 سبد خرید"],
        ["📦 وضعیت سفارش من"],
        ["🆘 پشتیبانی"],
    ]
    if is_admin:
        keyboard.append(["📊 داشبورد فروش"])
        keyboard.append(["📋 سفارش‌های آماده ارسال"])
        keyboard.append(["🚚 سفارش‌های ارسال شده"])
        keyboard.append(["🚪 خروج از ادمین"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def form_keyboard() -> ReplyKeyboardMarkup:
    """کیبورد ساده مخصوص فرم (فقط انصراف). منوی اصلی را موقتاً جایگزین می‌کند."""
    keyboard = [["❌ انصراف"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


# **[تغییر]** تعریف تابع main_menu برای استفاده از Inline Keyboard در Callback Query ها
def main_menu() -> InlineKeyboardMarkup:
    """ساخت کیبورد Inline برای منو اصلی در محیط Callback (بعد از اتمام کار)"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ لیست محصولات" , callback_data="menu:products")] ,
        [InlineKeyboardButton("🧺 سبد خرید" , callback_data="menu:cart")],
        [InlineKeyboardButton("🆘 پشتیبانی" , callback_data="menu:support")]
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
        [InlineKeyboardButton("✉️ پیام به مشتری", callback_data=f"admin:msg:{order_id}")],
    ])




# ------------------ Admin UI (single message) ------------------
def _admin_ui_key(chat_id: int) -> str:
    return f"admin_ui_msg:{int(chat_id)}"

async def admin_ui_send_or_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    text: str,
    reply_markup=None,
    parse_mode: Optional[str] = None,
    disable_web_page_preview: bool = True,
):
    """یک پیام واحد برای کنترل سفارش‌ها در چت ادمین نگه می‌دارد تا شلوغ نشود."""
    chat_id = update.effective_chat.id
    key = _admin_ui_key(chat_id)
    msg_id = context.bot_data.get(key)

    # اگر از callback آمده، ترجیحاً همان پیام را edit کن
    try:
        if update.callback_query and update.callback_query.message:
            msg_id = update.callback_query.message.message_id
            context.bot_data[key] = msg_id
    except Exception:
        pass

    if update.message and not update.callback_query:
        try:
            await update.message.delete()
        except Exception:
            pass

        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
        context.bot_data[key] = sent.message_id
        return

    if msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=int(msg_id),
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
            return
        except Exception:
            # اگر ادیت ممکن نبود، پیام جدید بفرست
            pass

    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
    )
    context.bot_data[key] = sent.message_id


def _admin_ready_orders() -> List[dict]:
    """سفارش‌هایی که پرداخت‌شان قطعی شده و هنوز به پست تحویل داده نشده‌اند (آماده بسته‌بندی/ارسال)."""
    orders = STORE.data.get("orders", []) or []

    def _score(o: dict) -> str:
        return o.get("confirmed_at") or o.get("paid_at") or o.get("created_at") or ""

    res: List[dict] = []
    for o in orders:
        st = o.get("status")
        ship = o.get("shipping_status") or "pending"
        # آماده ارسال = پرداخت شده (آنلاین یا تایید دستی) + هنوز shipped/delivered نشده
        if st in ("paid", "paid_confirmed") and ship in ("pending", "packed"):
            res.append(o)

    res.sort(key=_score, reverse=True)
    return res


def _order_fulfilled_dt_local(order: dict) -> Optional[datetime]:
    """زمان ارسال (ثبت کد رهگیری) را به زمان محلی برمی‌گرداند."""
    dt = _parse_dt_utc_z(order.get("fulfilled_at"))
    if not dt:
        return None
    try:
        return dt.astimezone(LOCAL_TZ)
    except Exception:
        return None


def _admin_shipped_orders() -> List[dict]:
    """همه سفارش‌هایی که «ارسال شده‌اند» (کد رهگیری ثبت شده) — شامل shipped و delivered."""
    orders = STORE.data.get("orders", []) or []

    def _score(o: dict) -> str:
        # fulfilled_at وقتی کد رهگیری ثبت می‌شود ذخیره می‌شود
        return o.get("fulfilled_at") or o.get("confirmed_at") or o.get("paid_at") or o.get("created_at") or ""

    res: List[dict] = []
    for o in orders:
        ship = o.get("shipping_status") or "pending"
        if ship in ("shipped", "delivered"):
            res.append(o)

    res.sort(key=_score, reverse=True)
    return res


def _admin_shipped_orders_by_date(target_date) -> List[dict]:
    """سفارش‌های ارسال‌شده در تاریخ مشخص (بر اساس زمان محلی). target_date از نوع date است."""
    orders = _admin_shipped_orders()

    res: List[dict] = []
    for o in orders:
        dt_local = _order_fulfilled_dt_local(o)
        if dt_local and dt_local.date() == target_date:
            res.append(o)

    # اگر fulfilled_at برای سفارش‌های قدیمی نبود، چیزی برنمی‌گردد. (می‌توانید بعداً مهاجرت بزنید)
    res.sort(key=lambda o: (o.get("fulfilled_at") or ""), reverse=True)
    return res


def _jalali_label_from_greg_date(d) -> str:
    try:
        jd = jdatetime.date.fromgregorian(date=d)
        return jd.strftime("%Y/%m/%d")
    except Exception:
        return d.strftime("%Y-%m-%d")


def _parse_admin_date_to_greg(date_text: str):
    """ورودی تاریخ از ادمین را به تاریخ میلادی (date) تبدیل می‌کند.

    ورودی‌های قابل قبول (با اعداد انگلیسی/فارسی/عربی):
      - 1404/03/06 یا 1404/3/6  (شمسی)
      - 1404-03-06 یا 1404-3-6  (شمسی)
      - 2026-01-04 یا 2026/1/4  (میلادی)
    جداکننده‌های رایج / و - پشتیبانی می‌شود (حتی برخی شکل‌های یونیکد).
    """
    if not date_text:
        return None

    s = _to_english_digits(date_text).strip()
    # نرمال‌سازی جداکننده‌ها و حذف فاصله‌ها
    s = re.sub(r"\s+", "", s)
    s = (
        s.replace("／", "/")
         .replace("⁄", "/")
         .replace("∕", "/")
         .replace("－", "-")
         .replace("−", "-")
         .replace("–", "-")
         .replace("—", "-")
         .replace(".", "/")
    )

    m = re.match(r"^(\d{4})[\-/](\d{1,2})[\-/](\d{1,2})$", s)
    if not m:
        return None

    try:
        y = int(m.group(1))
        mo = int(m.group(2))
        da = int(m.group(3))
    except Exception:
        return None

    # چک‌های اولیه
    if not (1 <= mo <= 12):
        return None
    if not (1 <= da <= 31):
        return None

    # اگر شمسی بود
    if 1300 <= y <= 1500:
        try:
            jd = jdatetime.date(y, mo, da)
            return jd.togregorian()
        except Exception:
            return None

    # در غیر این صورت میلادی
    try:
        return datetime(y, mo, da).date()
    except Exception:
        return None

def admin_shipped_date_picker_keyboard(days: int = 10) -> InlineKeyboardMarkup:
    """انتخاب تاریخ برای مشاهده سفارش‌های ارسال‌شده."""
    today = datetime.now(timezone.utc).astimezone(LOCAL_TZ).date()
    buttons = []
    row = []
    for i in range(days):
        d = today - timedelta(days=i)
        lbl = _jalali_label_from_greg_date(d)
        row.append(InlineKeyboardButton(f"📅 {lbl}", callback_data=f"admin:shipped:date:{d.isoformat()}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    # سفارش‌های ارسال‌شده‌ای که تاریخ ارسال (fulfilled_at) ندارند
    try:
        missing = [o for o in _admin_shipped_orders() if not o.get("fulfilled_at")]
    except Exception:
        missing = []
    if missing:
        buttons.append([InlineKeyboardButton(f"❓ بدون تاریخ ({len(missing)})", callback_data="admin:shipped:date:unknown")])


    buttons += [
        [InlineKeyboardButton("📅 وارد کردن تاریخ", callback_data="admin:shipped:enter_date")],
        [InlineKeyboardButton("📋 آماده ارسال", callback_data="admin:queue")],
        [InlineKeyboardButton("📊 داشبورد فروش", callback_data="admin:dashboard")],
    ]
    return InlineKeyboardMarkup(buttons)


def admin_shipped_list_keyboard(orders: List[dict], date_iso: str, limit: int = 20) -> InlineKeyboardMarkup:
    """کیبورد لیست سفارش‌های ارسال‌شده برای یک روز."""
    btns = []
    for o in orders[:limit]:
        oid = o.get("order_id")
        if not oid:
            continue
        name = (o.get("customer") or {}).get("name") or "—"
        track = o.get("tracking_code") or "—"
        total = _ftm_toman(o.get("total", 0))
        btns.append([InlineKeyboardButton(f"🚚 {oid} | {name} | {track} | {total}", callback_data=f"admin:open:shipped:{oid}")])

    controls = [
        [InlineKeyboardButton("⬅️ انتخاب تاریخ دیگر", callback_data="admin:shipped")],
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"admin:shipped:date:{date_iso}")],
        [InlineKeyboardButton("📋 آماده ارسال", callback_data="admin:queue")],
        [InlineKeyboardButton("📊 داشبورد فروش", callback_data="admin:dashboard")],
    ]
    return InlineKeyboardMarkup(btns + controls)

# (سازگاری با نسخه‌های قبلی)# (سازگاری با نسخه‌های قبلی) — همان «آماده ارسال»
def _admin_queue_orders() -> List[dict]:
    return _admin_ready_orders()



def admin_queue_keyboard(orders: List[dict], limit: int = 15) -> InlineKeyboardMarkup:
    """کیبورد لیست «آماده ارسال» (قبل از تحویل پست)."""
    btns = []
    for o in orders[:limit]:
        oid = o.get("order_id")
        if not oid:
            continue
        name = (o.get("customer") or {}).get("name") or "—"
        ship = SHIP_STATUS_FA.get(o.get("shipping_status") or "pending", "—")
        total = _ftm_toman(o.get("total", 0))
        btns.append([InlineKeyboardButton(f"🧾 {oid} | {name} | {ship} | {total}", callback_data=f"admin:open:ready:{oid}")])
    controls = [
        [InlineKeyboardButton("🔄 بروزرسانی لیست", callback_data="admin:queue")],
        [InlineKeyboardButton("🚚 سفارش‌های ارسال شده", callback_data="admin:shipped")],
        [InlineKeyboardButton("📊 داشبورد فروش", callback_data="admin:dashboard")],
    ]
    return InlineKeyboardMarkup(btns + controls)


def admin_shipped_keyboard(orders: List[dict], limit: int = 15) -> InlineKeyboardMarkup:
    """کیبورد لیست «ارسال شده» (دارای کد رهگیری، هنوز delivered نشده)."""
    btns = []
    for o in orders[:limit]:
        oid = o.get("order_id")
        if not oid:
            continue
        name = (o.get("customer") or {}).get("name") or "—"
        ship = SHIP_STATUS_FA.get(o.get("shipping_status") or "pending", "—")
        track = o.get("tracking_code") or "—"
        total = _ftm_toman(o.get("total", 0))
        btns.append([InlineKeyboardButton(f"🚚 {oid} | {name} | {track} | {total}", callback_data=f"admin:open:shipped:{oid}")])
    controls = [
        [InlineKeyboardButton("🔄 بروزرسانی لیست", callback_data="admin:shipped")],
        [InlineKeyboardButton("📋 آماده ارسال", callback_data="admin:queue")],
        [InlineKeyboardButton("📊 داشبورد فروش", callback_data="admin:dashboard")],
    ]
    return InlineKeyboardMarkup(btns + controls)



def admin_order_keyboard(order_id: str, back_to: str = "admin:queue") -> InlineKeyboardMarkup:
    kb = admin_panel_keyboard(order_id).inline_keyboard
    rows = [list(r) for r in kb]
    rows = [[InlineKeyboardButton("⬅️ برگشت به لیست سفارش‌ها", callback_data=back_to)]] + rows
    return InlineKeyboardMarkup(rows)




async def admin_ack_status(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    admin_chat_id: int,
    base_message_id: Optional[int],
    ok: bool,
    action: str,
    customer_msg_id: Optional[int] = None,
    err: Optional[str] = None,
) -> None:
    """نمایش وضعیت ارسال پیام به مشتری در چت ادمین (Reply زیر پنل).

    توجه: تلگرام برای بات‌ها رسید «تحویل به کاربر/seen» نمی‌دهد؛ این وضعیت یعنی
    ارسال به سرورهای تلگرام موفق بوده یا با خطا مواجه شده (مثلاً کاربر بات را بلاک کرده).
    """
    # پاک کردن پیام وضعیت قبلی (اگر وجود داشت) تا چت شلوغ نشود
    last_key = f"admin_last_ack_msg:{int(admin_chat_id)}"
    last_id = context.bot_data.get(last_key)
    if last_id:
        try:
            await context.bot.delete_message(chat_id=admin_chat_id, message_id=int(last_id))
        except Exception:
            pass

    if ok:
        txt = f"✅ {action}: پیام به مشتری با موفقیت ارسال شد (تحویل تلگرام)."
        if customer_msg_id is not None:
            txt += f"\n🆔 msg_id: {customer_msg_id}"
    else:
        txt = f"❌ {action}: ارسال پیام به مشتری ناموفق بود."
        if err:
            # کوتاه و قابل فهم
            txt += f"\nℹ️ خطا: {str(err)[:120]}"

    kwargs = {
        "chat_id": admin_chat_id,
        "text": txt,
        "disable_web_page_preview": True,
    }
    if base_message_id:
        kwargs["reply_to_message_id"] = int(base_message_id)

    try:
        sent = await context.bot.send_message(**kwargs)
        context.bot_data[last_key] = sent.message_id
    except Exception:
        pass


async def admin_queue_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
    if not _is_admin_activated(update):
        if update.message:
            await update.message.reply_text("⛔️ دسترسی ندارید.", reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))
        elif update.callback_query:
            await update.callback_query.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return

    orders = _admin_ready_orders()
    if not orders:
        await admin_ui_send_or_edit(
            update,
            context,
            text="📋 *سفارشِ آماده‌ای برای ارسال ندارید.*\n\n(درگاه پرداخت یا تاییدشده توسط ادمین)",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 بروزرسانی لیست", callback_data="admin:queue")],
                [InlineKeyboardButton("🚚 سفارش‌های ارسال شده", callback_data="admin:shipped")],
                [InlineKeyboardButton("📊 داشبورد فروش", callback_data="admin:dashboard")],
            ]),
        )
        return

    await admin_ui_send_or_edit(
        update,
        context,
        text=f"📋 *سفارش‌های آماده ارسال*\nتعداد: {len(orders)}\n\nروی هر سفارش بزنید تا گزینه‌های مدیریت نمایش داده شود.",
        reply_markup=admin_queue_keyboard(orders),
    )



async def admin_shipped_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """صفحه انتخاب تاریخ برای مشاهده سفارش‌های «ارسال شده»."""
    if update.callback_query:
        await update.callback_query.answer()
    if not _is_admin_activated(update):
        if update.message:
            await update.message.reply_text("⛔️ دسترسی ندارید.", reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))
        elif update.callback_query:
            await update.callback_query.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return

    shipped_all = _admin_shipped_orders()
    await admin_ui_send_or_edit(
        update,
        context,
        text=f"""🚚 *سفارش‌های ارسال شده*
کل سفارش‌های ارسال‌شده: {len(shipped_all)}

یک تاریخ را انتخاب کنید تا سفارش‌های ارسال‌شده در همان روز نمایش داده شود.""",
        reply_markup=admin_shipped_date_picker_keyboard(),
        parse_mode="Markdown",
    )


async def admin_shipped_show_date(update: Update, context: ContextTypes.DEFAULT_TYPE, date_iso: str) -> None:
    """نمایش سفارش‌های ارسال‌شده در یک روز مشخص."""
    if update.callback_query:
        await update.callback_query.answer()

    if not _is_admin_activated(update):
        if update.callback_query:
            await update.callback_query.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return

    # special: shipped orders with missing fulfilled_at
    if (date_iso or "").strip().lower() == "unknown":
        try:
            orders = [o for o in _admin_shipped_orders() if not o.get("fulfilled_at")]
        except Exception:
            orders = []
        header = "📅 تاریخ: بدون تاریخ"

        if not orders:
            await admin_ui_send_or_edit(
                update,
                context,
                text=f"🚚 *سفارش ارسال‌شده‌ای در بخش «بدون تاریخ» ندارید.*\n{header}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ انتخاب تاریخ دیگر", callback_data="admin:shipped")],
                    [InlineKeyboardButton("📋 آماده ارسال", callback_data="admin:queue")],
                    [InlineKeyboardButton("📊 داشبورد فروش", callback_data="admin:dashboard")],
                ]),
                parse_mode="Markdown",
            )
            return

        # remember view
        try:
            _m = context.bot_data.setdefault("admin_current_shipped_back", {})
            _m[int(update.effective_chat.id)] = "admin:shipped:date:unknown"
        except Exception:
            pass

        await admin_ui_send_or_edit(
            update,
            context,
            text=f"🚚 *سفارش‌های ارسال شده*\n{header}\nتعداد: {len(orders)}\n\nروی هر سفارش بزنید تا گزینه‌های مدیریت نمایش داده شود.",
            reply_markup=admin_shipped_list_keyboard(orders, "unknown"),
            parse_mode="Markdown",
        )
        return


    try:
        target_date = datetime.fromisoformat(date_iso).date()
    except Exception:
        await admin_ui_send_or_edit(
            update,
            context,
            text="❌ تاریخ نامعتبر است. لطفاً دوباره تلاش کنید.",
            reply_markup=admin_shipped_date_picker_keyboard(),
            parse_mode="Markdown",
        )
        return

    # remember current shipped view for the back button inside order page
    try:
        _m = context.bot_data.setdefault("admin_current_shipped_back", {})
        _m[int(update.effective_chat.id)] = f"admin:shipped:date:{date_iso}"
    except Exception:
        pass

    orders = _admin_shipped_orders_by_date(target_date)

    # labels for header
    jalali = _jalali_label_from_greg_date(target_date)
    greg = target_date.strftime("%Y-%m-%d")
    header = f"📅 تاریخ: {jalali} ({greg})"

    if not orders:
        await admin_ui_send_or_edit(
            update,
            context,
            text=f"""🚚 *سفارش ارسال‌شده‌ای برای این تاریخ ندارید.*
{header}""",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ انتخاب تاریخ دیگر", callback_data="admin:shipped")],
                [InlineKeyboardButton("📋 آماده ارسال", callback_data="admin:queue")],
                [InlineKeyboardButton("📊 داشبورد فروش", callback_data="admin:dashboard")],
            ]),
            parse_mode="Markdown",
        )
        return

    await admin_ui_send_or_edit(
        update,
        context,
        text=f"""🚚 *سفارش‌های ارسال شده*
{header}
تعداد: {len(orders)}

روی هر سفارش بزنید تا گزینه‌های مدیریت نمایش داده شود.""",
        reply_markup=admin_shipped_list_keyboard(orders, date_iso),
        parse_mode="Markdown",
    )

def _admin_order_summary(order: dict) -> str:
    oid = order.get("order_id")
    cust = order.get("customer") or {}
    ship_method = (cust.get("shipping_method") or "").strip()
    ship_method_label = SHIPPING_METHODS.get(ship_method, {}).get("label") if ship_method else None
    pay_label = PAY_STATUS_FA.get(order.get("status") or "", order.get("status") or "—")
    ship_label = SHIP_STATUS_FA.get(order.get("shipping_status") or "pending", "—")
    track = order.get("tracking_code") or "ثبت نشده"
    items = order.get("items") or []
    lines = [f"🧾 *سفارش* {oid}",
             f"👤 نام: {cust.get('name') or '—'}",
             f"📞 موبایل: {cust.get('phone') or '—'}",
             f"📍 آدرس: {cust.get('address') or '—'}",
             f"🏷 کدپستی: {cust.get('postal') or '—'}",
             f"🚚 روش ارسال: {ship_method_label or ship_method or '—'}",
             f"💳 پرداخت: {pay_label}",
             f"📦 وضعیت ارسال: {ship_label}",
             f"🔎 کد رهگیری: {track}",
             "",
             f"💰 مبلغ کل: *{_ftm_toman(order.get('total', 0))}*",
             "",
             "🛒 اقلام:"]
    for it in items:
        pname = it.get("name") or it.get("product") or "—"
        size = it.get("size") or "—"
        qty = it.get("qty") or 1
        price = _ftm_toman(it.get("price", 0))
        lines.append(f"• {pname} | سایز: {size} | تعداد: {qty} | قیمت: {price}")
    return "\n".join(lines)


async def admin_open_order(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str, back_to: str = "admin:queue") -> None:
    if update.callback_query:
        await update.callback_query.answer()
    if not _is_admin_activated(update):
        if update.callback_query:
            await update.callback_query.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return

    order = STORE.find_order(order_id)
    if not order:
        if update.callback_query:
            await update.callback_query.answer("سفارش پیدا نشد.", show_alert=True)
        else:
            await update.message.reply_text("❌ سفارش پیدا نشد.")
        return

    # remember which list to return to (per admin chat)
    try:
        _bt = context.bot_data.setdefault("admin_last_back_to", {})
        _bt[int(update.effective_chat.id)] = back_to
    except Exception:
        pass

    await admin_ui_send_or_edit(
        update,
        context,
        text=_admin_order_summary(order),
        reply_markup=admin_order_keyboard(order_id, back_to=(context.bot_data.get("admin_last_back_to", {}) or {}).get(int(update.effective_chat.id), "admin:queue")),
    )

# ------------------ Shipping methods ------------------
# روش‌های ارسال (فعلاً هزینه ثابت/صفر؛ بعداً می‌توانید برای هر روش مبلغ تعیین کنید)
SHIPPING_METHODS = {
    "post": {"label": "📮 پست"},
    "tipax": {"label": "🚚 تیپاکس"},
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
    raw = re.sub(r"\D+", "", str(card_number or ""))
    nbsp = "\u00A0" 
    grouped = nbsp.join(raw[i:i+4] for i in range(0, len(raw), 4))
    LRI = "\u2066"
    PDI = "\u2069"
    return f"{LRI}{grouped}{PDI}"


def _build_cards_text_and_entities(cards):
    block = ""
    raw_numbers = []
    for i, card in enumerate(cards, start=1):
        raw = re.sub(r"\D+", "", str(card.get("number", "") or "")).strip()
        raw_numbers.append(raw)
        grouped = " ".join(raw[j:j+4] for j in range(0, len(raw), 4))
        holder = html.escape(str(card.get("holder", "") or ""))
        block += (
            f"{i}) 💳\n"
            f"<pre>{grouped}</pre>\n"
            f"👤 ({holder})\n\n"
        )
    return block, [], raw_numbers


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




async def _safe_send_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs) -> Tuple[bool, Optional[int], Optional[str]]:
    """Send message to user and return (ok, message_id, error_text).

    نکته مهم: تلگرام/بات‌ها «رسیدِ تحویل به کاربر» یا «seen» نمی‌دهند؛
    فقط می‌توانیم مطمئن شویم پیام با موفقیت به سرورهای تلگرام تحویل داده شده است.
    """
    try:
        msg = await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return True, getattr(msg, "message_id", None), None
    except Exception as e:
        logger.error("Failed to send message to user chat_id=%s: %s", chat_id, e)
        return False, None, str(e)



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


# ------------------ Sales dashboard helpers ------------------
# فروش را بر اساس «زمان پرداخت» حساب می‌کنیم:
# - پرداخت آنلاین: paid_at
# - پرداخت کارت‌به‌کارت: confirmed_at (پس از تایید ادمین)
# - در نهایت fallback به created_at
PAID_STATUSES = {"paid", "paid_confirmed", "fulfilled"}

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

def _top_items_text(counter: Counter, n: int = 3) -> str:
    """متن پرفروش‌ها (فقط ۳ مورد اول)."""
    if not counter:
        return "—"
    parts = []
    for pid, qty in counter.most_common(n):
        parts.append(f"• {_product_name_by_id(pid)} |({qty})")
    return "\n".join(parts) if parts else "—"

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
def _to_english_digits(value: str) -> str:
    """تبدیل اعداد فارسی/عربی به انگلیسی.

    پشتیبانی از:
    - فارسی: ۰۱۲۳۴۵۶۷۸۹
    - عربی (Arabic-Indic): ٠١٢٣٤٥٦٧٨٩
    """
    if value is None:
        return ""
    s = str(value)
    trans = {
        ord("۰"): "0", ord("۱"): "1", ord("۲"): "2", ord("۳"): "3", ord("۴"): "4",
        ord("۵"): "5", ord("۶"): "6", ord("۷"): "7", ord("۸"): "8", ord("۹"): "9",
        ord("٠"): "0", ord("١"): "1", ord("٢"): "2", ord("٣"): "3", ord("٤"): "4",
        ord("٥"): "5", ord("٦"): "6", ord("٧"): "7", ord("٨"): "8", ord("٩"): "9",
    }
    return s.translate(trans)


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


def _decrement_inventory(item:dict):
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
    if cur < qty :
        return False
    sizes[size] = cur - qty 
    STORE.set_catalog(CATALOG)
    return True

def _increment_inventory(item: dict):
    """برگرداندن/آزادسازی موجودی رزرو شده (برعکس _decrement_inventory)."""
    p = _find_product(item["gender"], item["category"], item["product_id"])
    if not p:
        return False
    color = item.get("color")
    size = item.get("size")
    qty = item["qty"]
    if "variants" in p and color:
        sizes = p["variants"][color]["sizes"]
    else:
        sizes = p["sizes"]
    cur = int(sizes.get(size, 0))
    sizes[size] = cur + qty
    STORE.set_catalog(CATALOG)
    return True




# ------------------ Inventory reservation (prevent oversell) ------------------
# ایده: به محض ورود کاربر به مرحله «پرداخت/ارسال رسید»، موجودی را رزرو می‌کنیم تا کاربر دیگری نتواند همان کالا را بخرد.
# اگر پرداخت انجام نشد یا کاربر رها کرد، بعد از مدت مشخص رزرو آزاد می‌شود.
try:
    RESERVE_TTL_MINUTES = int(os.getenv("RESERVE_TTL_MINUTES", "15"))
except Exception:
    RESERVE_TTL_MINUTES = 15

def _reserve_inventory_for_order(order_id: str) -> bool:
    """رزرو موجودی برای یک سفارش. اگر موجودی کافی نباشد، هیچ رزروی باقی نمی‌ماند."""
    order = STORE.find_order(order_id)
    if not order:
        return False

    # اگر قبلاً رزرو شده
    if order.get("inventory_reserved"):
        return True

    reserved_items = []
    for it in (order.get("items") or []):
        ok = _decrement_inventory(it)
        if not ok:
            # rollback
            for rit in reserved_items:
                _increment_inventory(rit)
            return False
        reserved_items.append(it)

    STORE.update_order(
        order_id,
        inventory_reserved=True,
        reserved_at=datetime.utcnow().isoformat() + "Z",
    )
    _order_log(order_id, "system", f"موجودی برای {RESERVE_TTL_MINUTES} دقیقه رزرو شد.")
    return True

def _release_inventory_for_order(order_id: str, reason: str = "رزرو آزاد شد.") -> None:
    """آزادسازی موجودی رزرو شده (برگرداندن به انبار)."""
    order = STORE.find_order(order_id)
    if not order:
        return
    if not order.get("inventory_reserved"):
        return

    for it in (order.get("items") or []):
        _increment_inventory(it)

    STORE.update_order(
        order_id,
        inventory_reserved=False,
        released_at=datetime.utcnow().isoformat() + "Z",
    )
    _order_log(order_id, "system", reason)

def _cleanup_expired_reservations() -> None:
    """آزادسازی رزروهای قدیمی (مثلاً وقتی کاربر پرداخت را نیمه‌کاره رها می‌کند)."""
    orders = STORE.data.get("orders", []) or []
    now_utc = datetime.now(timezone.utc)
    ttl = timedelta(minutes=RESERVE_TTL_MINUTES)

    for o in orders:
        try:
            if not o.get("inventory_reserved"):
                continue
            # اگر به مرحله قطعی رسیده، آزاد نکن
            if o.get("status") in ("paid", "paid_confirmed", "fulfilled"):
                continue

            dt = _parse_dt_utc_z(o.get("reserved_at"))
            if not dt:
                continue

            if (now_utc - dt) > ttl:
                oid = o.get("order_id")
                if not oid:
                    continue
                _release_inventory_for_order(oid, reason="رزرو منقضی شد و آزاد گردید.")
                STORE.update_order(oid, status="cancelled", cancel_reason="reservation_expired")
        except Exception:
            continue
# ------------------ end inventory reservation ------------------


#   /start

async def start(update:Update , context:ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        # پاکسازی اطلاعات موقت فقط در صورت شروع از /start
        context.user_data.pop("cart", None)
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
        await q.message.reply_text(text , reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))
    else:
        await update.message.reply_text(text , reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))


#     نمایش مراحل


# --- Admin registration helpers ---
async def admin_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register current chat as admin chat (برای دریافت رسیدها و هشدارها). فقط ادمین‌های مجاز."""
    if not update.message:
        return

    # 🔒 جلوگیری از ادمین شدن افراد ناشناس
    if not _is_admin_user(update):
        await update.message.reply_text("⛔️ دسترسی ندارید.", reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))
        return

    chat_id = update.effective_chat.id
    try:
        # ذخیره چند ادمین (لیست) + سازگاری با کلید قدیمی admin_chat_id
        lst = STORE.data.get("admin_chat_ids") or []
        if not isinstance(lst, list):
            lst = [lst] if lst else []

        legacy = STORE.data.get("admin_chat_id")
        if legacy and str(legacy) not in [str(x) for x in lst]:
            lst.append(str(legacy))

        if str(chat_id) not in [str(x) for x in lst]:
            lst.append(str(chat_id))

        STORE.data["admin_chat_ids"] = lst
        STORE.data["admin_chat_id"] = str(chat_id)  # legacy
        STORE.save()
    except Exception:
        pass

    await update.message.reply_text(
        f"✅ ادمین ثبت شد. از این به بعد رسیدها به این چت ارسال می‌شوند.\nAdminChatID: {chat_id}",
        reply_markup=main_menu_reply(is_admin=True)
    )


async def admin_unregister(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """خروج از حالت ادمین برای این چت (حذف چت از لیست دریافت رسید/هشدار). فقط ادمین‌های مجاز."""
    if not update.message:
        return

    if not _is_admin_activated(update):
        await update.message.reply_text("⛔️ دسترسی ندارید.", reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))
        return

    chat_id = update.effective_chat.id

    try:
        lst = STORE.data.get("admin_chat_ids") or []
        if not isinstance(lst, list):
            lst = [lst] if lst else []
        lst = [x for x in lst if str(x) != str(chat_id)]
        STORE.data["admin_chat_ids"] = lst

        # اگر legacy روی همین چت بود، پاکش کن
        if str(STORE.data.get("admin_chat_id") or "") == str(chat_id):
            STORE.data["admin_chat_id"] = None

        STORE.save()
    except Exception:
        pass

    await update.message.reply_text(
        "✅ این چت از حالت ادمین خارج شد. (دیگر رسید/هشدارها به این چت ارسال نمی‌شود.)",
        reply_markup=main_menu_reply(is_admin=_is_admin_activated(update))
    )

async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """منوی داشبورد فروش (امروز/۷ روز گذشته/۳۰ روز گذشته)."""
    # 🔒 فقط ادمینِ فعال‌شده (اول /admin در همین چت)
    if not _is_admin_activated(update):
        if update.message:
            await update.message.reply_text(
                "⛔️ ابتدا در همین چت /admin را بزنید.",
                reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)),
            )
        elif update.callback_query:
            await update.callback_query.answer("⛔️ ابتدا در همین چت /admin را بزنید.", show_alert=True)
        return

    msg = "📊 داشبورد فروش\n\nیک بازه را انتخاب کنید:"
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("امروز", callback_data="admin:dashboard:today"),
            InlineKeyboardButton("۷ روز گذشته", callback_data="admin:dashboard:week"),
        ],
        [InlineKeyboardButton("۳۰ روز گذشته", callback_data="admin:dashboard:month")],
        [
            InlineKeyboardButton("📋 سفارش‌های آماده ارسال", callback_data="admin:queue"),
            InlineKeyboardButton("🚚 سفارش‌های ارسال شده", callback_data="admin:shipped"),
        ],
    ])

    if update.message:
        await update.message.reply_text(msg, reply_markup=kb)
    else:
        q = update.callback_query
        await q.answer()
        try:
            await q.edit_message_text(msg, reply_markup=kb)
        except Exception:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, reply_markup=kb)


async def admin_dashboard_show_period(update: Update, context: ContextTypes.DEFAULT_TYPE, period: str) -> None:
    """نمایش داشبورد فروش برای یک بازه."""
    # 🔒 فقط ادمینِ فعال‌شده
    if not _is_admin_activated(update):
        if update.callback_query:
            await update.callback_query.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return

    orders = STORE.data.get("orders", []) or []
    now_local = datetime.now(timezone.utc).astimezone(LOCAL_TZ)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    if period == "today":
        title = "امروز"
        start = today_start
        end = tomorrow_start
        prev_start = start - timedelta(days=1)
        prev_end = start
        compare_label = "نسبت به دیروز"
        range_label = _jalali_label_from_greg_date(start.date())
    elif period == "week":
        title = "۷ روز گذشته"
        start = today_start - timedelta(days=6)
        end = tomorrow_start
        prev_start = start - timedelta(days=7)
        prev_end = start
        compare_label = "نسبت به ۷ روز قبل"
        range_label = f"{_jalali_label_from_greg_date(start.date())} تا {_jalali_label_from_greg_date((end - timedelta(days=1)).date())}"
    else:
        title = "۳۰ روز گذشته"
        start = today_start - timedelta(days=29)
        end = tomorrow_start
        prev_start = start - timedelta(days=30)
        prev_end = start
        compare_label = "نسبت به ۳۰ روز قبل"
        range_label = f"{_jalali_label_from_greg_date(start.date())} تا {_jalali_label_from_greg_date((end - timedelta(days=1)).date())}"

    curr = _sales_agg(orders, start, end)
    prev = _sales_agg(orders, prev_start, prev_end)
    pct_orders = _format_pct(_pct_change(curr.get("count", 0), prev.get("count", 0)))
    pct_amount = _format_pct(_pct_change(curr.get("amount", 0), prev.get("amount", 0)))

    # وضعیت سفارش‌ها (کلی)
    status_counts: Dict[str, int] = {}
    for o in (orders or []):
        s = (o.get("status") or "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    lines = []
    lines.append(f"📊 داشبورد فروش - {title}")
    lines.append(f"بازه: {range_label}")
    lines.append("")
    lines.append(f"تعداد سفارشِ پرداخت‌شده: {curr.get('count', 0)}  ({compare_label}: {pct_orders})")
    lines.append(f"فروش: {format_toman(curr.get('amount', 0))}  ({compare_label}: {pct_amount})")
    avg = 0
    try:
        avg = int(curr.get("amount", 0)) // max(int(curr.get("count", 0)), 1)
    except Exception:
        avg = 0
    lines.append(f"میانگین هر سفارش: {format_toman(avg)}")
    lines.append("")
    lines.append("پرفروش‌ها (۳ مورد):")
    lines.append(_top_items_text(curr.get("items", Counter()), n=3))
    lines.append("")
    lines.append("📦 وضعیت سفارش‌ها (کلی):")
    for key, label in ORDER_STATUS_FA.items():
        lines.append(f"• {label}: {status_counts.get(key, 0)}")

    msg = "\n".join(lines)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ انتخاب بازه", callback_data="admin:dashboard"),
            InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"admin:dashboard:{period}"),
        ],
        [
            InlineKeyboardButton("📋 سفارش‌های آماده ارسال", callback_data="admin:queue"),
            InlineKeyboardButton("🚚 سفارش‌های ارسال شده", callback_data="admin:shipped"),
        ],
    ])

    if update.callback_query:
        q = update.callback_query
        await q.answer()
        try:
            await q.edit_message_text(msg, reply_markup=kb)
        except Exception:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, reply_markup=kb)
    elif update.message:
        await update.message.reply_text(msg, reply_markup=kb)


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
        "gender":gender , 
        "category":category , 
        "product_id":product_id , 
        "name":p["name"] , 
        "color":color , 
        "price":price , 
        "sizes":sizes ,
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
    total_price = sum(item['price'] * item['qty'] for item in cart)
    text = ""
    reply_markup = None
    if not cart:
        # سبد خالی است
        text = emoji.emojize("سبد خرید شما خالی است :shopping_bags: \n جهت اضافه کردن محصول به منو اصلی بازگردید.")
        # **[تغییر]** استفاده از main_menu (Inline) برای سازگاری در ویرایش پیام از طریق CallbackQuery
        reply_markup = main_menu()
    else:
        # سبد پر است
        text += emoji.emojize("🛒 لیست محصولات در سبد خرید شما:\n\n")
        cart_keyboard = []
        for i, item in enumerate(cart):
            # ⭐️ (جدید) محاسبه موجودی در هر بار نمایش ⭐️
            max_qty = _get_item_inventory(item) 
            
            item_text = f"**{i+1}. {item['name']}**\n"
            item_text += f" رنگ: {item.get('color') or '—'} | سایز: {item.get('size') or '—'}\n"
            item_text += f" تعداد: {item['qty']} / موجودی فروشگاه: {max_qty} عدد\n" # ⭐️ (جدید) نمایش موجودی ⭐️
            item_text += f" قیمت واحد: {item['price']:,} تومان\n"
            item_text += f" قیمت کل: {(item['price'] * item['qty']):,} تومان\n"
            text += item_text + "--------\n"
            
            # دکمه‌های Inline برای مدیریت سبد خرید
            # ⭐️ (اصلاح) نمایش تعداد فعلی در دکمه وسط به صورت (تعداد/موجودی) ⭐️
            current_qty_display = f"{item['qty']}/{max_qty}" 
            
            cart_keyboard.append([
                InlineKeyboardButton(f"محصول #{i+1}", callback_data="none"), 
                InlineKeyboardButton("➖", callback_data=f"cart:minus:{i}"),
                InlineKeyboardButton(current_qty_display, callback_data="none"),
                InlineKeyboardButton("➕", callback_data=f"cart:plus:{i}")
            ])
        
        text += f"\n**مجموع مبلغ قابل پرداخت: {total_price:,} تومان**"
        
        # دکمه‌های نهایی سبد خرید
        final_buttons = [
            # ⭐️ (اصلاح) تغییر callback_data به "checkout:begin" برای شروع Conversation Handler ⭐️
            InlineKeyboardButton("✅ ثبت سفارش و پرداخت", callback_data="checkout:begin")
        ]
        cart_keyboard.append(final_buttons)
        reply_markup = InlineKeyboardMarkup(cart_keyboard)

    # ⭐️ منطق اصلی برای مدیریت Reply Keyboard vs Inline Keyboard ⭐️
    if update.callback_query:
        # اگر از دکمه Inline آمده (CallbackQuery)
        q = update.callback_query
        await q.answer()
        # پیام قبلی (که دارای دکمه Inline بوده) ویرایش می‌شود
        if q.message.caption:
            await q.edit_message_caption(caption=text , reply_markup=reply_markup )
        else:
            await q.edit_message_text(text , reply_markup=reply_markup )
    else:
        # اگر از دکمه Reply Keyboard آمده (Message)
        # یک پیام جدید ارسال می‌شود
        await update.message.reply_text(text , reply_markup=reply_markup )
    return


async def show_my_order_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    orders = STORE.data.get("orders", [])

    mine = [o for o in orders if int(o.get("user_chat_id", 0)) == int(chat_id)]
    if not mine:
        await update.message.reply_text("هنوز سفارشی برای شما ثبت نشده است.", reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))
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


    await update.message.reply_text(text, reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))



async def menu_reply_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    روتر برای مدیریت پیام‌های متنی دریافتی از دکمه‌های Reply Keyboard (پایین صفحه).
    """
    text = update.message.text
    
    if text == "🛍️ لیست محصولات":
        # هدایت به مرحله اول انتخاب محصولات (انتخاب جنسیت)
        await show_gender(update, context) 
    
    elif text == "🧺 سبد خرید":
        # تابع show_cart قبلاً اصلاح شد.
        await show_cart(update, context)
        
    elif text == "🆘 پشتیبانی":
        await update.message.reply_text("برای پشتیبانی با @amirmehdi_84_10 تماس بگیرید.")
    
    elif text == "📦 وضعیت سفارش من":
        await show_my_order_status(update, context)

    elif text == "📊 داشبورد فروش":
        if not _is_admin_activated(update):
            await update.message.reply_text("⛔️ دسترسی ندارید.", reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))
            return
        await admin_dashboard(update, context)


    elif text == "📋 سفارش‌های آماده ارسال":
        if not _is_admin_activated(update):
            await update.message.reply_text("⛔️ دسترسی ندارید.", reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))
            return
        await admin_queue_show(update, context)


    elif text == "🚚 سفارش‌های ارسال شده":
        if not _is_admin_activated(update):
            await update.message.reply_text("⛔️ دسترسی ندارید.", reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))
            return
        await admin_shipped_show(update, context)


    elif text == "🚪 خروج از ادمین":
        # خروج از حالت ادمین برای همین چت
        await admin_unregister(update, context)



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
        await update.message.reply_text("❌ فرم لغو شد. از منوی پایین استفاده کن.", reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))
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
        if re.fullmatch(r"\d{10}" , _to_english_digits(text)):
            context.user_data["customer"]["postal"] = _to_english_digits(text)
            context.user_data["awaiting"] = "shipping"  # تغییر وضعیت به انتخاب روش ارسال
            # نمایش دکمه‌های انتخاب روش ارسال (ReplyKeyboard)
            shipping_keyboard = ReplyKeyboardMarkup([
                ["📮 پست", "🚚 تیپاکس"],
                ["🛵 پیک (درون‌شهری)", "❌ انصراف"]
            ], resize_keyboard=True, one_time_keyboard=False)
            await update.message.reply_text(
                "🚚 حالا روش ارسال مورد نظر خود را انتخاب کنید:",
                reply_markup=shipping_keyboard
            )
            return CUSTOMER_SHIPPING
        else:
            await update.message.reply_text("کد پستی نامعتبر است. ۱۰ رقم (فارسی یا انگلیسی) وارد کنید.")
            return CUSTOMER_POSTAL
    if awaiting == "shipping":
        # نگاشت متن دکمه‌ها به کلیدهای داخلی
        shipping_map = {
            "📮 پست": "post",
            "🚚 تیپاکس": "tipax",
            "🛵 پیک (درون‌شهری)": "courier",
        }
        if text in shipping_map:
            method = shipping_map[text]
            context.user_data["customer"]["shipping_method"] = method
            context.user_data["awaiting"] = None
            # حالا خلاصه سفارش را نشان بده
            await show_checkout_summary(update, context)
            return ConversationHandler.END
        elif text == "❌ انصراف":
            context.user_data.pop("customer", None)
            context.user_data["awaiting"] = None
            await update.message.reply_text("❌ فرم لغو شد.", reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))
            await show_cart(update, context)
            return ConversationHandler.END
        else:
            await update.message.reply_text("لطفاً یکی از گزینه‌های روش ارسال را انتخاب کنید.")
            return CUSTOMER_SHIPPING

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
    
    # آیا این کاربر ادمین مجاز است؟ (برای نمایش گزینه داشبورد در Reply Keyboard)
    if isinstance(update_or_msg, Update):
        is_admin = _is_admin_activated(update_or_msg)
    else:
        is_admin = _is_admin_activated_from_message(update_or_msg)

    send = context.bot.send_message
    
    cart = context.user_data.get("cart" , [])
    customer = context.user_data.get("customer" , {})
    total = _calc_cart_total(cart)
    
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
    # 🟢 نمایش خلاصه سفارش و اطلاعات مشتری با فرمت Markdown
    info = (
        "🧾 **خلاصه سفارش و مشخصات مشتری*:\n\n"
        "👤 **نام و نام خانوادگی*: {name}\n"
        "📞 **شماره موبایل*: {phone}\n"
        "🏠 **آدرس*: {address}\n"
        "📮 **کد پستی*: {postal}\n"
        "🚚 **روش ارسال*: {ship}\n\n"
        "🛍️ **محصولات سفارش داده شده*:\n"
        f"{joined_lines}\n\n"
        f"💰 **مبلغ قابل پرداخت*: **{_ftm_toman(total)}**"
    ).format(
        name=customer.get('name', '—'),
        phone=customer.get('phone', '—'),
        address=customer.get('address', '—'),
        postal=customer.get('postal', '—'),
        ship=(SHIPPING_METHODS.get(customer.get('shipping_method'), {}).get('label') if customer.get('shipping_method') else 'انتخاب نشده')
    )
    
    # 🟢 دکمه‌های مورد درخواست کاربر
    kb = InlineKeyboardMarkup([
    [InlineKeyboardButton("✏️ ویرایش مشخصات", callback_data="checkout:begin")],
    [InlineKeyboardButton("💳 اقدام به پرداخت نهایی", callback_data="checkout:pay")],
    [InlineKeyboardButton("❌ لغو سفارش", callback_data="checkout:cancel")],
    [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")]
])

    await send(chat_id=chat_id, text=info, reply_markup=kb)
    # ✅ بازگرداندن منوی اصلی (Reply Keyboard) بعد از اتمام فرم
    m = await context.bot.send_message(
        chat_id=chat_id,
        text="✅فرم مشخصات تکمیل شد.",
        reply_markup=main_menu_reply(is_admin=is_admin),
    )
    context.user_data["form_done_msg_id"] = m.message_id

def _build_checkout_summary_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    cart = context.user_data.get("cart", [])
    customer = context.user_data.get("customer", {})
    total = _calc_cart_total(cart)

    lines = []
    for i, it in enumerate(cart, 1):
        lines.append(
            f"{i}) {it['name']} | رنگ: {it.get('color') or '—'} | سایز: {it.get('size') or '—'} | "
            f"تعداد: {it['qty']} | {_ftm_toman(it['qty'] * it['price'])}"
        )
    joined_lines = "\n".join(lines) if lines else "—"

    ship_label = SHIPPING_METHODS.get(customer.get("shipping_method"), {}).get("label") if customer.get("shipping_method") else "انتخاب نشده"

    info = (
        "🧾 **خلاصه سفارش و مشخصات مشتری*:\n\n"
        "👤 **نام و نام خانوادگی*: {name}\n"
        "📞 **شماره موبایل*: {phone}\n"
        "🏠 **آدرس*: {address}\n"
        "📮 **کد پستی*: {postal}\n"
        "🚚 **روش ارسال*: {ship}\n\n"
        "🛍️ **محصولات سفارش داده شده*:\n"
        "{items}\n\n"
        "💰 **مبلغ قابل پرداخت*: **{total}**"
    ).format(
        name=customer.get('name', '—'),
        phone=customer.get('phone', '—'),
        address=customer.get('address', '—'),
        postal=customer.get('postal', '—'),
        ship=ship_label,
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
    """(سازگاری) اولین چت ادمین ثبت‌شده را برمی‌گرداند."""
    ids = _get_admin_chat_ids()
    return ids[0] if ids else None



def _clear_user_cart_after_paid(app, user_id: int) -> None:
    """بعد از تایید پرداخت توسط ادمین، سبد و وضعیت‌های خرید کاربر را پاک می‌کند تا سفارش قبلی reuse نشود."""
    if not user_id:
        return

    ud = app.user_data.get(int(user_id))
    if not isinstance(ud, dict):
        return

    for k in (
        "cart",
        "customer",
        "pending",
        "awaiting",
        "awaiting_receipt",
        "active_order_id",
        "current_order_id",
    ):
        ud.pop(k, None)
def _create_order_from_current_cart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    """Create (or reuse) an order id for current user's cart+customer."""
    cart = context.user_data.get("cart", [])
    customer = context.user_data.get("customer", {})
    if not cart or not customer:
        return None

    existing = context.user_data.get("current_order_id")
    if existing and STORE.find_order(existing):
        # اگر سفارش قبلی نهایی/پرداخت شده باشد، نباید reuse شود.
        order = STORE.find_order(existing)
        if order and (order.get("status") in PAID_STATUSES or order.get("status") == "cancelled"):
            context.user_data.pop("current_order_id", None)
        else:
            # sync shipping method/customer with latest user_data
            cust = dict((order or {}).get("customer", {}))
            cust.update(customer)  # customer جدید user_data
            STORE.update_order(existing, customer=cust, shipping_method=cust.get("shipping_method"))
            return existing


    order_id = _make_order_id()
    order = {
        "order_id": order_id,
        "status": "awaiting_receipt",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "total": _calc_cart_total(cart),
        "items": cart,
        "customer": customer,
        "shipping_method": customer.get("shipping_method"),
        "shipping_status": "pending",
        "tracking_code": None,
        "history": [{"at": datetime.utcnow().isoformat() + "Z", "by": "system", "text": "سفارش ساخته شد و در انتظار رسید است."}],
        "user_chat_id": update.effective_chat.id,
        "user_id": update.effective_user.id if update.effective_user else None,
        "username": (update.effective_user.username if update.effective_user else None),
        "receipt": None,
    }
    STORE.add_order(order)
    context.user_data["current_order_id"] = order_id
    return order_id


async def manual_payment_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str) -> None:
    """Send card-to-card payment instructions.

    ✅ What is (and isn't) possible:
    - Bots cannot make *plain message text* copy-to-clipboard on a single tap.
    - The only true one-tap clipboard copy from a bot is InlineKeyboardButton(copy_text=CopyTextButton(...)),
      which requires both:
        1) python-telegram-bot that includes CopyTextButton (your server env), and
        2) a Telegram client that supports "copy_text" buttons.
    """

    # 🧹 حذف پیام «فرم مشخصات تکمیل شد» تا زیر پیام پرداخت نمایش داده نشود
    mid = context.user_data.pop("form_done_msg_id", None)
    if mid:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=int(mid))
        except Exception:
            pass

    order = STORE.find_order(order_id)
    total = int(order.get("total", 0)) if order else 0

    shipping_method = (order.get("shipping_method") or (order.get("customer", {}) or {}).get("shipping_method")) if order else None
    shipping_note = SHIPPING_INFO.get(shipping_method, "هزینه ارسال بر عهده مشتری است.")
    ship_label = SHIPPING_METHODS.get(shipping_method, {}).get("label", "انتخاب نشده")

    # copy hint depending on library support
    if _HAS_COPY_BUTTON:
        copy_hint = "برای کپی یک‌ضرب، روی «خودِ شماره کارت» در دکمه‌های پایین پیام بزنید."
    else:
        copy_hint = "⚠️ کپی یک‌ضرب در این نسخه فعال نیست (CopyTextButton موجود نیست). برای فعال شدن باید python-telegram-bot روی سرور آپدیت شود."

    # --- Build HTML text (clean + readable) ---
    parts = []
    header = (
        "💳 <b>پرداخت کارت به کارت</b>"
        f"🔸 <b>مبلغ قابل پرداخت:</b> {_ftm_toman(total)}"
        f"🚚 <b>روش ارسال:</b> {html.escape(str(ship_label))}"
        f"{html.escape(str(shipping_note))}"
        "🔹 <b>اطلاعات حساب‌های فروشگاه:</b>"
        f"{html.escape(copy_hint)}"
    )
    parts.append(header)

    # Card blocks in text (NOT masked; formatting like config/code)
    for i, c in enumerate(CARDS, start=1):
        raw = re.sub(r"\D+", "", str(c.get("number", "") or "")).strip()
        holder = str(c.get("holder", "") or "").strip()
        if not raw and not holder:
            continue

        # نمایش گروه‌بندی شده با فاصله (فعلی)
        grouped = " ".join(raw[j:j+4] for j in range(0, len(raw), 4))
        block = (
            f"{i}) 💳"
            f"<pre>{html.escape(grouped)}</pre>"
            f"({html.escape(holder)})"
        )
        parts.append(block)

    footer = "📸 بعد از پرداخت، روی دکمه زیر بزنید و عکس رسید پرداخت را ارسال کنید."
    parts.append(html.escape(footer))

    text_html = "".join(parts)

    # --- Inline keyboard ---
    rows = []

    # One-tap copy buttons: show the NUMBER itself as the button text
    if _HAS_COPY_BUTTON:
        for i, c in enumerate(CARDS, start=1):
            raw = re.sub(r"\D+", "", str(c.get("number", "") or "")).strip()
            if not raw:
                continue
            # readable label on button (group 4-4-4-4)
            grouped = " ".join(raw[j:j+4] for j in range(0, len(raw), 4))
            rows.append([
                InlineKeyboardButton(
                    text=f"{i}) {grouped}",
                    copy_text=CopyTextButton(text=raw[:256]),
                )
            ])

    # keep your existing flow buttons
    rows += [
        [InlineKeyboardButton("📸 ارسال عکس رسید پرداخت", callback_data=f"receipt:start:{order_id}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")],
    ]
    kb = InlineKeyboardMarkup(rows)

    chat_id = update.effective_chat.id

    if update.callback_query:
        q = update.callback_query
        await q.answer()
        try:
            await q.edit_message_text(text_html, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text_html,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text_html,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


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

    # پاکسازی رزروهای منقضی شده
    _cleanup_expired_reservations()

    # رزرو موجودی در صورت نیاز (برای جلوگیری از فروش بیش از موجودی)
    ok = _reserve_inventory_for_order(order_id)
    if not ok:
        STORE.update_order(order_id, status="cancelled", cancel_reason="out_of_stock")
        await q.edit_message_text("❌ متأسفانه موجودی این سفارش تمام شده است. اگر پرداخت انجام داده‌اید، با پشتیبانی هماهنگ کنید.", reply_markup=main_menu())
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
        await q.edit_message_text(text, reply_markup=kb)
    except Exception:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=kb)


async def receipt_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    oid = context.user_data.get("awaiting_receipt")
    if oid:
        _release_inventory_for_order(oid, reason="کاربر فرآیند ارسال رسید را لغو کرد و رزرو آزاد شد.")
        STORE.update_order(oid, status="cancelled", cancel_reason="user_cancelled")

    context.user_data.pop("awaiting_receipt", None)
    context.user_data.pop("active_order_id", None)
    context.user_data.pop("current_order_id", None)
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
        await update.message.reply_text("❌ سفارش پیدا نشد. لطفاً دوباره تلاش کنید.", reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))
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

    admin_ids = _get_admin_chat_ids()
    if not admin_ids:
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

    admin_text = (
        "🧾 **رسید پرداخت جدید**\n"
        f"OrderID: {order_id}\n"
        f"UserChatID: {order.get('user_chat_id')}\n"
        f"User: @{order.get('username') or '—'}\n"
        f"جمع کل: **{_ftm_toman(order.get('total', 0))}**\n\n"
        "👤 مشتری:\n"
        f"نام: {order['customer'].get('name')}\n"
        f"موبایل: {order['customer'].get('phone')}\n"
        f"آدرس: {order['customer'].get('address')}\n"
        f"کدپستی: {order['customer'].get('postal')}\n\n"
        "اقلام:\n" + "\n".join(lines)
    )

    admin_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید پرداخت", callback_data=f"admin:approve:{order_id}")],
        [InlineKeyboardButton("❌ مشکل دارد", callback_data=f"admin:reject:{order_id}")],
    ])

    try:
        await _broadcast_admin_photo(
            context,
            photo=file_id,
            caption=admin_text,
            reply_markup=admin_kb
        )
    except Exception as e:
        logger.error("Failed to send receipt to admin: %s", e)


async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str) -> None:
    q = update.callback_query
    await q.answer()

    # 🔒 فقط ادمین‌های مجاز
    if not _is_admin_activated(update):
        await q.answer("دسترسی ندارید.", show_alert=True)
        return


    order = STORE.find_order(order_id)
    if not order:
        await q.edit_message_text("❌ سفارش پیدا نشد.")
        return

    if order.get("status") == "paid_confirmed":
        await q.answer("قبلاً تایید شده.", show_alert=False)
        return

    # موجودی قبلاً هنگام checkout_pay رزرو شده است؛ اینجا کم‌کردن دوباره انجام نمی‌شود.
    STORE.update_order(order_id, status="paid_confirmed", confirmed_at=datetime.utcnow().isoformat() + "Z", inventory_reserved=False, reserved_consumed_at=datetime.utcnow().isoformat() + "Z")
    _order_log(order_id, "admin", "پرداخت تایید شد. سفارش وارد مرحله پردازش شد.")


    # ✅ پاکسازی سشن کاربر (سبد و current_order_id) تا سفارش پرداخت‌شده در خرید بعدی تکرار نشود
    _clear_user_cart_after_paid(context.application, order.get("user_id"))
    admin_panel = admin_panel_keyboard(order_id)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🛠 کنترل سفارش {order_id}",
        reply_markup=admin_panel
    )



    user_chat_id = order.get("user_chat_id")
    try:
        await context.bot.send_message(
            chat_id=int(user_chat_id),
            text=f"✅ پرداخت شما برای سفارش {order_id} تایید شد. سفارش شما در حال پردازش است.",
            reply_markup=main_menu_reply()
        )
    except Exception as e:
        logger.error("Failed to notify user for approve: %s", e)

    await q.edit_message_caption(caption=(q.message.caption or "") + "\n\n✅ پرداخت تایید شد.", reply_markup=None)


async def admin_reject_start(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str) -> None:
    q = update.callback_query
    await q.answer()

    # 🔒 فقط ادمین‌های مجاز
    if not _is_admin_activated(update):
        await q.answer("دسترسی ندارید.", show_alert=True)
        return


    order = STORE.find_order(order_id)
    if not order:
        await q.edit_message_text("❌ سفارش پیدا نشد.")
        return

    # mark pending admin reply in bot_data (shared)
    # mark pending admin reply in bot_data (per admin chat)
    pend_map = context.bot_data.setdefault("admin_pending_reply", {})
    pend_map[update.effective_chat.id] = {
        "order_id": order_id,
        "user_chat_id": order.get("user_chat_id"),
    }
    await q.edit_message_caption(
        caption=(q.message.caption or "") + "\n\n❌ لطفاً دلیل/پیام را تایپ کنید تا برای مشتری ارسال شود.*",
        reply_markup=q.message.reply_markup
    )


async def admin_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    دریافت متن از ادمین بعد از بعضی اکشن‌ها:
      - وارد کردن کد رهگیری پست
      - ارسال پیام به مشتری
      - نوشتن دلیل رد رسید
    (با پشتیبانی چند ادمین)
    """
    if not update.message:
        return

    # 🔒 فقط ادمین‌های مجاز
    if not _is_admin_activated(update):
        return

    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return

    # ---------------- tracking code flow ----------------
    track_map = context.bot_data.get("admin_pending_tracking") or {}
    pending_track = track_map.get(chat_id) if isinstance(track_map, dict) else None
    if pending_track:
        back_to = (pending_track or {}).get("back_to") or (context.bot_data.get("admin_last_back_to", {}) or {}).get(int(chat_id), "admin:queue")
        order_id = pending_track.get("order_id")
        order = STORE.find_order(order_id) if order_id else None

        if not order:
            await update.message.reply_text("❌ سفارش پیدا نشد.")
            try:
                track_map.pop(chat_id, None)
                if not track_map:
                    context.bot_data.pop("admin_pending_tracking", None)
            except Exception:
                context.bot_data.pop("admin_pending_tracking", None)
            return

        track = text

        # ذخیره وضعیت ارسال
        STORE.update_order(
            order_id,
            shipping_status="shipped",
            tracking_code=track,
            status="fulfilled",
            fulfilled_at=datetime.utcnow().isoformat() + "Z"
        )

        _order_log(order_id, "admin", f"ارسال شد. کد رهگیری: {track}")

        # ارسال پیام به مشتری
        ok, mid, err = await _safe_send_message(
            context,
            chat_id=int(order["user_chat_id"]),
            text=(
                "🚚 سفارش شما ارسال شد.\n"
                f"🧾 شماره سفارش: {order_id}\n"
                f"🔎 کد رهگیری: {track}"
            ),
            reply_markup=main_menu_reply(),
        )
        if not ok:
            # ✅ پیام وضعیت برای ادمین (Reply زیر پنل)
            base_id = context.bot_data.get(_admin_ui_key(chat_id))
            await admin_ack_status(
                context,
                admin_chat_id=int(chat_id),
                base_message_id=int(base_id) if base_id else None,
                ok=False,
                action="تحویل پست شد",
                customer_msg_id=None,
                err=err,
            )
            try:
                track_map.pop(chat_id, None)
                if not track_map:
                    context.bot_data.pop("admin_pending_tracking", None)
            except Exception:
                context.bot_data.pop("admin_pending_tracking", None)
            return
            try:
                track_map.pop(chat_id, None)
                if not track_map:
                    context.bot_data.pop("admin_pending_tracking", None)
            except Exception:
                context.bot_data.pop("admin_pending_tracking", None)
            return

        _order_log(order_id, "system", f"پیام ارسال+کد رهگیری به مشتری شد. msg_id={mid}")

        # تایید به ادمین (آپدیت پنل واحد) + پاکسازی وضعیت انتظار
        try:
            # پیام راهنما و پیام ادمین را (در صورت امکان) پاک کن تا چت خلوت بماند
            prompt_id = (pending_track or {}).get("prompt_msg_id")
            if prompt_id:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=int(prompt_id))
                except Exception:
                    pass
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
            except Exception:
                pass
        except Exception:
            pass

        order = STORE.find_order(order_id) or order
        await admin_ui_send_or_edit(
            update,
            context,
            text="✅ تحویل پست شد و کد رهگیری برای مشتری ارسال شد.\n🟢 پیام به مشتری ارسال شد\n🆔 msg_id: " + str(mid) + "\n\n" + _admin_order_summary(order),
            reply_markup=admin_order_keyboard(order_id, back_to=back_to),
        )

        # ✅ پیام وضعیت برای ادمین (Reply زیر پنل)
        base_id = context.bot_data.get(_admin_ui_key(chat_id))
        await admin_ack_status(
            context,
            admin_chat_id=int(chat_id),
            base_message_id=int(base_id) if base_id else None,
            ok=True,
            action="تحویل پست شد",
            customer_msg_id=mid,
            err=None,
        )

        try:
            track_map.pop(chat_id, None)
            if not track_map:
                context.bot_data.pop("admin_pending_tracking", None)
        except Exception:
            context.bot_data.pop("admin_pending_tracking", None)
        return

    
    # ---------------- shipped date filter flow ----------------
    shipdate_map = context.bot_data.get("admin_pending_shipped_date") or {}
    pending_shipdate = shipdate_map.get(chat_id) if isinstance(shipdate_map, dict) else None
    if pending_shipdate:
        target = _parse_admin_date_to_greg(text)
        if not target:
            await admin_ui_send_or_edit(
                update,
                context,
                text="""❌ *فرمت تاریخ درست نیست.*
مثال: 1404/10/14 یا 2026-01-04""",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ بازگشت", callback_data="admin:shipped")],
                ]),
                parse_mode="Markdown",
            )
            return

        # clear pending
        try:
            shipdate_map.pop(chat_id, None)
            if not shipdate_map:
                context.bot_data.pop("admin_pending_shipped_date", None)
        except Exception:
            context.bot_data.pop("admin_pending_shipped_date", None)

        await admin_shipped_show_date(update, context, target.isoformat())
        return

# ---------------- admin message flow ----------------
    msg_map = context.bot_data.get("admin_pending_msg") or {}
    pending_msg = msg_map.get(chat_id) if isinstance(msg_map, dict) else None
    if pending_msg:
        back_to = (pending_msg or {}).get("back_to") or (context.bot_data.get("admin_last_back_to", {}) or {}).get(int(chat_id), "admin:queue")
        order_id = pending_msg.get("order_id")
        order = STORE.find_order(order_id) if order_id else None

        if not order:
            await update.message.reply_text("❌ سفارش پیدا نشد.")
            try:
                msg_map.pop(chat_id, None)
                if not msg_map:
                    context.bot_data.pop("admin_pending_msg", None)
            except Exception:
                context.bot_data.pop("admin_pending_msg", None)
            return

        msg = text
        _order_log(order_id, "admin", f"پیام ادمین به مشتری: {msg}")

        # ارسال پیام واقعی به مشتری
        ok, mid, err = await _safe_send_message(
            context,
            chat_id=int(order["user_chat_id"]),
            text=f"✉️ پیام پشتیبانی درباره سفارش {order_id}:\n{msg}",
            reply_markup=main_menu_reply(),
        )
        if not ok:
            # ✅ پیام وضعیت برای ادمین (Reply زیر پنل)
            base_id = context.bot_data.get(_admin_ui_key(chat_id))
            await admin_ack_status(
                context,
                admin_chat_id=int(chat_id),
                base_message_id=int(base_id) if base_id else None,
                ok=False,
                action="پیام به مشتری",
                customer_msg_id=None,
                err=err,
            )
            try:
                msg_map.pop(chat_id, None)
                if not msg_map:
                    context.bot_data.pop("admin_pending_msg", None)
            except Exception:
                context.bot_data.pop("admin_pending_msg", None)
            return

        _order_log(order_id, "system", f"پیام ادمین به مشتری ارسال شد. msg_id={mid}")

        # تایید به ادمین (آپدیت پنل واحد) + پاکسازی وضعیت انتظار
        try:
            prompt_id = (pending_msg or {}).get("prompt_msg_id")
            if prompt_id:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=int(prompt_id))
                except Exception:
                    pass
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
            except Exception:
                pass
        except Exception:
            pass

        order = STORE.find_order(order_id) or order
        await admin_ui_send_or_edit(
            update,
            context,
            text="✅ پیام برای مشتری ارسال شد.\n🟢 پیام به مشتری ارسال\n🆔 msg_id: " + str(mid) + "\n\n" + _admin_order_summary(order),
            reply_markup=admin_order_keyboard(order_id, back_to=back_to),
        )

        # ✅ پیام وضعیت برای ادمین (Reply زیر پنل)
        base_id = context.bot_data.get(_admin_ui_key(chat_id))
        await admin_ack_status(
            context,
            admin_chat_id=int(chat_id),
            base_message_id=int(base_id) if base_id else None,
            ok=True,
            action="پیام به مشتری",
            customer_msg_id=mid,
            err=None,
        )

        try:
            msg_map.pop(chat_id, None)
            if not msg_map:
                context.bot_data.pop("admin_pending_msg", None)
        except Exception:
            context.bot_data.pop("admin_pending_msg", None)
        return

    # ---------------- receipt reject reason flow ----------------
    reply_map = context.bot_data.get("admin_pending_reply") or {}
    pending = reply_map.get(chat_id) if isinstance(reply_map, dict) else None
    if not pending:
        return

    msg = text
    order_id = pending.get("order_id")
    user_chat_id = pending.get("user_chat_id")
    if not (order_id and user_chat_id):
        try:
            reply_map.pop(chat_id, None)
            if not reply_map:
                context.bot_data.pop("admin_pending_reply", None)
        except Exception:
            context.bot_data.pop("admin_pending_reply", None)
        return

    # update order status
    STORE.update_order(order_id, status="receipt_rejected", rejected_at=datetime.utcnow().isoformat() + "Z", reject_message=msg)
    _release_inventory_for_order(order_id, reason="رسید رد شد و رزرو آزاد گردید.")

    try:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 ارسال مجدد رسید", callback_data=f"receipt:start:{order_id}")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")],
        ])

        await context.bot.send_message(
            chat_id=int(user_chat_id),
            text=(
                f"❌ رسید پرداخت برای سفارش {order_id} تایید نشد.\n\n"
                f"پیام ادمین: {msg}\n\n"
                "لطفاً روی «ارسال مجدد رسید» بزن و دوباره عکس رسید را ارسال کن."
            ),
            reply_markup=kb
        )
    except Exception as e:
        logger.error("Failed to send reject message to user: %s", e)

    await update.message.reply_text("✅ پیام برای مشتری ارسال شد.")
    try:
        reply_map.pop(chat_id, None)
        if not reply_map:
            context.bot_data.pop("admin_pending_reply", None)
    except Exception:
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
        await q.answer("لطفاً ابتدا روش ارسال را در فرم مشخصات انتخاب کنید.", show_alert=True)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ ویرایش مشخصات", callback_data="checkout:begin")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")]
        ])
        try:
            await q.edit_message_text(
                "❌ روش ارسال انتخاب نشده است.\n\n"
                "لطفاً روی دکمه «ویرایش مشخصات» کلیک کنید و فرم را تا انتها (شامل انتخاب روش ارسال) تکمیل کنید.",
                reply_markup=kb
            )
        except Exception:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ روش ارسال انتخاب نشده است.\n\nلطفاً از منوی اصلی گزینه «سبد خرید» را انتخاب کنید و سپس روی «ثبت سفارش» کلیک کنید.",
                reply_markup=kb
            )
        return

    # پاکسازی رزروهای منقضی شده (جلوگیری از قفل شدن موجودی)
    _cleanup_expired_reservations()

    order_id = _create_order_from_current_cart(update, context)
    if not order_id:
        await q.edit_message_text("❌ سبد خرید یا مشخصات مشتری کامل نیست. لطفاً دوباره تلاش کنید.", reply_markup=main_menu())
        return

    # ذخیره سفارش فعال برای لغو احتمالی
    context.user_data["active_order_id"] = order_id

    # رزرو موجودی قبل از ارسال کاربر به مرحله پرداخت/ارسال رسید
    ok = _reserve_inventory_for_order(order_id)
    if not ok:
        # سفارش ساخته شده ولی موجودی کافی نیست؛ کنسل و اطلاع‌رسانی
        STORE.update_order(order_id, status="cancelled", cancel_reason="out_of_stock")
        context.user_data.pop("active_order_id", None)
        await q.edit_message_text("❌ متأسفانه موجودی برخی اقلام تمام شد. لطفاً سبد خرید را بررسی کنید.", reply_markup=main_menu())
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
    
    # موجودی قبلاً در مرحله checkout_pay رزرو شده است؛ اینجا دیگر از موجودی کم نمی‌کنیم.
    STORE.update_order(
        order_id,
        status="paid",
        paid_at=datetime.utcnow().isoformat() + "Z",
        inventory_reserved=False,
        reserved_consumed_at=datetime.utcnow().isoformat() + "Z",
        payment={**order["payment"], "verify_raw": res.get("raw"), "track_id": res.get("track_id")}
    )

    context.user_data["cart"] = []
    context.user_data.pop("active_order_id", None)

    await q.edit_message_text(
        f"🎉 پرداخت با موفقیت انجام شد!\nشماره سفارش: {order_id}\n"
        f"کد رهگیری پرداخت: {res.get('track_id') or '—'}\n"
        f"مبلغ: {_ftm_toman(order['total'])}\n\n"
        "سفارش شما برای پردازش به ادمین ارسال شد.",
        reply_markup=main_menu()
    )

    if _has_admin_chat():
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
            await _broadcast_admin_message(context, msg)
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
            reply_markup=main_menu_reply(is_admin=_is_admin_activated(update))
        )
    else:
        await update.message.reply_text(text, reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)))

#      روتر کلی دکمه ها 
async def menu_router(update:Update , context:ContextTypes.DEFAULT_TYPE) -> None :
    q = update.callback_query
    data = (q.data or "").strip()



    # 🔒 دسترسی به callback های ادمین
    if (data.startswith("admin:") or data.startswith("ship:")) and not _is_admin_activated(update):
        await q.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return


    if data == "admin:dashboard":
        await admin_dashboard(update, context)
        return

    if data.startswith("admin:dashboard:"):
        # admin:dashboard:today|week|month
        period = data.split("admin:dashboard:", 1)[1].strip()
        if period in ("today", "week", "month"):
            await admin_dashboard_show_period(update, context, period)
        else:
            await admin_dashboard(update, context)
        return

    if data == "admin:queue":
        await admin_queue_show(update, context)
        return

    
    if data == "admin:shipped":
        await admin_shipped_show(update, context)
        return

    if data.startswith("admin:shipped:date:"):
        # admin:shipped:date:YYYY-MM-DD
        try:
            date_iso = data.split("admin:shipped:date:", 1)[1]
        except Exception:
            date_iso = ""
        await admin_shipped_show_date(update, context, date_iso)
        return

    if data == "admin:shipped:enter_date":
        # ask admin to type date (message will be captured by admin_text_reply)
        try:
            m = context.bot_data.setdefault("admin_pending_shipped_date", {})
            m[int(update.effective_chat.id)] = {"kind": "shipped_date"}
        except Exception:
            context.bot_data["admin_pending_shipped_date"] = {int(update.effective_chat.id): {"kind": "shipped_date"}}

        await admin_ui_send_or_edit(
            update,
            context,
            text="""📅 *تاریخ را وارد کنید*
فرمت‌های قابل قبول:
• 1404/10/14 (شمسی)
• 2026-01-04 (میلادی)

بعد از ارسال، همانجا لیست سفارش‌های ارسال‌شده‌ی آن تاریخ نمایش داده می‌شود.""",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ بازگشت", callback_data="admin:shipped")],
            ]),
            parse_mode="Markdown",
        )
        return

    if data.startswith("admin:open:"):
        # admin:open:<list_tag>:<order_id>
        _, _, list_tag, order_id = data.split(":", 3)

        if list_tag == "ready":
            back_to = "admin:queue"
        else:
            # اگر ادمین از نمای تاریخِ ارسال‌شده‌ها آمده باشد، همانجا برگردد
            try:
                back_to = (context.bot_data.get("admin_current_shipped_back", {}) or {}).get(
                    int(update.effective_chat.id),
                    "admin:shipped",
                )
            except Exception:
                back_to = "admin:shipped"

        await admin_open_order(update, context, order_id, back_to=back_to)
        return


    logger.info(f"Received callback data: {data}")
    logger.info(f"CATEGORY_MAP: {CATEGORY_MAP}")

    if data == "menu:back_home":
        await show_home_menu(update, context)
        return
        
    if data == "menu:products":
        await show_gender(update , context) ; return
    
    if data == "menu:cart":
        await show_cart(update , context) ; return

    if data == "menu:support":
        await q.edit_message_text(" پشتیبانی: @amirmehdi_84_10", reply_markup=main_menu()) ; return
        
    
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

        # پیام به مشتری (تحویل به تلگرام)
        ok, mid, err = await _safe_send_message(
            context,
            chat_id=int(order["user_chat_id"]),
            text=f"📦 سفارش {order_id} بسته‌بندی شد و به‌زودی ارسال می‌شود.",
            reply_markup=main_menu_reply(),
        )
        if ok:
            _order_log(order_id, "system", f"پیام بسته‌بندی به مشتری ارسال شد. msg_id={mid}")
            user_send_note = f"🟢 پیام به مشتری ارسال شد (تحویل تلگرام)\n🆔 msg_id: {mid}"
        else:
            _order_log(order_id, "system", f"ارسال پیام بسته‌بندی به مشتری ناموفق بود. err={err}")
            user_send_note = "🔴 ارسال پیام به مشتری ناموفق بود (خطای تلگرام/مسدود بودن ربات)."

        # ✅ آپدیت پنل واحد ادمین (بدون شلوغ‌کاری)
        order = STORE.find_order(order_id) or order
        back_to = (context.bot_data.get("admin_last_back_to", {}) or {}).get(int(update.effective_chat.id), "admin:queue")
        await admin_ui_send_or_edit(
            update,
            context,
            text="✅ وضعیت سفارش بروزرسانی شد: *بسته‌بندی شد*\n" + user_send_note + "\n\n" + _admin_order_summary(order),
            reply_markup=admin_order_keyboard(order_id, back_to=back_to),
        )

        # ✅ پیام وضعیت برای ادمین (Reply زیر پنل)
        base_id = context.bot_data.get(_admin_ui_key(update.effective_chat.id))
        await admin_ack_status(
            context,
            admin_chat_id=int(update.effective_chat.id),
            base_message_id=int(base_id) if base_id else None,
            ok=ok,
            action="بسته‌بندی شد",
            customer_msg_id=mid if ok else None,
            err=err if not ok else None,
        )

        await q.answer("ثبت شد ✅")
        return

    
    if data.startswith("ship:need_track:"):
        _, _, order_id = data.split(":", 2)
        # ذخیره سفارش در وضعیت انتظار کد رهگیری (برای همین چت ادمین)
        pending = context.bot_data.setdefault("admin_pending_tracking", {})
        sent = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔎 لطفاً کد رهگیری پست را تایپ کنید:"
        )
        pending[update.effective_chat.id] = {
            "order_id": order_id,
            "prompt_msg_id": sent.message_id,
            "back_to": (context.bot_data.get("admin_last_back_to", {}) or {}).get(int(update.effective_chat.id), "admin:queue"),
        }
        await q.answer("منتظر کد رهگیری…", show_alert=False)
        return

    
    if data.startswith("admin:msg:"):
        _, _, order_id = data.split(":", 2)
        pending = context.bot_data.setdefault("admin_pending_msg", {})
        sent = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✉️ لطفاً پیام را تایپ کنید تا برای مشتری ارسال شود:"
        )
        pending[update.effective_chat.id] = {
            "order_id": order_id,
            "prompt_msg_id": sent.message_id,
            "back_to": (context.bot_data.get("admin_last_back_to", {}) or {}).get(int(update.effective_chat.id), "admin:queue"),
        }

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
            "product_id" : pend["product_id"] ,
            "gender" : pend["gender"] , 
            "category" : pend["category"] , 
            "name" : pend["name"] , 
            "color" : pend.get("color") , 
            "size" : pend.get("size") , 
            "qty" : pend["qty"] , 
            "price" : pend["price"] ,  
        }
        cart = context.user_data.setdefault("cart" , [])
        _merge_cart_item(cart , item)
        context.user_data.pop("pending" , None)

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
            text=warning_message)
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
        oid = context.user_data.get("active_order_id") or context.user_data.get("awaiting_receipt")
        if oid:
            _release_inventory_for_order(oid, reason="کاربر سفارش را لغو کرد و رزرو آزاد شد.")
            STORE.update_order(oid, status="cancelled", cancel_reason="user_cancelled")

        context.user_data.pop("active_order_id", None)
        context.user_data.pop("awaiting_receipt", None)
        context.user_data.pop("cart" , None)
        context.user_data.pop("customer" , None)
        context.user_data.pop("pending" , None)
        context.user_data['awaiting'] = None
        await q.edit_message_text("❌ سفارش لغو شد. سبد خرید خالی شد.", reply_markup=main_menu())

# ✅ بازگرداندن منوی اصلی (Reply Keyboard)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="از منوی پایین می‌تونی ادامه بدی.",
            reply_markup=main_menu_reply(is_admin=_is_admin_activated(update)),
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
application.add_handler(CommandHandler("unadmin", admin_unregister))
application.add_handler(CommandHandler("myid", my_id))
application.add_handler(CommandHandler("dashboard", admin_dashboard))
application.add_handler(CommandHandler("sales", admin_dashboard))

# Conversation Handler برای فرم مشتری
conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(begin_customer_form, pattern=r"^checkout:begin$")],
    states={
        CUSTOMER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],
        CUSTOMER_PHONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, on_text),
            MessageHandler(filters.CONTACT, on_contact)
        ],
        CUSTOMER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],
        CUSTOMER_POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],
        CUSTOMER_SHIPPING: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],  # جدید
    },
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
