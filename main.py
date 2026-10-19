import os, time, logging, requests, sqlite3, traceback, pandas as pd
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
log=logging.getLogger("BOT")

TOKEN=(os.getenv("TELEGRAM_TOKEN")or"").strip().replace('"','').replace("'","")
API_KEY=(os.getenv("BINANCE_API_KEY")or"").strip()
API_SECRET=(os.getenv("BINANCE_API_SECRET")or"").strip()
TRADING_REAL=(os.getenv("TRADING_REAL") or "false").lower()=="true"
MONTO=float(os.getenv("MONTO_POR_TRADE") or "10")

INTERVAL="15m"
DB="cerebro.db"
CHAT="chat_id.txt"

BASE_SYMBOLS=["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","SHIBUSDT","DOTUSDT","LINKUSDT","TRXUSDT","MATICUSDT","LTCUSDT","BCHUSDT","UNIUSDT","ATOMUSDT","ETCUSDT","XLMUSDT","FILUSDT","PEPEUSDT","BONKUSDT","WIFUSDT","FLOKIUSDT","ARBUSDT","OPUSDT","SUIUSDT","APTUSDT","STXUSDT","IMXUSDT","NEARUSDT","RNDRUSDT","INJUSDT","TIAUSDT","SEIUSDT","PYTHUSDT","JUPUSDT","WUSDT","ARUSDT","FETUSDT","LDOUSDT","MKRUSDT","AAVEUSDT","RUNEUSDT","KASUSDT","FTMUSDT","ALGOUSDT","VETUSDT"]

def fmt(p):
 try:
  p=float(p)
  if p>=1: return f"${p:,.4f}"
  if p>=0.01: return f"${p:,.6f}"
  if p>=0.0001: return f"${p:,.8f}"
  return f"${p:.10f}"
 except: return f"${p}"

def init_db():
 try:
  con=sqlite3.connect(DB);cur=con.cursor();cur.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, fecha TEXT, simbolo TEXT, precio REAL, score REAL, rsi REAL, resultado TEXT, pnl REAL, real INTEGER)");con.commit();con.close()
 except: pass

def save_chat(c):
 try: open(CHAT,"w").write(str(c))
 except: pass
def get_chat():
 try: return int(open(CHAT).read().strip())
 except: return None

def save_trade(s,p,sc,rsi,real=0):
 try: con=sqlite3.connect(DB);cur=con.cursor();cur.execute("INSERT INTO trades (fecha,simbolo,precio,score,rsi,resultado,pnl,real) VALUES (?,?,?,?,?,?,?,?)",(datetime.now().isoformat(),s,p,sc,rsi,"PENDIENTE",0,real));con.commit();con.close()
 except: pass

def get_learn():
 try:
  con=sqlite3.connect(DB);cur=con.cursor();cur.execute("SELECT * FROM trades WHERE resultado!='PENDIENTE' ORDER BY id DESC LIMIT 30");rows=cur.fetchall();con.close()
  if not rows: return 0,"Sin historial aun - aprendiendo"
  win=len([r for r in rows if r[6]=="GANADA"]);tot=len(rows);wr=win/tot*100 if tot else 0
  bad=0
  for r in rows:
   try:
    if float(r[4])>70 and r[6]=="PERDIDA": bad+=1
   except: pass
  adj=-0.5 if bad>2 else 0
  return adj,f"Historial {tot} WR {wr:.0f}% Adj {adj}"
 except Exception as e:
  return 0,f"Error learn {e}"

def comprar_real_binance(simbolo, monto_usdt):
 if not TRADING_REAL:
  return False,"PAPER DEMO"
 if not API_KEY or not API_SECRET:
  return False,"Faltan API KEYS"
 try:
  from binance.client import Client
  client=Client(API_KEY, API_SECRET)
  # Seguridad: si simbolo es stable $1, no comprar
  if simbolo in ["RLUSDUSDT","AUSDT","USDCUSDT","FDUSDUSDT","TUSDUSDT","DAIUSDT","USDPUSDT","EURUSDT"]:
   return False,"Stable bloqueada"
  # Seguridad: nuevas listadas muy volatiles, max 5 USDT
  # Si monto > 50, bloquea por seguridad
  if monto_usdt>50:
   monto_usdt=50
  order=client.order_market_buy(symbol=simbolo, quoteOrderQty=monto_usdt)
  return True,f"REAL COMPRADO {simbolo} {monto_usdt}USDT ID {order.get('orderId')}"
 except Exception as e:
  log.error(f"Error compra real {e}")
  return False,f"Error real {e}"

