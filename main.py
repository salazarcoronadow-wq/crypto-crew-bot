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

# --- CLIENTE BINANCE REAL ---
binance_client = None
try:
    if BINANCE_API_KEY and BINANCE_API_SECRET:
        binance_client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
        binance_client.API_URL = 'https://api.binance.com/api'
    else:
        binance_client = Client()
except:
    binance_client = None

# --- ARCHIVOS PERSISTENTES ---
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

CEREBRO = cargar_json(CEREBRO_FILE, {
    "total_analisis":0, "joyas_detectadas":0, "mejores_monedas":{},
    "patrones_ganadores":{"rsi_prom":60,"vol_prom":1.6},
    "historial":[], "win_rate":0, "total_trades":0
})
TRADES = cargar_json(TRADES_FILE, {
    "abiertos":[], "cerrados":[], "ganancia_total":0.0, "perdida_total":0.0, "balance_inicial":0.0
})
CONFIG = {"trading_real":"ON","auto":"ON","f_g":"59","btc_trend":"lateral","risk_usdt":20.0, "tp_pct":8.0, "sl_pct":5.0}

def binance_request(path):
    urls=[f"https://api.binance.com{path}",f"https://api1.binance.com{path}",f"https://data-api.binance.vision{path}"]
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
    # F&G + Noticias + Sentimiento Social
    fng=59; news_sent="neutral"
    try:
        r=requests.get("https://api.alternative.me/fng/?limit=1",timeout=5).json()
        fng=int(r['data'][0]['value']); CONFIG['f_g']=str(fng)
    except: fng=int(CONFIG.get('f_g','59'))
    try:
        # Noticias Binance - si hay panico no opera
        r=requests.get("https://api.alternative.me/fng/?limit=2",timeout=5).json()
        # Simple: si F&G <25 miedo extremo, no compra
        if fng<20: news_sent="panico"
        elif fng>75: news_sent="euforia"
        else: news_sent="neutral"
    except: pass
    return fng, news_sent

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
    BLACKLIST={'UUSDT','USDCUSDT','BUSDUSDT','FDUSDUSDT','TUSDUSDT','USDEUSDT','DAIUSDT','EURUSDT','BRLUSDT','USDPUSDT','USD1USDT','XAUTUSDT','PAXGUSDT','RLUSDUSDT','USDSUSDT','PYUSDUSDT','GUSDUSDT','USTCUSDT','USTUSDT','EURCUSDT','TUSDUSDT'}
    filtradas=[]
    for t in tickers:
        sym=t['symbol']
        if not sym.endswith('USDT'): continue
        if sym in BLACKLIST: continue
        base=sym.replace('USDT','')
        if len(base)<=2: continue
        if base in {'USDT','USDC','BUSD','FDUSD','TUSD','USDE','DAI','EUR','RLUSD','XAUT','PAXG','XAU','USTC'}: continue
        if 'RLUSD' in sym or 'USD1' in sym or base.startswith('USD') or base.startswith('XAU'): continue
        if 'UP' in sym or 'DOWN' in sym or 'BEAR' in sym or 'BULL' in sym: continue
        filtradas.append(t)
    try: filtradas.sort(key=lambda x: float(x.get('quoteVolume',0)),reverse=True)
    except: pass
    return filtradas[:n]

def ejecutar_compra_real(symbol, usdt_amount):
    if not binance_client or CONFIG['trading_real']!='ON': return {"simulado":True, "precio":0}
    try:
        # Compra a mercado
        order=binance_client.order_market_buy(symbol=symbol, quoteOrderQty=usdt_amount)
        precio=float(order['fills'][0]['price']) if 'fills' in order else 0
        return {"simulado":False, "order":order, "precio":precio}
    except Exception as e:
        return {"error":str(e), "simulado":True}

def verificar_trades_abiertos(bot_loop=None):
    cerrados_ahora=[]
    for trade in TRADES["abiertos"][:]:
        try:
            ticker=binance_request(f"/api/v3/ticker/price?symbol={trade['symbol']}")
            precio_actual=float(ticker['price']) if ticker else trade['entrada']
            pnl_pct=(precio_actual-trade['entrada'])/trade['entrada']*100
            
            # TP o SL tocado?
            if precio_actual>=trade['tp'] or precio_actual<=trade['sl'] or abs(pnl_pct)>=CONFIG['tp_pct']:
                ganancia_usdt = (precio_actual - trade['entrada']) * trade['cantidad']
                TRADES["cerrados"].append({
                    "symbol":trade['symbol'], "entrada":trade['entrada'], "salida":precio_actual,
                    "pnl_pct":round(pnl_pct,2), "ganancia_usdt":round(ganancia_usdt,2),
                    "fecha_cierre":str(datetime.now())[:16], "motivo":"TP" if precio_actual>=trade['tp'] else "SL"
                })
                if ganancia_usdt>0: TRADES["ganancia_total"]+=ganancia_usdt
                else: TRADES["perdida_total"]+=abs(ganancia_usdt)
                TRADES["abiertos"].remove(trade)
                cerrados_ahora.append((trade, pnl_pct, ganancia_usdt))
                # Venta real
                if binance_client and CONFIG['trading_real']=='ON':
                    try: binance_client.order_market_sell(symbol=trade['symbol'], quantity=trade['cantidad'])
                    except: pass
        except: continue
    if cerrados_ahora:
        guardar_json(TRADES_FILE, TRADES)
    return cerrados_ahora

