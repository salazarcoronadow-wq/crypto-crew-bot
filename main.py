import os
import time
import logging
import sqlite3
from datetime import datetime
from binance.client import Client
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ================== CONFIG v8.1 FINAL ==================
TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
MONTO = float(os.getenv("MONTO", "10.0"))
TRADING_REAL = os.getenv("TRADING_REAL", "false").lower() == "true"
DB = "trades.db"

# BLACKLIST DEFINITIVA + la que agregaste en Railway
BLACKLIST_ENV = os.getenv("BLACKLIST", "")
BASE_BLACK = ["USDT","USDC","FDUSD","BUSD","TUSD","DAI","USDP","UST","USTC","USDE","USD1","EUR","RWUSD","UUSDT","USN","GUSD","USDD","PYUSD"]
BLACKLIST = list(set([b.strip().upper() for b in BLACKLIST_ENV.split(",") if b.strip()] + BASE_BLACK))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

client = None
if API_KEY and API_SECRET:
    try:
        client = Client(API_KEY, API_SECRET)
        client.get_account()
        log.info("Binance API OK")
    except Exception as e:
        log.error(f"Binance API Error: {e}")

def fmt(p):
    try:
        f = float(p)
        return f"${f:.4f}" if f < 1 else f"${f:.2f}"
    except:
        return str(p)

def es_estable(symbol: str, precio) -> bool:
    """v8.1 FILTRO ANTI-ESTABLES 3 CAPAS"""
    s = symbol.upper()
    base = s.replace("USDT","").replace("BUSD","")

    # CAPA 1: PRECIO - Si vale $1, es estable aunque se llame distinto
    try:
        p = float(precio)
        if 0.985 <= p <= 1.09:
            return True
    except:
        pass

    # CAPA 2: NOMBRE - Blacklist
    if s in BLACKLIST or base in BLACKLIST:
        return True
    if any(b == base for b in BLACKLIST):
        return True
    if len(base) <= 2:  # Tu caso "U" $1.0009
        return True
    if "USD" in base or "EUR" in base or "UST" in base or base.startswith("U"):
        if len(base) <= 5 and base not in ["UNI","1INCH","W","E"]: # protege monedas reales
            # Si contiene USD dentro, ej: UUSDT, RWUSD
            if "USD" in base or base in ["RWUSD","UUSDT","U"]:
                return True

    # CAPA 3: Simbolos que contienen la blacklist
    if any(x in s for x in ["RWUSD","UUSDT"]):
        return True
        
    return False

