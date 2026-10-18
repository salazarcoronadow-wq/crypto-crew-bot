import os, json, requests, datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
TOKEN=os.getenv("BOT_TOKEN")
FILE="saldo.json"
def get_saldo():
 try:
  with open(FILE,"r") as f: return json.load(f)
 except: return {"usd":1000.0,"btc":0.0,"historial":[],"lecciones":[]}
def save_saldo(s):
 with open(FILE,"w") as f: json.dump(s,f)
def precio(coin):
 try:
  r=requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd&include_24hr_change=true").json()
  return r[coin]['usd'],r[coin]['usd_24h_change']
 except: return 0,0
async def start(update,context):
 await update.message.reply_text("🧠 BOT CEREBRO CRYPTO CREW\n\nTodo en español\nModo simulado $1000\n\n/analizar btc\n/comprar btc 100\n/vender btc 100\n/saldo\n/oportunidad\n/error vendi por miedo",parse_mode="Markdown")
async def analizar(update,context):
 coin=context.args[0].lower() if context.args else "bitcoin"
 if coin=="btc": coin="bitcoin"
 if coin=="eth": coin="ethereum"
 p,c=precio(coin)
 saldo=get_saldo()
 if c<-4: dec="🔥 OPORTUNIDAD ORO: Descuento fuerte. YO COMPRARIA"
 elif c<-1: dec="👀 Descuento leve. Comprar escalonado"
 elif c>5: dec="💰 SOBRECOMPRA: VENDER y tomar ganancia"
 else: dec="🤔 NEUTRAL: Esperar"
 lec=saldo["lecciones"][-1] if saldo["lecciones"] else "Aprendiendo"
 await update.message.reply_text(f"🧠 {coin.upper()} ${p:,.2f} ({c:.2f}%)\n\n{dec}\n\nLeccion: {lec}\n\nUsa /comprar {coin} 100")
async def comprar(update,context):
 try:
  coin=context.args[0].lower() if len(context.args)>0 else "bitcoin"
  if coin=="btc": coin="bitcoin"
  monto=float(context.args[1]) if len(context.args)>1 else 100
  pr,_=precio(coin)
  s=get_saldo()
  if s["usd"]<monto:
   await update.message.reply_text(f"❌ Solo tienes ${s['usd']:.2f}")
   return
  s["usd"]-=monto
  s["historial"].append(f"{datetime.datetime.now().strftime('%d/%m')} COMPRA {coin} ${monto}")
  save_saldo(s)
  await update.message.reply_text(f"✅ SIMULADO Compre ${monto} de {coin} a ${pr:,.2f}\nSaldo: ${s['usd']:.2f}")
 except Exception as e: await update.message.reply_text(f"Usa /comprar btc 100")
async def vender(update,context):
 try:
  coin=context.args[0].lower() if len(context.args)>0 else "bitcoin"
  monto=float(context.args[1]) if len(context.args)>1 else 100
  pr,_=precio(coin)
  s=get_saldo()
  s["usd"]+=monto
  s["historial"].append(f"{datetime.datetime.now().strftime('%d/%m')} VENTA {coin} ${monto}")
  save_saldo(s)
  await update.message.reply_text(f"✅ SIMULADO Vendi ${monto} de {coin}\nSaldo: ${s['usd']:.2f}")
 except: await update.message.reply_text("Usa /vender btc 100")
async def saldo_cmd(update,context):
 s=get_saldo()
 g=s["usd"]-1000
 txt=f"💼 SALDO ${s['usd']:.2f}\nGanancia {g:+.2f}\n\n"+"\n".join(s["historial"][-10:])
 await update.message.reply_text(txt)
async def oportunidad(update,context):
 txt="🔍 OPORTUNIDADES\n\n"
 for c in ["bitcoin","ethereum","solana"]:
  p,ch=precio(c)
  if ch<-2: txt+=f"🟢 {c} {ch:.1f}% DESCUENTO COMPRAR\n"
  elif ch>4: txt+=f"🔴 {c} +{ch:.1f}% ALTO VENDER\n"
 await update.message.reply_text(txt)
async def error_cmd(update,context):
 lec=" ".join(context.args)
 if not lec:
  await update.message.reply_text("Usa /error vendi por miedo")
  return
 s=get_saldo()
 s["lecciones"].append(lec)
 save_saldo(s)
 await update.message.reply_text(f"🧠 Aprendido: {lec}")
def main():
 app=Application.builder().token(TOKEN).build()
 app.add_handler(CommandHandler("start",start))
 app.add_handler(CommandHandler("analizar",analizar))
 app.add_handler(CommandHandler("comprar",comprar))
 app.add_handler(CommandHandler("vender",vender))
 app.add_handler(CommandHandler("saldo",saldo_cmd))
 app.add_handler(CommandHandler("oportunidad",oportunidad))
 app.add_handler(CommandHandler("error",error_cmd))
 app.add_handler(CommandHandler("precio",analizar))
 app.run_polling()
if __name__=="__main__": main()
