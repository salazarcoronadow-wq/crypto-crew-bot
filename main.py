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
       
