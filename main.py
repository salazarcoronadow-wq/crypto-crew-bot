import os, requests, asyncio, logging
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

CEREBRO = {"total_analisis": 0}
CONFIG = {"trading_real": "ON","auto": "ON","f_g": "59", "btc_trend": "lateral"}

def get_config(k,d=""): return CONFIG.get(k,d)
def set_config(k,v): CONFIG[k]=str(v)

def binance_request(path):
    urls = [
        f"https://api.binance.com{path}",
        f"https://api1.binance.com{path}",
        f"https://api2.binance.com{path}",
        f"https://api3.binance.com{path}",
        f"https://data-api.binance.vision{path}"
    ]
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
        trend = "alcista" if closes[-1]>avg20 else "bajista" if closes[-1]<avg20*0.995 else "lateral"
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
        if 48<=rsi<=70: score+=2.0
        elif 40<=rsi<48: score+=1.0
        if tendencia=="alcista": score+=2.0
        elif tendencia=="lateral": score+=0.5
        if vol_x>=1.5: score+=1.0
        if closes[-1]>ema200: score+=0.5
        score=min(score,10.0)
        return {"rsi":round(rsi,1),"vol_x":round(vol_x,2),"tendencia":tendencia,"score":round(score,1),"precio":closes[-1]}
    except: return None

# --- v11.5 FIX DEFINITIVO ANTI-UUSDT ---
def buscar_top_monedas(n=250):
    tickers=get_all_tickers()
    if not tickers: return []
    
    BLACKLIST_SYMBOLS = {'UUSDT','USDCUSDT','BUSDUSDT','FDUSDUSDT','TUSDUSDT','USDEUSDT','DAIUSDT','EURUSDT','BRLUSDT','USDPUSDT','USD1USDT','USDSUSDT','PYUSDUSDT','GUSDUSDT','TUSDUSDT','USTCUSDT','USTUSDT'}
    BLACKLIST_BASES = {'USDT','USDC','BUSD','FDUSD','TUSD','USDE','DAI','EUR','BRL','USD','USDP','USD1','USTC','UST','PYUSD','GUSD'}
    
    filtradas=[]
    for t in tickers:
        sym=t['symbol']
        if not sym.endswith('USDT'): continue
        if sym in BLACKLIST_SYMBOLS: continue
        base=sym.replace('USDT','')
        if len(base)<=2: continue
        if base in BLACKLIST_BASES: continue
        if base.startswith('USD'): continue
        if 'UP' in sym or 'DOWN' in sym or 'BEAR' in sym or 'BULL' in sym: continue
        filtradas.append(t)
    
    try: filtradas.sort(key=lambda x: float(x.get('quoteVolume',0)),reverse=True)
    except: pass
    return filtradas[:n]

async def start_cmd(update,context):
    fng=get_fng(); btc=get_tendencia_btc()
    msg=f"ULTRA BOT v11.5 INMORTAL 24/7 365 ANTI-UUSDT FIXED\nMODO REAL {get_config('trading_real','ON')}\nF&G {fng} | BTC {btc}\nTrading {get_config('trading_real','ON')} | Auto {get_config('auto','ON')}\nFiltro UUSDT BLOQUEADO\n\nComandos:\n/oportunidad - 3 joyas\n/top - top 10\n/analizar BTC\n/aprender\n/auto_on"
    await update.message.reply_text(msg)

async def auto_on_cmd(update,context):
    set_config('auto','ON'); set_config('trading_real','ON')
    await update.message.reply_text("AUTO INMORTAL v11.5 ACTIVADO - UUSDT BLOQUEADO - Escaneo cada 30 min")

async def auto_off_cmd(update,context):
    set_config('auto','OFF')
    await update.message.reply_text("AUTO PAUSADO")

async def oportunidad_cmd(update,context):
    fng=get_fng(); btc=get_tendencia_btc()
    await update.message.reply_text(f"ULTRA v11.5 ANALIZANDO 250 (sin UUSDT)... F&G {fng} BTC {btc}")
    tops=buscar_top_monedas(250)
    if not tops:
        await update.message.reply_text("Bloqueo momentaneo, reintenta 15 seg")
        return
    resultados=[]
    for t in tops:
        g=leer_grafico_ultra(t['symbol'])
        if g: 
            resultados.append((t['symbol'],g))
            CEREBRO['total_analisis']+=1
        if len(resultados)>=50: break
        await asyncio.sleep(0.02)
    resultados.sort(key=lambda x: x[1]['score'],reverse=True)
    msg=f"3 JOYAS 9/10 ULTRA v11.5 F&G {fng} BTC {btc}\n\n"
    for sym,g in resultados[:3]:
        msg+=f"{sym} Score {g['score']}/10 RSI {g['rsi']} Vol {g['vol_x']}x {g['tendencia']}\n"
    await update.message.reply_text(msg)

async def top_cmd(update,context):
    await update.message.reply_text("TOP 10 v11.5 (UUSDT BLOQUEADO) ANALIZANDO 250...")
    tops=buscar_top_monedas(250)
    res=[]
    for t in tops:
        g=leer_grafico_ultra(t['symbol'])
        if g: res.append((t['symbol'],g))
        if len(res)>=30: break
    res.sort(key=lambda x: x[1]['score'],reverse=True)
    msg="TOP 10 JOYAS v11.5 SIN UUSDT\n"
    for s,g in res[:10]: msg+=f"{s} {g['score']}/10 RSI {g['rsi']} {g['tendencia']} Vol {g['vol_x']}x\n"
    await update.message.reply_text(msg)

async def aprender_cmd(update,context):
    await update.message.reply_text(f"CEREBRO v11.5\nTotal: {CEREBRO['total_analisis']}\nF&G {CONFIG['f_g']} BTC {CONFIG['btc_trend']}\nFiltro UUSDT BLOQUEADO ACTIVO")

async def trading_on_cmd(update,context):
    set_config('trading_real','ON')
    await update.message.reply_text("Trading Real ON")
async def trading_off_cmd(update,context):
    set_config('trading_real','OFF')
    await update.message.reply_text("Trading Real OFF")
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
    await update.message.reply_text(f"{sym} Score {g['score']}/10 RSI {g['rsi']} Vol {g['vol_x']}x {g['tendencia']}")

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
        res.sort(key=lambda x: x[1]['score'],reverse=True)
        if res:
            msg=f"AUTO v11.5 DETECTO {len(res)} JOYAS F&G {CONFIG['f_g']} BTC {CONFIG['btc_trend']}\n"
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
    app.add_handler(CommandHandler("auto_on",auto_on_cmd))
    app.add_handler(CommandHandler("auto_off",auto_off_cmd))
    app.add_handler(CommandHandler("analizar",analizar_cmd))
    app.add_handler(CommandHandler("trading_real_on",trading_on_cmd))
    app.add_handler(CommandHandler("trading_real_off",trading_off_cmd))
    app.job_queue.run_repeating(job_scan,interval=1800,first=60)
    print("ULTRA BOT v11.5 INICIADO UUSDT BLOQUEADO")
    app.run_polling()

if __name__=="__main__": main()
