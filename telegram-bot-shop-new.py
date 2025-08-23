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
    val = re.sub(r'[^\w\-]', '', val)
    return val[:20]  # حداکثر 20 کاراکتر


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
            {"id":"men-shoe-Air Force 1 WH 1990" , 
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
            {"id":"men-shirt-model MDSS-CG3719" , 
             "name":"پیراهن آستین بلند مردانه مدل MDSS-CG3719" , 
             "thumbnail": "https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/9a7c3ddeb6558e2d798678b89df60d6f801be3fd_1723288662.webp" ,
             "price" : 3_000_000 ,
             "sizes":{"L":4 , "XL":5 , "XXL":3}
             },
             {"id":"men-shirt-model SB-SS-4513" , 
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
                      "photo":"https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/ec042c22e457c962511c3d014d513aefd96cf593_1635272463.webp" , 
                      "price":540_000 , 
                      "sizes":{"40":3 , "41":2 , "43":2 , "44":3}
                  }
              }
                 
             }
        ],
        "شلوار":[
            {"id":"women-pants-mazerati_raste_kerem" , 
             "name":"شلوار زنانه مدل ریتا مازراتی راسته رنگ کرم روشن" ,
             "photo":"https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/4cda707f7d8e25ccdfdc4fab12d0e43552624376_1722364117.webp" , 
             "price":560_000 , 
             "sizes":{"44":3 , "46":3 , "50":2 , "52":4}
             },
             {"id":"women-pants-bag_lenin" , 
              "name":"شلوار زنانه مدل بگ لینن کنفی" , 
              "photo":"https://github.com/NovaAmir/telegram_shop_image/raw/refs/heads/main/55ceaeb80ec2d0464a47880afd966769f00e3faa_1748870325.webp" , 
              "price":800_000 , 
              "sizes":{"44":6 , "46":5 , "50":3 , "52":4}
              }
        ]
    }
}

CATALOG = STORE.get_catalog(CATALOG)

# ...existing code...
CATEGORY_MAP = {}
for gender in CATALOG:
    for cat in CATALOG[gender]:
        CATEGORY_MAP[_safe_callback(cat)] = cat
# ...existing code...


#     منوها

def main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🛍️ لیست محصولات", callback_data="menu:products")] , 
        [InlineKeyboardButton("🧺 سبد خرید", callback_data="menu:cart")] , 
        [InlineKeyboardButton("🆘 پشتیبانی", callback_data="menu:support")],]
    return InlineKeyboardMarkup(keyboard)


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


def colors_keyboard(gender:str , category:str , product_id:str) -> InlineKeyboardMarkup:
    product = _find_product(gender , category , product_id)
    assert product and "variants" in product
    colors = list(product["variants"].keys())
    rows = []
    for i in range(0 , len(colors) , 2):
        chunk = colors[i:i+2]
        rows.append([InlineKeyboardButton(col , callback_data=f"catalog:color:{gender}:{_safe_callback(category)}:{product_id}:{_safe_callback(col)}")for col in chunk])
    rows.append([InlineKeyboardButton("⬅️ انتخاب محصول دیگر " , callback_data=f"catalog:category:{gender}:{_safe_callback(category)}")])
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
    if p.get("thumbnail"):
        return p["thumbnail"]
    if p.get("photo"):
        return p["photo"]
    if "variants" in p and p["variants"]:
        first_color = next(iter(p["variants"].values()))
        return first_color.get("photo")
    return None


def _unit_price_and_sizes(p:Dict , color:Optional[str]) -> Tuple[int , Dict[str,int]]:
    if "variants" in p and color :
        v = p["variants"][color]
        return v["price"] , v["sizes"]
    return p["price"] , p["sizes"]


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
    text = emoji.emojize("سلام:waving_hand:\n به ربات فروشگاه ... خوش آمدید . \n لطفا یکی از گزینه های زیر را انتخاب کنید")
    if update.message:
        await update.message.reply_text(text , reply_markup=main_menu())
    else:
        q = update.callback_query
        await q.edit_message_text(text , reply_markup=main_menu())


