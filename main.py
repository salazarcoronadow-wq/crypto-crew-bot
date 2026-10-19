import os, time, logging, sqlite3, requests
from datetime import datetime
from binance.client import Client
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN=os.getenv("TELEGRAM_TOKEN"); API_KEY=os.getenv("BINANCE_API_KEY"); API_SECRET=os.getenv("BINANCE_API_SECRET")
MONTO=float(os.getenv("MONTO","10.0")); DB="trades.db"
BLACKLIST=["RWUSD","UUSDT","USDT","USDC","FDUSD","BUSD","TUSD","DAI","USDP","UST","USTC","USDE","USD1","EUR","PYUSD","GUSD","USDD"]

logging.basicConfig(level=logging.INFO); log=logging.getLogger(__name__)
client=None
try:
    client=Client(API_KEY,API_SECRET) if API_KEY and API_SECRET else Client()
except:
    try: client=Client()
    except: client=None

def fmt(p):
    try:
        f=float(p)
        if f<0.0001: return f"${f:.8f}"
        if f<0.01: return f"${f:.6f}"
        if f<1: return f"${f:.4f}"
        return f"${f:.2f}"
    except: return str(p)

def es_estable(s,p):
    s=s.upper()
    try:
        if 0.985 <= float(p) <= 1.09: return True
    except: pass
    if s in BLACKLIST or s.replace("USDT","") in BLACKLIST: return True
    if len(s.replace("USDT",""))<=2: return True
    if "RWUSD" in s or "UUSDT" in s: return True
    return False

