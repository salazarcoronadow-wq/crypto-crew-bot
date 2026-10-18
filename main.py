import os, time, logging, requests, sqlite3, traceback
import pandas as pd
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIG ---
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("BOT")
TOKEN = (os.getenv("TELEGRAM_TOKEN") or "").strip().replace('"','').replace("'","")
INTERVAL = "15m"
DB_FILE = "cerebro.db"
CHAT_FILE = "chat_id.txt"
PAPER_MODE = True

SYMBOLS = [
"BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT",
"ADAUSDT","AVAXUSDT","SHIBUSDT","DOTUSDT","LINKUSDT","TRXUSDT",
"MATICUSDT","LTCUSDT","BCHUSDT","UNIUSDT","ATOMUSDT","ETCUSDT",
"XLMUSDT","FILUSDT","PEPEUSDT","BONKUSDT","WIFUSDT","FLOKIUSDT",
"ARBUSDT","OPUSDT","SUIUSDT","APTUSDT","STXUSDT","IMXUSDT",
"NEARUSDT","RNDRUSDT","INJUSDT","TIAUSDT","SEIUSDT","PYTHUSDT",
"JUPUSDT","WUSDT","ARUSDT","FETUSDT","LDOUSDT","MKRUSDT",
"AAVEUSDT","RUNEUSDT","KASUSDT","FTMUSDT","ALGOUSDT","VETUSDT"
]

# --- DB CEREBRO ---
def init_db():
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, fecha TEXT, simbolo TEXT, precio REAL, score REAL, rsi REAL, resultado TEXT, pnl REAL)")
        con.commit()
        con.close()
    except Exception as e:
        log.error(f"DB {e}")

def save_chat_id(chat_id):
    try:
        with open(CHAT_FILE, "w") as f:
            f.write(str(chat_id))
    except:
        pass

def get_chat_id():
    try:
        with open(CHAT_FILE, "r") as f:
            return int(f.read().strip())
    except:
        return None

def guardar_trade(sim, precio, score, rsi):
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("INSERT INTO trades (fecha,simbolo,precio,score,rsi,resultado,pnl) VALUES (?,?,?,?,?,?,?)", (datetime.now().isoformat(), sim, precio, score, rsi, "PENDIENTE", 0))
        con.commit()
        con.close()
    except:
        pass

def get_aprendizaje():
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("SELECT * FROM trades WHERE resultado != 'PENDIENTE' ORDER BY id DESC LIMIT 20")
        rows = cur.fetchall()
        con.close()
        if not rows:
            return 0, "Sin historial aun - aprendiendo"
        ganadas = len([r for r in rows if r[6] == "GANADA"])
        total = len(rows)
        winrate = ganadas / total * 100 if total > 0 else 0
        rsi_alto_perd = len([r for r in rows if r[4] > 70 and r[6] == "PERDIDA"])
        ajuste = -0.5 if rsi_alto_perd > 2 else 0
        txt = f"Historial {total} trades WR {winrate:.0f}% Ajuste {ajuste}"
        return ajuste, txt
    except:
        return 0, "Error aprendizaje"

def actualizar_aprendizaje_automatico():
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("SELECT id, fecha, simbolo, precio FROM trades WHERE resultado = 'PENDIENTE'")
        pendientes = cur.fetchall()
        for pid, fecha_str, sim, precio_entry in pendientes:
            try:
                fecha = datetime.fromisoformat(fecha_str)
                if datetime.now() - fecha < timedelta(hours=4):
                    continue
                df = get_candles(sim, limit=10)
                if df.empty:
                    continue
                precio_now = float(df["c"].iloc[-1])
                pnl_pct = (precio_now - precio_entry) / precio_entry * 100
                if pnl_pct >= 4:
                    res = "GANADA"
                elif pnl_pct <= -3:
                    res = "PERDIDA"
                else:
                    res = "NEUTRA"
                cur.execute("UPDATE trades SET resultado = ?, pnl = ? WHERE id = ?", (res, pnl_pct, pid))
            except:
                continue
        con.commit()
        con.close()
        log.info("Aprendizaje auto actualizado")
    except Exception as e:
        log.error(f"Aprendizaje auto error {e}")