#     نمایش مراحل

async def show_gender(update:Update , context:ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("جنسیت رو انتخاب کن :" , reply_markup=gender_keyboard())


async def show_categories(update:Update , context:ContextTypes.DEFAULT_TYPE , gender:str) -> None:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(f"انتخاب جنسیت: {'👨 مردانه' if gender=='men' else '👩 زنانه'}\nحالا نوع محصول رو انتخاب کن:", reply_markup=category_keyboard(gender))


async def show_products(update:Update , context:ContextTypes.DEFAULT_TYPE , gender:str , category:str) -> None:
    q = update.callback_query
    await q.answer()
    items = CATALOG.get(gender , {}).get(category , [])
    if not items:
        await q.edit_message_text("فعلا محصولی در این دسته نیست" , reply_markup = category_keyboard(gender))
        return

    for p in items:
        if "variants" in p:
            btn = InlineKeyboardButton("انتخاب", callback_data=f"catalog:select:{gender}:{_safe_callback(category)}:{p['id']}")
        else:
            btn = InlineKeyboardButton("انتخاب", callback_data=f"catalog:select:{gender}:{_safe_callback(category)}:{p['id']}")
        photo = _product_photo_for_list(p)
        caption = f"{p['name']}"

        # ساخت دکمه انتخاب مناسب هر محصول
        if "variants" in p:
            # محصول هم رنگ دارد هم سایز
            btn = InlineKeyboardButton("انتخاب", callback_data=f"catalog:select:{gender}:{_safe_callback(category)}:{p['id']}")
        else:
            # محصول فقط سایز دارد
            btn = InlineKeyboardButton("انتخاب", callback_data=f"catalog:sizeonly:{gender}:{_safe_callback(category)}:{p['id']}")

        keyboard = InlineKeyboardMarkup([[btn]])

        if photo:
            await q.message.reply_photo(photo=photo, caption=caption, reply_markup=keyboard)
        else:
            await q.message.reply_text(caption, reply_markup=keyboard)

    # پیام راهنما و دکمه بازگشت
    await q.message.reply_text(
        f"دسته: {category}\nبرای انتخاب هر محصول روی دکمه زیر عکس آن کلیک کن.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ انتخاب دسته دیگر", callback_data=f"catalog:gender:{gender}")],
            [InlineKeyboardButton("🏠 منو اصلی", callback_data="menu:back_home")],
        ])
   )
    
async def ask_color_and_size(update:Update , context:ContextTypes.DEFAULT_TYPE , gender:str , category:str , product_id:str) -> None:
    q = update.callback_query
    await q.answer()

    p = _find_product(gender , category , product_id)
    if not p or "variants" not in p:
        await q.message.reply_text("محصول یا رنگ‌ها پیدا نشد.", reply_markup=category_keyboard(gender))
        return

    rows = []
    for color, v in p["variants"].items():
        available_sizes = [sz for sz, qty in v["sizes"].items() if qty > 0]
        for sz in available_sizes:
            btn_text = f"{color} | سایز {sz}"
            rows.append([InlineKeyboardButton(
                btn_text,
                callback_data=f"catalog:choose:{gender}:{_safe_callback(category)}:{product_id}:{_safe_callback(color)}:{sz}"
            )])
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
    rows = [[InlineKeyboardButton(f"سایز {sz}", callback_data=f"catalog:chooseonly:{gender}:{_safe_callback(category)}:{product_id}:{sz}")] for sz in available_sizes]
    rows.append([InlineKeyboardButton("⬅️ انتخاب محصول دیگر", callback_data=f"catalog:category:{gender}:{_safe_callback(category)}")])
    
    await q.message.reply_text(
        f"✅ {p['name']}\nلطفاً سایز را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(rows)
    )
    


