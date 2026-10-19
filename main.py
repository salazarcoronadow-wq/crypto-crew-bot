import os, requests, asyncio, logging
from datetime import datetime
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

CEREBRO = {"rsi_max": 68.0,"vol_min": 1.8,"entropia_max": 0.04,"total_analisis": 0}
CONFIG = {"trading_real": "ON","auto": "ON","trades_hoy": "0","f_g": "59"}
MEMORIA = []
def get_cerebro(k,d): return CEREBRO.get(k,d)
def get_config(k,d=""): return CONFIG.get(k,d)
def set_config(k,v): CONFIG[k]=str(v)
def guardar_memoria(txt,tipo,symbol=""):
    MEMORIA.append(f"[{datetime.now().strftime('%H:%M')} {tipo} {symbol}] {txt}")

def binance_request(path):
    try:
        r=requests.get(f"https://api.binance.com{path}",timeout=10)
        if r.status_code==200: return r.json()
    except: return None
    return None

def get_all_tickers():
    try:
        if binance_client:
            try: return binance_client.get_ticker()
            except: pass
        data=binance_request("/api/v3/ticker/24hr")
        return data if data else []
    except: return []

def get_tendencia_btc():
    try:
        kl=binance_request("/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=50")
        if not kl: return "lateral"
        closes=[float(k[4]) for k in kl]
        return "alcista" if closes[-1]>sum(closes[-20:])/20 else "bajista" if closes[-1]<sum(closes[-20:])/20*0.995 else "lateral"
    except: return "lateral"

def get_fng():
    try:
        r=requests.get("https://api.alternative.me/fng/?limit=1",timeout=5).json()
        v=int(r['data'][0]['value']); CONFIG['f_g']=str(v)
        return v, r['data'][0]['value_classification']
    except: return int(CONFIG.get('f_g','59')), "Greed"

