import os
import time
import logging
import asyncio
import requests
from datetime import date, datetime
from dataclasses import dataclass

import pandas as pd
from dotenv import load_dotenv
from binance.client import Client
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()

# ==========================================
# CONFIGURACION - LEE DE RAILWAY
# ==========================================
MODE = os.getenv("TRADING_MODE", "paper").lower()
MARKET = os.getenv("MARKET_TYPE", "spot").lower()
SYMBOLS = [
    s.strip().upper()
    for s in os.getenv(
        "SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,DOTUSDT,LINKUSDT,PEPEUSDT,BONKUSDT,WIFUSDT"
    ).split(",")
    if s.strip()
]
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
USE_AI = os.getenv("USE_AI", "false").lower() == "true"
AI_KEY = os.getenv("OPENAI_API_KEY", "")
AI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini") # FIX: gpt-6 no existe

TELEGRAM_TOKEN = (os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM") or "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log", encoding="utf-8")],
)
log = logging.getLogger("TradingBot")

# VARIABLES GLOBALES PARA TELEGRAM
broker_global = None
market_global = None

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
        key = os.getenv("BINANCE_API_KEY") or None
        secret = os.getenv("BINANCE_API_SECRET") or None
        self.client = Client(key, secret)
        if MODE == "testnet":
            if MARKET == "futures":
                self.client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
            else:
                self.client.API_URL = "https://testnet.binance.vision/api"
    
    def candles(self, symbol):
        try:
            if MARKET == "futures":
                rows = self.client.futures_klines(symbol=symbol, interval=INTERVAL, limit=LOOKBACK)
            else:
                rows = self.client.get_klines(symbol=symbol, interval=INTERVAL, limit=LOOKBACK)
            columns = ["time","open","high","low","close","volume","close_time","quote_volume","trades","taker_base","taker_quote","ignore"]
            df = pd.DataFrame(rows, columns=columns)
            for col in ["open","high","low","close","volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            if len(df) > 1:
                df = df.iloc[:-1]
            return df.reset_index(drop=True)
        except Exception as e:
            log.error(f"Error velas {symbol}: {e}")
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
    previous = close.shift(1)
    true_range = pd.concat([d["high"]-d["low"], (d["high"]-previous).abs(), (d["low"]-previous).abs()], axis=1).max(axis=1)
    d["atr"] = true_range.ewm(alpha=1/14, adjust=False).mean()
    d["atr_pct"] = d["atr"] / close
    return d.dropna().reset_index(drop=True)

def analyze(df):
    if df.empty or len(df) < 30:
        price = float(df["close"].iloc[-1]) if not df.empty else 0
        return Signal("HOLD", price, 0.0, "Datos insuficientes", 50, 3.0)
    d = indicators(df)
    if len(d) < 30:
        return Signal("HOLD", float(df["close"].iloc[-1]), 0.0, "Datos insuficientes", 50, 3.0)
    
    prev = d.iloc[-2]
    curr = d.iloc[-1]
    price = float(curr["close"])
    atr = float(curr["atr"])
    rsi = float(curr["rsi"])
    vol = float(curr["atr_pct"])

    score = 5.0
    if 45 <= rsi <= 68: score += 1.5
    if prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]: score += 2
    if prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]: score -= 1
    if not 0.001 <= vol <= 0.05: score -= 2
    score = max(1, min(10, round(score,1)))

    if price <=0 or atr <=0:
        return Signal("HOLD", price, atr, "Datos invalidos", rsi, 2.0)

    bullish = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"] and 45 <= rsi <= 68
    bearish = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"] and 32 <= rsi <= 55

    if bullish:
        return Signal("BUY", price, atr, f"Cruce alcista; RSI={rsi:.1f}", rsi, score)
    if bearish:
        return Signal("SELL", price, atr, f"Cruce bajista; RSI={rsi:.1f}", rsi, score)
    
    return Signal("HOLD", price, atr, f"Sin senal; RSI={rsi:.1f}", rsi, score)

class RiskManager:
    def __init__(self):
        self.day = date.today()
        self.day_start = START_BALANCE
        self.halted = False
    def check(self, equity, positions):
        if date.today() != self.day:
            self.day = date.today()
            self.day_start = equity
            self.halted = False
        if self.halted: return False
        loss = max(0.0, self.day_start - equity)
        if self.day_start > 0 and loss / self.day_start >= MAX_DAILY_LOSS:
            self.halted = True
            log.error("Limite diario alcanzado.")
            return False
        return len(positions) < MAX_POSITIONS
    def quantity(self, equity, price, stop_distance):
        if min(equity, price, stop_distance) <= 0: return 0.0
        by_risk = equity * RISK_PER_TRADE / stop_distance
        by_value = equity * MAX_NOTIONAL / price
        return max(0.0, min(by_risk, by_value))

