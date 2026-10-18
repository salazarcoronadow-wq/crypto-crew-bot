import os
import logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger()

TOKEN = (os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
log.info(f"Iniciando... Token existe: {bool(TOKEN)}")

if not TOKEN:
    log.error("FALTA TELEGRAM_TOKEN en Variables de Railway - durmiendo para no crashear")
    import time
    while True:
        time.sleep(60)
        log.info("Esperando token... pon TELEGRAM_TOKEN en Variables")

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ BOT ACTIVO - Ahora si puedes poner el código de trading")

async def oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 CEREBRO: BTC $115k Score 8/10 - Sistema base OK")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", oportunidad))
    app.add_handler(CommandHandler("oportunidad", oportunidad))
    app.add_handler(CommandHandler("top", oportunidad))
    log.info("BOT INICIADO - LISTO PARA TELEGRAM")
    app.run_polling()

if __name__ == "__main__":
    main()
