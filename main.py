import os, time, logging, requests, pandas as pd
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("BOT")
TOKEN = (os.getenv("TELEGRAM_TOKEN") or "").strip().replace('"','').replace("'","")
INTERVAL = "15m"
SYMBOLS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","SHIBUSDT","DOTUSDT","LINKUSDT","TRXUSDT","MATICUSDT","LTCUSDT","BCHUSDT","UNIUSDT","ATOMUSDT","ETCUSDT","XLMUSDT","FILUSDT","PEPEUSDT","BONKUSDT","WIFUSDT","FLOKIUSDT","ARBUSDT","OPUSDT","SUIUSDT","APTUSDT","STXUSDT","IMXUSDT","NEARUSDT","RNDRUSDT"]

def get_candles(sym, limit=100):
    try:
        url = "https://data-api.binance.vision/api/v3/klines"
        url = f"{url}?symbol={sym}&interval={INTERVAL}&limit={limit}"
        r = requests.get(url, timeout=10).json()
        if not r or isinstance(r, dict):
            return pd.DataFrame()
        if len(r) < 50:
            return pd.DataFrame()
        cols = ["t","o","h","l","c","v","ct","qv","tr","tb","tq","ig"]
        df = pd.DataFrame(r, columns=cols)
        for c in ["o","h","l","c","v"]:
            df[c] = pd.to_numeric(df[c])
        return df
    except:
        return pd.DataFrame()

def analyze(df):
    if df.empty:
        return 3.0, "Sin datos", 0, 50
    close = df["c"]
    ema9 = close.ewm(span=9).mean()
    ema21 = close.ewm(span=21).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    crsi = float(rsi.iloc[-1])
    price = float(close.iloc[-1])
    score = 5.0
    reason = ""
    if ema9.iloc[-2] <= ema21.iloc[-2] and ema9.iloc[-1] > ema21.iloc[-1]:
        score += 3
        reason += "Cruce alcista "
    if ema9.iloc[-2] >= ema21.iloc[-2] and ema9.iloc[-1] < ema21.iloc[-1]:
        score -= 2
        reason += "Cruce bajista "
    if 50 <= crsi <= 68:
        score += 1.5
        reason += f"RSI {crsi:.0f} "
    elif crsi > 75:
        score -= 2
        reason += f"RSI {crsi:.0f} sobrecompra "
    elif crsi < 30:
        score += 1
        reason += f"RSI {crsi:.0f} sobreventa "
    score = max(1, min(10, round(score, 1)))
    if not reason:
        reason = f"Consolid RSI {crsi:.0f}"
    return score, reason, price, crsi

def get_news():
    try:
        url = "https://min-api.cryptocompare.com/data/v2/news/?lang=EN"
        r = requests.get(url, timeout=8).json()
        txt = "**NOTICIAS:**\n\n"
        for n in r.get("Data", [])[:3]:
            txt += f"• {n['title'][:80]}\n"
        return txt
    except:
        return "Noticias no disponibles"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🧠 worren-crew-bot v5.3 ONLINE\n"
    msg += "/oportunidad\n/top\n/analizar btc\n/noticias\n/balance"
    await update.message.reply_text(msg)

async def oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Escaneando... 20 seg")
    res = []
    for s in SYMBOLS:
        df = get_candles(s)
        sc, re, pr, rsi = analyze(df)
        res.append((s, sc, re, pr, rsi))
        time.sleep(0.15)
    res.sort(key=lambda x: x[1], reverse=True)
    best = [x for x in res if x[1] >= 7]
    if not best:
        top = res[0]
        txt = f"Sin oportunidad clara. Mejor {top[0]} Score {top[1]}"
        await update.message.reply_text(txt)
        return
    txt = f"🧠 CEREBRO {datetime.now().strftime('%H:%M')}\n\n"
    for item in best[:3]:
        sym, sc, re, pr, rsi = item
        e = "🟢" if sc >= 8 else "🟡"
        name = sym.replace("USDT","")
        txt += f"{e} {name} ${pr:.2f} Score {sc}\n {re}\n\n"
    txt += get_news()
    await update.message.reply_text(txt)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔥 TOP 10...")
    res = []
    for s in SYMBOLS:
        df = get_candles(s)
        sc, re, pr, rsi = analyze(df)
        res.append((s, sc, re, pr, rsi))
    res.sort(key=lambda x: x[1], reverse=True)
    txt = f"🔥 TOP 10 {datetime.now().strftime('%H:%M')}\n\n"
    i = 1
    for item in res[:10]:
        sym, sc, re, pr, rsi = item
        e = "🟢" if sc >= 7 else "🟡" if sc >= 5 else "🔴"
        name = sym.replace("USDT","")
        txt += f"{i}. {e} {name} Score {sc} ${pr:.2f}\n {re}\n\n"
        i += 1
    await update.message.reply_text(txt)

async def analizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /analizar btc")
        return
    coin = context.args[0].upper().replace("USDT","") + "USDT"
    df = get_candles(coin)
    if df.empty:
        await update.message.reply_text(f"No hay datos {coin}")
        return
    sc, re, pr, rsi = analyze(df)
    sig = "🟢 COMPRABLE" if sc >= 7 else "🟡 ESPERAR" if sc >= 5 else "🔴 PELIGRO"
    txt = f"📊 {coin} ${pr:.4f}\nScore {sc}\nRSI {rsi:.1f}\n{re}\n\n{sig}"
    await update.message.reply_text(txt)

async def noticias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_news())

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💰 Balance demo $1000 - v5.3 ACTIVE")

def main():
    if not TOKEN or ":" not in TOKEN:
        log.error("TOKEN MALO")
        time.sleep(99999)
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("oportunidad", oportunidad))
    app.add_handler(CommandHandler("oportunidades", oportunidad))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("analizar", analizar))
    app.add_handler(CommandHandler("noticias", noticias))
    app.add_handler(CommandHandler("balance", balance))
    log.info("BOT v5.3 LISTO")
    app.run_polling()

if __name__ == "__main__":
    main()
