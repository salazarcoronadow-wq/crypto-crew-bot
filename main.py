import os
import time
import logging
import threading
import requests
from datetime import date, datetime
from dataclasses import dataclass
import pandas as pd
from binance.client import Client

# Telegram
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("TradingBot")

# === CONFIG - ANTI CRASH ===
MODE = os.getenv("TRADING_MODE", "paper").lower()
MARKET = os.getenv("MARKET_TYPE", "spot").lower()
SYMBOLS_ENV = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,PEPEUSDT,BONKUSDT,WIFUSDT,DOGEUSDT,AVAXUSDT")
SYMBOLS = [s.strip().upper() for s in SYMBOLS_ENV.split(",") if s.strip()]
INTERVAL = os.getenv("INTERVAL", "5m")
LOOKBACK = int(os.getenv("LOOKBACK", "250"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
START_BALANCE = float(os.getenv("PAPER_START_BALANCE", "1000"))
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.005"))
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "0.02"))
MAX_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "2"))
MAX_NOTIONAL = float(os.getenv("MAX_NOTIONAL_FRACTION", "0.20"))
STOP_ATR = float(os.getenv("STOP_ATR_MULTIPLIER", "2"))
TAKE_R = float(os.getenv("TAKE_PROFIT_R_MULTIPLE", "2"))

# ESTA ES LA CLAVE - LEE CUALQUIER NOMBRE DE TOKEN
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM") or ""
TELEGRAM_TOKEN = TELEGRAM_TOKEN.strip()
if TELEGRAM_TOKEN:
    log.info(f"Token encontrado: {TELEGRAM_TOKEN[:10]}...")
else:
    log.warning("NO HAY TELEGRAM_TOKEN - El bot de trading seguira pero sin Telegram")

@dataclass
class Signal:
    action: str
    price: float
    atr: float
    reason: str
    rsi: float = 50.0
    score: float = 5.0

