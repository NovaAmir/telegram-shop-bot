if data == "qty:noop":
        await q.answer() ; return
    

    if data == "flow:cancel":
        context.user_data.pop("pending" , None)
        context.user_data['awaiting'] = None
        await q.edit_message_text("لغو شد.", reply_markup=main_menu())
        return
    

    if data == "checkout:begin":
        # حذف edit_message_text و اجرای begin_customer_form به دلیل اینکه یک مکالمه جدید شروع می‌شود
        await begin_customer_form(update , context) ; return
    

    if data == "checkout:pay":
        await checkout_pay(update , context) ; return
    

    if data.startswith("checkout:verify:"):
        _, _, order_id = data.split(":", 2)
        await checkout_verify(update, context, order_id); return
        
    if data == "checkout:cancel":
        context.user_data.pop("cart" , None)
        context.user_data.pop("customer" , None)
        await q.edit_message_text("❌ سفارش لغو شد. سبد خرید خالی شد.", reply_markup=main_menu())
        return
    

    await q.edit_message_text("❌ گزینه نامعتبر.", reply_markup=main_menu())


#        /start و اجرای برنامه
# ساخت اپلیکیشن PTB
application = Application.builder().token(BOT_TOKEN).build()

# تعریف مکالمه
checkout_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(begin_customer_form, pattern=r"^checkout:begin$")],
    states={
        CUSTOMER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],
        CUSTOMER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text), MessageHandler(filters.CONTACT, on_contact)],
        CUSTOMER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],
        CUSTOMER_POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)],
    },
    fallbacks=[CallbackQueryHandler(menu_router, pattern=r"^flow:cancel$")], # در صورت انصراف در هر مرحله
    map_to_storage=True,
)


application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(menu_router))

# اضافه کردن ConversationHandler به اپلیکیشن
application.add_handler(checkout_conv)

# این دو خط باید حذف یا تغییر داده شوند چون در ConversationHandler مدیریت می‌شوند
# application.add_handler(MessageHandler(filters.CONTACT , on_contact)) 
# application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND , on_text))
# اگر می‌خواهید پیام‌های متنی خارج از مکالمه هم به start برگردند:
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))


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
flask_app = Flask(name)

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

if name == "main":
    port = int(os.getenv("PORT", "10000"))
    flask_app.run(host="0.0.0.0", port=port, debug=False)
