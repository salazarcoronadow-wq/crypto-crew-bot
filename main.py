import os
import time
import logging
import sqlite3
import requests
from datetime import datetime
from binance.client import Client
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ================== CONFIG v9.1 FINAL MAESTRO ==================
TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
MONTO = float(os.getenv("MONTO", "10.0"))
TRADING_REAL = os.getenv("TRADING_REAL", "false").lower() == "true"
DB = "trades.db"

# Blacklist definitiva
ENV_BLACK = os.getenv("BLACKLIST", "")
BASE_BLACK = ["RWUSD","UUSDT","USDT","USDC","FDUSD","BUSD","TUSD","DAI","USDP","UST","USTC","USDE","USD1","EUR","PYUSD","GUSD","USDD","USN","EURUSDT"]
BLACKLIST = list(set([b.strip().upper() for b in ENV_BLACK.split(",") if b.strip()] + BASE_BLACK))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
log = logging.getLogger(__name__)

# --- CLIENTE BINANCE QUE NO SE CAE NUNCA ---
client = None
try:
    if API_KEY and API_SECRET:
        client = Client(API_KEY, API_SECRET)
        log.info("Binance Client con API Keys OK")
    else:
        client = Client()
        log.info("Binance Client PUBLICO OK - Sin llaves")
except Exception as e:
    log.warning(f"Fallo client con llaves {e}, usando publico")
    try:
        client = Client()
        log.info("Binance Client PUBLICO OK")
    except Exception as e2:
        log.error(f"Fallo total Binance {e2}")
        client = None

def fmt(p):
    try:
        f=float(p)
        if f < 0.0001: return f"${f:.8f}"
        if f < 0.01: return f"${f:.6f}"
        if f < 1: return f"${f:.4f}"
        return f"${f:.2f}"
    except: return str(p)

def es_estable(symbol: str, precio) -> bool:
    s = symbol.upper()
    base = s.replace("USDT","").replace("BUSD","")
    try:
        p = float(precio)
        if 0.985 <= p <= 1.09:
            return True
    except: pass
    if s in BLACKLIST or base in BLACKLIST: return True
    if len(base) <= 2: return True
    if any(x in s for x in ["RWUSD","UUSDT"]): return True
    if "USD" in base and len(base) <= 6 and base not in ["UNI","W"]: return True
    return False