def init_db():
    con=sqlite3.connect(DB); c=con.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, simbolo TEXT, precio REAL, score REAL, rsi REAL, volx REAL, tendencia TEXT, fg INTEGER, noticia TEXT, resultado TEXT, pnl REAL, real INTEGER, fecha TEXT, tipo TEXT, macd REAL, stoch REAL, momentum REAL, entropia REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS cerebro (clave TEXT PRIMARY KEY, valor REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS memoria (id INTEGER PRIMARY KEY, fecha TEXT, leccion TEXT, tipo TEXT, simbolo TEXT)")
    c.execute("INSERT OR IGNORE INTO cerebro VALUES ('rsi_max', 68.0)")
    c.execute("INSERT OR IGNORE INTO cerebro VALUES ('vol_min', 1.8)")
    c.execute("INSERT OR IGNORE INTO cerebro VALUES ('score_min', 8.8)")
    c.execute("INSERT OR IGNORE INTO cerebro VALUES ('entropia_max', 0.04)")
    con.commit(); con.close()

def save_chat(cid):
    try: con=sqlite3.connect(DB); con.execute("INSERT OR IGNORE INTO chats VALUES (?)",(cid,)); con.commit(); con.close()
    except: pass

def get_cerebro(k,d):
    try: con=sqlite3.connect(DB); r=con.execute("SELECT valor FROM cerebro WHERE clave=?",(k,)).fetchone(); con.close(); return r[0] if r else d
    except: return d

def set_cerebro(k,v):
    try: con=sqlite3.connect(DB); con.execute("INSERT OR REPLACE INTO cerebro VALUES (?,?)",(k,v)); con.commit(); con.close()
    except: pass

def guardar_memoria(leccion,tipo="aprendizaje",simbolo="GENERAL"):
    try: con=sqlite3.connect(DB); con.execute("INSERT INTO memoria (fecha,leccion,tipo,simbolo) VALUES (?,?,?,?)",(datetime.now().isoformat(),leccion,tipo,simbolo)); con.commit(); con.close()
    except: pass

def get_fear_greed():
    try: r=requests.get("https://api.alternative.me/fng/?limit=1",timeout=5).json(); return int(r['data'][0]['value']), r['data'][0]['value_classification']
    except: return 50,"Neutral"

def get_crypto_noticias():
    noticias=[]
    try:
        fg,_=get_fear_greed(); noticias.append(f"F&G {fg}")
        g=requests.get("https://api.coingecko.com/api/v3/search/trending",timeout=6).json()
        for c in g.get('coins',[])[:5]: noticias.append(c['item']['symbol'].upper())
    except: pass
    return noticias, ["coingecko","alternative"]

def get_tendencia_btc():
    try:
        kl=client.get_klines(symbol="BTCUSDT", interval=Client.KLINE_INTERVAL_1HOUR, limit=50)
        closes=[float(k[4]) for k in kl]
        return "alcista" if closes[-1]>sum(closes[-20:])/20 else "bajista"
    except: return "lateral"

def leer_grafico_ultra(symbol):
    try:
        kl=client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=200)
        closes=[float(k[4]) for k in kl]; highs=[float(k[2]) for k in kl]; lows=[float(k[3]) for k in kl]; vols=[float(k[5]) for k in kl]
        if len(closes)<100: return None
        deltas=[closes[i]-closes[i-1] for i in range(1,len(closes))]
        gains=[d if d>0 else 0 for d in deltas[-14:]]; losses=[-d if d<0 else 0 for d in deltas[-14:]]
        rs=(sum(gains)/14)/(sum(losses)/14) if sum(losses)!=0 else 100
        rsi=100-(100/(1+rs))
        ema12=sum(closes[-12:])/12; ema26=sum(closes[-26:])/26; ema20=sum(closes[-20:])/20; ema50=sum(closes[-50:])/50; ema200=sum(closes[-200:])/200
        macd_line=ema12-ema26
        std20=(sum([(c-ema20)**2 for c in closes[-20:]])/20)**0.5; boll_upper=ema20+2*std20; boll_ok=closes[-1] < boll_upper*0.986
        low14=min(lows[-14:]); high14=max(highs[-14:]); stoch_k=((closes[-1]-low14)/(high14-low14)*100) if high14!=low14 else 50
        swing_high=max(highs[-50:]); swing_low=min(lows[-50:]); fib_618=swing_high-(swing_high-swing_low)*0.618
        vol_prom=sum(vols[-30:-1])/29; vol_x=vols[-1]/vol_prom if vol_prom>0 else 0
        velocidad=closes[-1]-closes[-5]; masa=vol_x; momentum=masa*velocidad
        energia=0.5*masa*(velocidad**2)
        returns=[abs(closes[i]-closes[i-1])/closes[i-1] for i in range(1,21)]
        entropia=sum(returns)/len(returns) if returns else 0
        reaccion=vol_x*(rsi/50)
        tendencia="alcista" if closes[-1]>ema20>ema50 and closes[-1]>ema200 and macd_line>0 else "bajista" if closes[-1]<ema20 else "lateral"
        score=0.0
        if 50<=rsi<=get_cerebro('rsi_max',68): score+=2.5
        if tendencia=="alcista": score+=2.5
        if vol_x>=get_cerebro('vol_min',1.8): score+=1.5
        if boll_ok: score+=1
        if 20<=stoch_k<=75: score+=1
        if closes[-1]>fib_618: score+=0.5
        if momentum>0 and entropia<get_cerebro('entropia_max',0.04): score+=1
        score=min(score,10.0)
        return {"rsi":round(rsi,1),"vol_x":round(vol_x,2),"tendencia":tendencia,"score":round(score,1),"precio":closes[-1],"ema20":ema20,"ema50":ema50,"ema200":ema200,"boll_ok":boll_ok,"macd":round(macd_line,4),"stoch_k":round(stoch_k,1),"fib_618":fib_618,"momentum":round(momentum,4),"entropia":round(entropia,5),"energia":round(energia,4),"reaccion":round(reaccion,2),"ebullicion":rsi>78}
    except: return None

def aprender_ultra():
    try:
        con=sqlite3.connect(DB); cur=con.cursor()
        cur.execute("SELECT rsi, volx, pnl FROM trades WHERE pnl<0 ORDER BY id DESC LIMIT 25")
        per=cur.fetchall(); con.close()
        if len(per)<5: return f"Cerebro ULTRA: {len(per)} perdidas, aprendiendo..."
        avg_rsi_perd=sum([p[0] for p in per])/len(per); avg_vol_perd=sum([p[1] for p in per])/len(per)
        msg="CEREBRO ULTRA APRENDIO:\n"; cambio=False
        if avg_rsi_perd>67:
            nuevo=max(62,avg_rsi_perd-2); set_cerebro('rsi_max',nuevo); msg+=f"- RSI {avg_rsi_perd:.1f} -> max {nuevo:.0f}\n"; guardar_memoria(f"RSI {avg_rsi_perd:.1f} perdi"); cambio=True
        if avg_vol_perd<1.9:
            set_cerebro('vol_min',2.0); msg+=f"- Vol {avg_vol_perd:.1f}x -> min 2.0x\n"; cambio=True
        return msg if cambio else "Estrategia rentable, mantengo"
    except Exception as e: return f"Error {e}"

