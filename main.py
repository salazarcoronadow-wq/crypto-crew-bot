import os, time, logging, threading, requests, traceback
from datetime import datetime
import pandas as pd
from binance.client import Client
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("BOT")

TOKEN = (os.getenv("TELEGRAM_TOKEN") or "").strip().replace('"','').replace("'","")
MODE = os.getenv("TRADING_MODE","paper")
# 80 monedas reales para tu cerebro
SYMBOLS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","SHIBUSDT","DOTUSDT","LINKUSDT","TRXUSDT","MATICUSDT","LTCUSDT","BCHUSDT","UNIUSDT","ATOMUSDT","ETCUSDT","XLMUSDT","FILUSDT","PEPEUSDT","BONKUSDT","WIFUSDT","FLOKIUSDT","ARBUSDT","OPUSDT","SUIUSDT","APTUSDT","STXUSDT","IMXUSDT"]
INTERVAL = "15m"

market = Client()

def get_candles(symbol, limit=100):
    try:
        rows = market.get_klines(symbol=symbol, interval=INTERVAL, limit=limit)
        df = pd.DataFrame(rows, columns=["t","o","h","l","c","v","ct","qv","tr","tb","tq","ig"])
        for col in ["o","h","l","c"]: df[col]=pd.to_numeric(df[col])
        return df
    except Exception as e:
        log.error(f"{symbol} {e}")
        return pd.DataFrame()

def analyze(df):
    if df.empty or len(df)<50: return 3.0, "Sin datos", 0, 50
    close = df["c"].astype(float)
    ema9 = close.ewm(span=9).mean()
    ema21 = close.ewm(span=21).mean()
    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14).mean()
    rs = gain/loss
    rsi = 100 - (100/(1+rs))
    curr_rsi = float(rsi.iloc[-1])
    price = float(close.iloc[-1])
    
    score = 5.0
    reason = ""
    # Cruces
    if ema9.iloc[-2] <= ema21.iloc[-2] and ema9.iloc[-1] > ema21.iloc[-1]:
        score+=3; reason+="Cruce alcista "
    if ema9.iloc[-2] >= ema21.iloc[-2] and ema9.iloc[-1] < ema21.iloc[-1]:
        score-=2; reason+="Cruce bajista "
    # RSI optimo
    if 50 <= curr_rsi <= 68: score+=1.5; reason+=f"RSI {curr_rsi:.0f} optimo "
    elif curr_rsi > 75: score-=2; reason+=f"RSI {curr_rsi:.0f} sobrecompra "
    elif curr_rsi < 30: score+=1; reason+=f"RSI {curr_rsi:.0f} sobreventa "
    
    score = max(1,min(10,round(score,1)))
    if not reason: reason=f"Consolidacion RSI {curr_rsi:.0f}"
    return score, reason, price, curr_rsi

def get_news():
    try:
        r = requests.get("https://min-api.cryptocompare.com/data/v2/news/?lang=EN", timeout=8).json()
        news = r.get("Data",[])[:3]
        txt="**ULTIMAS NOTICIAS CRYPTO:**\n\n"
        for n in news:
            txt+=f"• {n['title'][:90]}\n"
        return txt
    except:
        return "Noticias no disponibles ahora"

# --- COMANDOS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 worren-crew-bot v5.0 ONLINE\n\n/oportunidad - Escaneo TOTAL 80 monedas + noticias\n/top - Top 10 del dia\n/analizar btc - Analiza una moneda\n/noticias - Ultimas noticias\n/balance - Tu balance paper")

async def cmd_oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Activando CEREBRO TOTAL... escaneando 80 monedas + noticias + analisis. 20 seg ⏳")
    results=[]
    for sym in SYMBOLS:
        df=get_candles(sym)
        score, reason, price, rsi = analyze(df)
        results.append((sym, score, reason, price, rsi))
        time.sleep(0.2)
    
    results.sort(key=lambda x: x[1], reverse=True)
    best = [r for r in results if r[1]>=7]
    
    if not best:
        txt="🧠 Cerebro dice: No hay oportunidades claras ahora. Mercado peligroso. Prueba /top\n\n"
        txt+=f"Mejor ahora: {results[0][0]} Score {results[0][1]} - {results[0][2]}"
        await update.message.reply_text(txt)
        return
    
    txt=f"🧠 CEREBRO TOTAL - {datetime.now().strftime('%H:%M')} (GMT-3)\n\n"
    for sym, score, reason, price, rsi in best[:3]:
        emoji="🟢" if score>=8 else "🟡"
        txt+=f"{emoji} {sym.replace('USDT','')} ${price:.4f} Score {score}/10\n   {reason}\n   RSI {rsi:.0f}\n\n"
    txt+=get_news()
    await update.message.reply_text(txt)

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔥 Escaneando TOP 10... 10 seg")
    results=[]
    for sym in SYMBOLS:
        df=get_candles(sym)
        score, reason, price, rsi = analyze(df)
        results.append((sym, score, reason, price, rsi))
    results.sort(key=lambda x: x[1], reverse=True)
    txt=f"🔥 TOP 10 - {datetime.now().strftime('%H:%M')}\n\n"
    for i,(sym, score, reason, price, rsi) in enumerate(results[:10],1):
        e="🟢" if score>=7 else "🟡" if score>=5 else "🔴"
        txt+=f"{i}. {e} {sym.replace('USDT','')} Score {score} ${price:.4f}\n   {reason}\n\n"
    await update.message.reply_text(txt)

async def cmd_analizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /analizar btc")
        return
    coin = context.args[0].upper().replace("USDT","")+"USDT"
    df=get_candles(coin)
    if df.empty:
        await update.message.reply_text(f"No encontre {coin}")
        return
    score, reason, price, rsi = analyze(df)
    txt=f"📊 {coin} ${price:.4f}\nScore: {score}/10\nRSI: {rsi:.1f}\n{reason}\n\n{'🟢 COMPRABLE' if score>=7 else '🟡 ESPERAR' if score>=5 else '🔴 PELIGRO'}"
    await update.message.reply_text(txt)

async def cmd_noticias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_news())

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💰 Paper Balance: $1000 (demo)\nModo: paper\nCuando actives trading real usa /trading_on")

def main():
    log.info(f"Iniciando bot... token {len(TOKEN)} chars")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("oportunidad", cmd_oportunidad))
    app.add_handler(CommandHandler("oportunidades", cmd_oportunidad))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("analizar", cmd_analizar))
    app.add_handler(CommandHandler("noticias", cmd_noticias))
    app.add_handler(CommandHandler("balance", cmd_balance))
    log.info("BOT v5.0 LISTO - SIN CRASH")
    app.run_polling()

if __name__ == "__main__":
    main()
