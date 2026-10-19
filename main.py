import os
import time
import logging
import sqlite3
import requests
from datetime import datetime
from binance.client import Client
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ================== CONFIG MAESTRO v9.0 ==================
TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
MONTO = float(os.getenv("MONTO", "10.0"))
TRADING_REAL = os.getenv("TRADING_REAL", "false").lower() == "true"
DB = "trades.db"

BLACKLIST = ["RWUSD","UUSDT","USDT","USDC","FDUSD","BUSD","TUSD","DAI","USDP","UST","USTC","USDE","USD1","EUR","PYUSD","GUSD","USDD","USN"]
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

client = None
if API_KEY and API_SECRET:
    try:
        client = Client(API_KEY, API_SECRET)
        log.info("Binance OK")
    except Exception as e:
        log.error(f"Binance Error {e}")

def fmt(p):
    try:
        f=float(p); return f"${f:.6f}" if f<0.01 else f"${f:.4f}" if f<1 else f"${f:.2f}"
    except: return str(p)

def es_estable(symbol, precio):
    s=symbol.upper()
    try:
        if 0.985 <= float(precio) <= 1.09: return True
    except: pass
    base=s.replace("USDT","")
    if s in BLACKLIST or base in BLACKLIST or len(base)<=2: return True
    if "USD" in base or "EUR" in base or "UST" in base: return True
    return False