class Market:
    def __init__(self):
        key = os.getenv("BINANCE_API_KEY")
        secret = os.getenv("BINANCE_API_SECRET")
        try:
            self.client = Client(key, secret) if key and secret else Client()
        except:
            self.client = Client()
    
    def candles(self, symbol):
        try:
            if MARKET == "futures":
                rows = self.client.futures_klines(symbol=symbol, interval=INTERVAL, limit=LOOKBACK)
            else:
                rows = self.client.get_klines(symbol=symbol, interval=INTERVAL, limit=LOOKBACK)
            cols = ["time","open","high","low","close","volume","close_time","quote_volume","trades","taker_base","taker_quote","ignore"]
            df = pd.DataFrame(rows, columns=cols)
            for c in ["open","high","low","close","volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            if len(df) > 1: df = df.iloc[:-1]
            return df.reset_index(drop=True)
        except Exception as e:
            log.error(f"Velas {symbol}: {e}")
            return pd.DataFrame()

def indicators(df):
    d = df.copy()
    close = d["close"]
    d["ema_fast"] = close.ewm(span=9, adjust=False).mean()
    d["ema_slow"] = close.ewm(span=21, adjust=False).mean()
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    d["rsi"] = 100 - (100 / (1 + rs))
    prev_close = close.shift(1)
    tr = pd.concat([d["high"]-d["low"], (d["high"]-prev_close).abs(), (d["low"]-prev_close).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    d["atr_pct"] = d["atr"] / close
    return d.dropna().reset_index(drop=True)

def analyze(df):
    if df.empty or len(df) < 30:
        p = float(df["close"].iloc[-1]) if not df.empty else 0
        return Signal("HOLD", p, 0, "Datos insuficientes", 50, 3.0)
    d = indicators(df)
    if len(d) < 30: return Signal("HOLD", float(df["close"].iloc[-1]), 0, "Datos insuficientes", 50, 3.0)
    prev, curr = d.iloc[-2], d.iloc[-1]
    price, atr, rsi = float(curr["close"]), float(curr["atr"]), float(curr["rsi"])
    vol = float(curr["atr_pct"])
    score = 5.0
    if 45 <= rsi <= 68: score += 1.5
    if prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]: score += 2
    if prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]: score -= 1
    if not 0.001 <= vol <= 0.05: score -= 1.5
    score = max(1, min(10, round(score,1)))
    bullish = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"] and 45 <= rsi <= 68
    bearish = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"] and 32 <= rsi <= 55
    if bullish: return Signal("BUY", price, atr, f"Cruce alcista RSI={rsi:.1f}", rsi, score)
    if bearish: return Signal("SELL", price, atr, f"Cruce bajista RSI={rsi:.1f}", rsi, score)
    return Signal("HOLD", price, atr, f"Sin senal RSI={rsi:.1f}", rsi, score)

class PaperBroker:
    def __init__(self):
        self.balance = START_BALANCE
        self.positions = {}
        self.trades = []
    def equity(self, prices):
        v = self.balance
        for s,p in self.positions.items():
            price = prices.get(s, p["entry"])
            d = 1 if p["side"]=="LONG" else -1
            v += d*(price-p["entry"])*p["qty"]
        return v
    def open_position(self, symbol, side, qty, price, stop, take):
        if symbol in self.positions or qty<=0: return False
        if MARKET=="spot" and side!="LONG": return False
        self.positions[symbol] = {"side":side,"qty":qty,"entry":price,"stop":stop,"take":take}
        log.info(f"ABRE {symbol} {qty:.4f} @ {price}")
        return True
    def manage(self, symbol, price):
        p = self.positions.get(symbol)
        if not p: return
        hit_stop = price <= p["stop"] if p["side"]=="LONG" else price >= p["stop"]
        hit_take = price >= p["take"] if p["side"]=="LONG" else price <= p["take"]
        if not hit_stop and not hit_take: return
        d = 1 if p["side"]=="LONG" else -1
        pnl = d*(price-p["entry"])*p["qty"]
        self.balance+=pnl
        del self.positions[symbol]
        log.info(f"CIERRA {symbol} PnL {pnl:.2f}")

# Globales
broker_global = PaperBroker()
market_global = Market()

def get_noticias():
    try:
        r = requests.get("https://min-api.cryptocompare.com/data/v2/news/?lang=EN", timeout=6).json()
        news = r.get('Data', [])[:3]
        return "\n".join([f"• {n['title'][:80]}" for n in news]) or "Sin noticias"
    except:
        return "Noticias no disponibles"

# === COMANDOS TELEGRAM ===
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🧠 BOT CEREBRO v4.3 ACTIVO\nModo {MODE} | {len(SYMBOLS)} monedas\n\n/oportunidad\n/top\n/analizar BTC\n/balance\n/noticias")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    eq = broker_global.equity({})
    txt = f"💰 BALANCE\nBalance: ${broker_global.balance:.2f}\nEquity: ${eq:.2f}\nPosiciones: {len(broker_global.positions)}"
    await update.message.reply_text(txt)

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Escaneando... 10s")
    res=[]
    for s in SYMBOLS:
        sig=analyze(market_global.candles(s))
        res.append((s,sig))
    res.sort(key=lambda x: x[1].score, reverse=True)
    txt=f"🔥 TOP {datetime.now().strftime('%H:%M')}\n\n"
    for i,(sym,sig) in enumerate(res[:5],1):
        e="🟢" if sig.score>=6 else "🟡" if sig.score>=4 else "🔴"
        txt+=f"{i}. {e} {sym.replace('USDT','')} Score {sig.score}\n   ${sig.price:.4f} {sig.action} RSI {sig.rsi:.1f}\n   {sig.reason}\n\n"
    await update.message.reply_text(txt)

async def cmd_oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 CEREBRO TOTAL 20s...")
    res=[]
    for s in SYMBOLS:
        res.append((s, analyze(market_global.candles(s))))
    res.sort(key=lambda x: x[1].score, reverse=True)
    txt="🧠 OPORTUNIDADES\n\n"
    for i,(sym,sig) in enumerate(res[:5],1):
        e="🟢" if sig.score>=6 else "🟡" if sig.score>=4 else "🔴"
        txt+=f"{i}. {e} {sym.replace('USDT','')} Score {sig.score}/10\n   ${sig.price:.4f} {sig.action}\n   {sig.reason}\n\n"
    txt+=f"\n📰 {get_noticias()}"
    await update.message.reply_text(txt)

async def cmd_analizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /analizar BTC")
        return
    coin=context.args[0].upper().replace("USDT","")+"USDT"
    sig=analyze(market_global.candles(coin))
    if sig.price==0:
        await update.message.reply_text(f"No encontre {coin}")
        return
    await update.message.reply_text(f"{coin} ${sig.price:.4f} Score {sig.score} {sig.action} {sig.reason}")

async def cmd_noticias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📰 {get_noticias()}")

def trading_loop_background():
    risk_day=date.today()
    day_start=START_BALANCE
    while True:
        try:
            prices={}
            for sym in SYMBOLS:
                sig=analyze(market_global.candles(sym))
                prices[sym]=sig.price
                if sig.action=="BUY" and sym not in broker_global.positions and len(broker_global.positions)<MAX_POSITIONS:
                    dist=sig.atr*STOP_ATR
                    if dist<=0: continue
                    qty=min(broker_global.equity(prices)*0.005/dist, broker_global.equity(prices)*0.20/sig.price)
                    if qty*sig.price>=10:
                        broker_global.open_position(sym,"LONG",qty,sig.price,sig.price-dist,sig.price+dist*TAKE_R)
                broker_global.manage(sym, sig.price)
                log.info(f"{sym} {sig.action} ${sig.price:.4f} Score {sig.score}")
            time.sleep(POLL_SECONDS)
        except Exception as e:
            log.error(f"Loop error {e}")
            time.sleep(10)

def main():
    # Inicia trading en hilo separado - NO CRASHEA
    t = threading.Thread(target=trading_loop_background, daemon=True)
    t.start()
    
    if not TELEGRAM_TOKEN:
        log.error("Falta TELEGRAM_TOKEN en Variables - Solo trading sin Telegram")
        while True: time.sleep(60)
    
    # Telegram - FORMA CORRECTA PARA PYTHON 3.13
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("oportunidad", cmd_oportunidad))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("analizar", cmd_analizar))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("noticias", cmd_noticias))
    log.info("BOT CEREBRO v4.3 INICIADO SIN CRASH")
    app.run_polling()

if __name__ == "__main__":
    main()