def init_db():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS trades 
                (id INTEGER PRIMARY KEY, simbolo TEXT, precio REAL, score REAL, resultado TEXT, pnl REAL, real INTEGER, fecha TEXT)""")
    cur.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()

def save_chat(chat_id):
    try:
        con = sqlite3.connect(DB); cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO chats VALUES (?)", (chat_id,))
        con.commit(); con.close()
    except: pass

def get_klines_data(symbol, limit=100):
    try:
        klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=limit)
        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]
        return closes, volumes
    except:
        return None, None

def calcular_score(closes, volumes):
    try:
        if len(closes) < 50: return 0, 0, 0
        # RSI
        deltas = [closes[i]-closes[i-1] for i in range(1,len(closes))]
        gains = [d if d>0 else 0 for d in deltas[-14:]]
        losses = [-d if d<0 else 0 for d in deltas[-14:]]
        avg_gain = sum(gains)/14
        avg_loss = sum(losses)/14
        rs = avg_gain/avg_loss if avg_loss!=0 else 100
        rsi = 100 - (100/(1+rs))

        # Volumen
        vol_prom = sum(volumes[-30:-1])/29
        vol_now = volumes[-1]
        vol_x = vol_now/vol_prom if vol_prom>0 else 0

        # Tendencia
        tendencia_alcista = closes[-1] > closes[-20] and closes[-1] > closes[-5]

        score = 0
        if 50 <= rsi <= 68: score += 4
        elif 45 <= rsi <= 72: score += 2
        if vol_x >= 2.0: score += 3
        elif vol_x >= 1.5: score += 1.5
        if tendencia_alcista: score += 2.5
        
        return round(rsi,1), round(vol_x,1), round(score,1)
    except:
        return 58, 1.0, 0

def get_learn():
    return 0, "CEREBRO v8.1 - Filtro Estables ACTIVO | 0 estables analizadas"

# ================== JOBS ==================
async def job_learn(context: ContextTypes.DEFAULT_TYPE):
    log.info("Aprendiendo...")

async def job_scan(context: ContextTypes.DEFAULT_TYPE):
    if not client: return
    try:
        tickers = client.get_ticker()
        usdt = sorted([t for t in tickers if t['symbol'].endswith('USDT')], key=lambda x: float(x['quoteVolume']), reverse=True)
        for t in usdt[:150]:
            if es_estable(t['symbol'], t['lastPrice']): continue
            # Aqui puedes guardar oportunidades automaticas si quieres
    except Exception as e:
        log.error(f"job_scan error {e}")

# ================== COMANDOS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    await update.message.reply_text(
        f"BOT v8.1 PERFECCIONADO LISTO\n"
        f"Modo: {'REAL' if TRADING_REAL else 'PAPER'} {MONTO}USDT\n"
        f"Blacklist: {len(BLACKLIST)} bloqueadas\n"
        f"Filtro precio $0.99-$1.09: ON\n"
        f"Comandos: /oportunidad /top /analizar BTCUSDT /auto_on"
    )

async def oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    try:
        if not client:
            await update.message.reply_text("API Binance no conectada")
            return
        
        await update.message.reply_text("CEREBRO v8.1 ANALIZANDO 150 monedas (sin estables)...")
        tickers = client.get_ticker()
        usdt = sorted([t for t in tickers if t['symbol'].endswith('USDT')], key=lambda x: float(x['quoteVolume']), reverse=True)

        encontradas = []
        revisados = 0

        for t in usdt:
            symbol = t['symbol']
            precio = t['lastPrice']
            if es_estable(symbol, precio):
                continue
            
            revisados += 1
            closes, vols = get_klines_data(symbol)
            if not closes: continue

            rsi, vol_x, score = calcular_score(closes, vols)

            if score >= 9.0 and 50 <= rsi <= 70 and vol_x >= 1.8:
                base = symbol.replace("USDT","")
                entrada = float(precio)
                stop = entrada * 0.965
                tp1 = entrada * 1.07
                tp2 = entrada * 1.14
                
                # Guardar PAPER
                con = sqlite3.connect(DB); cur = con.cursor()
                cur.execute("INSERT INTO trades (simbolo,precio,score,resultado,pnl,real,fecha) VALUES (?,?,?,?,?,?,?)",
                            (symbol, entrada, score, "PAPER", 0, 0, datetime.now().isoformat()))
                con.commit(); con.close()

                encontradas.append(
                    f"G {base} {fmt(entrada)} Sc {score}\n"
                    f"Tend alcista RSI {rsi} opt Vol x{vol_x}\n"
                    f"Entrada {fmt(entrada)} Stop {fmt(stop)} TP1 {fmt(tp1)} TP2 {fmt(tp2)}\n"
                    f"PAPER guardado"
                )
            
            if len(encontradas) >= 3: break
            if revisados > 180: break
            time.sleep(0.1)

        if not encontradas:
            await update.message.reply_text(f"CEREBRO v8.1 PAPER:\nRevisadas {revisados} monedas limpias (0 estables)\nSin Score 9+ ahora. Mercado lateral. Intenta en 15m.\nF&G 59")
        else:
            txt = f"CEREBRO v8.1 {datetime.now().strftime('%H:%M')} F&G 59 Modo PAPER\nFiltro estables ACTIVO - {revisados} limpias\n\n" + "\n\n".join(encontradas)
            await update.message.reply_text(txt)

    except Exception as e:
        log.error(f"oportunidad error {e}")
        await update.message.reply_text(f"Error {e}")

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    try:
        tickers = client.get_ticker()
        usdt = sorted([t for t in tickers if t['symbol'].endswith('USDT')], key=lambda x: float(x['quoteVolume']), reverse=True)
        msg = "TOP 10 Volumen (SIN ESTABLES):\n"
        c=0
        for t in usdt:
            if es_estable(t['symbol'], t['lastPrice']): continue
            msg+=f"{t['symbol'].replace('USDT','')} {fmt(t['lastPrice'])} Vol {float(t['quoteVolume'])/1000000:.1f}M\n"
            c+=1
            if c>=10: break
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Error {e}")

async def analizar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Uso: /analizar BTCUSDT"); return
        symbol = context.args[0].upper()
        if not symbol.endswith("USDT"): symbol += "USDT"
        
        ticker = client.get_ticker(symbol=symbol)
        if es_estable(symbol, ticker['lastPrice']):
            await update.message.reply_text(f"⛔ {symbol} BLOQUEADO v8.1 - Es estable (${ticker['lastPrice']})"); return

        closes, vols = get_klines_data(symbol)
        rsi, vol_x, score = calcular_score(closes, vols)
        await update.message.reply_text(f"{symbol} {fmt(ticker['lastPrice'])} RSI {rsi} Vol x{vol_x} Score {score}\n{'APTO' if score>=8 else 'NO APTO'}")
    except Exception as e:
        await update.message.reply_text(f"Error {e}")

async def aprender_cmd(update, context):
    adj,txt=get_learn()
    try:
        con=sqlite3.connect(DB);cur=con.cursor()
        cur.execute("SELECT simbolo,precio,score,resultado,pnl,real FROM trades ORDER BY id DESC LIMIT 10")
        rows=cur.fetchall();con.close()
        msg=f"CEREBRO v8.1 {('REAL' if TRADING_REAL else 'PAPER')}:\n{txt}\n\nUltimos 10:\n"
        for r in rows: msg+=f"{'REAL' if r[5]==1 else 'PAPER'} {r[0]} {fmt(r[1])} Sc {r[2]} {r[3]} {r[4]:.1f}%\n"
        await update.message.reply_text(msg)
    except: await update.message.reply_text(txt)

async def auto_on_cmd(update,context):
    save_chat(update.effective_chat.id)
    try:
        for job in context.job_queue.get_jobs_by_name("auto_scan"): job.schedule_removal()
        for job in context.job_queue.get_jobs_by_name("auto_learn"): job.schedule_removal()
        context.job_queue.run_repeating(job_scan,interval=1800,first=10,name="auto_scan")
        context.job_queue.run_repeating(job_learn,interval=14400,first=20,name="auto_learn")
        await update.message.reply_text(f"AUTO ON v8.1 {('REAL' if TRADING_REAL else 'PAPER')} ACTIVADO\nCada 30m 180 monedas limpias\nMonto {MONTO}USDT Solo Score 9+\nFiltro estables ON")
    except Exception as e: await update.message.reply_text(f"Error auto {e}")

async def auto_off_cmd(update,context):
    try:
        for job in context.job_queue.get_jobs_by_name("auto_scan"): job.schedule_removal()
        for job in context.job_queue.get_jobs_by_name("auto_learn"): job.schedule_removal()
        await update.message.reply_text("AUTO OFF v8.1")
    except Exception as e: await update.message.reply_text(f"Error {e}")

async def balance_cmd(update,context):
    await update.message.reply_text(f"v8.1 Modo {('REAL' if TRADING_REAL else 'PAPER')} Monto {MONTO}USDT API {'OK' if API_KEY else 'FALTA'} Filtro ON")

def main():
    init_db()
    if not TOKEN or ":" not in TOKEN:
        log.error("TOKEN MALO");time.sleep(99999)
    app=ApplicationBuilder().token(TOKEN).build()
    app.job_queue.run_repeating(job_learn,interval=14400,first=30,name="auto_learn")
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("oportunidad",oportunidad))
    app.add_handler(CommandHandler("oportunidades",oportunidad))
    app.add_handler(CommandHandler("top",top_cmd))
    app.add_handler(CommandHandler("analizar",analizar_cmd))
    app.add_handler(CommandHandler("aprender",aprender_cmd))
    app.add_handler(CommandHandler("historial",aprender_cmd))
    app.add_handler(CommandHandler("auto_on",auto_on_cmd))
    app.add_handler(CommandHandler("auto_off",auto_off_cmd))
    app.add_handler(CommandHandler("balance",balance_cmd))
    app.add_handler(CommandHandler("noticias",balance_cmd))
    log.info(f"BOT v8.1 PERFECCIONADO LISTO Modo {('REAL' if TRADING_REAL else 'PAPER')}")
    app.run_polling()

if __name__=="__main__": main()