async def job_scan(context):
    try:
        if not client: return
        fg,_=get_fear_greed(); btc=get_tendencia_btc()
        if fg<12: return
        tickers=client.get_ticker(); usdt=sorted([t for t in tickers if t['symbol'].endswith('USDT')], key=lambda x: float(x['quoteVolume']), reverse=True)
        encontradas=[]
        for t in usdt[:200]:
            sym=t['symbol']
            if es_estable(sym,t['lastPrice']): continue
            data=leer_grafico_ultra(sym)
            if not data or data['score']<9.0 or data['tendencia']!="alcista" or not data['boll_ok'] or data['entropia']>get_cerebro('entropia_max',0.04): continue
            encontradas.append(f"{sym.replace('USDT','')} {fmt(data['precio'])} Sc {data['score']} Mom {data['momentum']}")
            if len(encontradas)>=2: break
        if encontradas:
            con=sqlite3.connect(DB); chats=con.execute("SELECT id FROM chats").fetchall(); con.close()
            txt=f"AUTO ULTRA {datetime.now().strftime('%H:%M')} F&G {fg} BTC {btc}\n" + "\n".join(encontradas)
            for chat in chats:
                try: await context.bot.send_message(chat_id=chat[0], text=txt)
                except: pass
    except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id); fg,_=get_fear_greed()
    await update.message.reply_text(f"ULTRA BOT v10.1 MAX LISTO 253 LINEAS ULTRA\nMente propia ON | Auto ON | Noticias ON\nFisica+Quimica ON | Futuros PAPER ON\nF&G {fg} | /oportunidad /top /analizar BTCUSDT /aprender /auto_on /futuros_paper /memoria")