async def show_qty_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, chosen_size):
    q = update.callback_query
    await q.answer()

    pend = context.user_data.get("pending")
    if not pend:
        await q.message.reply_text("اطلاعات محصول ناقص است.", reply_markup=main_menu())
        return
    p = _find_product(pend["gender"], pend["category"], pend["product_id"])
    if not p or "sizes" not in p or chosen_size not in p["sizes"]:
        await q.message.reply_text("سایز انتخابی معتبر نیست.", reply_markup=main_menu())
        return
    available = int(p["sizes"].get(chosen_size, 0))
    if available <= 0:
        await q.message.reply_text("این سایز موجود نیست.", reply_markup=main_menu())
        return

    pend["size"] = chosen_size
    pend["available"] = available
    pend["qty"] = 1

    photo = _product_photo_for_list(p)
    cap = (
        f"{p['name']}\nسایز: {chosen_size}\n"
        f"موجودی: {available}\n"
        f"قیمت واحد: {_ftm_toman(p['price'])}\n"
        f"قیمت نهایی: {_ftm_toman(p['price'])}"
    )
    if photo:
        await q.message.reply_photo(photo=photo, caption=cap, reply_markup=qty_keyboard(1, available))
    else:
        await q.message.reply_text(cap, reply_markup=qty_keyboard(1, available))


async def show_qty_picker_combined(update: Update, context: ContextTypes.DEFAULT_TYPE, gender, category, product_id, color, size):
    q = update.callback_query
    await q.answer()

    p = _find_product(gender, category, product_id)
    if not p or "variants" not in p or color not in p["variants"]:
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
        await q.message.reply_photo(photo=photo, caption=cap, reply_markup=qty_keyboard(1, available))
    else:
        await q.message.reply_text(cap, reply_markup=qty_keyboard(1, available))


#       cart / checkout
PHONE_REGEX = re.compile(r"^09\d{9}$")

async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    cart = context.user_data.get("cart" , [])
    if not cart:
        await q.edit_message_text("🧺 سبد خرید خالی است.", reply_markup=main_menu())
        return
    
    lines = []
    total = 0
    for i , it in enumerate(cart , 1):
        subtotal = it["qty"] * it["price"]
        total += subtotal
        lines.append(
            f"{i}) {it['name']} | رنگ: {it.get('color') or '—'} | سایز: {it.get('size') or '—'} | "
            f"تعداد: {it['qty']} | هزینه: {_ftm_toman(subtotal)}"
        )
    txt = "اقلام سبد خرید:\n\n" + "\n".join(lines) + f"\n\nجمع کل: {_ftm_toman(total)}"
    await q.edit_message_text(txt , reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧾 ادامه و ثبت مشخصات", callback_data="checkout:begin")] , 
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")]
    ]))


async def begin_customer_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if context.user_data.get("cart"):
        await q.edit_message_text(
            "نام و نام خانوادگی را وارد کن:",
            reply_markup = InlineKeyboardMarkup.from_button(
                InlineKeyboardButton("انصراف" , callback_data="cancel")
            ),
        )
        context.user_data["awaiting"] = "name"
        return CUSTOMER_NAME
    else:
        await q.edit_message_text("❌ سبد خرید شما خالی است. ابتدا محصولی انتخاب کنید.")
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
        await update.message.reply_text("شماره موبایل را وارد کن (یا دکمهٔ زیر):", reply_markup=kb)
        return 
    if awaiting == "phone":
        if PHONE_REGEX.match(text):
            context.user_data["customer"]["phone"] = text
            context.user_data["awaiting"] = "address"
            await update.message.reply_text("آدرس پستی کامل:", reply_markup=ReplyKeyboardRemove())
        else:
            await update.message.reply_text("شماره نامعتبر است. با قالب 09xxxxxxxxx وارد کن.")
        return
    if awaiting == "address":
        context.user_data["customer"]["address"] = text
        context.user_data["awaiting"] = "postal"
        await update.message.reply_text("کد پستی ۱۰ رقمی:")
        return
    if awaiting == "postal":
        if re.fullmatch(r"\d{10}" , text):
            context.user_data["customer"]["postal"] = text
            context.user_data["awaiting"] = None
            await show_checkout_summary(update, context)
        else:
            await update.message.reply_text("کد پستی نامعتبر است. ۱۰ رقم وارد کن.")
        return