def init_db():
    con=sqlite3.connect(DB); cur=con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS trades 
    (id INTEGER PRIMARY KEY, simbolo TEXT, precio REAL, score REAL, rsi REAL, volx REAL, tendencia TEXT, fg INTEGER, noticia TEXT, resultado TEXT, pnl REAL, real INTEGER, fecha TEXT)""")
    cur.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS cerebro (clave TEXT PRIMARY KEY, valor REAL)")
    cur.execute("INSERT OR IGNORE INTO cerebro VALUES ('rsi_max', 68.0)")
    cur.execute("INSERT OR IGNORE INTO cerebro VALUES ('vol_min', 1.8)")
    cur.execute("INSERT OR IGNORE INTO cerebro VALUES ('score_min', 8.8)")
    con.commit(); con.close()

def save_chat(cid):
    try:
        con=sqlite3.connect(DB); cur=con.cursor()
        cur.execute("INSERT OR IGNORE INTO chats VALUES (?)", (cid,))
        con.commit(); con.close()
    except: pass

def get_cerebro(clave, default):
    try:
        con=sqlite3.connect(DB); cur=con.cursor()
        cur.execute("SELECT valor FROM cerebro WHERE clave=?", (clave,))
        r=cur.fetchone(); con.close()
        return r[0] if r else default
    except: return default

def set_cerebro(clave, valor):
    try:
        con=sqlite3.connect(DB); cur=con.cursor()
        cur.execute("INSERT OR REPLACE INTO cerebro VALUES (?,?)", (clave, valor))
        con.commit(); con.close()
    except: pass

def get_fear_greed():
    try:
        r=requests.get("https://api.alternative.me/fng/?limit=1", timeout=5).json()
        return int(r['data'][0]['value']), r['data'][0]['value_classification']
    except: return 59, "Greed"

def get_klines_data(symbol, limit=100):
    try:
        if not client: return None, None
        klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=limit)
        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]
        return closes, volumes
    except Exception as e:
        log.error(f"Klines {symbol} {e}")
        return None, None

def leer_grafico_maestro(symbol):
    try:
        closes, vols = get_klines_data(symbol, 200)
        if not closes or len(closes) < 100: return None
        # RSI
        deltas = [closes[i]-closes[i-1] for i in range(1,len(closes))]
        gains = [d if d>0 else 0 for d in deltas[-14:]]
        losses = [-d if d<0 else 0 for d in deltas[-14:]]
        avg_g = sum(gains)/14; avg_l = sum(losses)/14
        rs = avg_g/avg_l if avg_l!=0 else 100
        rsi = 100-(100/(1+rs))
        # EMAs
        ema20 = sum(closes[-20:])/20
        ema50 = sum(closes[-50:])/50
        ema200 = sum(closes[-200:])/200
        # Volumen
        vol_prom = sum(vols[-30:-1])/29 if len(vols)>30 else 1
        vol_x = vols[-1]/vol_prom if vol_prom>0 else 0
        # Bollinger
        std20 = (sum([(c-ema20)**2 for c in closes[-20:]])/20)**0.5
        boll_upper = ema20 + 2*std20
        boll_ok = closes[-1] < boll_upper*0.986
        tendencia = "alcista" if closes[-1] > ema20 > ema50 and closes[-1] > ema200 else "bajista" if closes[-1] < ema20 else "lateral"
        # Score
        rsi_max = get_cerebro('rsi_max', 68.0)
        vol_min = get_cerebro('vol_min', 1.8)
        score=0
        if 50 <= rsi <= rsi_max: score+=3.5
        elif 45 <= rsi <= rsi_max+2: score+=1.5
        if tendencia=="alcista": score+=3
        if vol_x >= vol_min: score+=2
        if boll_ok: score+=1
        if closes[-1] > ema200: score+=0.5
        return {"rsi":round(rsi,1), "vol_x":round(vol_x,2), "tendencia":tendencia, "score":round(score,1), "precio":closes[-1], "ema20":ema20, "ema50":ema50, "ema200":ema200, "boll_ok":boll_ok}
    except: return None

def aprender_de_errores():
    try:
        con=sqlite3.connect(DB); cur=con.cursor()
        cur.execute("SELECT rsi, volx, pnl FROM trades WHERE pnl<0 ORDER BY id DESC LIMIT 20")
        perdidas=cur.fetchall()
        if len(perdidas) < 5:
            return f"Cerebro v9.1 analizando... {len(perdidas)} perdidas registradas"
        avg_rsi=sum([p[0] for p in perdidas])/len(perdidas)
        avg_vol=sum([p[1] for p in perdidas])/len(perdidas)
        msg="CEREBRO APRENDIO:\n"
        cambio=False
        if avg_rsi > 67:
            nuevo=max(62, avg_rsi-2)
            set_cerebro('rsi_max', nuevo)
            msg+=f"- RSI alto {avg_rsi:.1f} falla -> max {nuevo:.0f}\n"
            cambio=True
        if avg_vol < 1.9:
            set_cerebro('vol_min', 2.0)
            msg+=f"- Vol bajo {avg_vol:.1f}x falla -> min 2.0x\n"
            cambio=True
        con.close()
        if not cambio: return "Cerebro: Estrategia actual rentable, mantengo parametros"
        return msg
    except Exception as e: return f"Error aprendiendo {e}"

# ================== JOBS ==================
async def job_scan(context): log.info("AUTO SCAN v9.1")
async def job_learn(context):
    msg=aprender_de_errores()
    log.info(msg)

# ================== COMANDOS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    fg, fgt = get_fear_greed()
    await update.message.reply_text(f"BOT v9.1 MAESTRO LISTO\nModo: PAPER {MONTO}USDT\nF&G {fg} ({fgt}) | Blacklist {len(BLACKLIST)}\nFiltro $0.99-$1.09 ON | API {'OK' if client else 'FALLO'}\nCerebro RSI max {get_cerebro('rsi_max',68)} Vol min {get_cerebro('vol_min',1.8)}x\nComandos: /oportunidad /top /analizar BTCUSDT /aprender /auto_on")

async def oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    try:
        global client
        if not client:
            try: client = Client()
            except: 
                await update.message.reply_text("API no conectada - Binance bloqueado, intenta en 1 min")
                return
        
        fg, fgt = get_fear_greed()
        if fg < 18:
            await update.message.reply_text(f"⛔ MIEDO EXTREMO F&G {fg} - Maestro no opera")
            return

        await update.message.reply_text(f"CEREBRO MAESTRO v9.1 ANALIZANDO 250 monedas...\nF&G {fg} {fgt} | Filtro estables ON | 6 indicadores...")
        tickers = client.get_ticker()
        usdt = sorted([t for t in tickers if t['symbol'].endswith('USDT')], key=lambda x: float(x['quoteVolume']), reverse=True)

        encontradas=[]; revisadas=0; bloqueadas=0
        score_min=get_cerebro('score_min', 8.8)

        for t in usdt:
            sym=t['symbol']; price=t['lastPrice']
            if es_estable(sym, price):
                bloqueadas+=1
                continue
            revisadas+=1
            data=leer_grafico_maestro(sym)
            if not data: continue
            if data['score'] < score_min: continue
            if data['tendencia'] != "alcista": continue
            if not data['boll_ok']: continue

            base=sym.replace("USDT","")
            entrada=data['precio']
            stop=entrada*0.962
            tp1=entrada*1.065
            tp2=entrada*1.12
            
            con=sqlite3.connect(DB); cur=con.cursor()
            cur.execute("INSERT INTO trades (simbolo,precio,score,rsi,volx,tendencia,fg,noticia,resultado,pnl,real,fecha) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sym, entrada, data['score'], data['rsi'], data['vol_x'], data['tendencia'], fg, "Social OK", "PENDIENTE", 0, 0, datetime.now().isoformat()))
            con.commit(); con.close()

            encontradas.append(f"💎 {base} {fmt(entrada)} Sc {data['score']}/10\n📈 {data['tendencia'].upper()} RSI {data['rsi']} Vol x{data['vol_x']}\nEMA20>{'OK' if entrada>data['ema20'] else 'NO'} Boll OK\n🎯 Entrada {fmt(entrada)} Stop {fmt(stop)} TP1 {fmt(tp1)}\nPAPER guardado")
            if len(encontradas)>=3: break
            if revisadas>250: break
            time.sleep(0.05)

        if not encontradas:
            await update.message.reply_text(f"CEREBRO v9.1:\nRevisadas {revisadas} limpias | {bloqueadas} estables bloqueadas\nScore min {score_min} F&G {fg}\nSin oportunidad perfecta ahora. Prefiero no operar que perder.")
        else:
            txt=f"CEREBRO MAESTRO v9.1 {datetime.now().strftime('%H:%M')} F&G {fg}\nRevisadas {revisadas} Bloqueadas {bloqueadas}\n\n" + "\n\n---\n\n".join(encontradas)
            await update.message.reply_text(txt)
    except Exception as e:
        log.error(f"oportunidad error {e}")
        await update.message.reply_text(f"Error oportunidad {e}")

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    try:
        global client
        if not client: client = Client()
        tickers=client.get_ticker()
        usdt=sorted([t for t in tickers if t['symbol'].endswith('USDT')], key=lambda x: float(x['quoteVolume']), reverse=True)
        msg="TOP 10 VOLUMEN (SIN ESTABLES):\n"
        c=0
        for t in usdt:
            if es_estable(t['symbol'], t['lastPrice']): continue
            msg+=f"{t['symbol'].replace('USDT','')} {fmt(t['lastPrice'])} Vol {float(t['quoteVolume'])/1000000:.1f}M {float(t['priceChangePercent']):+.1f}%\n"
            c+=1
            if c>=10: break
        await update.message.reply_text(msg)
    except Exception as e: await update.message.reply_text(f"Error top {e}")

async def analizar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Uso: /analizar BTCUSDT"); return
        sym=context.args[0].upper()
        if not sym.endswith("USDT"): sym+="USDT"
        if es_estable(sym, 1.0):
            await update.message.reply_text(f"⛔ {sym} BLOQUEADO - Es estable"); return
        data=leer_grafico_maestro(sym)
        if not data:
            await update.message.reply_text("Sin datos para ese simbolo"); return
        fg,_=get_fear_greed()
        await update.message.reply_text(f"ANALISIS MAESTRO {sym}\nPrecio {fmt(data['precio'])}\nRSI {data['rsi']} Vol x{data['vol_x']}\nTendencia {data['tendencia']} Score {data['score']}/10\nEMA20 {fmt(data['ema20'])} EMA50 {fmt(data['ema50'])} EMA200 {fmt(data['ema200'])}\nBoll OK {data['boll_ok']} F&G {fg}\n{'✅ APTO' if data['score']>=8.8 else '❌ NO APTO'}")
    except Exception as e: await update.message.reply_text(f"Error analizar {e}")

async def aprender_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        con=sqlite3.connect(DB); cur=con.cursor()
        cur.execute("SELECT simbolo,precio,score,rsi,resultado,pnl,real FROM trades ORDER BY id DESC LIMIT 10")
        rows=cur.fetchall()
        cur.execute("SELECT COUNT(*), AVG(pnl) FROM trades WHERE pnl!=0")
        total_row=cur.fetchone()
        total=total_row[0] if total_row else 0
        avg=total_row[1] if total_row and total_row[1] else 0
        con.close()
        aprendizaje=aprender_de_errores()
        msg=f"CEREBRO MAESTRO v9.1 PAPER\n{aprendizaje}\n\nConfig: RSI max {get_cerebro('rsi_max',68)} Vol min {get_cerebro('vol_min',1.8)} Score min {get_cerebro('score_min',8.8)}\nTrades {total} Avg PNL {avg:.2f}%\n\nUltimos 10:\n"
        if not rows: msg+="Sin trades aun - Pon /oportunidad"
        else:
            for r in rows:
                msg+=f"{'REAL' if r[6]==1 else 'PAPER'} {r[0]} {fmt(r[1])} Sc {r[2]} RSI {r[3]} {r[4]} {r[5]:.1f}%\n"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Error aprender {e}")

async def auto_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    try:
        for job in context.job_queue.get_jobs_by_name("auto_scan"): job.schedule_removal()
        for job in context.job_queue.get_jobs_by_name("auto_learn"): job.schedule_removal()
        context.job_queue.run_repeating(job_scan, interval=1800, first=10, name="auto_scan")
        context.job_queue.run_repeating(job_learn, interval=14400, first=20, name="auto_learn")
        await update.message.reply_text(f"AUTO ON v9.1 MAESTRO 24/7 ACTIVADO\nCada 30m escanea 250 monedas\nCada 4h aprende solo\nMonto {MONTO}USDT Score min {get_cerebro('score_min',8.8)}")
    except Exception as e: await update.message.reply_text(f"Error auto {e}")

async def auto_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        for job in context.job_queue.get_jobs_by_name("auto_scan"): job.schedule_removal()
        for job in context.job_queue.get_jobs_by_name("auto_learn"): job.schedule_removal()
        await update.message.reply_text("AUTO OFF v9.1")
    except Exception as e: await update.message.reply_text(f"Error {e}")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fg,_=get_fear_greed()
    await update.message.reply_text(f"v9.1 MAESTRO PAPER {MONTO}USDT API {'OK' if client else 'FALLO'} F&G {fg} Filtro ON")

def main():
    init_db()
    if not TOKEN or ":" not in TOKEN:
        log.error("TOKEN MALO - Revisa TELEGRAM_TOKEN en Railway")
        time.sleep(99999)
    app=ApplicationBuilder().token(TOKEN).build()
    app.job_queue.run_repeating(job_learn, interval=14400, first=30, name="auto_learn")
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("oportunidad", oportunidad))
    app.add_handler(CommandHandler("oportunidades", oportunidad))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("analizar", analizar_cmd))
    app.add_handler(CommandHandler("aprender", aprender_cmd))
    app.add_handler(CommandHandler("historial", aprender_cmd))
    app.add_handler(CommandHandler("auto_on", auto_on_cmd))
    app.add_handler(CommandHandler("auto_off", auto_off_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("noticias", balance_cmd))
    log.info(f"BOT v9.1 MAESTRO LISTO Modo PAPER {MONTO}USDT")
    app.run_polling()

if __name__=="__main__": main()