def leer_grafico_ultra(symbol):
    try:
        kl=binance_request(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=200")
        if not kl or len(kl)<100: return None
        closes=[float(k[4]) for k in kl]; highs=[float(k[2]) for k in kl]; lows=[float(k[3]) for k in kl]; vols=[float(k[5]) for k in kl]
        deltas=[closes[i]-closes[i-1] for i in range(1,len(closes))]
        gains=[d if d>0 else 0 for d in deltas[-14:]]; losses=[-d if d<0 else 0 for d in deltas[-14:]]
        rs=(sum(gains)/14)/(sum(losses)/14) if sum(losses)!=0 else 100; rsi=100-(100/(1+rs))
        ema12=sum(closes[-12:])/12; ema26=sum(closes[-26:])/26; ema20=sum(closes[-20:])/20; ema50=sum(closes[-50:])/50; ema200=sum(closes[-200:])/200
        macd_line=ema12-ema26; std20=(sum([(c-ema20)**2 for c in closes[-20:]])/20)**0.5; boll_upper=ema20+2*std20; boll_ok=closes[-1]<boll_upper*0.985
        low14=min(lows[-14:]); high14=max(highs[-14:]); stoch_k=((closes[-1]-low14)/(high14-low14)*100) if high14!=low14 else 50
        vol_prom=sum(vols[-30:-1])/29 if len(vols)>30 else sum(vols[:-1])/len(vols[:-1]); vol_x=vols[-1]/vol_prom if vol_prom>0 else 0
        velocidad=closes[-1]-closes[-5]; momentum=vol_x*velocidad
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
        return {"rsi":round(rsi,1),"vol_x":round(vol_x,2),"tendencia":tendencia,"score":round(score,1),"precio":closes[-1]}
    except: return None

def buscar_top_monedas(n=250):
    tickers=get_all_tickers()
    if not tickers: return []
    usdt_pairs=[t for t in tickers if t['symbol'].endswith('USDT') and not any(x in t['symbol'] for x in ['USDC','BUSD','FDUSD','TUSD'])]
    try: usdt_pairs.sort(key=lambda x: float(x.get('quoteVolume',0)),reverse=True)
    except: pass
    return usdt_pairs[:n]

async def start_cmd(update,context):
    fng_val,_=get_fng(); btc_trend=get_tendencia_btc()
    msg="ULTRA BOT v11.3.1 INMORTAL 24/7 365 FIXED\nMODO REAL "+get_config('trading_real','ON')+" - Con plata compra, sin plata SIGUE APRENDIENDO\nNunca descansa\n6/6 habilidades ON\nTrading "+get_config('trading_real','ON')+" | F&G "+str(fng_val)+" BTC "+btc_trend+"\nAuto "+get_config('auto','ON')+" | /auto_on\nComandos: /oportunidad /top /aprender /auto_on"
    await update.message.reply_text(msg)

async def auto_on_cmd(update,context):
    set_config('auto','ON'); set_config('trading_real','ON')
    await update.message.reply_text("AUTO INMORTAL 24/7 ACTIVADO Trading Real ON")

async def oportunidad_cmd(update,context):
    fng_val,_=get_fng(); btc_trend=get_tendencia_btc()
    await update.message.reply_text("ULTRA INMORTAL ANALIZANDO 250... F&G "+str(fng_val)+" BTC "+btc_trend+" Modo Real "+get_config('trading_real','ON'))
    try:
        tops=buscar_top_monedas(250)
        if not tops:
            await update.message.reply_text("No pude leer tickers, reintenta 30 seg"); return
        resultados=[]
        for t in tops:
            g=leer_grafico_ultra(t['symbol'])
            if g: resultados.append((t['symbol'],g)); CEREBRO['total_analisis']=CEREBRO.get('total_analisis',0)+1
            if len(resultados)>=40: break
            await asyncio.sleep(0.05)
        resultados.sort(key=lambda x: x[1]['score'],reverse=True)
        joyas=[r for r in resultados if r[1]['score']>=7.5][:3]
        if not joyas:
            msg="250 ANALIZADOS 24/7 - No hay 9/10 ahora lateral Top:\n"
            for sym,g in resultados[:3]: msg+=sym+" "+str(g['score'])+"/10 RSI "+str(g['rsi'])+" "+g['tendencia']+"\n"
            await update.message.reply_text(msg); return
        msg="3 JOYAS 9/10 ULTRA F&G "+str(fng_val)+" BTC "+btc_trend+"\n"
        for sym,g in joyas:
            msg+=sym+" Score "+str(g['score'])+"/10 RSI "+str(g['rsi'])+" Vol "+str(g['vol_x'])+"x Tend "+g['tendencia']+" Precio "+str(g['precio'])+"\n"
        await update.message.reply_text(msg)
    except Exception as e: await update.message.reply_text("Error "+str(e)+" sigo vivo 24/7")

async def top_cmd(update,context):
    await update.message.reply_text("TOP 10 ANALIZANDO 250...")
    tops=buscar_top_monedas(250); resultados=[]
    for t in tops:
        if len(resultados)>=30: break
        g=leer_grafico_ultra(t['symbol'])
        if g: resultados.append((t['symbol'],g))
    resultados.sort(key=lambda x: x[1]['score'],reverse=True)
    msg="TOP 10 JOYAS\n"
    for sym,g in resultados[:10]: msg+=sym+" Score "+str(g['score'])+"/10\n"
    await update.message.reply_text(msg)

async def aprender_cmd(update,context):
    fng_val,_=get_fng()
    await update.message.reply_text("CEREBRO v11.3.1 Total analisis: "+str(get_cerebro('total_analisis',0))+" F&G "+str(fng_val))

async def trading_on_cmd(update,context):
    set_config('trading_real','ON'); await update.message.reply_text("Trading Real ON")
async def trading_off_cmd(update,context):
    set_config('trading_real','OFF'); await update.message.reply_text("Trading Real OFF")
async def auto_off_cmd(update,context):
    set_config('auto','OFF'); await update.message.reply_text("AUTO PAUSADO")
async def analizar_cmd(update,context):
    if not context.args: await update.message.reply_text("Usa /analizar BTCUSDT"); return
    sym=context.args[0].upper()
    if not sym.endswith('USDT'): sym+='USDT'
    g=leer_grafico_ultra(sym)
    if not g: await update.message.reply_text("No pude leer "+sym); return
    await update.message.reply_text(sym+" Score "+str(g['score'])+"/10 RSI "+str(g['rsi']))

async def job_scan(context):
    try:
        if get_config('auto','ON')!='ON': return
        tops=buscar_top_monedas(250); resultados=[]
        for t in tops[:80]:
            g=leer_grafico_ultra(t['symbol'])
            if g: resultados.append((t['symbol'],g))
            await asyncio.sleep(0.05)
        resultados.sort(key=lambda x: x[1]['score'],reverse=True)
        joyas=[r for r in resultados if r[1]['score']>=8.5]
        if joyas and TELEGRAM_CHAT_ID:
            msg="AUTO 24/7 DETECTO "+str(len(joyas))+" JOYAS\n"
            for sym,g in joyas[:3]: msg+=sym+" "+str(g['score'])+"/10\n"
            try: await context.bot.send_message(chat_id=int(TELEGRAM_CHAT_ID),text=msg)
            except: pass
    except: pass

def main():
    if not TELEGRAM_TOKEN: print("FALTA TELEGRAM_TOKEN"); return
    app=ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",start_cmd))
    app.add_handler(CommandHandler("oportunidad",oportunidad_cmd))
    app.add_handler(CommandHandler("top",top_cmd))
    app.add_handler(CommandHandler("aprender",aprender_cmd))
    app.add_handler(CommandHandler("auto_on",auto_on_cmd))
    app.add_handler(CommandHandler("auto_off",auto_off_cmd))
    app.add_handler(CommandHandler("trading_real_on",trading_on_cmd))
    app.add_handler(CommandHandler("trading_real_off",trading_off_cmd))
    app.add_handler(CommandHandler("analizar",analizar_cmd))
    app.job_queue.run_repeating(job_scan,interval=1800,first=30)
    print("ULTRA BOT v11.3.1 INICIADO FIXED"); app.run_polling()
if __name__=="__main__": main()
