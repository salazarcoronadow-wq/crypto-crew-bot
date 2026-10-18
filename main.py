import os, time, logging, requests, pandas as pd
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("BOT")
TOKEN = (os.getenv("TELEGRAM_TOKEN") or "").strip().replace('"','').replace("'","")
INTERVAL = "15m"
SYMBOLS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","SHIBUSDT","DOTUSDT","LINKUSDT","TRXUSDT","MATICUSDT","LTCUSDT","BCHUSDT","UNIUSDT","ATOMUSDT","ETCUSDT","XLMUSDT","FILUSDT","PEPEUSDT","BONKUSDT","WIFUSDT","FLOKIUSDT","ARBUSDT","OPUSDT","SUIUSDT","APTUSDT","STXUSDT","IMXUSDT","NEARUSDT","RNDRUSDT"]

def get_candles(symbol, limit=100):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={INTERVAL}&limit={limit}"
        r = requests.get(url, timeout=10).json()
        if not r or isinstance(r, dict) or len(r)<50: return pd.DataFrame()
        df = pd.DataFrame(r, columns=["t","o","h","l","c","v","ct","qv","tr","tb","tq","ig"])
        for col in ["o","h","l","c","v"]: df[col]=pd.to_numeric(df[col])
        return df
    except: return pd.DataFrame()

def analyze(df):
    if df.empty: return 3.0, "Sin datos", 0, 50
    close = df["c"]
    ema9 = close.ewm(span=9).mean(); ema21 = close.ewm(span=21).mean()
    delta = close.diff(); gain = delta.clip(lower=0).ewm(alpha=1/14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14).mean(); rs = gain/loss
    rsi = 100 - (100/(1+rs)); curr_rsi = float(rsi.iloc[-1]); price = float(close.iloc[-1])
    score=5.0; reason=""
    if ema9.iloc[-2]<=ema21.iloc[-2] and ema9.iloc[-1]>ema21.iloc[-1]: score+=3; reason+="Cruce alcista "
    if ema9.iloc[-2]>=ema21.iloc[-2] and ema9.iloc[-1]<ema21.iloc[-1]: score-=2; reason+="Cruce bajista "
    if 50<=curr_rsi<=68: score+=1.5; reason+=f"RSI {curr_rsi:.0f} optimo "
    elif curr_rsi>75: score-=2; reason+=f"RSI {curr_rsi:.0f} sobrecompra "
    elif curr_rsi<30: score+=1; reason+=f"RSI {curr_rsi:.0f} sobreventa "
    score=max(1,min(10,round(score,1)))
    if not reason: reason=f"Consolidacion RSI {curr_rsi:.0f}"
    return score, reason, price, curr_rsi

def get_news():
    try:
        r=requests.get("https://min-api.cryptocompare.com/data/v2/news/?lang=EN",timeout=8).json()
        txt="**ULTIMAS NOTICIAS CRYPTO:**\n\n"
        for n in r.get("Data",[])[:3]: txt+=f"• {n['title'][:90]}\n"
        return txt
    except: return "Noticias no disponibles"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 worren-crew-bot v5.1 ONLINE\n/oportunidad - Cerebro total\n/top - Top 10\n/analizar btc\n/noticias\n/balance")

async def oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Activando CEREBRO TOTAL... escaneando 80 monedas + noticias + analisis. 20 seg ⏳")
    results=[]
    for sym in SYMBOLS:
        df=get_candles(sym); score,reason,price,rsi=analyze(df)
        results.append((sym,score,reason,price,rsi)); time.sleep(0.15)
    results.sort(key=lambda x:x[1],reverse=True)
    best=[r for r in results if r[1]>=7]
    if not best:
        txt=f"🧠 Cerebro dice: No hay oportunidades claras ahora. Mercado peligroso. Prueba /top\n\nMejor: {results[0][0]} Score {results[0][1]} - {results[0][2]}"
        await update.message.reply_text(txt); return
    txt=f"🧠 CEREBRO TOTAL - {datetime.now().strftime('%H:%M')}\n\n"
    for sym,score,reason,price,rsi in best[:3]:
        e="🟢" if score>=8 else "🟡"; txt+=f"{e} {sym.replace('USDT','')} ${price:.4f} Score {score}/10\n   {reason}\n\n"
    txt+=get_news(); await update.message.reply_text(txt)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔥 Escaneando TOP 10...")
    results=[]
    for sym in SYMBOLS:
        df=get_candles(sym); score,reason,price,rsi=analyze(df); results.append((sym,score,reason,price,rsi))
    results.sort(key=lambda x:x[1],reverse=True)
    txt=f"🔥 TOP 10 - {datetime.now().strftime('%H:%M')}\n\n"
    for i,(sym,score,reason,price,rsi) in enumerate(results[:10],1):
        e="🟢" if score>=7 else "🟡" if score>=5 else "🔴"
        txt+=f"{i}. {e} {sym.replace('USDT','')} Score {score} ${price:.2f}\n   {reason}\n\n"
    await update.message.reply_text(txt)

async def analizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: await update.message.reply_text("Uso: /analizar btc"); return
    coin=context.args[0].upper().replace("USDT","")+"USDT"
    df=get_candles(coin)
    if df.empty: await update.message.reply_text(f"No encontre {coin}"); return
    score,reason,price,rsi=analyze(df)
    await update.message.reply_text(f"📊 {coin} ${price:.4f}\nScore: {score}/10\nRSI: {rsi:.1f}\n{reason}\n\n{'🟢 COMPRABLE' if score>=7 else '🟡 ESPERAR' if score>=5 else '🔴 PELIGRO'}")

async def noticias(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(get_news())
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("💰 Paper Balance: $1000 (demo) - Bot estable v5.1")

def main():
    if not TOKEN or ":" not in TOKEN: log.error("TOKEN INVALIDO"); time.sleep(99999)
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("oportunidad",oportunidad))
    app.add_handler(CommandHandler("oportunidades",oportunidad)); app.add_handler(CommandHandler("top",top))
    app.add_handler(CommandHandler("analizar",analizar)); app.add_handler(CommandHandler("noticias",noticias))
    app.add_handler(CommandHandler("balance",balance))
    log.info("BOT v5.1 LISTO"); app.run_polling()

if __name__=="__main__": main()