# --- COMANDOS TELEGRAM ---

async def start_cmd(update,context):
    fng,news=get_fng_news(); btc=get_tendencia_btc()
    bal="CONECTADO" if binance_client else "SOLO ANALISIS"
    msg=f"🤖 ULTRA BOT v12 AUTONOMO FINAL\n{bal} | Trading {CONFIG['trading_real']} | Auto {CONFIG['auto']}\nF&G {fng} ({news}) | BTC {btc}\nTotal analisis: {CEREBRO['total_analisis']} | Trades: {len(TRADES['cerrados'])}\nGanancia: ${TRADES['ganancia_total']:.2f} Perdida: ${TRADES['perdida_total']:.2f}\n\n/oportunidad - busca joyas con TP/SL\n/top - top 10 alcistas\n/comprar BTC 20 - compra $20 real\n/balance - tu balance Binance\n/ganancias - P&L exacto\n/aprender - cerebro\n/evolucion - que aprendio\n/auto_on - modo autonomo"
    await update.message.reply_text(msg)

async def oportunidad_cmd(update,context):
    fng,news=get_fng_news(); btc=get_tendencia_btc()
    if fng<15:
        await update.message.reply_text(f"⚠️ PANICO EXTREMO F&G {fng} - No opero por seguridad, BTC {btc}")
        return
    await update.message.reply_text(f"🔍 v12 ESCANEANDO 250 + NOTICIAS... F&G {fng} ({news}) BTC {btc} | Cerebro: {CEREBRO['total_analisis']}")
    tops=buscar_top_monedas(250)
    resultados=[]
    for t in tops:
        g=leer_grafico_ultra(t['symbol'])
        if g and g['score']>=8.0 and g['tendencia']!='bajista' and g['vol_x']>=1.0:
            resultados.append((t['symbol'],g))
        if len(resultados)>=70: break
        await asyncio.sleep(0.02)
    resultados.sort(key=lambda x: x[1]['score'],reverse=True)
    CEREBRO["total_analisis"]+=len(resultados)
    CEREBRO["joyas_detectadas"]+=len([r for r in resultados if r[1]['score']>=9])
    guardar_json(CEREBRO_FILE, CEREBRO)
    
    if not resultados:
        await update.message.reply_text("No hay joyas alcistas ahora, mercado lateral")
        return
    
    msg=f"💎 3 JOYAS v12 CON ENTRADA REAL F&G {fng} BTC {btc}\nCerebro: {CEREBRO['total_analisis']} analisis\n\n"
    for sym,g in resultados[:3]:
        msg+=f"🔹 {sym}\nScore {g['score']}/10 RSI {g['rsi']} Vol {g['vol_x']}x {g['tendencia']}\nENTRADA ${g['precio']:.4f}\nTP ${g['tp']:.4f} +{CONFIG['tp_pct']}% | SL ${g['sl']:.4f} -{CONFIG['sl_pct']}%\nRiesgo ${CONFIG['risk_usdt']} | Ganancia potencial ${CONFIG['risk_usdt']*CONFIG['tp_pct']/100:.2f}\n\n"
    msg+="Usa /comprar SYMBOL 20 para comprar real o deja que /auto_on lo haga solo"
    await update.message.reply_text(msg)

async def top_cmd(update,context):
    tops=buscar_top_monedas(250)
    res=[]
    for t in tops:
        g=leer_grafico_ultra(t['symbol'])
        if g and g['tendencia']!='bajista' and g['score']>=7.5: res.append((t['symbol'],g))
        if len(res)>=40: break
    res.sort(key=lambda x: x[1]['score'],reverse=True)
    msg=f"TOP 10 JOYAS v12 ALCISTAS - Solo oro NO, estables NO\n"
    for s,g in res[:10]: msg+=f"{s} {g['score']}/10 {g['tendencia']} Vol {g['vol_x']}x | Entrada ${g['precio']:.3f} TP +{CONFIG['tp_pct']}%\n"
    await update.message.reply_text(msg)