def get_fear_greed():
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        r = requests.get(url, timeout=5).json()
        val = int(r["data"][0]["value"])
        txt = r["data"][0]["value_classification"]
        return val, txt
    except:
        return 50, "Neutral"

def get_candles(sym, limit=100):
    for intento in range(3):
        try:
            base = "https://data-api.binance.vision/api/v3/klines"
            url = f"{base}?symbol={sym}&interval={INTERVAL}&limit={limit}"
            r = requests.get(url, timeout=10).json()
            if not r or isinstance(r, dict):
                time.sleep(1)
                continue
            if len(r) < 60:
                return pd.DataFrame()
            cols = ["t","o","h","l","c","v","ct","qv","tr","tb","tq","ig"]
            df = pd.DataFrame(r, columns=cols)
            for c in ["o","h","l","c","v"]:
                df[c] = pd.to_numeric(df[c])
            return df
        except:
            time.sleep(1)
    return pd.DataFrame()

def analyze_pro(df, fg_val, ajuste):
    if df.empty:
        return 3.0, "Sin datos", 0, 50, 0
    close = df["c"]
    vol = df["v"]
    ema9 = close.ewm(span=9).mean()
    ema21 = close.ewm(span=21).mean()
    ema50 = close.ewm(span=50).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    crsi = float(rsi.iloc[-1])
    price = float(close.iloc[-1])
    v_now = float(vol.iloc[-1])
    v_avg = float(vol.tail(20).mean())
    v_ratio = v_now / v_avg if v_avg > 0 else 1
    score = 5.0
    reason = ""
    if ema9.iloc[-1] > ema21.iloc[-1] > ema50.iloc[-1]:
        score += 2.0
        reason += "Tendencia alcista "
    if ema9.iloc[-2] <= ema21.iloc[-2] and ema9.iloc[-1] > ema21.iloc[-1]:
        score += 2.5
        reason += "Cruce alcista "
    if ema9.iloc[-2] >= ema21.iloc[-2] and ema9.iloc[-1] < ema21.iloc[-1]:
        score -= 2.5
        reason += "Cruce bajista "
    if 55 <= crsi <= 68:
        score += 1.5
        reason += f"RSI {crsi:.0f} opt "
    elif crsi > 78:
        score -= 2.0
        reason += f"RSI {crsi:.0f} sobrecompra "
    elif crsi < 28:
        score += 1.0
        reason += f"RSI {crsi:.0f} sobreventa "
    if v_ratio > 1.5:
        score += 1.0
        reason += f"Vol x{v_ratio:.1f} "
    if fg_val < 25:
        score += 1.0
        reason += "Miedo extremo "
    if fg_val > 85:
        score -= 1.0
        reason += "Codicia "
    score += ajuste
    score = max(1, min(10, round(score, 1)))
    if not reason:
        reason = f"Consolid RSI {crsi:.0f}"
    return score, reason, price, crsi, v_ratio