def auto_learn():
 try:
  con=sqlite3.connect(DB);cur=con.cursor();cur.execute("SELECT id,fecha,simbolo,precio FROM trades WHERE resultado='PENDIENTE'");pend=cur.fetchall()
  for pid,fecha_str,sim,pe in pend:
   try:
    fe=datetime.fromisoformat(fecha_str)
    if datetime.now()-fe<timedelta(hours=4): continue
    df=get_candles(sim,10)
    if df.empty: continue
    pn=float(df["c"].iloc[-1]);pct=(pn-pe)/pe*100
    res="GANADA" if pct>=4 else "PERDIDA" if pct<=-3 else "NEUTRA"
    cur.execute("UPDATE trades SET resultado=?,pnl=? WHERE id=?",(res,pct,pid))
   except: continue
  con.commit();con.close()
 except: pass

def get_fg():
 try: r=requests.get("https://api.alternative.me/fng/?limit=1",timeout=5).json();v=int(r["data"][0]["value"]);t=r["data"][0]["value_classification"];return v,t
 except: return 50,"Neutral"

def get_binance_universe():
 try:
  url="https://data-api.binance.vision/api/v3/ticker/24hr"
  r=requests.get(url,timeout=15).json()
  usdt=[x for x in r if x["symbol"].endswith("USDT") and float(x["quoteVolume"])>500000]
  usdt_sorted=sorted(usdt,key=lambda x: float(x["quoteVolume"]),reverse=True)
  top120=[x["symbol"] for x in usdt_sorted[:120]]
  universe=list(dict.fromkeys(BASE_SYMBOLS+top120))
  blacklist=["USDCUSDT","FDUSDUSDT","TUSDUSDT","DAIUSDT","USDPUSDT","EURUSDT","RLUSDUSDT","AUSDT","BFUSDUSDT","USDEUSDT"]
  universe=[s for s in universe if s not in blacklist]
  return universe[:150]
 except:
  return BASE_SYMBOLS

def get_candles(sym,limit=100):
 for _ in range(3):
  try:
   url=f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval={INTERVAL}&limit={limit}";r=requests.get(url,timeout=10).json()
   if not r or isinstance(r,dict): time.sleep(0.5);continue
   if len(r)<60: return pd.DataFrame()
   cols=["t","o","h","l","c","v","ct","qv","tr","tb","tq","ig"];df=pd.DataFrame(r,columns=cols)
   for c in ["o","h","l","c","v"]: df[c]=pd.to_numeric(df[c])
   return df
  except: time.sleep(0.5)
 return pd.DataFrame()

def analyze(df,fg,adj):
 if df.empty: return 3.0,"Sin datos",0,50,0
 close=df["c"];vol=df["v"];ema9=close.ewm(span=9).mean();ema21=close.ewm(span=21).mean();ema50=close.ewm(span=50).mean()
 delta=close.diff();gain=delta.clip(lower=0).ewm(alpha=1/14).mean();loss=(-delta.clip(upper=0)).ewm(alpha=1/14).mean();rs=gain/loss;rsi=100-(100/(1+rs))
 crsi=float(rsi.iloc[-1]);price=float(close.iloc[-1]);vn=float(vol.iloc[-1]);va=float(vol.tail(20).mean());vr=vn/va if va>0 else 1
 sc=5.0;rea=""
 if ema9.iloc[-1]>ema21.iloc[-1]>ema50.iloc[-1]: sc+=2.0;rea+="Tend alcista "
 if ema9.iloc[-2]<=ema21.iloc[-2] and ema9.iloc[-1]>ema21.iloc[-1]: sc+=2.5;rea+="Cruce alcista "
 if ema9.iloc[-2]>=ema21.iloc[-2] and ema9.iloc[-1]<ema21.iloc[-1]: sc-=2.5;rea+="Cruce bajista "
 if 55<=crsi<=68: sc+=1.5;rea+=f"RSI {crsi:.0f} opt "
 elif crsi>78: sc-=2.0;rea+=f"RSI {crsi:.0f} sobrecomp "
 elif crsi<28: sc+=1.0;rea+=f"RSI {crsi:.0f} sobreventa "
 if vr>1.5: sc+=1.0;rea+=f"Vol x{vr:.1f} "
 if fg<25: sc+=1.0;rea+="Miedo ext "
 if fg>85: sc-=1.0;rea+="Codicia "
 sc+=adj;sc=max(1,min(10,round(sc,1)))
 if not rea: rea=f"Consolid RSI {crsi:.0f}"
 return sc,rea,price,crsi,vr