async def oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    try:
        global client
        if not client: client=Client()
        fg,fgt=get_fear_greed(); btc=get_tendencia_btc(); noticias,_=get_crypto_noticias()
        if fg<12: await update.message.reply_text(f"MIEDO EXTREMO F&G {fg} - No opero"); return
        await update.message.reply_text(f"ULTRA MAX ANALIZANDO 250... F&G {fg} BTC {btc} Noticias {noticias[:3]}")
        tickers=client.get_ticker(); usdt=sorted([t for t in tickers if t['symbol'].endswith('USDT')], key=lambda x: float(x['quoteVolume']), reverse=True)
        encontradas=[]; rev=0; bloq=0
        for t in usdt:
            sym=t['symbol']
            if es_estable(sym,t['lastPrice']): bloq+=1; continue
            rev+=1; data=leer_grafico_ultra(sym)
            if not data or data['score']<get_cerebro('score_min',8.8) or data['tendencia']!="alcista" or not data['boll_ok'] or data['entropia']>0.04 or data['momentum']<=0: continue
            base=sym.replace("USDT",""); entrada=data['precio']; stop=entrada*0.962; tp1=entrada*1.065
            con=sqlite3.connect(DB); con.execute("INSERT INTO trades (simbolo,precio,score,rsi,volx,tendencia,fg,noticia,resultado,pnl,real,fecha,tipo,macd,stoch,momentum,entropia) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(sym,entrada,data['score'],data['rsi'],data['vol_x'],data['tendencia'],fg,str(noticias[:2]),"PENDIENTE",0,0,datetime.now().isoformat(),"SPOT",data['macd'],data['stoch_k'],data['momentum'],data['entropia'])); con.commit(); con.close()
            encontradas.append(f"{base} {fmt(entrada)} Sc {data['score']}/10 RSI {data['rsi']} MACD {data['macd']} Mom {data['momentum']} Ent {data['entropia']} Entrada {fmt(entrada)} Stop {fmt(stop)} TP {fmt(tp1)} BTC {btc}")
            if len(encontradas)>=3 or rev>300: break
        if not encontradas: await update.message.reply_text(f"ULTRA: Revisadas {rev} Bloqueadas {bloq} Sin oportunidad 9/10")
        else: await update.message.reply_text(f"ULTRA {datetime.now().strftime('%H:%M')} F&G {fg} BTC {btc}\n" + "\n---\n".join(encontradas))
    except Exception as e: await update.message.reply_text(f"Error {e}")

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    try:
        if not client: client=Client()
        tickers=client.get_ticker(); usdt=sorted([t for t in tickers if t['symbol'].endswith('USDT')], key=lambda x: float(x['quoteVolume']), reverse=True)
        msg="TOP 10 ULTRA:\n"; c=0
        for t in usdt:
            if es_estable(t['symbol'],t['lastPrice']): continue
            d=leer_grafico_ultra(t['symbol']); extra=f" Mom {d['momentum']}" if d else ""
            msg+=f"{t['symbol'].replace('USDT','')} {fmt(t['lastPrice'])} {float(t['priceChangePercent']):+.1f}%{extra}\n"; c+=1
            if c>=10: break
        await update.message.reply_text(msg)
    except Exception as e: await update.message.reply_text(f"Error {e}")

async def analizar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args: await update.message.reply_text("Uso: /analizar BTCUSDT"); return
        sym=context.args[0].upper()
        if not sym.endswith("USDT"): sym+="USDT"
        if es_estable(sym,1.0): await update.message.reply_text(f"{sym} BLOQUEADO"); return
        data=leer_grafico_ultra(sym)
        if not data: await update.message.reply_text("Sin datos"); return
        fg,_=get_fear_greed()
        await update.message.reply_text(f"ANALISIS ULTRA {sym} Precio {fmt(data['precio'])} RSI {data['rsi']} MACD {data['macd']} Stoch {data['stoch_k']} EMA200 {fmt(data['ema200'])} Mom {data['momentum']} Ent {data['entropia']} Energia {data['energia']} Score {data['score']}/10 F&G {fg} {'APTO' if data['score']>=8.8 else 'NO APTO'}")
    except Exception as e: await update.message.reply_text(f"Error {e}")

async def aprender_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        con=sqlite3.connect(DB); rows=con.execute("SELECT simbolo,precio,score,rsi,resultado,pnl,tipo FROM trades ORDER BY id DESC LIMIT 10").fetchall(); total=con.execute("SELECT COUNT(*), AVG(pnl) FROM trades WHERE pnl!=0").fetchone(); mem=con.execute("SELECT leccion FROM memoria ORDER BY id DESC LIMIT 3").fetchall(); con.close()
        apr=aprender_ultra()
        msg=f"CEREBRO ULTRA v10.1 MAX\n{apr}\nTrades {total[0] if total else 0} Avg {total[1] if total and total[1] else 0:.2f}%\nMemoria:\n"
        for m in mem: msg+=f"- {m[0]}\n"
        for r in rows: msg+=f"{r[6]} {r[0]} {fmt(r[1])} Sc {r[2]} {r[4]} {r[5]:.1f}%\n"
        await update.message.reply_text(msg)
    except Exception as e: await update.message.reply_text(f"Error {e}")

async def futuros_paper_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id); fg,_=get_fear_greed(); btc=get_tendencia_btc()
    await update.message.reply_text(f"FUTUROS PAPER ULTRA ON BTC {btc} F&G {fg} Aprende 14 dias PAPER 1x-3x")

async def auto_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    for j in context.job_queue.get_jobs_by_name("auto_scan"): j.schedule_removal()
    for j in context.job_queue.get_jobs_by_name("auto_learn"): j.schedule_removal()
    context.job_queue.run_repeating(job_scan, interval=1800, first=10, name="auto_scan")
    context.job_queue.run_repeating(lambda ctx: aprender_ultra(), interval=14400, first=20, name="auto_learn")
    await update.message.reply_text("AUTO ON