# --- JOBS AUTONOMOS ---
async def job_auto_scan(context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = get_chat_id()
        if not chat_id:
            return
        fg_val, fg_txt = get_fear_greed()
        ajuste, txt_apr = get_aprendizaje()
        log.info(f"AUTO SCAN F&G {fg_val} {txt_apr}")
        res = []
        for s in SYMBOLS:
            df = get_candles(s)
            sc, re, pr, rsi, vr = analyze_pro(df, fg_val, ajuste)
            res.append((s, sc, re, pr, rsi, vr))
            time.sleep(0.08)
        res.sort(key=lambda x: x[1], reverse=True)
        best = [x for x in res if x[1] >= 9.0]
        if not best:
            return
        txt = f"AUTO ALERTA v7.1 {datetime.now().strftime('%H:%M')} F&G {fg_val}\n"
        txt += f"{txt_apr}\n\n"
        for item in best[:2]:
            sym, sc, re, pr, rsi, vr = item
            name = sym.replace("USDT","")
            entry = pr
            stop = pr * 0.96
            take1 = pr * 1.08
            txt += f"G {name} ${pr:.4f} Score {sc}\n"
            txt += f" {re}\n"
            txt += f" Entrada ${entry:.4f} Stop ${stop:.4f}\n"
            txt += f" TP ${take1:.4f}\n"
            guardar_trade(sym, pr, sc, rsi)
            txt += f" PAPER guardado\n\n"
        await context.bot.send_message(chat_id=chat_id, text=txt)
    except Exception as e:
        log.error(f"job_auto_scan error {e} {traceback.format_exc()}")

async def job_aprender(context: ContextTypes.DEFAULT_TYPE):
    try:
        actualizar_aprendizaje_automatico()
    except Exception as e:
        log.error(f"job_aprender error {e}")

# --- COMANDOS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    save_chat_id(update.effective_chat.id)
    msg = "BOT v7.1 AUTONOMO REAL ONLINE\n"
    msg += "Ya guarda tu chat para alertas\n\n"
    msg += "Modo: PAPER DEMO\n"
    msg += "/oportunidad - Escanea ahora\n"
    msg += "/top - Top 15\n"
    msg += "/analizar btc\n"
    msg += "/auto_on - Activa cada 30m REAL\n"
    msg += "/auto_off - Desactiva\n"
    msg += "/aprender - Ver cerebro\n"
    msg += "/historial - Trades\n"
    msg += "/balance"
    await update.message.reply_text(msg)

async def oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        save_chat_id(update.effective_chat.id)
        fg_val, fg_txt = get_fear_greed()
        ajuste, txt_apr = get_aprendizaje()
        await update.message.reply_text(f"PRO 50 F&G {fg_val} {fg_txt}\n{txt_apr}\n30 seg...")
        res = []
        for s in SYMBOLS:
            df = get_candles(s)
            sc, re, pr, rsi, vr = analyze_pro(df, fg_val, ajuste)
            res.append((s, sc, re, pr, rsi, vr))
            time.sleep(0.08)
        res.sort(key=lambda x: x[1], reverse=True)
        best = [x for x in res if x[1] >= 8.0]
        if not best:
            top = res[0]
            name = top[0].replace("USDT","")
            txt = f"No Score 8+ Mejor {name} {top[1]} F&G {fg_val}"
            await update.message.reply_text(txt)
            return
        txt = f"CEREBRO v7.1 {datetime.now().strftime('%H:%M')} F&G {fg_val}\n{txt_apr}\n\n"
        for item in best[:3]:
            sym, sc, re, pr, rsi, vr = item
            name = sym.replace("USDT","")
            entry = pr
            stop = pr * 0.96
            take1 = pr * 1.08
            take2 = pr * 1.15
            txt += f"G {name} ${pr:.4f} Score {sc}\n {re}\n"
            txt += f" Entrada ${entry:.4f} Stop ${stop:.4f}\n"
            txt += f" TP1 ${take1:.4f} TP2 ${take2:.4f}\n"
            guardar_trade(sym, pr, sc, rsi)
            txt += f" PAPER guardado\n\n"
        await update.message.reply_text(txt)
    except Exception as e:
        log.error(traceback.format_exc())
        await update.message.reply_text(f"Error: {e}")

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fg_val, fg_txt = get_fear_greed()
        ajuste, _ = get_aprendizaje()
        await update.message.reply_text(f"TOP 15 F&G {fg_val}...")
        res = []
        for s in SYMBOLS:
            df = get_candles(s)
            sc, re, pr, rsi, vr = analyze_pro(df, fg_val, ajuste)
            res.append((s, sc, re, pr, rsi, vr))
        res.sort(key=lambda x: x[1], reverse=True)
        txt = f"TOP 15 v7.1 {datetime.now().strftime('%H:%M')}\n\n"
        i = 1
        for item in res[:15]:
            sym, sc, re, pr, rsi, vr = item
            e = "G" if sc >= 8 else "Y" if sc >= 6 else "R"
            name = sym.replace("USDT","")
            txt += f"{i}. {e} {name} Sc {sc} ${pr:.2f} {re}\n\n"
            i += 1
        await update.message.reply_text(txt)
    except Exception as e:
        await update.message.reply_text(f"Error top {e}")

async def analizar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /analizar btc")
        return
    try:
        fg_val, fg_txt = get_fear_greed()
        ajuste, _ = get_aprendizaje()
        coin = context.args[0].upper().replace("USDT","") + "USDT"
        df = get_candles(coin)
        if df.empty:
            await update.message.reply_text(f"No datos {coin}")
            return
        sc, re, pr, rsi, vr = analyze_pro(df, fg_val, ajuste)
        txt = f"ANALISIS {coin} ${pr:.4f}\nSc {sc} RSI {rsi:.1f} Vol x{vr:.1f}\n"
        txt += f"F&G {fg_val} {re}\nStop {pr*0.96:.4f} TP {pr*1.08:.4f}"
        await update.message.reply_text(txt)
    except Exception as e:
        await update.message.reply_text(f"Error {e}")

async def aprender_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ajuste, txt = get_aprendizaje()
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("SELECT simbolo, precio, score, resultado, pnl FROM trades ORDER BY id DESC LIMIT 10")
        rows = cur.fetchall()
        con.close()
        msg = f"CEREBRO v7.1:\n{txt}\n\nUltimos 10:\n"
        for r in rows:
            msg += f"{r[0]} ${r[1]:.2f} Sc {r[2]} {r[3]} {r[4]:.1f}%\n"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"{txt} Error {e}")