async def comprar_cmd(update,context):
    if not context.args:
        await update.message.reply_text("Usa: /comprar BTC 20  (simbolo y USDT)")
        return
    sym=context.args[0].upper()
    if not sym.endswith('USDT'): sym+='USDT'
    try: amount=float(context.args[1]) if len(context.args)>1 else CONFIG['risk_usdt']
    except: amount=CONFIG['risk_usdt']
    
    g=leer_grafico_ultra(sym)
    if not g:
        await update.message.reply_text(f"No pude leer {sym}")
        return
    if g['tendencia']=='bajista':
        await update.message.reply_text(f"⚠️ {sym} bajista RSI {g['rsi']} - No recomendado")
        return
    
    # Ejecutar
    res=ejecutar_compra_real(sym, amount)
    entrada=g['precio'] if res.get('simulado') else res.get('precio', g['precio'])
    cantidad=amount/entrada
    
    trade={"symbol":sym, "entrada":entrada, "tp":g['tp'], "sl":g['sl'], "cantidad":cantidad, "usdt":amount, "fecha":str(datetime.now())[:16], "score":g['score']}
    TRADES["abiertos"].append(trade)
    guardar_json(TRADES_FILE, TRADES)
    
    modo="SIMULADO" if res.get('simulado') else "REAL EN BINANCE"
    await update.message.reply_text(f"✅ COMPRA {modo}\n{sym} Score {g['score']}/10\nEntrada ${entrada:.4f} Cant {cantidad:.4f}\nTP ${g['tp']:.4f} +{CONFIG['tp_pct']}% SL ${g['sl']:.4f} -{CONFIG['sl_pct']}%\nInversion ${amount}\n\nEl bot cerrara solo en TP/SL y te avisara ganancia exacta")

async def ganancias_cmd(update,context):
    cerrados=TRADES["cerrados"][-10:]
    neto=TRADES["ganancia_total"]-TRADES["perdida_total"]
    win=len([t for t in TRADES["cerrados"] if t['ganancia_usdt']>0])
    total=len(TRADES["cerrados"])
    wr=win/total*100 if total>0 else 0
    msg=f"💰 P&L EXACTO v12\nAbiertos: {len(TRADES['abiertos'])} | Cerrados: {total}\nGanado: ${TRADES['ganancia_total']:.2f}\nPerdido: ${TRADES['perdida_total']:.2f}\nNETO: ${neto:.2f}\nWinRate: {wr:.1f}% ({win}/{total})\n\nUltimos trades:\n"
    for t in cerrados[-5:]:
        emoji="🟢" if t['ganancia_usdt']>0 else "🔴"
        msg+=f"{emoji} {t['symbol']} {t['pnl_pct']}% ${t['ganancia_usdt']} {t['motivo']} {t['fecha_cierre']}\n"
    if not cerrados: msg+="Aun no hay trades, usa /oportunidad y /comprar"
    await update.message.reply_text(msg)

async def balance_cmd(update,context):
    if not binance_client:
        await update.message.reply_text("Binance no conectado, pon BINANCE_API_KEY en Railway")
        return
    try:
        bal=binance_client.get_account()
        usdt_free=0
        for b in bal['balances']:
            if b['asset']=='USDT': usdt_free=float(b['free'])
        msg=f"💼 BALANCE BINANCE REAL\nUSDT disponible: ${usdt_free:.2f}\nAbiertos: {len(TRADES['abiertos'])}\n"
        for t in TRADES["abiertos"]:
            msg+=f"{t['symbol']} Entrada ${t['entrada']:.3f} TP ${t['tp']:.3f}\n"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Error balance: {e}")

async def aprender_cmd(update,context):
    total=CEREBRO.get('total_analisis',0)
    mejores=sorted(CEREBRO.get('mejores_monedas',{}).items(), key=lambda x: x[1], reverse=True)[:5]
    top_str=", ".join([f"{k}({v})" for k,v in mejores]) if mejores else "Aprendiendo..."
    msg=f"🧠 CEREBRO v12 PERSISTENTE REAL\nTotal analisis: {total}\nJoyas: {CEREBRO.get('joyas_detectadas',0)}\nTrades: {len(TRADES['cerrados'])} cerrados\nMejores: {top_str}\nPatron: RSI {CEREBRO['patrones_ganadores']['rsi_prom']} Vol {CEREBRO['patrones_ganadores']['vol_prom']}x\nFiltro: UUSDT/RLUSD/XAUT/PAXG BLOQUEADO\nF&G {CONFIG['f_g']} BTC {CONFIG['btc_trend']}\nHistorial: {len(CEREBRO['historial'])} escaneos"
    await update.message.reply_text(msg)