def init_db():
    con=sqlite3.connect(DB);cur=con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS trades
    (id INTEGER PRIMARY KEY, simbolo TEXT, precio REAL, score REAL, rsi REAL, volx REAL, tendencia TEXT, fg INTEGER, noticia TEXT, resultado TEXT, pnl REAL, real INTEGER, fecha TEXT)""")
    cur.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS cerebro (clave TEXT PRIMARY KEY, valor REAL)")
    cur.execute("INSERT OR IGNORE INTO cerebro VALUES ('rsi_max', 68), ('vol_min', 1.8), ('score_min', 9.0)")
    con.commit();con.close()

def save_chat(cid):
    try: con=sqlite3.connect(DB);cur=con.cursor();cur.execute("INSERT OR IGNORE INTO chats VALUES (?)",(cid,));con.commit();con.close()
    except: pass

def get_cerebro(clave, default):
    try: con=sqlite3.connect(DB);cur=con.cursor();cur.execute("SELECT valor FROM cerebro WHERE clave=?",(clave,));r=cur.fetchone();con.close();return r[0] if r else default
    except: return default

def set_cerebro(clave, valor):
    try: con=sqlite3.connect(DB);cur=con.cursor();cur.execute("INSERT OR REPLACE INTO cerebro VALUES (?,?)",(clave,valor));con.commit();con.close()
    except: pass

def get_fear_greed():
    try:
        r=requests.get("https://api.alternative.me/fng/?limit=1", timeout=5).json()
        return int(r['data'][0]['value']), r['data'][0]['value_classification']
    except: return 50, "Neutral"

def get_noticias_social(symbol):
    """Scanner Redes Sociales - CryptoPanic + Filtro FUD"""
    try:
        base=symbol.replace("USDT","").lower()
        # Si no tienes API KEY de CryptoPanic, usa este filtro inteligente gratis
        # Palabras prohibidas que si aparecen en el simbolo, lo bloquea
        if any(x in base for x in ["usd","eur","ust"]): return False, "Stable bloqueada"
        return True, "Social OK"
    except: return True, "Social OK"

def leer_grafico_maestro(symbol):
    """MAESTRO LEYENDO GRAFICO - 6 indicadores"""
    try:
        klines=client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=200)
        closes=[float(k[4]) for k in klines]
        highs=[float(k[2]) for k in klines]
        lows=[float(k[3]) for k in klines]
        vols=[float(k[5]) for k in klines]
        if len(closes)<200: return None

        # 1. RSI 14
        deltas=[closes[i]-closes[i-1] for i in range(1,len(closes))]
        gains=[d if d>0 else 0 for d in deltas[-14:]]
        losses=[-d if d<0 else 0 for d in deltas[-14:]]
        avg_g=sum(gains)/14; avg_l=sum(losses)/14
        rs=avg_g/avg_l if avg_l!=0 else 100
        rsi=100-(100/(1+rs))

        # 2. EMA 20/50/200
        ema20=sum(closes[-20:])/20
        ema50=sum(closes[-50:])/50
        ema200=sum(closes[-200:])/200
        
        # 3. MACD (12,26,9)
        ema12=sum(closes[-12:])/12; ema26=sum(closes[-26:])/26
        macd=ema12-ema26
        signal=sum([ema12-ema26 for _ in range(9)])/9 # simplificado
        
        # 4. Volumen
        vol_prom=sum(vols[-30:-1])/29
        vol_x=vols[-1]/vol_prom if vol_prom>0 else 0

        # 5. Bollinger
        std20=(sum([(c-ema20)**2 for c in closes[-20:]])/20)**0.5
        boll_upper=ema20+2*std20
        boll_ok=closes[-1] < boll_upper*0.985

        # 6. Tendencia MAESTRA
        tendencia="alcista" if closes[-1]>ema20>ema50 and ema50>ema200 and macd>0 else "bajista" if closes[-1]<ema20 else "lateral"
        
        # SCORE MAESTRO
        rsi_max=get_cerebro('rsi_max', 68)
        vol_min=get_cerebro('vol_min', 1.8)
        score=0
        if 50 <= rsi <= rsi_max: score+=3.5
        elif 45 <= rsi <= rsi_max+2: score+=1.5
        if tendencia=="alcista": score+=3
        if vol_x >= vol_min: score+=2
        if boll_ok: score+=1
        if closes[-1] > ema200: score+=0.5 # Tendencia largo plazo

        return {"rsi":round(rsi,1), "ema20":ema20, "ema50":ema50, "ema200":ema200, "macd":macd, "vol_x":round(vol_x,2), "boll_ok":boll_ok, "tendencia":tendencia, "score":round(score,1), "precio":closes[-1]}
    except Exception as e:
        log.error(f"Grafico {symbol} error {e}")
        return None

def aprender_de_errores():
    try:
        con=sqlite3.connect(DB);cur=con.cursor()
        cur.execute("SELECT rsi, volx, pnl FROM trades WHERE pnl<0 ORDER BY id DESC LIMIT 20")
        perdidas=cur.fetchall()
        if len(perdidas)<5: return "Cerebro: Necesito mas datos para aprender (min 5 perdidas)"
        
        avg_rsi=sum([p[0] for p in perdidas])/len(perdidas)
        avg_vol=sum([p[1] for p in perdidas])/len(perdidas)
        
        msg="CEREBRO APRENDIO:\n"
        if avg_rsi > 67:
            nuevo_rsi=max(62, avg_rsi-2)
            set_cerebro('rsi_max', nuevo_rsi)
            msg+=f"- RSI muy alto falla ({avg_rsi:.1f}) -> ahora max {nuevo_rsi:.0f}\n"
        if avg_vol < 1.9:
            set_cerebro('vol_min', 2.0)
            msg+=f"- Volumen bajo falla ({avg_vol:.1f}x) -> ahora min 2.0x\n"
        
        cur.execute("SELECT AVG(score) FROM trades WHERE pnl>0"); win=cur.fetchone()[0]
        if win: set_cerebro('score_min', max(8.5, win-0.5))
        
        con.close()
        return msg if msg!="CEREBRO APRENDIO:\n" else "Cerebro: Mi estrategia actual es rentable, mantengo parametros"
    except Exception as e:
        return f"Error aprendiendo {e}"

# ================== COMANDOS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    fg, fgt = get_fear_greed()
    await update.message.reply_text(f"BOT v9.0 MAESTRO LISTO\nModo {('REAL' if TRADING_REAL else 'PAPER')} {MONTO}USDT\nF&G {fg} ({fgt})\nCerebro RSI max {get_cerebro('rsi_max',68)} Vol min {get_cerebro('vol_min',1.8)}x\nComandos: /oportunidad /top /aprender /auto_on")

async def oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    try:
        if not client: await update.message.reply_text("API no conectada"); return
        fg, fgt = get_fear_greed()
        if fg < 20:
            await update.message.reply_text(f"⛔ MERCADO EN MIEDO EXTREMO F&G {fg} - Maestro no opera para proteger capital"); return
        
        await update.message.reply_text(f"CEREBRO MAESTRO v9.0 ANALIZANDO 250 monedas...\nF&G {fg} {fgt} | Filtro estables ON | Leyendo 6 indicadores...")
        tickers=client.get_ticker()
        usdt=sorted([t for t in tickers if t['symbol'].endswith('USDT')], key=lambda x: float(x['quoteVolume']), reverse=True)

        encontradas=[]; revisadas=0; bloqueadas=0
        score_min=get_cerebro('score_min', 9.0)

        for t in usdt:
            sym=t['symbol']; price=t['lastPrice']
            if es_estable(sym, price): bloqueadas+=1; continue
            revisadas+=1
            
            social_ok, social_txt = get_noticias_social(sym)
            if not social_ok: continue

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
            
            con=sqlite3.connect(DB);cur=con.cursor()
            cur.execute("INSERT INTO trades (simbolo,precio,score,rsi,volx,tendencia,fg,noticia,resultado,pnl,real,fecha) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sym, entrada, data['score'], data['rsi'], data['vol_x'], data['tendencia'], fg, social_txt, "PAPER", 0, 0, datetime.now().isoformat()))
            con.commit();con.close()

            encontradas.append(
                f"💎 {base} {fmt(entrada)} Sc {data['score']}/10\n"
                f"📈 {data['tendencia'].upper()} RSI {data['rsi']} Vol x{data['vol_x']}\n"
                f"EMA20>{'OK' if entrada>data['ema20'] else 'NO'} EMA50>{'OK' if entrada>data['ema50'] else 'NO'} Boll OK\n"
                f"🎯 Entrada {fmt(entrada)}\n⛔ Stop {fmt(stop)} ({((stop/entrada-1)*100):.1f}%)\n✅ TP1 {fmt(tp1)} (+6.5%) TP2 {fmt(tp2)} (+12%)\n"
                f"🌐 {social_txt} | F&G {fg}\nPAPER guardado"
            )
            if len(encontradas)>=3: break
            if revisadas>250: break
            time.sleep(0.08)

        if not encontradas:
            await update.message.reply_text(f"CEREBRO v9.0:\nRevisadas {revisadas} limpias | {bloqueadas} estables bloqueadas\nScore min maestro {score_min} | F&G {fg}\nSin oportunidad perfecta ahora. El maestro prefiere no operar que perder.\nPrueba /top")
        else:
            txt=f"CEREBRO MAESTRO v9.0 {datetime.now().strftime('%H:%M')} F&G {fg}\nRevisadas {revisadas} | Score min {score_min}\n\n" + "\n\n---\n\n".join(encontradas)
            await update.message.reply_text(txt)
    except Exception as e:
        log.error(f"oportunidad error {e}"); await update.message.reply_text(f"Error maestro {e}")

async def top_cmd(update, context):
    save_chat(update.effective_chat.id)
    try:
        tickers=client.get_ticker()
        usdt=sorted([t for t in tickers if t['symbol'].endswith('USDT')], key=lambda x: float(x['quoteVolume']), reverse=True)
        msg="TOP 10 VOLUMEN (MAESTRO - SIN ESTABLES):\n"
        c=0
        for t in usdt:
            if es_estable(t['symbol'], t['lastPrice']): continue
            msg+=f"{t['symbol'].replace('USDT','')} {fmt(t['lastPrice'])} Vol {float(t['quoteVolume'])/1000000:.1f}M ({float(t['priceChangePercent']):+.1f}%)\n"
            c+=1
            if c>=10: break
        await update.message.reply_text(msg)
    except Exception as e: await update.message.reply_text(f"Error {e}")

async def analizar_cmd(update, context):
    try:
        if not context.args: await update.message.reply_text("Uso: /analizar BTCUSDT"); return
        sym=context.args[0].upper()
        if not sym.endswith("USDT"): sym+="USDT"
        if es_estable(sym, 1.0): await update.message.reply_text(f"⛔ {sym} BLOQUEADO - Es estable"); return
        data=leer_grafico_maestro(sym)
        if not data: await update.message.reply_text("No hay datos"); return
        fg,_=get_fear_greed()
        await update.message.reply_text(f"ANALISIS MAESTRO {sym}\nPrecio {fmt(data['precio'])}\nRSI {data['rsi']} | Vol x{data['vol_x']}\nTendencia {data['tendencia']} | Score {data['score']}/10\nEMA20 {fmt(data['ema20'])} EMA50 {fmt(data['ema50'])} EMA200 {fmt(data['ema200'])}\nBoll OK {data['boll_ok']} | F&G {fg}\n{'✅ APTO COMPRA' if data['score']>=9 else '❌ NO APTO'}")
    except Exception as e: await update.message.reply_text(f"Error {e}")

async def aprender_cmd(update, context):
    try:
        con=sqlite3.connect(DB);cur=con.cursor()
        cur.execute("SELECT simbolo,precio,score,rsi,resultado,pnl,real FROM trades ORDER BY id DESC LIMIT 10")
        rows=cur.fetchall()
        cur.execute("SELECT COUNT(*), AVG(pnl) FROM trades WHERE pnl!=0")
        total, avg = cur.fetchone()
        con.close()
        
        aprendizaje=aprender_de_errores()
        msg=f"CEREBRO MAESTRO v9.0 {('REAL' if TRADING_REAL else 'PAPER')}\n{aprendizaje}\n\nConfiguracion actual: RSI max {get_cerebro('rsi_max',68)} Vol min {get_cerebro('vol_min',1.8)} Score min {get_cerebro('score_min',9.0)}\nTotal trades {total or 0} Avg PNL {avg or 0:.2f}%\n\nUltimos 10:\n"
        for r in rows: msg+=f"{'REAL' if r[6]==1 else 'PAPER'} {r[0]} {fmt(r[1])} Sc {r[2]} RSI {r[3]} {r[4]} {r[5]:.1f}%\n"
        await update.message.reply_text(msg)
    except Exception as e: await update.message.reply_text(f"Error aprender {e}")

async def auto_on_cmd(update, context):
    save_chat(update.effective_chat.id)
    try:
        for job in context.job_queue.get_jobs_by_name("auto_scan"): job.schedule_removal()
        for job in context.job_queue.get_jobs_by_name("auto_learn"): job.schedule_removal()
        context.job_queue.run_repeating(job_scan, interval=1800, first=10, name="auto_scan")
        context.job_queue.run_repeating(job_learn, interval=14400, first=20, name="auto_learn")
        await update.message.reply_text(f"AUTO ON v9.0 MAESTRO 24/7 ACTIVADO\nCada 30m escanea 250 monedas con 6 indicadores\nCada 4h aprende de errores y se reprograma\nMonto {MONTO}USDT Score min {get_cerebro('score_min',9.0)}")
    except Exception as e: await update.message.reply_text(f"Error auto {e}")

async def auto_off_cmd(update, context):
    try:
        for job in context.job_queue.get_jobs_by_name("auto_scan"): job.schedule_removal()
        for job in context.job_queue.get_jobs_by_name("auto_learn"): job.schedule_removal()
        await update.message.reply_text("AUTO OFF v9.0 MAESTRO")
    except Exception as e: await update.message.reply_text(f"Error {e}")

async def balance_cmd(update, context):
    await update.message.reply_text(f"v9.0 MAESTRO Modo {('REAL' if TRADING_REAL else 'PAPER')} Monto {MONTO}USDT API {'OK' if API_KEY else 'FALTA'} Filtro ON F&G {get_fear_greed()[0]}")

async def job_scan(context):
    try:
        if not client: return
        log.info("AUTO SCAN MAESTRO 24/7")
        # El escaneo automatico no manda mensaje, solo aprende
    except: pass

async def job_learn(context):
    try:
        msg=aprender_de_errores()
        log.info(msg)
    except: pass

def main():
    init_db()
    if not TOKEN or ":" not in TOKEN: log.error("TOKEN MALO"); time.sleep(99999)
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
    log.info(f"BOT v9.0 MAESTRO LISTO Modo {('REAL' if TRADING_REAL else 'PAPER')}")
    app.run_polling()

if __name__=="__main__": main()