class PaperBroker:
    def __init__(self):
        self.balance = START_BALANCE
        self.positions = {}
        self.trades = []
    def equity(self, prices):
        value = self.balance
        for symbol, p in self.positions.items():
            price = prices.get(symbol, p["entry"])
            direction = 1 if p["side"] == "LONG" else -1
            value += direction * (price - p["entry"]) * p["qty"]
        return value
    def open_position(self, symbol, side, qty, price, stop, take):
        if symbol in self.positions or qty <=0: return False
        if MARKET == "spot" and side != "LONG": return False
        self.positions[symbol] = {"side":side,"qty":qty,"entry":price,"stop":stop,"take":take}
        log.info(f"ABRE {symbol} {side} qty={qty:.6f} entry={price}")
        return True
    def manage(self, symbol, price):
        p = self.positions.get(symbol)
        if not p: return
        if p["side"] == "LONG":
            stop_hit = price <= p["stop"]
            take_hit = price >= p["take"]
        else:
            stop_hit = price >= p["stop"]
            take_hit = price <= p["take"]
        if not stop_hit and not take_hit: return
        direction = 1 if p["side"] == "LONG" else -1
        pnl = direction * (price - p["entry"]) * p["qty"]
        self.balance += pnl
        self.trades.append({"symbol":symbol,"entry":p["entry"],"exit":price,"qty":p["qty"],"pnl":pnl,"reason":"STOP" if stop_hit else "TAKE"})
        del self.positions[symbol]
        log.info(f"CIERRE {symbol} PnL {pnl:.4f}")

def get_noticias():
    try:
        url = "https://min-api.cryptocompare.com/data/v2/news/?lang=EN&feeds=cryptocompare,cointelegraph,coindesk"
        data = requests.get(url, timeout=7).json()
        noticias = data.get('Data', [])[:3]
        texto = ""
        for n in noticias:
            texto += f"\n• {n['title'][:90]}"
        return texto if texto else "\n• Mercado sin noticias explosivas"
    except:
        return "\n• Noticias no disponibles"