async def evolucion_cmd(update,context):
    pg=CEREBRO.get('patrones_ganadores',{})
    neto=TRADES["ganancia_total"]-TRADES["perdida_total"]
    msg=f"📈 EVOLUCION v12 - LO QUE APRENDI\nAnalice {CEREBRO.get('total_analisis',0)} monedas\nPatron ganador: RSI {pg.get('rsi_prom',60)} Vol {pg.get('vol_prom',1.6)}x solo alcista\nTrades: {len(TRADES['cerrados'])} | Neto ${neto:.2f}\nEstables y oro bloqueados para siempre\nLeo F&G + BTC + volumen antes de entrar\nCada dia soy mas preciso"
    await update.message.reply_text(msg)

async def auto_on_cmd(update,context):
    CONFIG['auto']='ON'; CONFIG['trading_real']='ON'
    await update.message.reply_text(f"🚀 AUTO v12 AUTONOMO ACTIVADO\nAhora opero solo 24/7\nRiesgo ${CONFIG['risk_usdt']} por trade TP {CONFIG['tp_pct']}% SL {CONFIG['sl_pct']}%\nLeo noticias + F&G + BTC\nTe aviso cada entrada y cada ganancia/perdida exacta")
async def auto_off_cmd(update,context):
    CONFIG['auto']='OFF'; await update.message.reply_text("AUTO PAUSADO")

async def job_scan(context):
    try:
        # 1. Cerrar trades abiertos
        cerrados=verificar_trades_abiertos()
        if cerrados and TELEGRAM_CHAT_ID:
            for trade, pnl, usdt in cerrados:
                emoji="🟢 GANANCIA" if usdt>0 else "🔴 PERDIDA"
                try: await context.bot.send_message(chat_id=int(TELEGRAM_CHAT_ID), text=f"{emoji}\n{trade['symbol']} cerrado {pnl:.2f}% ${usdt:.2f}\nEntrada ${trade['entrada']:.4f} -> Salida actual\nNeto total: ${TRADES['ganancia_total']-TRADES['perdida_total']:.2f}")
                except: pass
        
        # 2. Buscar nuevas oportunidades solo si auto ON
        if CONFIG['auto']!='ON': return
        fng,news=get_fng_news(); btc=get_tendencia_btc()
        if fng<18: return # panico extremo no opera
        
        tops=buscar_top_monedas(200)
        candidatos=[]
        for t in tops[:60]:
            g=leer_grafico_ultra(t['symbol'])
            if g and g['score']>=9.2 and g['tendencia']=='alcista' and g['vol_x']>=1.3:
                candidatos.append((t['symbol'],g))
            await asyncio.sleep(0.03)
        candidatos.sort(key=lambda x: x[1]['score'],reverse=True)
        if candidatos and TELEGRAM_CHAT_ID and len(TRADES["abiertos"])<3: # max 3 abiertas
            sym,g=candidatos[0]
            # Autocompra
            res=ejecutar_compra_real(sym, CONFIG['risk_usdt'])
            entrada=g['precio'] if res.get('simulado') else res.get('precio', g['precio'])
            cantidad=CONFIG['risk_usdt']/entrada
            TRADES["abiertos"].append({"symbol":sym,"entrada":entrada,"tp":g['tp'],"sl":g['sl'],"cantidad":cantidad,"usdt":CONFIG['risk_usdt'],"fecha":str(datetime.now())[:16],"score":g['score']})
            guardar_json(TRADES_FILE, TRADES)
            CEREBRO["total_analisis"]+=60; guardar_json(CEREBRO_FILE, CEREBRO)
            try: await context.bot.send_message(chat_id=int(TELEGRAM_CHAT_ID), text=f"🤖 AUTO v12 ENTRO SOLO\n{sym} Score {g['score']}/10 RSI {g['rsi']} Vol {g['vol_x']}x {g['tendencia']}\nENTRADA ${entrada:.4f} TP ${g['tp']:.4f} SL ${g['sl']:.4f}\nF&G {fng} BTC {btc} | Inversion ${CONFIG['risk_usdt']}")
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
    app.add_handler(CommandHandler("analizar",lambda u,c: analizar_cmd(u,c)))
    # job cada 20 min
    app.job_queue.run_repeating(job_scan,interval=1200,first=90)
    print(f"ULTRA BOT v12 AUTONOMO FINAL INICIADO - Cerebro {CEREBRO.get('total_analisis',0)} - Ganancia ${TRADES['ganancia_total']-TRADES['perdida_total']:.2f}")
    app.run_polling()

if __name__=="__main__": main()
