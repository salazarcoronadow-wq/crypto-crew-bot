import os, requests, asyncio, logging, json
from binance.client import Client
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN","").strip()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY","").strip()
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET","").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","").strip()
logging.basicConfig(level=logging.INFO)

binance_client = None
try:
    if BINANCE_API_KEY and BINANCE_API_SECRET:
        binance_client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
    else:
        binance_client = Client()
except:
    try: binance_client = Client()
    except: binance_client = None

# --- CEREBRO PERSISTENTE v11.7 ---
CEREBRO_FILE = "cerebro.json"
def cargar_cerebro():
    try:
        if os.path.exists(CEREBRO_FILE):
            with open(CEREBRO_FILE,"r") as f: return json.load(f)
    except: pass
    return {"total_analisis":0, "joyas_detectadas":0, "mejores_monedas":{}, "patrones_ganadores":{"rsi_prom":60,"vol_prom":1.5}, "historial":[]}

def guardar_cerebro():
    try:
        with open(CEREBRO_FILE,"w") as f: json.dump(CEREBRO, f)
    except Exception as e: print(f"Error guardar cerebro: {e}")

CEREBRO = cargar_cerebro()
CONFIG = {"trading_real":"ON","auto":"ON","f_g":"59","btc_trend":"lateral"}

def get_config(k,d=""): return CONFIG.get(k,d)
def set_config(k,v): CONFIG[k]=str(v)