async def job_scan(context):
 try:
  chat=get_chat()
  if not chat: return
  fg,ft=get_fg();adj,txt=get_learn();SYMBOLS=get_binance_universe()
  res=[]
  for s in SYMBOLS:
   df=get_candles(s);sc,re,pr,rsi,vr=analyze(df,fg,adj);res.append((s,sc,re,pr,rsi,vr));time.sleep(0.05)
  res.sort(key=lambda x:x[1],reverse=True);best=[x for x in res if x[1]>=9.0]
  if not best: return
  msg=f"AUTO ALERTA v8.0 {datetime.now().strftime('%H:%M')} F&G {fg} Universo {len(SYMBOLS)}\n{txt}\nModo: {'REAL' if TRADING_REAL else 'PAPER'} {MONTO}USDT\n\n"
  for it in best[:3]:
   sym,sc,re,pr,rsi,vr=it;name=sym.replace("USDT","")
   ok,detail=comprar_real_binance(sym,MONTO)
   if ok:
    msg+=f"COMPRA REAL {name} {fmt(pr)} Sc {sc}\n {re}\n {detail}\n Stop {fmt(pr*0.96)} TP {fmt(pr*1.08)}\n\n";save_trade(sym,pr,sc,rsi,1)
   else:
    if TRADING_REAL: msg+=f"FALLO REAL {name} {detail}\n"
    else: msg+=f"G {name} {fmt(pr)} Sc {sc}\n {re}\n Entrada {fmt(pr)} Stop {fmt(pr*0.96)} TP {fmt(pr*1.08)}\n PAPER guardado\n\n";save_trade(sym,pr,sc,rsi,0)
  await context.bot.send_message(chat_id=chat,text=msg)
 except Exception as e: log.error(f"scan {e}")

async def job_learn(context):
 try: auto_learn()
 except: pass

async def start(update,context):
 init_db();save_chat(update.effective_chat.id)
 modo="REAL" if TRADING_REAL else "PAPER"
 await update.message.reply_text(f"BOT v8.0 {modo} ONLINE\nMonto {MONTO}USDT por trade\nFIX PEPE precio real\n150 + nuevas Binance\nTRADING_REAL={TRADING_REAL}\n/oportunidad\n/top\n/analizar btc\n/auto_on\n/aprender\n/balance")

async def oportunidad(update,context):
 try:
  save_chat(update.effective_chat.id);fg,ft=get_fg();adj,txt=get_learn();SYMBOLS=get_binance_universe()
  await update.message.reply_text(f"PRO {len(SYMBOLS)} F&G {fg} {ft}\n{txt}\nModo {('REAL' if TRADING_REAL else 'PAPER')} 40 seg...")
  res=[]
  for s in SYMBOLS:
   df=get_candles(s);sc,re,pr,rsi,vr=analyze(df,fg,adj);res.append((s,sc,re,pr,rsi,vr));time.sleep(0.05)
  res.sort(key=lambda x:x[1],reverse=True);best=[x for x in res if x[1]>=8.0]
  if not best:
   top=res[0];await update.message.reply_text(f"No Score 8+ Mejor {top[0].replace('USDT','')} {top[1]} {fmt(top[3])}");return
  msg=f"CEREBRO v8.0 {datetime.now().strftime('%H:%M')} F&G {fg} Modo {('REAL' if TRADING_REAL else 'PAPER')}\n{txt}\n\n"
  for it in best[:3]:
   sym,sc,re,pr,rsi,vr=it;name=sym.replace("USDT","");msg+=f"G {name} {fmt(pr)} Sc {sc}\n {re}\n Entrada {fmt(pr)} Stop {fmt(pr*0.96)} TP1 {fmt(pr*1.08)} TP2 {fmt(pr*1.15)}\n {'REAL' if TRADING_REAL else 'PAPER'} guardado\n\n";save_trade(sym,pr,sc,rsi,1 if TRADING_REAL else 0)
  await update.message.reply_text(msg)
 except Exception as e: await update.message.reply_text(f"Error {e}")

async def top_cmd(update,context):
 try:
  fg,ft=get_fg();adj,_=get_learn();SYMBOLS=get_binance_universe()
  await update.message.reply_text(f"TOP 15 de {len(SYMBOLS)} F&G {fg}...");res=[]
  for s in SYMBOLS:
   df=get_candles(s);sc,re,pr,rsi,vr=analyze(df,fg,adj);res.append((s,sc,re,pr,rsi,vr))
  res.sort(key=lambda x:x[1],reverse=True);msg=f"TOP 15 v8.0 {datetime.now().strftime('%H:%M')} {('REAL' if TRADING_REAL else 'PAPER')}\n\n";i=1
  for it in res[:15]:
   sym,sc,re,pr,rsi,vr=it;e="G" if sc>=8 else "Y" if sc>=6 else "R";name=sym.replace("USDT","");msg+=f"{i}. {e} {name} Sc {sc} {fmt(pr)} {re}\n\n";i+=1
  await update.message.reply_text(msg)
 except Exception as e: await update.message.reply_text(f"Error top {e}")

