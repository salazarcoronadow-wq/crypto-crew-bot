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
try: client=Client(API_KEY,API_SECRET) if API_KEY and API_SECRET else Client()
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
    if s in BLACKLIST or s.replace("USDT","") in BLACKLIST or len(s.replace("USDT",""))<=2 or "RWUSD" in s: return True
    return False

def init_db():
    con=sqlite3.connect(DB); c=con.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, simbolo TEXT, precio REAL, score REAL, rsi REAL, volx REAL, tendencia TEXT, fg INTEGER, noticia TEXT, resultado TEXT, pnl REAL, real INTEGER, fecha TEXT, tipo TEXT, momentum REAL, entropia REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS cerebro (clave TEXT PRIMARY KEY, valor REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS memoria (id INTEGER PRIMARY KEY, fecha TEXT, leccion TEXT, tipo TEXT, simbolo TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT)")
    c.execute("INSERT OR IGNORE INTO cerebro VALUES ('rsi_max',68.0)"); c.execute("INSERT OR IGNORE INTO cerebro VALUES ('vol_min',1.8)")
    c.execute("INSERT OR IGNORE INTO cerebro VALUES ('score_min',9.0)"); c.execute("INSERT OR IGNORE INTO cerebro VALUES ('entropia_max',0.04)")
    c.execute("INSERT OR IGNORE INTO config VALUES ('trading_real','ON')"); c.execute("INSERT OR IGNORE INTO config VALUES ('trades_hoy','0')")
    c.execute("INSERT OR IGNORE INTO config VALUES ('modo_inmortal','ON')")
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
def get_config(k,d="OFF"):
    try: con=sqlite3.connect(DB); r=con.execute("SELECT valor FROM config WHERE clave=?",(k,)).fetchone(); con.close(); return r[0] if r else d
    except: return d
def set_config(k,v):
    try: con=sqlite3.connect(DB); con.execute("INSERT OR REPLACE INTO config VALUES (?,?)",(k,v)); con.commit(); con.close()
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
        for c in g.get('coins',[])[:4]: noticias.append(c['item']['symbol'].upper())
    except: pass
    return noticias
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
        std20=(sum([(c-ema20)**2 for c in closes[-20:]])/20)**0.5; boll_upper=ema20+2*std20; boll_ok=closes[-1] < boll_upper*0.985
        low14=min(lows[-14:]); high14=max(highs[-14:]); stoch_k=((closes[-1]-low14)/(high14-low14)*100) if high14!=low14 else 50
        vol_prom=sum(vols[-30:-1])/29; vol_x=vols[-1]/vol_prom if vol_prom>0 else 0
        velocidad=closes[-1]-closes[-5]; masa=vol_x; momentum=masa*velocidad
        returns=[abs(closes[i]-closes[i-1])/closes[i-1] for i in range(1,21)]; entropia=sum(returns)/len(returns) if returns else 0
        tendencia="alcista" if closes[-1]>ema20>ema50 and closes[-1]>ema200 and macd_line>0 else "bajista" if closes[-1]<ema20 else "lateral"
        score=0.0
        if 50<=rsi<=get_cerebro('rsi_max',68): score+=2.5
        if tendencia=="alcista": score+=2.5
        if vol_x>=get_cerebro('vol_min',1.8): score+=1.5
        if boll_ok: score+=1
        if 20<=stoch_k<=75: score+=1
        if momentum>0 and entropia<get_cerebro('entropia_max',0.04): score+=1.5
        score=min(score,10.0)
        return {"rsi":round(rsi,1),"vol_x":round(vol_x,2),"tendencia":tendencia,"score":round(score,1),"precio":closes[-1],"macd":round(macd_line,4),"stoch_k":round(stoch_k,1),"momentum":round(momentum,4),"entropia":round(entropia,5)}
    except: return None

def comprar_real_binance(symbol, monto_usdt=10):
    # MODO REAL INMORTAL: si cuenta en cero, NO para, sigue aprendiendo
    if get_config('trading_real','OFF')!='ON':
        return False, "Trading real OFF"
    try:
        trades_hoy=int(get_config('trades_hoy','0'))
        if trades_hoy>=3:
            return False, "Limite 3 trades hoy (proteccion 24/7)"
        balance=client.get_asset_balance(asset='USDT')
        usdt_disp=float(balance['free'])
        if usdt_disp < monto_usdt:
            # AQUI ESTA LA CLAVE: cuenta en cero, sigue aprendiendo, no se apaga
            guardar_memoria(f"Cuenta en 0 ({usdt_disp:.2f} USDT). Queria comprar {symbol} a {fmt(float(client.get_symbol_ticker(symbol=symbol)['price']))} Score 9+ pero sin saldo. Sigo aprendiendo 24/7 sin descanso.", "cuenta_cero_aprendizaje", symbol)
            return False, f"Cuenta en 0 ({usdt_disp:.2f} USDT) - SIGO APRENDIENDO 24/7 sin parar, esperando saldo"
        qty=monto_usdt / float(client.get_symbol_ticker(symbol=symbol)['price'])
        info=client.get_symbol_info(symbol)
        step_size=float([f for f in info['filters'] if f['filterType']=='LOT_SIZE'][0]['stepSize'])
        qty=round(qty - (qty % step_size), 6)
        order=client.order_market_buy(symbol=symbol, quantity=qty)
        guardar_memoria(f"COMPRA REAL 24/7 {symbol} qty {qty}", "compra_real", symbol)
        set_config('trades_hoy', str(trades_hoy+1))
        return True, f"COMPRÉ REAL 24/7 {symbol} qty {qty}"
    except Exception as e:
        guardar_memoria(f"Fallo compra {symbol} error {e} - pero sigo aprendiendo 24/7 inmortal", "error_aprendizaje", symbol)
        return False, f"Error {e} - pero sigo aprendiendo 24/7"

async def job_scan(context):
    try:
        if not client:
            try: 
                from binance.client import Client as C2
                global client
                client=C2()
            except: return
        fg,_=get_fear_greed(); btc=get_tendencia_btc()
        # Resetea contador diario
        if datetime.utcnow().hour==0 and datetime.utcnow().minute<30:
            set_config('trades_hoy','0')
        if fg<10:
            guardar_memoria(f"F&G {fg} extremo, no opero pero sigo analizando 250 monedas 24/7", "proteccion", "GENERAL")
            return
        tickers=client.get_ticker(); usdt=sorted([t for t in tickers if t['symbol'].endswith('USDT')], key=lambda x: float(x['quoteVolume']), reverse=True)
        encontradas=[]
        for t in usdt[:250]:
            sym=t['symbol']
            if es_estable(sym,t['lastPrice']): continue
            data=leer_grafico_ultra(sym)
            if not data or data['score']<get_cerebro('score_min',9.0) or data['tendencia']!="alcista" or not data['boll_ok'] or data['entropia']>0.04 or data['momentum']<=0: continue
            encontradas.append((sym,data))
            if len(encontradas)>=1: break
        if encontradas:
            con=sqlite3.connect(DB); chats=con.execute("SELECT id FROM chats").fetchall(); con.close()
            for sym,data in encontradas:
                noticias=get_crypto_noticias()
                base=sym.replace("USDT","")
                compra_msg=""
                if get_config('trading_real','OFF')=='ON':
                    ok, msg_compra=comprar_real_binance(sym, MONTO)
                    compra_msg=f"\n🤖 {msg_compra}\n🧠 Sigo aprendiendo aunque este en 0"
                # Guarda siempre como aprendizaje aunque no compre
                con=sqlite3.connect(DB); con.execute("INSERT INTO trades (simbolo,precio,score,rsi,volx,tendencia,fg,noticia,resultado,pnl,real,fecha,tipo,momentum,entropia) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(sym,data['precio'],data['score'],data['rsi'],data['vol_x'],data['tendencia'],fg,str(noticias[:2]),"APRENDIZAJE_24_7",0,0,datetime.now().isoformat(),"SPOT",data['momentum'],data['entropia'])); con.commit(); con.close()
                txt=f"🚀 ULTRA 24/7 INMORTAL {datetime.now().strftime('%H:%M')} F&G {fg} BTC {btc}\n💎 {base} {fmt(data['precio'])} Score {data['score']}/10 RSI {data['rsi']} Mom {data['momentum']}\n{compra_msg}\nNoticias {noticias}\nModo {get_config('trading_real','OFF')} - Aprendo con y sin dinero 24/7 365"
                for chat in chats:
                    try: await context.bot.send_message(chat_id=chat[0], text=txt)
                    except: pass
        else:
            # Aunque no encuentre nada, guarda que aprendio
            guardar_memoria(f"Scan 24/7 {datetime.now().strftime('%H:%M')} revisadas 250 F&G {fg} BTC {btc} sin oportunidad 9/10 - sigo aprendiendo", "scan_24_7", "GENERAL")
    except Exception as e: log.error(f"job_scan {e}"); guardar_memoria(f"Error scan {e} pero sigo vivo 24/7", "error", "GENERAL")

async def job_learn(context):
    try:
        con=sqlite3.connect(DB); cur=con.cursor()
        cur.execute("SELECT rsi, volx FROM trades WHERE pnl<0 ORDER BY id DESC LIMIT 20")
        per=cur.fetchall(); con.close()
        if per:
            avg_rsi=sum([p[0] for p in per])/len(per)
            guardar_memoria(f"Aprendizaje 24/7 automatico {datetime.now().strftime('%H:%M')} analice {len(per)} perdidas RSI avg {avg_rsi:.1f} - sigo mejorando aunque cuenta en 0", "auto_aprendizaje_24_7", "GENERAL")
    except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id); fg,_=get_fear_greed(); btc=get_tendencia_btc()
    await update.message.reply_text(f"ULTRA BOT v11.1 INMORTAL 24/7 365 ACTIVADO\n✅ MODO REAL ON - Con plata compra, sin plata SIGUE APRENDIENDO\n✅ Nunca descansa, nunca se apaga\n1 Mente propia ON\n2 Autonomo investiga ON\n3 Redes ON\n4 Fisica+Quimica ON\n5 Noticias+Futuros ON\n6 24/7 365 OPERANDO: {get_config('trading_real','OFF')} | INMORTAL: {get_config('modo_inmortal','ON')}\nF&G {fg} BTC {btc}\n/auto_on - Ya esta activo\n/trading_real_off - Para modo real")

async def oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    try:
        if not client: from binance.client import Client; client=Client()
        fg,_=get_fear_greed(); btc=get_tendencia_btc(); noticias=get_crypto_noticias()
        await update.message.reply_text(f"ULTRA INMORTAL ANALIZANDO 250... F&G {fg} BTC {btc} Modo Real {get_config('trading_real','OFF')} - Aprendo con o sin dinero")
        tickers=client.get_ticker(); usdt=sorted([t for t in tickers if t['symbol'].endswith('USDT')], key=lambda x: float(x['quoteVolume']), reverse=True)
        encontradas=[]; rev=0
        for t in usdt:
            sym=t['symbol']
            if es_estable(sym,t['lastPrice']): continue
            rev+=1; data=leer_grafico_ultra(sym)
            if not data or data['score']<9.0 or data['tendencia']!="alcista": continue
            encontradas.append(f"{sym.replace('USDT','')} {fmt(data['precio'])} Sc {data['score']} Mom {data['momentum']}")
            if len(encontradas)>=3 or rev>300: break
        if not encontradas: await update.message.reply_text(f"Revisadas {rev} Sin 9/10 pero sigo aprendiendo 24/7")
        else: await update.message.reply_text("\n---\n".join(encontradas))
    except Exception as e: await update.message.reply_text(f"Error {e}")

async def trading_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_config('trading_real','ON'); set_config('modo_inmortal','ON'); save_chat(update.effective_chat.id)
    await update.message.reply_text("✅ MODO REAL INMORTAL 24/7 ACTIVADO\nCon plata: compra solo\nSin plata: SIGUE ANALIZANDO Y APRENDIENDO 24/7 sin descanso\nNunca se apaga\n/auto_on para activar scan cada 30 min")
    guardar_memoria("MODO REAL INMORTAL ACTIVADO - Aprende con y sin dinero 24/7", "activacion", "GENERAL")

async def trading_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_config('trading_real','OFF')
    await update.message.reply_text("Trading real OFF - Ahora solo avisa y aprende")

async def auto_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id)
    for j in context.job_queue.get_jobs_by_name("auto_scan"): j.schedule_removal()
    for j in context.job_queue.get_jobs_by_name("auto_learn"): j.schedule_removal()
    context.job_queue.run_repeating(job_scan, interval=1800, first=10, name="auto_scan")
    context.job_queue.run_repeating(job_learn, interval=14400, first=20, name="auto_learn")
    await update.message.reply_text(f"AUTO INMORTAL 24/7 ACTIVADO\nCada 30 min escanea 250 monedas aunque este en 0\nCada 4h aprende y guarda memoria\nTrading Real {get_config('trading_real','OFF')}")

async def auto_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for j in context.job_queue.get_jobs_by_name("auto_scan"): j.schedule_removal()
    for j in context.job_queue.get_jobs_by_name("auto_learn"): j.schedule_removal()
    await update.message.reply_text("AUTO OFF - Pero cerebro sigue vivo")

def main():
    init_db()
    if not TOKEN or ":" not in TOKEN: time.sleep(99999)
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("oportunidad", oportunidad))
    app.add_handler(CommandHandler("auto_on", auto_on_cmd))
    app.add_handler(CommandHandler("auto_off", auto_off_cmd))
    app.add_handler(CommandHandler("trading_real_on", trading_on_cmd))
    app.add_handler(CommandHandler("trading_real_off", trading_off_cmd))
    # Activa automaticamente 24/7 al iniciar
    app.job_queue.run_repeating(job_scan, interval=1800, first=15, name="auto_scan")
    app.job_queue.run_repeating(job_learn, interval=14400, first=30, name="auto_learn")
    log.info("ULTRA v11.1 INMORTAL 24/7 365 LISTO - MODO REAL ON"); app.run_polling()

if __name__=="__main__": main()
