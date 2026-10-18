
import os
import requests
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")

# Base de datos simulada en memoria
usuarios = {}

# --- FUNCIONES BINANCE ---
def get_all_tickers():
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        data = requests.get(url, timeout=10).json()
        # Solo pares USDT, top por volumen
        usdt = [x for x in data if x['symbol'].endswith('USDT')]
        usdt_sorted = sorted(usdt, key=lambda x: float(x['quoteVolume']), reverse=True)
        return usdt_sorted[:80]  # Top 80 por volumen
    except:
        return []

def get_klines(symbol, interval="1h", limit=100):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        return requests.get(url, timeout=10).json()
    except:
        return []

def analizar_rsi(cierres):
    if len(cierres) < 15: return 50
    ganancias = 0
    perdidas = 0
    for i in range(1, 15):
        diff = cierres[-i] - cierres[-i-1]
        if diff > 0: ganancias += diff
        else: perdidas += abs(diff)
    if perdidas == 0: return 100
    rs = (ganancias/14) / (perdidas/14)
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

# --- COMANDOS TELEGRAM ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in usuarios:
        usuarios[uid] = {"saldo": 1000.0, "posiciones": {}}
    
    msg = (
        "🧠 **BOT CEREBRO CRYPTO CREW - v2 TODO BINANCE**\n\n"
        "Ya no es solo BTC. Ahora escaneo TODO Binance.\n\n"
        "📋 **COMANDOS:**\n"
        "/oportunidad - Top 5 oportunidades de TODO el mercado\n"
        "/analizar btc - Analiza cualquier moneda: btc, eth, sol, pepe, etc\n"
        "/top - Ranking de las que más suben hoy\n"
        "/saldo - Ver tu portafolio simulado\n"
        "/comprar btc 100 - Comprar 100 USD simulados\n"
        "/vender btc 100 - Vender\n"
        "/noticias - Noticias importantes\n\n"
        "Prueba: /oportunidad"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def analizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /analizar btc  o  /analizar eth  o  /analizar sol")
        return
    coin = context.args[0].upper()
    symbol = coin if coin.endswith("USDT") else coin + "USDT"
    
    await update.message.reply_text(f"🔍 Analizando {symbol} en todo Binance...")
    
    klines = get_klines(symbol)
    if not klines:
        await update.message.reply_text(f"No encontré {symbol} en Binance")
        return
        
    cierres = [float(k[4]) for k in klines]
    precio = cierres[-1]
    rsi = analizar_rsi(cierres)
    
    # Tendencia simple
    sma20 = sum(cierres[-20:])/20
    tendencia = "ALCISTA 📈" if precio > sma20 else "BAJISTA 📉"
    
    cambio_24h = ((cierres[-1] - cierres[0]) / cierres[0]) * 100
    
    if rsi < 30:
        senal = "💎 SOBREVENTA - Oportunidad de COMPRA"
    elif rsi > 70:
        senal = "⚠️ SOBRECOMPRA - Cuidado, posible venta"
    else:
        senal = "😐 NEUTRAL"

    msg = (
        f"📊 **{symbol}**\n"
        f"Precio: ${precio}\n"
        f"Tendencia {interval}: {tendencia}\n"
        f"RSI (14): {rsi}\n"
        f"Cambio 24h aprox: {cambio_24h:.2f}%\n\n"
        f"{senal}\n\n"
        f"SMA 20: ${sma20:.4f}"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Escaneando las 80 monedas con más volumen de Binance... dame 15 seg ⏳")
    
    tickers = get_all_tickers()
    oportunidades = []
    
    for t in tickers[:40]: # Analizamos 40 para que no demore mucho
        symbol = t['symbol']
        # Filtros: que no sea stablecoin
        if symbol in ['USDTUSDT', 'USDCUSDT', 'FDUSDUSDT', 'DAIUSDT']: continue
        
        klines = get_klines(symbol, limit=50)
        if not klines: continue
        cierres = [float(k[4]) for k in klines]
        if len(cierres) < 20: continue
        
        rsi = analizar_rsi(cierres)
        cambio = float(t['priceChangePercent'])
        
        # Logica de oportunidad: RSI < 40 y cambio positivo, o RSI muy bajo
        score = 0
        if rsi < 35: score += 3
        elif rsi < 45: score += 1
        if 0 < cambio < 8: score += 2 # Subiendo pero no explotada
        if cambio > 0: score += 1
        
        if score >= 3:
            oportunidades.append({"symbol": symbol, "rsi": rsi, "cambio": cambio, "precio": t['lastPrice'], "score": score})

    oportunidades = sorted(oportunidades, key=lambda x: x['score'], reverse=True)[:5]
    
    if not oportunidades:
        await update.message.reply_text("Ahora no veo oportunidades claras de compra. Mercado sobrecomprado. Prueba /top")
        return

    msg = "🔥 **TOP 5 OPORTUNIDADES AHORA (Todo Binance):**\n\n"
    for i, op in enumerate(oportunidades, 1):
        msg += f"{i}. **{op['symbol']}** - ${op['precio']}\n   RSI: {op['rsi']} | 24h: {op['cambio']:.2f}% | Score: {op['score']}/6\n\n"
    msg += "Analiza con /analizar btc"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = get_all_tickers()
    top_ganadoras = sorted(tickers, key=lambda x: float(x['priceChangePercent']), reverse=True)[:10]
    
    msg = "🚀 **TOP 10 QUE MÁS SUBEN HOY (Binance USDT):**\n\n"
    for i, t in enumerate(top_ganadoras, 1):
        if t['symbol'] in ['USDTUSDT', 'USDCUSDT']: continue
        msg += f"{i}. {t['symbol']} - {float(t['priceChangePercent']):.2f}% - ${t['lastPrice']}\n"
    await update.message.reply_text(msg)

async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in usuarios:
        usuarios[uid] = {"saldo": 1000.0, "posiciones": {}}
    u = usuarios[uid]
    msg = f"💰 **Saldo:** ${u['saldo']:.2f} USD (simulado)\n"
    if not u['posiciones']:
        msg += "Sin posiciones."
    else:
        for coin, cant in u['posiciones'].items():
            msg += f"- {coin}: {cant}\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def comprar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in usuarios:
        usuarios[uid] = {"saldo": 1000.0, "posiciones": {}}
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /comprar btc 100")
        return
    coin = context.args[0].upper()
    try:
        monto = float(context.args[1])
    except:
        await update.message.reply_text("Monto inválido")
        return
    
    u = usuarios[uid]
    if u['saldo'] < monto:
        await update.message.reply_text(f"No tienes saldo. Tienes ${u['saldo']}")
        return
    
    symbol = coin if coin.endswith("USDT") else coin + "USDT"
    klines = get_klines(symbol, limit=1)
    if not klines:
        await update.message.reply_text(f"No encontré {symbol}")
        return
    precio = float(klines[0][4])
    
    u['saldo'] -= monto
    cantidad = monto / precio
    u['posiciones'][coin] = u['posiciones'].get(coin, 0) + cantidad
    
    await update.message.reply_text(f"✅ Compraste {cantidad:.6f} {coin} a ${precio} con ${monto}. Saldo restante: ${u['saldo']:.2f}")

async def vender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Similar a comprar pero al revés
    uid = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /vender btc 100")
        return
    coin = context.args[0].upper()
    monto = float(context.args[1])
    
    symbol = coin if coin.endswith("USDT") else coin + "USDT"
    klines = get_klines(symbol, limit=1)
    precio = float(klines[0][4])
    
    u = usuarios[uid]
    cantidad = monto / precio
    
    if u['posiciones'].get(coin, 0) < cantidad:
        await update.message.reply_text(f"No tienes suficiente {coin}")
        return
    
    u['posiciones'][coin] -= cantidad
    u['saldo'] += monto
    
    await update.message.reply_text(f"✅ Vendiste {cantidad:.6f} {coin} por ${monto}. Saldo: ${u['saldo']:.2f}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analizar", analizar))
    app.add_handler(CommandHandler("oportunidad", oportunidad))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("saldo", saldo))
    app.add_handler(CommandHandler("comprar", comprar))
    app.add_handler(CommandHandler("vender", vender))
    
    print("Bot v2 TODO BINANCE iniciado")
    app.run_polling()
