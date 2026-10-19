import os, requests, asyncio, logging, json, time
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
        binance_client.API_URL = 'https://api.binance.com/api'
    else:
        binance_client = Client()
except:
    try: binance_client = Client()
    except: binance_client = None

CEREBRO_FILE = "cerebro.json"
TRADES_FILE = "trades.json"

def cargar_json(file, default):
    try:
        if os.path.exists(file):
            with open(file,"r") as f: return json.load(f)
    except: pass
    return default

def guardar_json(file, data):
    try:
        with open(file,"w") as f: json.dump(data, f, indent=2)
    except Exception as e: print(f"Error {file}: {e}")

CEREBRO = cargar_json(CEREBRO_FILE, {"total_analisis":0, "joyas_detectadas":0, "mejores_monedas":{}, "patrones_ganadores":{"rsi_prom":60,"vol_prom":1.6}, "historial":[]})
TRADES = cargar_json(TRADES_FILE, {"abiertos":[], "cerrados":[], "ganancia_total":0.0, "perdida_total":0.0})
CONFIG = {"trading_real":"ON","auto":"ON","f_g":"59","btc_trend":"lateral","risk_usdt":20.0, "tp_pct":8.0, "sl_pct":5.0}

def binance_request(path):
    urls=[f"https://api.binance.com{path}",f"https://api1.binance.com{path}",f"https://api2.binance.com{path}",f"https://data-api.binance.vision{path}"]
    for url in urls:
        try:
            r=requests.get(url,timeout=8, headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code==200:
                d=r.json()
                if d: return d
        except: continue
    return None

def get_all_tickers():
    try:
        if binance_client:
            try:
                t=binance_client.get_ticker()
                if t and len(t)>50: return t
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
        def get_fng_news():
    fng=59; news="neutral"
    try:
        r=requests.get("https://api.alternative.me/fng/?limit=1",timeout=5).json()
        fng=int(r['data'][0]['value']); CONFIG['f_g']=str(fng)
        if fng<20: news="panico"
        elif fng>75: news="euforia"
        else: news="neutral"
    except: fng=int(CONFIG.get('f_g','59'))
    return fng, news

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
        vol_prom=sum(vols[-30:-1])/29 if len(vols)>30 else 1
        vol_x=vols[-1]/vol_prom if vol_prom>0 else 0
        if closes[-1]>ema20>ema50 and closes[-1]>ema200*0.98: tendencia="alcista"
        elif closes[-1]<ema20 and closes[-1]<ema50: tendencia="bajista"
        else: tendencia="lateral"
        score=5.0
        if 52<=rsi<=70: score+=2.5
        elif 45<=rsi<52: score+=1.0
        elif rsi>80 or rsi<30: score-=2.0
        if tendencia=="alcista": score+=2.5
        elif tendencia=="lateral": score+=0.5
        else: score-=2.5
        if vol_x>=1.4: score+=2.0
        elif vol_x>=1.0: score+=0.8
        elif vol_x<0.7: score-=2.0
        if closes[-1]>ema200: score+=0.5
        score=max(0,min(score,10.0))
        precio=closes[-1]
        tp=precio*(1+CONFIG['tp_pct']/100)
        sl=precio*(1-CONFIG['sl_pct']/100)
        return {"rsi":round(rsi,1),"vol_x":round(vol_x,2),"tendencia":tendencia,"score":round(score,1),"precio":precio,"tp":tp,"sl":sl}
    except: return None

def buscar_top_monedas(n=250):
    tickers=get_all_tickers()
    if not tickers: return []
    BLACKLIST={'UUSDT','USDCUSDT','BUSDUSDT','FDUSDUSDT','TUSDUSDT','USDEUSDT','DAIUSDT','EURUSDT','BRLUSDT','USDPUSDT','USD1USDT','XAUTUSDT','PAXGUSDT','RLUSDUSDT','USDSUSDT','PYUSDUSDT','GUSDUSDT','USTCUSDT','USTUSDT','EURCUSDT','EURIUSDT'}
    filtradas=[]
    for t in tickers:
        sym=t['symbol']
        if not sym.endswith('USDT'): continue
        if sym in BLACKLIST: continue
        base=sym.replace('USDT','')
        if len(base)<=2: continue
        if base in {'USDT','USDC','BUSD','FDUSD','TUSD','USDE','DAI','EUR','RLUSD','XAUT','PAXG','XAU','USTC','EURI','PYUSD','GUSD'}: continue
        if 'RLUSD' in sym or 'USD1' in sym or base.startswith('USD') or base.startswith('XAU'): continue
        if 'UP' in sym or 'DOWN' in sym or 'BEAR' in sym or 'BULL' in sym: continue
        filtradas.append(t)
    try: filtradas.sort(key=lambda x: float(x.get('quoteVolume',0)),reverse=True)
    except: pass
    return filtradas[:n]

def aprender_de_resultados(resultados):
    try:
        if not resultados: return
        CEREBRO["total_analisis"]+=len(resultados)
        joyas=[r for r in resultados if r[1]['score']>=8.5 and r[1]['tendencia']!='bajista']
        CEREBRO["joyas_detectadas"]+=len(joyas)
        for sym,g in joyas:
            CEREBRO["mejores_monedas"][sym]=CEREBRO["mejores_monedas"].get(sym,0)+1
        if joyas:
            rsi_avg=sum([g['rsi'] for _,g in joyas])/len(joyas)
            vol_avg=sum([g['vol_x'] for _,g in joyas])/len(joyas)
            CEREBRO["patrones_ganadores"]["rsi_prom"]=round((CEREBRO["patrones_ganadores"]["rsi_prom"]*0.7 + rsi_avg*0.3),1)
            CEREBRO["patrones_ganadores"]["vol_prom"]=round((CEREBRO["patrones_ganadores"]["vol_prom"]*0.7 + vol_avg*0.3),2)
        CEREBRO["historial"].append({"fecha":str(datetime.now())[:16], "analizadas":len(resultados), "joyas":len(joyas)})
        if len(CEREBRO["historial"])>100: CEREBRO["historial"]=CEREBRO["historial"][-100:]
        guardar_json(CEREBRO_FILE, CEREBRO)
    except Exception as e: print(f"Error aprender {e}")
        def ejecutar_compra_real(symbol, usdt_amount):
    if not binance_client or CONFIG['trading_real']!='ON': return {"simulado":True, "precio":0}
    try:
        order=binance_client.order_market_buy(symbol=symbol, quoteOrderQty=usdt_amount)
        precio=float(order['fills'][0]['price']) if 'fills' in order else 0
        return {"simulado":False, "order":order, "precio":precio}
    except Exception as e: return {"error":str(e), "simulado":True}

def verificar_trades_abiertos():
    cerrados_ahora=[]
    for trade in TRADES["abiertos"][:]:
        try:
            ticker=binance_request(f"/api/v3/ticker/price?symbol={trade['symbol']}")
            precio_actual=float(ticker['price']) if ticker else trade['entrada']
            pnl_pct=(precio_actual-trade['entrada'])/trade['entrada']*100
            if precio_actual>=trade['tp'] or precio_actual<=trade['sl']:
                ganancia_usdt=(precio_actual-trade['entrada'])*trade['cantidad']
                TRADES["cerrados"].append({"symbol":trade['symbol'], "entrada":trade['entrada'], "salida":precio_actual, "pnl_pct":round(pnl_pct,2), "ganancia_usdt":round(ganancia_usdt,2), "fecha_cierre":str(datetime.now())[:16], "motivo":"TP" if precio_actual>=trade['tp'] else "SL"})
                if ganancia_usdt>0: TRADES["ganancia_total"]+=ganancia_usdt
                else: TRADES["perdida_total"]+=abs(ganancia_usdt)
                TRADES["abiertos"].remove(trade)
                cerrados_ahora.append((trade, pnl_pct, ganancia_usdt))
                if binance_client and CONFIG['trading_real']=='ON':
                    try: binance_client.order_market_sell(symbol=trade['symbol'], quantity=trade['cantidad'])
                    except: pass
        except: continue
    if cerrados_ahora: guardar_json(TRADES_FILE, TRADES)
    return cerrados_ahora

async def start_cmd(update,context):
    fng,news=get_fng_news(); btc=get_tendencia_btc()
    bal="CONECTADO" if binance_client else "SOLO ANALISIS"
    msg=f"ULTRA BOT v12.1 531 LINEAS\n{bal} | Trading {CONFIG['trading_real']} | Auto {CONFIG['auto']}\nF&G {fng} ({news}) | BTC {btc}\nTotal {CEREBRO['total_analisis']} Joyas {CEREBRO['joyas_detectadas']} Trades {len(TRADES['cerrados'])}\nNeto ${TRADES['ganancia_total']-TRADES['perdida_total']:.2f} Historial {len(CEREBRO['historial'])}\n\n/oportunidad\n/top\n/comprar BTC 20\n/balance\n/ganancias\n/aprender\n/evolucion\n/auto_on"
    await update.message.reply_text(msg)

async def oportunidad_cmd(update,context):
    fng,news=get_fng_news(); btc=get_tendencia_btc()
    if fng<15:
        await update.message.reply_text(f"PANICO F&G {fng} No opero")
        return
    await update.message.reply_text(f"ESCANEANDO 250 F&G {fng} BTC {btc} Total {CEREBRO['total_analisis']}")
    tops=buscar_top_monedas(250)
    resultados=[]
    for t in tops:
        g=leer_grafico_ultra(t['symbol'])
        if g and g['score']>=8.0 and g['tendencia']!='bajista' and g['vol_x']>=1.0:
            resultados.append((t['symbol'],g))
        if len(resultados)>=70: break
        await asyncio.sleep(0.02)
    resultados.sort(key=lambda x: x[1]['score'],reverse=True)
    aprender_de_resultados(resultados)
    if not resultados:
        await update.message.reply_text("No hay joyas alcistas ahora")
        return
    msg=f"3 JOYAS v12.1 F&G {fng} BTC {btc} Cerebro {CEREBRO['total_analisis']} Historial {len(CEREBRO['historial'])}\n\n"
    for sym,g in resultados[:3]:
        msg+=f"{sym} Score {g['score']}/10 RSI {g['rsi']} Vol {g['vol_x']}x {g['tendencia']} ENTRADA ${g['precio']:.4f} TP ${g['tp']:.4f} +8% SL ${g['sl']:.4f} -5%\n"
    await update.message.reply_text(msg)
async def top_cmd(update,context):
    tops=buscar_top_monedas(250)
    res=[]
    for t in tops:
        g=leer_grafico_ultra(t['symbol'])
        if g and g['tendencia']!='bajista' and g['score']>=7.5: res.append((t['symbol'],g))
        if len(res)>=40: break
    res.sort(key=lambda x: x[1]['score'],reverse=True)
    aprender_de_resultados(res)
    msg=f"TOP 10 v12.1 Total {CEREBRO['total_analisis']}\n"
    for s,g in res[:10]: msg+=f"{s} {g['score']}/10 {g['tendencia']} Vol {g['vol_x']}x Entrada ${g['precio']:.3f}\n"
    await update.message.reply_text(msg)

async def comprar_cmd(update,context):
    if not context.args:
        await update.message.reply_text("Usa: /comprar BTC 20")
        return
    sym=context.args[0].upper()
    if not sym.endswith('USDT'): sym+='USDT'
    try: amount=float(context.args[1]) if len(context.args)>1 else CONFIG['risk_usdt']
    except: amount=CONFIG['risk_usdt']
    g=leer_grafico_ultra(sym)
    if not g:
        await update.message.reply_text(f"No pude leer {sym}")
        return
    res=ejecutar_compra_real(sym, amount)
    entrada=g['precio'] if res.get('simulado') else res.get('precio', g['precio'])
    cantidad=amount/entrada if entrada>0 else 0
    trade={"symbol":sym, "entrada":entrada, "tp":g['tp'], "sl":g['sl'], "cantidad":cantidad, "usdt":amount, "fecha":str(datetime.now())[:16], "score":g['score']}
    TRADES["abiertos"].append(trade)
    guardar_json(TRADES_FILE, TRADES)
    modo="SIMULADO" if res.get('simulado') else "REAL"
    await update.message.reply_text(f"COMPRA {modo} {sym} Entrada ${entrada:.4f} TP ${g['tp']:.4f} SL ${g['sl']:.4f} Inversion ${amount}")

async def ganancias_cmd(update,context):
    neto=TRADES["ganancia_total"]-TRADES["perdida_total"]
    win=len([t for t in TRADES["cerrados"] if t['ganancia_usdt']>0])
    total=len(TRADES["cerrados"])
    wr=win/total*100 if total>0 else 0
    msg=f"P&L Abiertos {len(TRADES['abiertos'])} Cerrados {total} Ganado ${TRADES['ganancia_total']:.2f} Perdido ${TRADES['perdida_total']:.2f} NETO ${neto:.2f} WinRate {wr:.1f}%\n"
    for t in TRADES["cerrados"][-5:]: msg+=f"{t['symbol']} {t['pnl_pct']}% ${t['ganancia_usdt']} {t['motivo']} {t['fecha_cierre']}\n"
    await update.message.reply_text(msg)

async def balance_cmd(update,context):
    if not binance_client:
        await update.message.reply_text("Binance no conectado")
        return
    try:
        bal=binance_client.get_account()
        usdt_free=0
        for b in bal['balances']:
            if b['asset']=='USDT': usdt_free=float(b['free'])
        msg=f"BALANCE USDT ${usdt_free:.2f} Abiertos {len(TRADES['abiertos'])}\n"
        for t in TRADES["abiertos"]: msg+=f"{t['symbol']} Entrada ${t['entrada']:.3f}\n"
        await update.message.reply_text(msg)
    except Exception as e: await update.message.reply_text(f"Error balance {e}")

async def aprender_cmd(update,context):
    mejores=sorted(CEREBRO.get('mejores_monedas',{}).items(), key=lambda x: x[1], reverse=True)[:5]
    top_str=", ".join([f"{k}({v})" for k,v in mejores]) if mejores else "Aprendiendo"
    msg=f"CEREBRO Total {CEREBRO.get('total_analisis',0)} Joyas {CEREBRO.get('joyas_detectadas',0)} Mejores {top_str} RSI {CEREBRO['patrones_ganadores']['rsi_prom']} Vol {CEREBRO['patrones_ganadores']['vol_prom']}x F&G {CONFIG['f_g']} BTC {CONFIG['btc_trend']} Historial {len(CEREBRO['historial'])}"
    await update.message.reply_text(msg)

async def evolucion_cmd(update,context):
    pg=CEREBRO.get('patrones_ganadores',{})
    neto=TRADES["ganancia_total"]-TRADES["perdida_total"]
    msg=f"EVOLUCION Analice {CEREBRO.get('total_analisis',0)} en {len(CEREBRO['historial'])} escaneos RSI {pg.get('rsi_prom',60)} Vol {pg.get('vol_prom',1.6)}x Trades {len(TRADES['cerrados'])} Neto ${neto:.2f}"
    await update.message.reply_text(msg)

async def auto_on_cmd(update,context):
    CONFIG['auto']='ON'; CONFIG['trading_real']='ON'
    await update.message.reply_text(f"AUTO ACTIVADO Riesgo ${CONFIG['risk_usdt']} TP {CONFIG['tp_pct']}% SL {CONFIG['sl_pct']}%")

async def auto_off_cmd(update,context):
    CONFIG['auto']='OFF'
    await update.message.reply_text("AUTO PAUSADO")
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
    await update.message.reply_text(f"{sym} Score {g['score']}/10 RSI {g['rsi']} Vol {g['vol_x']}x {g['tendencia']} Precio {g['precio']:.4f}")

async def job_scan(context):
    try:
        cerrados=verificar_trades_abiertos()
        if cerrados and TELEGRAM_CHAT_ID:
            for trade, pnl, usdt in cerrados:
                emoji="GANANCIA" if usdt>0 else "PERDIDA"
                try: await context.bot.send_message(chat_id=int(TELEGRAM_CHAT_ID), text=f"{emoji} {trade['symbol']} cerrado {pnl:.2f}% ${usdt:.2f} Neto ${TRADES['ganancia_total']-TRADES['perdida_total']:.2f}")
                except: pass
        if CONFIG['auto']!='ON': return
        fng,news=get_fng_news(); btc=get_tendencia_btc()
        if fng<18: return
        tops=buscar_top_monedas(200)
        candidatos=[]
        for t in tops[:60]:
            g=leer_grafico_ultra(t['symbol'])
            if g and g['score']>=9.2 and g['tendencia']=='alcista' and g['vol_x']>=1.3:
                candidatos.append((t['symbol'],g))
            await asyncio.sleep(0.03)
        candidatos.sort(key=lambda x: x[1]['score'],reverse=True)
        if candidatos and TELEGRAM_CHAT_ID and len(TRADES["abiertos"])<3:
            sym,g=candidatos[0]
            res=ejecutar_compra_real(sym, CONFIG['risk_usdt'])
            entrada=g['precio'] if res.get('simulado') else res.get('precio', g['precio'])
            cantidad=CONFIG['risk_usdt']/entrada if entrada>0 else 0
            TRADES["abiertos"].append({"symbol":sym, "entrada":entrada, "tp":g['tp'], "sl":g['sl'], "cantidad":cantidad, "usdt":CONFIG['risk_usdt'], "fecha":str(datetime.now())[:16], "score":g['score']})
            guardar_json(TRADES_FILE, TRADES)
            aprender_de_resultados(candidatos)
            try: await context.bot.send_message(chat_id=int(TELEGRAM_CHAT_ID), text=f"AUTO ENTRO {sym} Score {g['score']}/10 ENTRADA ${entrada:.4f} TP ${g['tp']:.4f} SL ${g['sl']:.4f} F&G {fng} BTC {btc}")
            except: pass
    except Exception as e: print(f"job_scan error {e}")

def main():
    app=ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",start_cmd))
    app.add_handler(CommandHandler("oportunidad",oportunidad_cmd))
    app.add_handler(CommandHandler("top",top_cmd))
    app.add_handler(CommandHandler("comprar",comprar_cmd))
    app.add_handler(CommandHandler("balance",balance_cmd))
    app.add_handler(CommandHandler("ganancias",ganancias_cmd))
    app.add_handler(CommandHandler("aprender",aprender_cmd))
    app.add_handler(CommandHandler("evolucion",evolucion_cmd))
    app.add_handler(CommandHandler("auto_on",auto_on_cmd))
    app.add_handler(CommandHandler("auto_off",auto_off_cmd))
    app.add_handler(CommandHandler("analizar",analizar_cmd))
    app.job_queue.run_repeating(job_scan,interval=1200,first=90)
    print(f"ULTRA BOT v12.1 531 LINEAS INICIADO Total {CEREBRO.get('total_analisis',0)} Historial {len(CEREBRO['historial'])}")
    app.run_polling()

if __name__=="__main__": main()
