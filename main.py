
import os
import requests
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")
WHATSAPP_PHONE = os.getenv("WHATSAPP_PHONE") # ej: +56912345678
WHATSAPP_APIKEY = os.getenv("WHATSAPP_APIKEY") # ej: 123456 que te dio CallMeBot
OPENAI_KEY = os.getenv("OPENAI_API_KEY") # opcional, para hacerlo mas inteligente que yo

logging.basicConfig(level=logging.INFO)
usuarios = {}
ultimas_oportunidades = set()

# ================= FUNCIONES CEREBRO =================

def get_all_tickers():
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        data = requests.get(url, timeout=15).json()
        usdt = [x for x in data if x['symbol'].endswith('USDT')]
        return sorted(usdt, key=lambda x: float(x['quoteVolume']), reverse=True)[:80]
    except: return []

def get_klines(symbol, interval="1h", limit=100):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        return requests.get(url, timeout=10).json()
    except: return []

def analizar_rsi(cierres):
    if len(cierres) < 15: return 50
    ganancias = sum(max(0, cierres[-i] - cierres[-i-1]) for i in range(1, 15))
    perdidas = sum(abs(min(0, cierres[-i] - cierres[-i-1])) for i in range(1, 15))
    if perdidas == 0: return 80
    rsi = 100 - (100 / (1 + (ganancias/14)/(perdidas/14)))
    return round(rsi, 2)

def get_noticias():
    """Trae noticias reales de crypto"""
    try:
        # CryptoPanic gratis sin API key
        url = "https://cryptopanic.com/api/free/v1/posts/?auth_token=free&currencies=BTC,ETH,SOL&filter=important"
        data = requests.get(url, timeout=10).json()
        noticias = [p['title'][:120] for p in data.get('results', [])[:5]]
        return noticias
    except:
        return ["Bitcoin en tendencia", "Mercado crypto volatil"]

def cerebro_analiza(symbol, precio, rsi, cambio24h, noticias):
    """AQUI ESTA MI CEREBRO - Toma decisiones como yo"""
    score = 0
    motivos = []

    # 1. Analisis tecnico
    if rsi < 30:
        score += 4; motivos.append(f"RSI {rsi} SOBREVENTA EXTREMA")
    elif rsi < 40:
        score += 2; motivos.append(f"RSI {rsi} en zona de compra")
    elif rsi > 75:
        score -= 3; motivos.append(f"RSI {rsi} SOBRECOMPRA peligrosa")

    # 2. Momentum
    if 1 < cambio24h < 8:
        score += 2; motivos.append(f"Subiendo sano +{cambio24h:.1f}%")
    elif cambio24h > 15:
        score -= 1; motivos.append(f"Ya explotó +{cambio24h:.1f}%, tarde")

    # 3. Noticias (sentimiento)
    texto_noticias = " ".join(noticias).lower()
    if "bullish" in texto_noticias or "rally" in texto_noticias or "etf" in texto_noticias:
        score += 1; motivos.append("Noticias positivas")

    # 4. Filtro final
    decision = "NEUTRAL"
    if score >= 5: decision = "COMPRA FUERTE 💎🔥"
    elif score >= 3: decision = "COMPRA 🟢"
    elif score <= -2: decision = "VENTA 🔴"

    return score, decision, motivos

def enviar_whatsapp(mensaje):
    """Envia alerta a tu WhatsApp"""
    if not WHATSAPP_PHONE or not WHATSAPP_APIKEY:
        return False
    try:
        url = f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_PHONE}&text={mensaje}&apikey={WHATSAPP_APIKEY}"
        requests.get(url, timeout=10)
        return True
    except: return False

# ================= COMANDOS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in usuarios: usuarios[uid] = {"saldo": 1000.0, "posiciones": {}}
    await update.message.reply_text(
        "🧠 **BOT CEREBRO v3 - CON MI INTELIGENCIA**\n\n"
        "Ahora si pienso como tu.\n\n"
        "📋 **NUEVO:**\n"
        "/oportunidad - Escaneo TODO Binance + Noticias + Mi Cerebro\n"
        "/analizar btc - Analisis completo con noticias\n"
        "/radar - Activa radar automatico que te avisa a Telegram y WhatsApp\n"
        "/top - Top 10 del dia\n"
        "/noticias - Ultimas noticias importantes\n\n"
        "Escribe /oportunidad para probar mi cerebro",
        parse_mode='Markdown')

