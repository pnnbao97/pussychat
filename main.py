import asyncio
import threading
import os
from dotenv import load_dotenv
from telegram.ext import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from flask import Flask, request
import logging
from handlers import setup_handlers
from api import fetch_and_store_news, fetch_crypto_and_macro
from telegram import Update

# Tải biến môi trường
load_dotenv()
TELEGRAM_API_KEY = os.getenv('TELEGRAM_BOT_TOKEN')

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot_application = None
loop = None

async def setup_bot():
    global bot_application
    logger.info("Starting bot setup...")
    bot_application = Application.builder().token(TELEGRAM_API_KEY).build()

    # Thiết lập handlers từ module handlers.py
    setup_handlers(bot_application)

    # Thiết lập scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(fetch_and_store_news, 'interval', hours=12, args=[bot_application])
    scheduler.add_job(fetch_crypto_and_macro, 'interval', hours=12, args=[bot_application])
    scheduler.add_job(keep_alive, 'interval', minutes=5, args=[bot_application])
    scheduler.start()

    webhook_url = "https://pussychat.onrender.com/webhook"
    await bot_application.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

    await bot_application.initialize()
    await bot_application.start()
    logger.info("Bot initialized and started successfully")
    return bot_application

async def keep_alive(context):
    import requests
    try:
        requests.get("https://pussychat.onrender.com/")
        logger.info("Sent keep-alive request")
    except Exception as e:
        logger.error(f"Keep-alive failed: {str(e)}")

@app.route('/webhook', methods=['POST'])
def webhook():
    global bot_application, loop
    if bot_application is None:
        logger.error("Bot application not initialized!")
        return '', 500
    data = request.get_json(force=True)
    if not data:
        logger.error("No data received in webhook!")
        return '', 400
    logger.info(f"Received webhook data: {data}")
    asyncio.run_coroutine_threadsafe(bot_application.process_update(Update.de_json(data, bot_application.bot)), loop)
    return '', 200

@app.route('/')
def health_check():
    logger.info("Health check requested")
    return "Bot is running", 200

def run_bot_setup():
    global bot_application, loop
    logger.info("Starting bot thread...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot_application = loop.run_until_complete(setup_bot())
    loop.run_forever()

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot_setup, daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port)