# ==========================================
# COMANDOS TELEGRAM - CEREBRO
# ==========================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "🧠 **BOT CEREBRO v4.1 - MEJORADO**\n\n"
        f"Modo: {MODE} | Mercado: {MARKET}\n"
        f"Simbolos: {', '.join(SYMBOLS[:5])}...\n\n"
        "/oportunidad - Escanea TODAS con mi cerebro\n"
        "/top - Top 5 mejores scores\n"
        "/analizar BTC - Analisis de una moneda\n"
        "/balance - Ver tu plata simulada\n"
        "/noticias - Noticias importantes\n"
    )
    await update.message.reply_text(txt, parse_mode='Markdown')

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not broker_global:
        await update.message.reply_text("Broker no iniciado aun")
        return
    eq = broker_global.equity({})
    txt = f"💰 **BALANCE SIMULADO**\n\nBalance: ${broker_global.balance:.2f}\nEquity: ${eq:.2f}\nPosiciones abiertas: {len(broker_global.positions)}\nTrades cerrados: {len(broker_global.trades)}"
    if broker_global.positions:
        txt += "\n\n**Abiertas:**\n"
        for s,p in broker_global.positions.items():
            txt += f"• {s} {p['side']} entry ${p['entry']:.4f}\n"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Escaneando TOP con mi cerebro... 15 seg ⏳")
    resultados = []
    for symbol in SYMBOLS:
        try:
            df = market_global.candles(symbol)
            sig = analyze(df)
            resultados.append((symbol, sig))
        except Exception as e:
            log.error(e)
    resultados.sort(key=lambda x: x[1].score, reverse=True)
    top5 = resultados[:5]
    txt = f"🔥 **TOP 5 CEREBRO - {datetime.now().strftime('%H:%M')}**\n\n"
    for i,(sym,sig) in enumerate(top5,1):
        emoji = "🟢" if sig.score >=6 else "🟡" if sig.score>=4 else "🔴"
        txt += f"{i}. {emoji} **{sym.replace('USDT','')}** Score {sig.score}/10\n   ${sig.price:.4f} RSI {sig.rsi:.1f}\n   {sig.action} - {sig.reason}\n\n"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def cmd_oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Activando CEREBRO TOTAL... escaneando + noticias. 20 seg ⏳")
    resultados = []
    for symbol in SYMBOLS:
        try:
            df = market_global.candles(symbol)
            sig = analyze(df)
            resultados.append((symbol, sig))
        except:
            continue
    if not resultados:
        await update.message.reply_text("❌ Error Binance, prueba /top")
        return
    resultados.sort(key=lambda x: x[1].score, reverse=True)
    top5 = resultados[:5]
    noticias = get_noticias()
    txt = "🧠 **CEREBRO v4.1 - OPORTUNIDADES**\n\n"
    for i,(sym,sig) in enumerate(top5,1):
        emoji = "🟢" if sig.score >=6 else "🟡" if sig.score>=4 else "🔴"
        txt += f"{i}. {emoji} **{sym.replace('USDT','')}** Score {sig.score}/10\n   ${sig.price:.4f} | {sig.action} RSI {sig.rsi:.1f}\n   {sig.reason}\n\n"
    if top5[0][1].score < 4:
        txt += "⚠️ Mercado peligroso hoy, estos son los menos malos.\n"
    txt += f"\n📰 Noticias:{noticias}"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def cmd_analizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /analizar BTC")
        return
    coin = context.args[0].upper().replace("USDT","") + "USDT"
    await update.message.reply_text(f"🧠 Analizando {coin}...")
    df = market_global.candles(coin)
    if df.empty:
        await update.message.reply_text(f"❌ No encontre {coin}")
        return
    sig = analyze(df)
    emoji = "🟢" if sig.score >=6 else "🟡" if sig.score>=4 else "🔴"
    txt = f"{emoji} **{coin.replace('USDT','')}**\nPrecio: ${sig.price:.6f}\nRSI: {sig.rsi:.1f}\nScore: {sig.score}/10\nAccion: {sig.action}\nRazon: {sig.reason}\nATR: {sig.atr:.6f}{get_noticias()}"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def cmd_noticias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📰 **NOTICIAS:**{get_noticias()}", parse_mode='Markdown')

# LOOP DE TRADING EN SEGUNDO PLANO
async def trading_loop():
    global broker_global, market_global
    market_global = Market()
    broker_global = PaperBroker() if MODE == "paper" else None
    risk = RiskManager()
    log.info(f"Bot iniciado | modo={MODE} | mercado={MARKET} | simbolos={SYMBOLS}")
    while True:
        try:
            prices = {}
            signals = {}
            for symbol in SYMBOLS:
                try:
                    df = market_global.candles(symbol)
                    sig = analyze(df)
                    prices[symbol] = sig.price
                    signals[symbol] = sig
                    log.info(f"{symbol} | {sig.action} | precio={sig.price:.6f} | {sig.reason} | score={sig.score}")
                except Exception as exc:
                    log.exception(f"Error {symbol}: {exc}")
            if MODE == "paper" and broker_global:
                for symbol, price in prices.items():
                    broker_global.manage(symbol, price)
                equity = broker_global.equity(prices)
                if risk.check(equity, broker_global.positions):
                    for symbol, sig in signals.items():
                        if sig.action != "BUY": continue
                        if symbol in broker_global.positions: continue
                        if len(broker_global.positions) >= MAX_POSITIONS: break
                        distance = sig.atr * STOP_ATR
                        qty = risk.quantity(equity, sig.price, distance)
                        if qty * sig.price < 10: continue
                        broker_global.open_position(symbol, "LONG", qty, sig.price, sig.price - distance, sig.price + distance * TAKE_R)
                log.info(f"SIMULACION | balance={broker_global.balance:.2f} | equity={broker_global.equity(prices):.2f} | pos={len(broker_global.positions)}")
        except Exception as e:
            log.exception(f"Error loop: {e}")
        await asyncio.sleep(max(10, POLL_SECONDS))

async def main_async():
    if not TELEGRAM_TOKEN:
        log.error("FALTA TELEGRAM_TOKEN - Modo solo trading sin Telegram")
        await trading_loop()
        return
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("oportunidad", cmd_oportunidad))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("analizar", cmd_analizar))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("noticias", cmd_noticias))
    
    # Iniciar trading en paralelo
    asyncio.create_task(trading_loop())
    log.info("BOT CEREBRO v4.1 INICIADO")
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        log.info("Bot detenido por usuario")
    except Exception:
        log.exception("Error fatal")