async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.contact:
        return
    awaiting = context.user_data.get("awaiting")
    if awaiting != "phone":
        return
    phone = update.message.contact.phone_number
    phone = phone.replace("+98", "0").replace(" ", "")
    if PHONE_REGEX.match(phone):
        context.user_data["customer"]["phone"] = phone
        context.user_data["awaiting"] = "address"
        await update.message.reply_text("آدرس پستی کامل:", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("شمارهٔ دریافتی نامعتبر بود. لطفاً دستی وارد کن.")


async def show_checkout_summary(update_or_msg, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(update_or_msg, Update):
        chat_id = update_or_msg.effective_chat.id
        send = context.bot.send_message
    else:
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
    info = (
        "✅ جمع‌بندی سفارش:\n\n" +
        "\n".join(lines) +
        f"\n\nجمع کل: {_ftm_toman(total)}" +
        "\n\n👤 اطلاعات گیرنده:\n"
        f"نام: {customer.get('name', '—')}\n"
        f"موبایل: {customer.get('phone', '—')}\n"
        f"آدرس: {customer.get('address', '—')}\n"
        f"کد پستی: {customer.get('postal', '—')}\n"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ ویرایش مشخصات", callback_data="checkout:begin")],
        [InlineKeyboardButton("💳 پرداخت آنلاین", callback_data="checkout:pay")],
        [InlineKeyboardButton("❌ لغو سفارش", callback_data="checkout:cancel")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:back_home")]
    ])
    await send(chat_id=chat_id, text=info, reply_markup=kb)


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
    cart = context.user_data.get("cart" , [])
    customer = context.user_data.get("customer", {})
    if not cart:
        await q.edit_message_text("سبد خرید خالی است.", reply_markup=main_menu())
        return
    missing = [k for k in ("name", "phone", "address", "postal") if not customer.get(k)]
    if missing:
        await q.edit_message_text("ابتدا مشخصات  را کامل کنید.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🧾 تکمیل مشخصات", callback_data="checkout:begin")],
            [InlineKeyboardButton("🏠 منو", callback_data="menu:back_home")]
        ]))
        return
    total = _calc_cart_total(cart)
    order_id = uuid.uuid4().hex[:10].upper()
    desc = f"سفارش تلگرام #{order_id} - {customer.get('name')}"
    
    res = PAY.create_payment(order_id, total, customer["name"], customer["phone"], desc, CALLBACK_URL)
    if not res.get("ok"):
        await q.edit_message_text("خطا در ایجاد پرداخت. لطفاً بعداً تلاش کن.", reply_markup=main_menu())
        logger.error("Payment create error: %s", res)
        return
    
    payment_id = res["payment_id"]
    pay_link = res["link"]

    order = {
        "order_id": order_id,
        "user_id": update.effective_user.id,
        "chat_id": update.effective_chat.id,
        "items": cart,
        "customer": customer,
        "total": total,
        "status": "awaiting_payment",
        "payment": {
            "provider": PAY.__class__.__name__,
            "payment_id": payment_id,
            "create_raw": res.get("raw"),
        },
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    STORE.add_order(order)
    await q.edit_message_text(
        f"✅ سفارش ثبت شد.\nشماره سفارش: {order_id}\nمبلغ قابل پرداخت: {_ftm_toman(total)}\n\n"
        "برای تکمیل، روی دکمهٔ زیر بزن:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 رفتن به درگاه پرداخت", url=pay_link)],
            [InlineKeyboardButton("🏠 منو", callback_data="menu:back_home")],
        ])
    )


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
    data = (q.data or "").strip() 

    if data == "menu:back_home":
        await start(update , context) ; return
        
    if data == "menu:products":
        await show_gender(update , context) ; return
    
    if data == "menu:cart":
        await show_cart(update , context) ; return

    if data == "menu:support":
        await q.edit_message_text(" پشتیبانی: @amirmehdi_84_10", reply_markup=main_menu()) ; return
        
    
    
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
        context.user_data["pending"] = {
            "gender": gender,
            "category": category,
            "product_id": product_id,
            "name": _find_product(gender, category, product_id)["name"],
            "size": size,
            "price": _find_product(gender, category, product_id)["price"],
        }
        await show_qty_picker(update, context, size) ; return
        
    
    if data.startswith("catalog:choose:"):
        parts = data.split(":", 6)
        if len(parts) != 7:
            await q.edit_message_text("داده انتخاب محصول ناقص است.", reply_markup=main_menu())
            return
        _, _, gender, category_safe, product_id, color, size = parts
        category = CATEGORY_MAP.get(category_safe , category_safe)
        await show_qty_picker_combined(update, context, gender, category, product_id, color, size) ; return
        
       
    if data.startswith("catalog:color:"):
        _, _, gender , category_safe , product_id , color = data.split(":" , 5)
        category = CATEGORY_MAP.get(category_safe , category_safe)
        await after_color_ask_size(update, context, gender, category, product_id , color) ; return
        
    if data.startswith("catalog:size"):
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
            f"\nرنگ:{pend['color'] or '-'} | سایز : {pend['size']}"
            f"\nموجودی:{pend['available']}"
            f"\nقیمت واحد : {_ftm_toman(pend['price'])}"
            f"\nقیمت نهایی: {_ftm_toman(pend['price'] * pend['qty'])}"
        )
        try:
            await q.edit_message_caption(caption=cap, reply_markup=qty_keyboard(pend["qty"], pend["available"]))
        except Exception:
            await q.edit_message_text(text=cap, reply_markup=qty_keyboard(pend["qty"], pend["available"]))
    
    
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
            f"\nرنگ:{pend['color'] or '-'} | سایز : {pend['size']}"
            f"\nموجودی:{pend['available']}"
            f"\nقیمت واحد:{_ftm_toman(pend['price'])}"
            f"\nقیمت نهایی:{_ftm_toman(pend['price'] * pend['qty'])}"
        )
        try:
            await q.edit_message_caption(caption=cap, reply_markup=qty_keyboard(pend["qty"], pend["available"]))
        except Exception:
            await q.edit_message_text(text=cap, reply_markup=qty_keyboard(pend["qty"], pend["available"]))
    
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
        await q.answer() ; return
    

    if data == "flow:cancel":
        context.user_data.pop("pending" , None)
        context.user_data['awaiting'] = None
        await q.edit_message_text("لغو شد.", reply_markup=main_menu())
        return
    

    if data == "checkout:begin":
        await begin_customer_form(update , context) ; return
    

    if data == "checkout:pay":
        await checkout_pay(update , context) ; return
    

    if data.startswith("checkout:verify:"):
        _, _, order_id = data.split(":", 2)
        await checkout_verify(update, context, order_id); return
    

    await q.edit_message_text("❌ گزینه نامعتبر.", reply_markup=main_menu())


#        /start و اجرای برنامه
# ساخت اپلیکیشن PTB
application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(menu_router))
application.add_handler(MessageHandler(filters.CONTACT , on_contact))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND , on_text))

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
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )
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
        update = Update.de_json(data, application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), LOOP)
        return "OK", 200
    except Exception as e:
        logger.exception("webhook handler error: %s", e)
        return "ERROR", 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    flask_app.run(host="0.0.0.0", port=port, debug=False)

        
        
        
        
        
        
        



