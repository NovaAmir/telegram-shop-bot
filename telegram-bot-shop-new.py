from telegram import (Update , InlineKeyboardButton , InlineKeyboardMarkup , ReplyKeyboardMarkup , ReplyKeyboardRemove)
from telegram.ext import (ApplicationBuilder , CommandHandler , ContextTypes , CallbackQueryHandler , Application , MessageHandler , filters , ConversationHandler)
import logging
import os
import json
import uuid
import re
from datetime import datetime
from typing import Dict,List,Optional,Tuple
import emoji
import requests
import asyncio
import threading
from flask import Flask, request


CUSTOMER_NAME, CUSTOMER_PHONE, CUSTOMER_ADDRESS, CUSTOMER_POSTAL = range(4)

logging.basicConfig(level=logging.INFO,format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN","").strip()
if not BOT_TOKEN :
    logger.warning("⚠️ متغییر محیطی BOT_TOKEN تنظیم نشده است . قبل از اجرا آن را ست کنید ")

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID" , "").strip() or None


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


#        catalog
CATALOG: Dict[str,Dict[str,List[Dict]]] = {
    "men":{
        "کفش":[
            {"id": "men-shoe-running-hobi-gs8226" , 
             "name":"کفش رانینگ هابی مدل GS8226" , 
             "thumbnail" : "https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/35adcfd858a7dc85c88988f3d5c45ae20c715a02_1752785555.webp" ,
             "variants": {
                 "مشکی" : {
                     "photo" : "https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/35adcfd858a7dc85c88988f3d5c45ae20c715a02_1752785555.webp" ,
                     "price" : 1_500_000 ,
                     "sizes" : {"40":3 , "41":1 , "42":4 , "43":3 ,  "44":2}
                    },
                 "سفید" : {
                     "photo" : "https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/15b7fe4d53208c04e109aa3bce8d099153a00f5c_1752815442.webp" ,
                     "price" : 1_300_000 ,
                     "sizes" : {"40":2 , "41":0 , "42":3 , "43":2 , "44":1}
                 }
                }    
            },
            # FIX: شناسه محصول حاوی فاصله برای Air Force 1
            {"id":"men-shoe-Air-Force-1-WH-1990" , 
             "name":"کفش پیاده روی مردانه مدل Air Force 1 WH 1990" ,
             "thumbnail":"https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/5665c3110aee39673eb5818ad1e5460c85a5e4e8_1657457249.webp" , 
             "variants":{
                 "مشکی" : {
                     "photo" : "https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/download.webp" , 
                     "price" : 650_000 , 
                     "sizes" : {"39":3 , "40":5 , "42":2 , "43":1}
                 },
                 "سفید" : {
                     "photo" : "https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/5665c3110aee39673eb5818ad1e5460c85a5e4e8_1657457249.webp" ,
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
             "thumbnail": "https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/9a7c3ddeb6558e2d798678b89df60d6f801be3fd_1723288662.webp" ,
             "price" : 3_000_000 ,
             "sizes":{"L":4 , "XL":5 , "XXL":3}
             },
             {"id":"men-shirt-SB-SS-4513" , 
              "name":"پیراهن آستین بلند مردانه مدل SB-SS-4513" , 
              "thumbnail":"https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/2e31b5f7959ecb020cd95af79c22bb97a96d7c46_1703611532.webp" , 
              "price": 2_500_000 ,
              "sizes":{"L":3 , "XL":4 , "XXL":2}
              }
        ],
        "تی شرت" : [
            {"id":"men-Tshirt-model TS63 B" , 
             "name":"تی شرت اورسایز مردانه نوزده نودیک مدل TS63 B" , 
             "thumbnail":"https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/6d5e77c9b3f25d11050c9e714675678b38314efa_1755035663.webp" , 
             "price" : 900_000 ,
             "sizes":{"L":3 , "XL":4 , "XXL":4}
             },
             {"id":"men-Tshirt-model TS1962 B" , 
              "name":"تی شرت ورزشی مردانه نوزده نودیک مدل TS1962 B" ,
              "thumbnail":"https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/deaaf226e0ef806723b4972f933cfffc6e5e9a76_1675938042.webp" , 
              "variants":{
                  "مشکی":{
                      "photo":"https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/d311f870573c4c6b8735dff9cebb5444228fe3ba_1675937971.webp" , 
                      "price":550_000 , 
                      "sizes":{"L":2 , "XL":2 , "XXL":2}

                  },
                  "سفید":{
                      "photo":"https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/668c0ffa1728779857a691c38d95a2bd6da9e3b2_1675853820.webp" , 
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
             "thumbnail": "https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/90ebe7a01f96086e63f0fc631962b019b9a4a75b_1732030099.webp" , 
             "price": 9_100_000 , 
             "sizes" : {"40":2 , "41":0 , "42":3 , "43":2 , "44":1}
             },
             {"id":"women-shoe-3Fashion M.D" , 
              "name":"کفش روزمره زنانه مدل Fashion سه چسب M.D" , 
              "thumbnail": "https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/285ea7731ca73c3dc525744bfda9cc41d2be5183_1635272433.webp" , 
              "variants":{
                  "مشکی":{
                      "photo":"https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/e36e35ddb30e9943407173f4a179e18fc4e7cb3e_1638708382.webp" , 
                      "price":520_000 , 
                      "sizes":{"40":3 , "41":2 , "43":3}
                  },
                  "سفید":{
                      "photo":"https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/ec042c22e457c96251c3d014d513aefd96cf593_1635272463.webp" , 
                      "price":540_000 , 
                      "sizes":{"40":3 , "41":2 , "43":2 , "44":3}
                  }
              }
                 
             }
        ],
        "شلوار":[
             {"id":"women-pants-bag-lenin" , 
              "name":"شلوار زنانه مدل بگ لینن کنفی" , 
              "thumbnail":"https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/55ceaeb80ec2d0464a47880afd966769f00e3faa_1748870325.webp" , 
              "price":800_000 , 
              "sizes":{"44":6 , "46":5 , "50":3 , "52":4}
              } , 
            {"id":"women-pants-rita-m-kerm" , # شناسه کوتاه شده برای جلوگیری از Button_data_invalid
             "name":"شلوار زنانه مدل ریتا مازراتی راسته رنگ کرم روشن" ,
             "thumbnail":"https://github.com/NovaAmir/telegram_shop_image/raw/main/20251112222400589692652.jpg" , 
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


#     منوها

def main_menu_reply() -> ReplyKeyboardMarkup:
    """ساخت کیبورد Reply برای منو اصلی (پایین صفحه)"""
    keyboard = [
        ["🛍️ لیست محصولات", "🧺 سبد خرید"] , 
        ["🆘 پشتیبانی"],
    ]
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

def _find_product(gender:str , category:str , product_id:str) -> Optional[Dict]:
    for p in CATALOG.get(gender , {}).get(category , []):
        if p.get("id") == product_id:
            return p 
    return None


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

# **[جدید]** توابع کمکی برای مدیریت سبد خرید (حذف/کم و زیاد کردن)
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


#   /start

async def start(update:Update , context:ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        context.user_data.pop("cart", None)
    context.user_data.pop("pending", None)
    context.user_data.pop("customer", None)
    context.user_data.pop("awaiting", None)
    text = emoji.emojize("سلام:waving_hand:\n به ربات فروشگاه ... خوش آمدید . \n لطفا یکی از گزینه های زیر را انتخاب کنید")
    
    # ⭐️ اصلاح: سازگار کردن با CallbackQuery ⭐️
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        # ویرایش پیام قبلی با دکمه‌های Inline به متن ساده
        await q.edit_message_text(text) 
        # ارسال یک پیام جدید با Reply Keyboard
        await q.message.reply_text(text , reply_markup=main_menu_reply())
    else:
        await update.message.reply_text(text , reply_markup=main_menu_reply())


#     نمایش مراحل

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
            await context.bot.send_message(chat_id=update.effective_chat.id, text="فعلا محصولی در این دسته نیست", reply_markup=category_keyboard(gender))
        return

    # سعی می‌کنیم پیام اولیه را ویرایش کنیم؛ در صورت شکست، پیام جدید می‌فرستیم
    title = f"👇 محصولات دسته «{category}» 👇"
    try:
        await q.edit_message_text(title)
    except Exception as e:
        logger.debug("Could not edit message for product list header: %s", e)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=title)

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

        # ارسال مقاوم: اول تلاش برای ارسال عکس (اگر موجود)، در صورت خطا یا نبود عکس -> ارسال متن
        try:
            if photo:
                # از context.bot.send_photo استفاده کنیم چون معمولاً پایدارتر است
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo, caption=caption, reply_markup=keyboard)
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=caption, reply_markup=keyboard)
        except Exception as e:
            logger.warning("Failed to send product %s (id=%s): %s. Falling back to text.", p.get("name"), p.get("id"), e)
            try:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"{caption}\n(⚠️ تصویر قابل نمایش نیست)", reply_markup=keyboard)
            except Exception as e2:
                logger.error("Fallback send_message also failed for product %s: %s", p.get("id"), e2)
        # کمی صبر کن تا telegram مانع نشه (معمولاً مشکل race/flood حل میشه)
        try:
            await asyncio.sleep(0.08)
        except Exception:
            pass

    # پیام راهنما و دکمه بازگشت (در انتها)
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"دسته: {category}\nبرای انتخاب هر محصول روی دکمهٔ زیر عکس آن کلیک کن.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ انتخاب دسته دیگر", callback_data=f"catalog:gender:{gender}")],
                [InlineKeyboardButton("🏠 منو اصلی", callback_data="menu:back_home")],
            ])
        )
    except Exception as e:
        logger.debug("Failed to send category footer: %s", e)
    
async def ask_color_and_size(update:Update, context:ContextTypes.DEFAULT_TYPE, gender:str, category:str, product_id:str) -> None:
    q = update.callback_query
    await q.answer()

    p = _find_product(gender, category, product_id)
    if not p or "variants" not in p:
        await q.message.reply_text("محصول یا رنگ‌ها پیدا نشد.", reply_markup=category_keyboard(gender))
        return

    rows = []
    # در اینجا از enumerate استفاده می‌کنیم تا به جای ارسال نام طولانی رنگ، فقط ایندکس آن را در callback بفرستیم.
    for i, (color, v) in enumerate(p["variants"].items()):
        available_sizes = [sz for sz, qty in v["sizes"].items() if qty > 0]
        for sz in available_sizes:
            btn_text = f"{color} | سایز {sz}"
            rows.append([InlineKeyboardButton(
                btn_text,
                # استفاده از ایندکس رنگ (i) به جای نام آن برای کوتاه شدن callback_data
                callback_data=f"catalog:choose:{gender}:{_safe_callback(category)}:{product_id}:{i}:{sz}"
            )])
    
    if not rows:
        await q.message.reply_text("هیچ رنگ و سایزی برای این محصول موجود نیست.", reply_markup=category_keyboard(gender))
        return
        
    rows.append([InlineKeyboardButton("⬅️ انتخاب محصول دیگر", callback_data=f"catalog:category:{gender}:{_safe_callback(category)}")])

    await q.message.reply_text(
        f"✅ {p['name']}\nلطفاً رنگ و سایز را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(rows)
    )
    

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

    p = _find_product(gender, category, product_id)
    if not p or "sizes" not in p:
        await q.message.reply_text("محصول یا سایزها پیدا نشد.", reply_markup=category_keyboard(gender))
        return
    available_sizes = [sz for sz, qty in p["sizes"].items() if qty > 0]
    # FIX: اطمینان از اینکه product_id با وجود اصلاحات، به درستی در callback استفاده شود.
    rows = [[InlineKeyboardButton(f"سایز {sz}", callback_data=f"catalog:chooseonly:{gender}:{_safe_callback(category)}:{product_id}:{sz}")] for sz in available_sizes]
    rows.append([InlineKeyboardButton("⬅️ انتخاب محصول دیگر", callback_data=f"catalog:category:{gender}:{_safe_callback(category)}")])
    
    await q.message.reply_text(
        f"✅ {p['name']}\nلطفاً سایز را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(rows)
    )


# این تابع را در کنار سایر توابع Asynchronous (Async) ربات تعریف کنید
async def menu_reply_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    روتر برای مدیریت پیام‌های متنی دریافتی از دکمه‌های Reply Keyboard (پایین صفحه).
    """
    # در این هندلر، update.message همیشه وجود دارد.
    text = update.message.text
    
    if text == "🛍️ لیست محصولات":
        # فراخوانی show_categories (که اکنون قابلیت مدیریت Message را دارد)
        await show_gender(update, context) 
    
    elif text == "🧺 سبد خرید":
        # فراخوانی show_cart (که اکنون قابلیت مدیریت Message را دارد)
        await show_cart(update, context)
        
    elif text == "🆘 پشتیبانی":
        # پاسخ مستقیم به کاربر
        await update.message.reply_text("برای پشتیبانی با @Admin_ID تماس بگیرید.")
        

async def show_qty_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, chosen_size):
    q = update.callback_query
    await q.answer()

    pend = context.user_data.get("pending")
    if not pend:
        await q.message.reply_text("اطلاعات محصول ناقص است.", reply_markup=main_menu())
        return
    
    # برای محصولات بدون رنگ
    p = _find_product(pend["gender"], pend["category"], pend["product_id"])
    if not p:
        await q.message.reply_text("محصول پیدا نشد.", reply_markup=main_menu())
        return
        
    sizes = p.get("sizes")
    price = p.get("price")
    
    if "variants" in p and pend.get("color"):
        # اگر محصول دارای رنگ بود، از وریانت‌های آن استفاده می‌کنیم
        color_variant = p["variants"].get(pend["color"])
        if color_variant:
            sizes = color_variant.get("sizes")
            price = color_variant.get("price")

    if not sizes or chosen_size not in sizes:
        await q.message.reply_text("سایز انتخابی معتبر نیست.", reply_markup=main_menu())
        return
        
    available = int(sizes.get(chosen_size, 0))
    if available <= 0:
        await q.message.reply_text("این سایز موجود نیست.", reply_markup=main_menu())
        return

    pend["size"] = chosen_size
    pend["available"] = available
    pend["qty"] = 1
    # قیمت واحد را با توجه به محصول یا وریانت آپدیت می‌کنیم
    pend["price"] = price 

    photo = _product_photo_for_list(p)
    cap = (
        f"{p['name']}\nسایز: {chosen_size}\n"
        f"موجودی: {available}\n"
        f"قیمت واحد: {_ftm_toman(price)}\n"
        f"قیمت نهایی: {_ftm_toman(price)}"
    )
    if photo:
        # FIX: افزودن try/except برای جلوگیری از توقف برنامه در صورت عدم ارسال عکس
        try:
            await q.message.reply_photo(photo=photo, caption=cap, reply_markup=qty_keyboard(1, available))
        except Exception as e:
            logger.error(f"Failed to send photo in qty picker for {p.get('id')}: {e}. Falling back to text.")
            await q.message.reply_text(cap, reply_markup=qty_keyboard(1, available))
    else:
        await q.message.reply_text(cap, reply_markup=qty_keyboard(1, available))


async def show_qty_picker_combined(update: Update, context: ContextTypes.DEFAULT_TYPE, gender, category, product_id, color, size):
    q = update.callback_query
    await q.answer()

    p = _find_product(gender, category, product_id)
    # اینجا نیازی به چک کردن color in p["variants"] نیست چون color را از ایندکس گرفته‌ایم
    if not p or "variants" not in p:
        await q.message.reply_text("محصول یا رنگ انتخابی معتبر نیست.", reply_markup=main_menu())
        return
    v = p["variants"][color]
    available = int(v["sizes"].get(size, 0))
    if available <= 0:
        await q.message.reply_text("این سایز موجود نیست.", reply_markup=main_menu())
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
    if photo:
        # FIX: افزودن try/except برای جلوگیری از توقف برنامه در صورت عدم ارسال عکس
        try:
            await q.message.reply_photo(photo=photo, caption=cap, reply_markup=qty_keyboard(1, available))
        except Exception as e:
            logger.error(f"Failed to send photo in combined qty picker for {p.get('id')}: {e}. Falling back to text.")
            await q.message.reply_text(cap, reply_markup=qty_keyboard(1, available))
    else:
        await q.message.reply_text(cap, reply_markup=qty_keyboard(1, available))


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
            item_text += f" تعداد: {item['qty']} / موجودی: {max_qty} عدد\n" # ⭐️ (جدید) نمایش موجودی ⭐️
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
            InlineKeyboardButton("✅ ثبت سفارش و پرداخت", callback_data="checkout:info"),
            InlineKeyboardButton("🏠 بازگشت به منو", callback_data="start")
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
            await q.edit_message_caption(caption=text , reply_markup=reply_markup , parse_mode="Markdown")
        else:
            await q.edit_message_text(text , reply_markup=reply_markup , parse_mode="Markdown")
    else:
        # اگر از دکمه Reply Keyboard آمده (Message)
        # یک پیام جدید ارسال می‌شود
        await update.message.reply_text(text , reply_markup=reply_markup , parse_mode="Markdown")
    return


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
        await update.message.reply_text("برای پشتیبانی با @Admin_ID تماس بگیرید.")


async def begin_customer_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if context.user_data.get("cart"):
        await q.edit_message_text(
            "نام و نام خانوادگی را وارد کن:",
            reply_markup = InlineKeyboardMarkup.from_button(
                InlineKeyboardButton("انصراف" , callback_data="flow:cancel")
            ),
        )
        context.user_data["awaiting"] = "name"
        return CUSTOMER_NAME
    else:
        # اینجا باید به منو اصلی برگردد نه اینکه پیغام خطا را در context:checkout:begin نمایش دهد.
        await q.edit_message_text("❌ سبد خرید شما خالی است. ابتدا محصولی انتخاب کنید.", reply_markup=main_menu())
        return ConversationHandler.END



async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return 
    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return
    
    text = update.message.text.strip()

    if awaiting == "name":
        context.user_data.setdefault("customer", {})["name"] = text
        context.user_data["awaiting"] = "phone"
        kb = ReplyKeyboardMarkup(
            [[{"text": "📱 ارسال شماره من", "request_contact": True}]],
            resize_keyboard=True, one_time_keyboard=True
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
            elif not phone.startswith("0"):
                phone = "0" + phone # اضافه کردن 0 اگر با 9 شروع شده باشد
            
            context.user_data["customer"]["phone"] = phone
            context.user_data["awaiting"] = "address"
            await update.message.reply_text("آدرس:", reply_markup=ReplyKeyboardRemove())
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
            await show_checkout_summary(update.message, context)
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
        await update.message.reply_text("آدرس:", reply_markup=ReplyKeyboardRemove())
        return CUSTOMER_ADDRESS
    else:
        await update.message.reply_text("شمارهٔ دریافتی نامعتبر بود. لطفاً دستی وارد کن.")
        return CUSTOMER_PHONE


async def show_checkout_summary(update_or_msg, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(update_or_msg, Update):
        chat_id = update_or_msg.effective_chat.id
        send = context.bot.send_message
    else: # اگر مستقیماً از یک message فراخوانی شده است
        chat_id = update_or_msg.chat.id
        send = update_or_msg.reply_text
    
    cart = context.user_data.get("cart" , [])
    customer = context.user_data.get("customer" , {})
    total = _calc_cart_total(cart)

    lines = []
    for i , it in enumerate(cart , 1):
        lines.append(
            f"{i}) {it['name']} | رنگ: {it.get('color') or '—'} | سایز: {it.get('size') or '—'} | "
            f"تعداد: {it['qty']} | {_ftm_toman(it['qty'] * it['price'])}"
        )
    
    # 🟢 تغییر: نمایش خلاصه سفارش و اطلاعات مشتری با فرمت Markdown
    info = (
        "🧾 **خلاصه سفارش و مشخصات مشتری**:\n\n"
        "👤 **نام و نام خانوادگی**: `{name}`\n"
        "📞 **شماره موبایل**: `{phone}`\n"
        "🏠 **آدرس**: `{address}`\n"
        "📮 **کد پستی**: `{postal}`\n\n"
        "🛍️ **محصولات سفارش داده شده**:\n"
        f"{'\n'.join(lines)}\n\n"
        f"💰 **مبلغ قابل پرداخت**: **{_ftm_toman(total)}**"
    ).format(
        name=customer.get('name', '—'),
        phone=customer.get('phone', '—'),
        address=customer.get('address', '—'),
        postal=customer.get('postal', '—')
    )
    
    # 🟢 تغییر: متن دکمه پرداخت به حالت Placeholder
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ ویرایش مشخصات", callback_data="checkout:begin")],
        [InlineKeyboardButton("💳 اقدام به پرداخت نهایی (فعلا غیرفعال)", callback_data="checkout:pay")], # تغییر متن دکمه
        [InlineKeyboardButton("❌ لغو سفارش", callback_data="checkout:cancel")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")]
    ])
    await send(chat_id=chat_id, text=info, reply_markup=kb, parse_mode="Markdown")


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
    await q.answer("فعلاً درگاه پرداخت غیرفعال است. لطفاً بعداً تلاش کنید.", show_alert=True)
    # اگر در آینده خواستید پرداخت را فعال کنید، بقیه منطق باید اینجا باشد
    return # توقف در همین مرحله طبق درخواست کاربر

    # cart = context.user_data.get("cart" , [])
    # customer = context.user_data.get("customer", {})
    # ... (بقیه منطق پرداخت) ...


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
        ok = _decrement_inventory(it)
        if not ok:
            logger.error("Inventory not enough for %s", it)
    
    STORE.update_order(
        order_id,
        status="paid",
        payment={**order["payment"], "verify_raw": res.get("raw"), "track_id": res.get("track_id")}
    )

    context.user_data["cart"] = []

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
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=msg)
        except Exception as e:
            logger.error("Failed to notify admin: %s", e)
        

#      روتر کلی دکمه ها 
async def menu_router(update:Update , context:ContextTypes.DEFAULT_TYPE) -> None :
    q = update.callback_query
    await q.answer() # پاسخ به کلیک اولیه برای حذف لودینگ
    data = (q.data or "").strip() 

    logger.info(f"Received callback data: {data}")
    logger.info(f"CATEGORY_MAP: {CATEGORY_MAP}")

    if data == "menu:back_home":
        await start(update , context) ; return
        
    if data == "menu:products":
        await show_gender(update , context) ; return
    
    if data == "menu:cart":
        await show_cart(update , context) ; return

    if data == "menu:support":
        await q.edit_message_text(" پشتیبانی: @amirmehdi_84_10", reply_markup=main_menu()) ; return
        
    # **[تغییر]** شروع بخش هندلرهای سبد خرید
    # ------------------ مدیریت سبد خرید ------------------
    cart: List[Dict] = context.user_data.get("cart" , [])
    
    # ⭐️ توجه: منطق cart:del: در این نسخه حذف شده بود و توسط شما به عنوان "محصول #i" جایگزین شده بود. 
    # برای جلوگیری از خطا، این بخش را کامنت می‌کنم تا در صورت نیاز بتوانید آن را برگردانید.
    # if data.startswith("cart:del:"):
    #     _, _, index_str = data.split(":", 2)
    #     try:
    #         index = int(index_str)
    #         if _delete_cart_item(cart, index):
    #             await show_cart(update, context) # نمایش مجدد سبد خرید به‌روز شده
    #         else:
    #             await q.answer("❌ خطای حذف آیتم.", show_alert=True)
    #     except Exception:
    #         await q.answer("❌ خطای حذف آیتم.", show_alert=True)
    #     return
        
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
        await q.answer("این دکمه فقط تعداد فعلی/موجودی را نشان می‌دهد." , show_alert=False) ; return # ⭐️ تغییر متن پیام ⭐️
        
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
            f"\nقیمت نهایی:{_ftm_toman(pend['price'] * pend["qty"])}"
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
            text=warning_message,
            parse_mode="Markdown"
        )
        # ----------------------------------------------------

        txt = "✅ به سبد خرید اضافه شد.\nمی‌تونی ادامه بدی یا سبد خرید رو ببینی:"
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
        context.user_data.pop("pending" , None)
        context.user_data['awaiting'] = None
        await q.edit_message_text("لغو شد.", reply_markup=main_menu())
        return
    

    if data == "checkout:begin":
        # توجه: این callback در Conversation Handler مدیریت می‌شود، اما اینجا برای جلوگیری از خطای "گزینه نامعتبر" نگه داشته می‌شود.
        # در حقیقت، این خط نباید اجرا شود چون در entry_points Conversation Handler گرفته می‌شود.
        if context.user_data.get("cart"):
            # اگر در ConvHandler گرفته نشد، اینجا آغاز شود
            await begin_customer_form(update , context)
            return 
        else:
            await q.answer("❌ سبد خرید شما خالی است.", show_alert=True)
            await q.edit_message_text("❌ سبد خرید شما خالی است. ابتدا محصولی انتخاب کنید.", reply_markup=main_menu())
            return
    

    if data == "checkout:pay":
        await checkout_pay(update , context) ; return
    
    # نیاز به هندلر برای لغو سفارش
    if data == "checkout:cancel":
        context.user_data.pop("cart" , None)
        context.user_data.pop("customer" , None)
        context.user_data.pop("pending" , None)
        context.user_data['awaiting'] = None
        await q.edit_message_text("❌ سفارش لغو شد. سبد خرید خالی شد.", reply_markup=main_menu())
        return

    if data.startswith("checkout:verify:"):
        _, _, order_id = data.split(":", 2)
        await checkout_verify(update, context, order_id); return
    

    await q.edit_message_text("❌ گزینه نامعتبر.", reply_markup=main_menu())


#        /start و اجرای برنامه
# ساخت اپلیکیشن PTB
application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))

# Conversation Handler برای فرم مشتری
conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(begin_customer_form, pattern=r"^checkout:begin$")],
    states={
        CUSTOMER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],
        CUSTOMER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text), MessageHandler(filters.CONTACT, on_contact)],
        CUSTOMER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],
        CUSTOMER_POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],
    },
    fallbacks=[CallbackQueryHandler(menu_router, pattern=r"^flow:cancel$")]
)
application.add_handler(conv_handler)


# هندلرهای اصلی (بعد از Conversation Handler)
application.add_handler(CallbackQueryHandler(menu_router))
# MessageHandler برای تماس و متن باید حذف شود چون در Conversation Handler مدیریت می‌شوند.
# application.add_handler(MessageHandler(filters.CONTACT , on_contact))
# application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND , on_text))
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