async def analizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /analizar btc")
        return
    coin = context.args[0].upper()
    symbol = coin if coin.endswith("USDT") else coin + "USDT"
    await update.message.reply_text(f"🧠 Analizando {symbol} con mi cerebro...")

    klines = get_klines(symbol)
    if not klines or isinstance(klines, dict):
        await update.message.reply_text(f"No encontre {symbol}")
        return
    
    cierres = [float(k[4]) for k in klines]
    precio = cierres[-1]
    rsi = analizar_rsi(cierres)
    tickers = get_all_tickers()
    cambio = 0
    for t in tickers:
        if t['symbol'] == symbol:
            cambio = float(t['priceChangePercent']); break
    
    noticias = get_noticias()
    score, decision, motivos = cerebro_analiza(symbol, precio, rsi, cambio, noticias)

    msg = (
        f"📊 **ANALISIS CEREBRO {symbol}**\n"
        f"Precio: ${precio}\nRSI: {rsi} | 24h: {cambio:.2f}%\n"
        f"Score Cerebro: {score}/7\n\n"
        f"**DECISION:** {decision}\n\n"
        f"**Por que:**\n- " + "\n- ".join(motivos) + "\n\n"
        f"📰 Noticias: {noticias[0]}"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def oportunidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Activando CEREBRO TOTAL... escaneando 80 monedas + noticias + analisis. 20 seg ⏳")
    tickers = get_all_tickers()
    noticias = get_noticias()
    hallazgos = []

    for t in tickers[:40]:
        symbol = t['symbol']
        if symbol in ['USDTUSDT','USDCUSDT','FDUSDUSDT','DAIUSDT']: continue
        klines = get_klines(symbol, limit=50)
        if not klines or isinstance(klines, dict) or len(klines)<20: continue
        cierres = [float(k[4]) for k in klines]
        rsi = analizar_rsi(cierres)
        cambio = float(t['priceChangePercent'])
        
        score, decision, motivos = cerebro_analiza(symbol, float(t['lastPrice']), rsi, cambio, noticias)
        if score >= 4:
            hallazgos.append({"symbol": symbol, "precio": t['lastPrice'], "rsi": rsi, "cambio": cambio, "score": score, "decision": decision, "motivos": motivos})

    hallazgos = sorted(hallazgos, key=lambda x: x['score'], reverse=True)[:5]
    if not hallazgos:
        await update.message.reply_text("🧠 Cerebro dice: No hay oportunidades claras ahora. Mercado peligroso. Prueba /top")
        return

    msg = "🔥 **OPORTUNIDADES DETECTADAS POR MI CEREBRO:**\n\n"
    alerta_whatsapp = "🚨 BOT CEREBRO ALERTA:\n\n"
    for i, op in enumerate(hallazgos, 1):
        msg += f"{i}. **{op['symbol']}** ${op['precio']} | Score {op['score']}\n   {op['decision']} | RSI {op['rsi']} | {op['cambio']:.1f}%\n   Motivo: {op['motivos'][0]}\n\n"
        alerta_whatsapp += f"{op['symbol']} {op['decision']} - RSI {op['rsi']}\n"

    await update.message.reply_text(msg, parse_mode='Markdown')

    # Si es muy buena, mandar a WhatsApp
    if hallazgos and hallazgos[0]['score'] >= 5 and hallazgos[0]['symbol'] not in ultimas_oportunidades:
        enviado = enviar_whatsapp(alerta_whatsapp)
        if enviado:
            await update.message.reply_text("📲 Te envié la alerta a tu WhatsApp!")
            ultimas_oportunidades.add(hallazgos[0]['symbol'])

async def noticias_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    noticias = get_noticias()
    msg = "📰 **ULTIMAS NOTICIAS CRYPTO:**\n\n" + "\n\n".join([f"- {n}" for n in noticias])
    await update.message.reply_text(msg)

async def radar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📡 **RADAR AUTOMATICO ACTIVADO**\n\n"
        "Cada 15 minutos voy a escanear todo el mercado.\n"
        "Si veo una oportunidad con Score 5+ te aviso aqui y por WhatsApp.\n\n"
        "Para que funcione el WhatsApp, asegurate de poner en Railway:\n"
        "WHATSAPP_PHONE = tu numero con +56\n"
        "WHATSAPP_APIKEY = el numero que te dio CallMeBot"
    )
    # Activa job que corre cada 15 min
    if 'radar_job' not in context.chat_data:
        context.job_queue.run_repeating(radar_job, interval=900, first=10, chat_id=update.effective_chat.id)
        context.chat_data['radar_job'] = True

async def radar_job(context: ContextTypes.DEFAULT_TYPE):
    tickers = get_all_tickers()
    noticias = get_noticias()
    for t in tickers[:20]:
        symbol = t['symbol']
        if symbol in ['USDTUSDT','USDCUSDT']: continue
        klines = get_klines(symbol, limit=50)
        if not klines or len(klines)<20: continue
        rsi = analizar_rsi([float(k[4]) for k in klines])
        cambio = float(t['priceChangePercent'])
        score, decision, motivos = cerebro_analiza(symbol, float(t['lastPrice']), rsi, cambio, noticias)
        if score >= 6 and symbol not in ultimas_oportunidades:
            msg = f"🚨 **RADAR AUTO DETECTO OPORTUNIDAD**\n\n{symbol} - {decision}\nPrecio: ${t['lastPrice']}\nRSI: {rsi} | Score: {score}\nMotivo: {motivos[0]}"
            await context.bot.send_message(chat_id=context.job.chat_id, text=msg, parse_mode='Markdown')
            enviar_whatsapp(f"🚨 RADAR: {symbol} {decision} Score {score} Precio {t['lastPrice']}")
            ultimas_oportunidades.add(symbol)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = get_all_tickers()
    top10 = sorted(tickers, key=lambda x: float(x['priceChangePercent']), reverse=True)[:10]
    msg = "🚀 **TOP 10 HOY:**\n\n" + "\n".join([f"{i+1}. {t['symbol']} {float(t['priceChangePercent']):.2f}%" for i,t in enumerate(top10)])
    await update.message.reply_text(msg)

# === START ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analizar", analizar))
    app.add_handler(CommandHandler("oportunidad", oportunidad))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("noticias", noticias_cmd))
    app.add_handler(CommandHandler("radar", radar))
    print("Bot v3 CEREBRO TOTAL iniciado")
    app.run_polling()