async def analizar_cmd(update,context):
 if not context.args: await update.message.reply_text("Uso: /analizar btc");return
 try:
  fg,ft=get_fg();adj,_=get_learn();coin=context.args[0].upper().replace("USDT","")+"USDT";df=get_candles(coin)
  if df.empty: await update.message.reply_text(f"No datos {coin}");return
  sc,re,pr,rsi,vr=analyze(df,fg,adj);await update.message.reply_text(f"ANALISIS {coin} {fmt(pr)}\nSc {sc} RSI {rsi:.1f} Vol x{vr:.1f}\nF&G {fg} {re}\nStop {fmt(pr*0.96)} TP {fmt(pr*1.08)}\nModo {('REAL' if TRADING_REAL else 'PAPER')}")
 except Exception as e: await update.message.reply_text(f"Error {e}")

async def aprender_cmd(update,context):
 adj,txt=get_learn()
 try:
  con=sqlite3.connect(DB);cur=con.cursor();cur.execute("SELECT simbolo,precio,score,resultado,pnl,real FROM trades ORDER BY id DESC LIMIT 10");rows=cur.fetchall();con.close()
  msg=f"CEREBRO v8.0 {('REAL' if TRADING_REAL else 'PAPER')}:\n{txt}\n\nUltimos 10:\n"
  for r in rows: msg+=f"{'REAL' if r[5]==1 else 'PAPER'} {r[0]} {fmt(r[1])} Sc {r[2]} {r[3]} {r[4]:.1f}%\n"
  await update.message.reply_text(msg)
 except: await update.message.reply_text(txt)

async def auto_on_cmd(update,context):
 save_chat(update.effective_chat.id)
 try:
  for job in context.job_queue.get_jobs_by_name("auto_scan"): job.schedule_removal()
  for job in context.job_queue.get_jobs_by_name("auto_learn"): job.schedule_removal()
  context.job_queue.run_repeating(job_scan,interval=1800,first=10,name="auto_scan")
  context.job_queue.run_repeating(job_learn,interval=14400,first=20,name="auto_learn")
  await update.message.reply_text(f"AUTO ON v8.0 {('REAL' if TRADING_REAL else 'PAPER')} ACTIVADO\nCada 30m 150 + nuevas Binance\nMonto {MONTO}USDT\nSolo Score 9+\nCada 4h aprende")
 except Exception as e: await update.message.reply_text(f"Error auto {e}")

async def auto_off_cmd(update,context):
 try:
  for job in context.job_queue.get_jobs_by_name("auto_scan"): job.schedule_removal()
  for job in context.job_queue.get_jobs_by_name("auto_learn"): job.schedule_removal()
  await update.message.reply_text("AUTO OFF")
 except Exception as e: await update.message.reply_text(f"Error {e}")

async def balance_cmd(update,context):
 await update.message.reply_text(f"v8.0 Modo {('REAL' if TRADING_REAL else 'PAPER')} Monto {MONTO}USDT API {'OK' if API_KEY else 'FALTA'}")

def main():
 init_db()
 if not TOKEN or ":" not in TOKEN:
  log.error("TOKEN MALO");time.sleep(99999)
 app=ApplicationBuilder().token(TOKEN).build()
 app.job_queue.run_repeating(job_learn,interval=14400,first=30,name="auto_learn")
 app.add_handler(CommandHandler("start",start));app.add_handler(CommandHandler("oportunidad",oportunidad));app.add_handler(CommandHandler("oportunidades",oportunidad));app.add_handler(CommandHandler("top",top_cmd));app.add_handler(CommandHandler("analizar",analizar_cmd));app.add_handler(CommandHandler("aprender",aprender_cmd));app.add_handler(CommandHandler("historial",aprender_cmd));app.add_handler(CommandHandler("auto_on",auto_on_cmd));app.add_handler(CommandHandler("auto_off",auto_off_cmd));app.add_handler(CommandHandler("balance",balance_cmd));app.add_handler(CommandHandler("noticias",balance_cmd))
 log.info(f"BOT v8.0 LISTO Modo {('REAL' if TRADING_REAL else 'PAPER')}");app.run_polling()
if __name__=="__main__": main()