async def historial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await aprender_cmd(update, context)

async def auto_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    # Programa jobs si no existen
    try:
        # Elimina previos
        for job in context.job_queue.get_jobs_by_name("auto_scan"):
            job.schedule_removal()
        for job in context.job_queue.get_jobs_by_name("auto_aprender"):
            job.schedule_removal()
        # Crea nuevos cada 30m y 4h
        context.job_queue.run_repeating(job_auto_scan, interval=1800, first=10, name="auto_scan")
        context.job_queue.run_repeating(job_aprender, interval=14400, first=20, name="auto_aprender")
        await update.message.reply_text("AUTO ON REAL ACTIVADO\nCada 30m escanea 50 monedas\nSolo te avisa si Score 9+\nCada 4h aprende solo si gano/perdio")
    except Exception as e:
        await update.message.reply_text(f"Error auto_on {e}")

async def auto_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        for job in context.job_queue.get_jobs_by_name("auto_scan"):
            job.schedule_removal()
        for job in context.job_queue.get_jobs_by_name("auto_aprender"):
            job.schedule_removal()
        await update.message.reply_text("AUTO OFF - Ya no escanea solo")
    except Exception as e:
        await update.message.reply_text(f"Error auto_off {e}")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = get_chat_id()
    await update.message.reply_text(f"v7.1 AUTONOMO REAL\nPaper: {PAPER_MODE}\nChat ID: {chat}\n50 monedas\nJobs activos cada 30m y 4h")

def main():
    init_db()
    if not TOKEN or ":" not in TOKEN:
        log.error("TOKEN MALO")
        time.sleep(99999)
    app = ApplicationBuilder().token(TOKEN).build()
    # Jobs que siempre corren aunque no des auto_on
    app.job_queue.run_repeating(job_aprender, interval=14400, first=30, name="auto_aprender")
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("oportunidad", oportunidad))
    app.add_handler(CommandHandler("oportunidades", oportunidad))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("analizar", analizar_cmd))
    app.add_handler(CommandHandler("aprender", aprender_cmd))
    app.add_handler(CommandHandler("historial", historial_cmd))
    app.add_handler(CommandHandler("auto_on", auto_on_cmd))
    app.add_handler(CommandHandler("auto_off", auto_off_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("noticias", balance_cmd))
    log.info("BOT v7.1 AUTONOMO REAL LISTO")
    app.run_polling()

if __name__ == "__main__":
    main()