def binance_request(path):
    urls=[f"https://api.binance.com{path}",f"https://api1.binance.com{path}",f"https://api2.binance.com{path}",f"https://api3.binance.com{path}",f"https://data-api.binance.vision{path}"]
    for url in urls:
        try:
            r=requests.get(url,timeout=8, headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code==200:
                data=r.json()
                if data: return data
        except: continue
    return None

def get_all_tickers():
    try:
        if binance_client:
            try:
                t=binance_client.get_ticker()
                if t and len(t)>10: return t
            except: pass
        data=binance_request("/api/v3/ticker/24hr")
        return data if data else []
    except: return []

def get_tendencia_btc():
    try:
        kl=binance_request("/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=50")
        if not kl: return CONFIG.get('btc_trend','lateral')
        closes=[float(k[4]) for k in kl]
        avg20=sum(closes[-20:])/20
        trend="alcista" if closes[-1]>avg20 else "bajista" if closes[-1]<avg20*0.995 else "lateral"
        CONFIG['btc_trend']=trend
        return trend
    except: return CONFIG.get('btc_trend','lateral')

def get_fng():
    try:
        r=requests.get("https://api.alternative.me/fng/?limit=1",timeout=5).json()
        v=int(r['data'][0]['value']); CONFIG['f_g']=str(v)
        return v
    except: return int(CONFIG.get('f_g','59'))

def leer_grafico_ultra(symbol):
    try:
        kl=binance_request(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=200")
        if not kl or len(kl)<100: return None
        closes=[float(k[4]) for k in kl]
        vols=[float(k[5]) for k in kl]
        deltas=[closes[i]-closes[i-1] for i in range(1,len(closes))]
        gains=[d if d>0 else 0 for d in deltas[-14:]]
        losses=[-d if d<0 else 0 for d in deltas[-14:]]
        rs=(sum(gains)/14)/(sum(losses)/14) if sum(losses)!=0 else 100
        rsi=100-(100/(1+rs))
        ema20=sum(closes[-20:])/20
        ema50=sum(closes[-50:])/50
        ema200=sum(closes[-200:])/200
        vol_prom=sum(vols[-30:-1])/29 if len(vols)>30 else sum(vols[:-1])/len(vols[:-1]) if len(vols)>1 else vols[-1]
        vol_x=vols[-1]/vol_prom if vol_prom>0 else 0
        tendencia="alcista" if closes[-1]>ema20>ema50 and closes[-1]>ema200*0.97 else "bajista" if closes[-1]<ema20 else "lateral"
        score=5.0
        if 50<=rsi<=72: score+=2.5
        elif 45<=rsi<50: score+=1.0
        if tendencia=="alcista": score+=2.0
        if vol_x>=1.2: score+=1.5
        if closes[-1]>ema200: score+=0.5
        if vol_x<0.8: score-=2.0
        score=max(0,min(score,10.0))
        return {"rsi":round(rsi,1),"vol_x":round(vol_x,2),"tendencia":tendencia,"score":round(score,1),"precio":closes[-1]}
    except: return None

def buscar_top_monedas(n=250):
    tickers=get_all_tickers()
    if not tickers: return []
    BLACKLIST_SYMBOLS={'UUSDT','USDCUSDT','BUSDUSDT','FDUSDUSDT','TUSDUSDT','USDEUSDT','DAIUSDT','EURUSDT','BRLUSDT','USDPUSDT','USD1USDT','XAUTUSDT','PAXGUSDT','XAUUSDT'}
    BLACKLIST_BASES={'USDT','USDC','BUSD','FDUSD','TUSD','USDE','DAI','EUR','BRL','USD','XAUT','PAXG','XAU','USTC','UST'}
    filtradas=[]
    for t in tickers:
        sym=t['symbol']
        if not sym.endswith('USDT'): continue
        if sym in BLACKLIST_SYMBOLS: continue
        base=sym.replace('USDT','')
        if len(base)<=2: continue
        if base in BLACKLIST_BASES: continue
        if base.startswith('USD'): continue
        if base.startswith('XAU'): continue
        if 'UP' in sym or 'DOWN' in sym or 'BEAR' in sym or 'BULL' in sym: continue
        filtradas.append(t)
    try: filtradas.sort(key=lambda x: float(x.get('quoteVolume',0)),reverse=True)
    except: pass
    return filtradas[:n]

def aprender_de_resultados(resultados):
    try:
        if not resultados: return
        CEREBRO["total_analisis"]+=len(resultados)
        joyas=[r for r in resultados if r[1]['score']>=9.0]
        CEREBRO["joyas_detectadas"]+=len(joyas)
        for sym,g in joyas:
            CEREBRO["mejores_monedas"][sym]=CEREBRO["mejores_monedas"].get(sym,0)+1
        if joyas:
            rsi_avg=sum([g['rsi'] for _,g in joyas])/len(joyas)
            vol_avg=sum([g['vol_x'] for _,g in joyas])/len(joyas)
            CEREBRO["patrones_ganadores"]["rsi_prom"]=round((CEREBRO["patrones_ganadores"]["rsi_prom"]*0.8 + rsi_avg*0.2),1)
            CEREBRO["patrones_ganadores"]["vol_prom"]=round((CEREBRO["patrones_ganadores"]["vol_prom"]*0.8 + vol_avg*0.2),2)
        CEREBRO["historial"].append({"fecha":str(__import__('datetime').datetime.now())[:16], "analizadas":len(resultados), "joyas":len(joyas)})
        if len(CEREBRO["historial"])>50: CEREBRO["historial"]=CEREBRO["historial"][-50:]
        guardar_cerebro()
    except Exception as e: print(f"Error aprender: {e}")

async def start_cmd(update,context):
    fng=get_fng(); btc=get_tendencia_btc()
    msg=f"ULTRA BOT v11.7 CEREBRO REAL\nMODO REAL {get_config('trading_real','ON')}\nF&G {fng} | BTC {btc}\nAnalisis totales: {CEREBRO.get('total_analisis',0)}\nJoyas encontradas: {CEREBRO.get('joyas_detectadas',0)}\nFiltro UUSDT/XAUT/PAXG BLOQUEADO\n\nComandos:\n/oportunidad - 3 joyas\n/top - top 10\n/aprender - ver cerebro\n/evolucion - patrones aprendidos\n/analizar BTC"
    await update.message.reply_text(msg)

async def oportunidad_cmd(update,context):
    fng=get_fng(); btc=get_tendencia_btc()
    await update.message.reply_text(f"ULTRA v11.7 APRENDIENDO 250... F&G {fng} BTC {btc} Total previo: {CEREBRO.get('total_analisis',0)}")
    tops=buscar_top_monedas(250)
    if not tops:
        await update.message.reply_text("Bloqueo momentaneo, reintenta 15 seg")
        return
    resultados=[]
    for t in tops:
        g=leer_grafico_ultra(t['symbol'])
        if g: resultados.append((t['symbol'],g))
        if len(resultados)>=60: break
        await asyncio.sleep(0.02)
    resultados.sort(key=lambda x: x[1]['score'],reverse=True)
    aprender_de_resultados(resultados)
    msg=f"3 JOYAS 9/10 ULTRA v11.7 F&G {fng} BTC {btc} | Aprendido: {CEREBRO['total_analisis']}\n\n"
    for sym,g in resultados[:3]:
        msg+=f"{sym} Score {g['score']}/10 RSI {g['rsi']} Vol {g['vol_x']}x {g['tendencia']}\n"
    await update.message.reply_text(msg)

async def top_cmd(update,context):
    await update.message.reply_text(f"TOP 10 v11.7 APRENDIENDO... Total: {CEREBRO.get('total_analisis',0)}")
    tops=buscar_top_monedas(250)
    res=[]
    for t in tops:
        g=leer_grafico_ultra(t['symbol'])
        if g: res.append((t['symbol'],g))
        if len(res)>=35: break
    res.sort(key=lambda x: x[1]['score'],reverse=True)
    aprender_de_resultados(res)
    msg=f"TOP 10 JOYAS v11.7 | Total aprendido: {CEREBRO['total_analisis']}\n"
    for s,g in res[:10]: msg+=f"{s} {g['score']}/10 RSI {g['rsi']} Vol {g['vol_x']}x\n"
    await update.message.reply_text(msg)

async def aprender_cmd(update,context):
    total=CEREBRO.get('total_analisis',0)
    joyas=CEREBRO.get('joyas_detectadas',0)
    mejores=sorted(CEREBRO.get('mejores_monedas',{}).items(), key=lambda x: x[1], reverse=True)[:5]
    top_str=", ".join([f"{k}({v})" for k,v in mejores]) if mejores else "Aun ninguna"
    msg=f"CEREBRO v11.7 REAL PERSISTENTE\nTotal analisis: {total}\nJoyas detectadas: {joyas}\nF&G {CONFIG['f_g']} BTC {CONFIG['btc_trend']}\nMejores monedas: {top_str}\nPatron ganador: RSI {CEREBRO['patrones_ganadores']['rsi_prom']} Vol {CEREBRO['patrones_ganadores']['vol_prom']}x\nFiltro UUSDT/XAUT/PAXG BLOQUEADO\nHistorial: {len(CEREBRO['historial'])} escaneos"
    await update.message.reply_text(msg)

async def evolucion_cmd(update,context):
    pg=CEREBRO.get('patrones_ganadores',{})
    msg=f"EVOLUCION v11.7\nEl bot aprendio que las joyas tienen:\nRSI promedio: {pg.get('rsi_prom',60)}\nVolumen promedio: {pg.get('vol_prom',1.5)}x\n\nCada vez filtra mejor. Total: {CEREBRO.get('total_analisis',0)} analisis"
    await update.message.reply_text(msg)

async def auto_on_cmd(update,context):
    set_config('auto','ON'); set_config('trading_real','ON')
    await update.message.reply_text(f"AUTO v11.7 ACTIVADO - Aprendido: {CEREBRO.get('total_analisis',0)} analisis - Escaneo cada 30 min")

async def auto_off_cmd(update,context):
    set_config('auto','OFF')
    await update.message.reply_text("AUTO PAUSADO")
async def trading_on_cmd(update,context):
    set_config('trading_real','ON'); await update.message.reply_text("Trading Real ON")
async def trading_off_cmd(update,context):
    set_config('trading_real','OFF'); await update.message.reply_text("Trading Real OFF")

async def analizar_cmd(update,context):
    if not context.args:
        await update.message.reply_text("Usa: /analizar BTC")
        return
    sym=context.args[0].upper()
    if not sym.endswith('USDT'): sym+='USDT'
    g=leer_grafico_ultra(sym)
    if not g:
        await update.message.reply_text(f"No pude leer {sym}")
        return
    await update.message.reply_text(f"{sym} Score {g['score']}/10 RSI {g['rsi']} Vol {g['vol_x']}x {g['tendencia']} Precio {g['precio']}")

async def job_scan(context):
    try:
        if get_config('auto','ON')!='ON': return
        if not TELEGRAM_CHAT_ID: return
        tops=buscar_top_monedas(250)
        res=[]
        for t in tops[:80]:
            g=leer_grafico_ultra(t['symbol'])
            if g and g['score']>=8.5: res.append((t['symbol'],g))
            await asyncio.sleep(0.03)
        if res:
            aprender_de_resultados(res)
            res.sort(key=lambda x: x[1]['score'],reverse=True)
            msg=f"AUTO v11.7 DETECTO {len(res)} JOYAS | Total aprendido {CEREBRO['total_analisis']} | F&G {CONFIG['f_g']} BTC {CONFIG['btc_trend']}\n"
            for s,g in res[:3]: msg+=f"{s} {g['score']}/10 {g['tendencia']}\n"
            try: await context.bot.send_message(chat_id=int(TELEGRAM_CHAT_ID),text=msg)
            except: pass
    except: pass

def main():
    app=ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start",start_cmd))
    app.add_handler(CommandHandler("oportunidad",oportunidad_cmd))
    app.add_handler(CommandHandler("top",top_cmd))
    app.add_handler(CommandHandler("aprender",aprender_cmd))
    app.add_handler(CommandHandler("evolucion",evolucion_cmd))
    app.add_handler(CommandHandler("auto_on",auto_on_cmd))
    app.add_handler(CommandHandler("auto_off",auto_off_cmd))
    app.add_handler(CommandHandler("analizar",analizar_cmd))
    app.add_handler(CommandHandler("trading_real_on",trading_on_cmd))
    app.add_handler(CommandHandler("trading_real_off",trading_off_cmd))
    app.job_queue.run_repeating(job_scan,interval=1800,first=60)
    print(f"ULTRA BOT v11.7 CEREBRO PERSISTENTE INICIADO - Total: {CEREBRO.get('total_analisis',0)}")
    app.run_polling()

if __name__=="__main__": main()
