
import os
import time
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from binance.client import Client

load_dotenv()

# =========================================================
# 1. CONFIGURACION
# =========================================================

MODE = os.getenv("TRADING_MODE", "paper").strip().lower()
MARKET = os.getenv("MARKET_TYPE", "spot").strip().lower()

SYMBOLS = list(dict.fromkeys(
    s.strip().upper()
    for s in os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
    if s.strip()
))

INTERVAL = os.getenv("INTERVAL", "5m")
LOOKBACK = int(os.getenv("LOOKBACK", "300"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))

START_BALANCE = float(os.getenv("PAPER_START_BALANCE", "1000"))
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.005"))
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "0.02"))
MAX_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "2"))
MAX_NOTIONAL = float(os.getenv("MAX_NOTIONAL_FRACTION", "0.20"))

STOP_ATR = float(os.getenv("STOP_ATR_MULTIPLIER", "2"))
TAKE_R = float(os.getenv("TAKE_PROFIT_R_MULTIPLE", "2"))
FEE_RATE = float(os.getenv("PAPER_FEE_RATE", "0.001"))
SLIPPAGE = float(os.getenv("PAPER_SLIPPAGE", "0.0005"))

MIN_TRADE_VALUE = float(os.getenv("MIN_TRADE_VALUE", "10"))
MAX_ATR_PCT = float(os.getenv("MAX_ATR_PCT", "0.05"))
MIN_ATR_PCT = float(os.getenv("MIN_ATR_PCT", "0.001"))

USE_AI = os.getenv("USE_AI", "false").lower() == "true"
AI_KEY = os.getenv("OPENAI_API_KEY", "")
AI_MODEL = os.getenv("OPENAI_MODEL", "")

# En esta versión, testnet y live solo analizan.
# Ningún modo envía órdenes reales.
ALLOWED_MODES = {"paper", "testnet", "live"}
ALLOWED_MARKETS = {"spot", "futures"}

# =========================================================
# 2. REGISTROS
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)

log = logging.getLogger("TradingBot")


# =========================================================
# 3. VALIDACION
# =========================================================

def validate_config():
    if MODE not in ALLOWED_MODES:
        raise ValueError("TRADING_MODE debe ser paper, testnet o live.")

    if MARKET not in ALLOWED_MARKETS:
        raise ValueError("MARKET_TYPE debe ser spot o futures.")

    if not SYMBOLS:
        raise ValueError("Debes configurar al menos un símbolo.")

    if len(SYMBOLS) > 30:
        raise ValueError("Máximo 30 símbolos en esta versión.")

    if not 50 <= LOOKBACK <= 1000:
        raise ValueError("LOOKBACK debe estar entre 50 y 1000.")

    if POLL_SECONDS < 5:
        raise ValueError("POLL_SECONDS debe ser como mínimo 5.")

    if START_BALANCE <= 0:
        raise ValueError("El balance inicial debe ser positivo.")

    if not 0 < RISK_PER_TRADE <= 0.02:
        raise ValueError("RISK_PER_TRADE debe estar entre 0 y 0.02.")

    if not 0 < MAX_DAILY_LOSS <= 0.10:
        raise ValueError("MAX_DAILY_LOSS debe estar entre 0 y 0.10.")

    if MAX_POSITIONS < 1:
        raise ValueError("MAX_OPEN_POSITIONS debe ser al menos 1.")

    if not 0 < MAX_NOTIONAL <= 1:
        raise ValueError("MAX_NOTIONAL_FRACTION debe estar entre 0 y 1.")

    if STOP_ATR <= 0 or TAKE_R <= 0:
        raise ValueError("Los multiplicadores de stop y objetivo deben ser positivos.")

    if not 0 <= FEE_RATE < 0.05:
        raise ValueError("PAPER_FEE_RATE no es válido.")

    if not 0 <= SLIPPAGE < 0.05:
        raise ValueError("PAPER_SLIPPAGE no es válido.")

    if MIN_TRADE_VALUE <= 0:
        raise ValueError("MIN_TRADE_VALUE debe ser positivo.")

    if not 0 < MIN_ATR_PCT < MAX_ATR_PCT:
        raise ValueError("El rango de volatilidad no es válido.")

    if MODE == "live":
        log.warning(
            "Modo LIVE: las órdenes reales están desactivadas en este código."
        )

    if MODE == "testnet":
        if not os.getenv("BINANCE_API_KEY") or not os.getenv("BINANCE_API_SECRET"):
            raise ValueError("Configura las credenciales de testnet.")

    if USE_AI and (not AI_KEY or not AI_MODEL):
        raise ValueError("Configura OPENAI_API_KEY y OPENAI_MODEL para usar IA.")


# =========================================================
# 4. ESTRUCTURA DE SEÑALES
# =========================================================

@dataclass
class Signal:
    action: str
    price: float
    atr: float
    rsi: float
    reason: str


# =========================================================
# 5. DATOS DE BINANCE
# =========================================================

class Market:
    def __init__(self):
        self.client = Client(
            os.getenv("BINANCE_API_KEY") or None,
            os.getenv("BINANCE_API_SECRET") or None,
            requests_params={"timeout": 15},
        )

        # Los endpoints públicos de datos se mantienen públicos.
        # No se ejecutan órdenes en ningún modo.
        if MODE == "testnet":
            if MARKET == "futures":
                self.client.FUTURES_URL = (
                    "https://testnet.binancefuture.com/fapi"
                )
            else:
                self.client.API_URL = (
                    "https://testnet.binance.vision/api"
                )

    def candles(self, symbol):
        if MARKET == "futures":
            rows = self.client.futures_klines(
                symbol=symbol,
                interval=INTERVAL,
                limit=LOOKBACK,
            )
        else:
            rows = self.client.get_klines(
                symbol=symbol,
                interval=INTERVAL,
                limit=LOOKBACK,
            )

        if not rows:
            raise ValueError(f"Binance no devolvió velas para {symbol}.")

        columns = [
            "time", "open", "high", "low", "close",
            "volume", "close_time", "quote_volume",
            "trades", "taker_base", "taker_quote", "ignore",
        ]

        df = pd.DataFrame(rows, columns=columns)

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["time"] = pd.to_numeric(df["time"], errors="coerce")
        df["close_time"] = pd.to_numeric(df["close_time"], errors="coerce")

        df = df.dropna(
            subset=["time", "open", "high", "low", "close", "volume"]
        )

        if len(df) > 1:
            # Se descarta la última vela, que puede estar incompleta.
            df = df.iloc[:-1]

        if len(df) < 50:
            raise ValueError(f"Datos insuficientes para {symbol}.")

        if (df[["open", "high", "low", "close"]] <= 0).any().any():
            raise ValueError(f"Precios inválidos para {symbol}.")

        return df.reset_index(drop=True)


# =========================================================
# 6. INDICADORES TECNICOS
# =========================================================

def indicators(df):
    d = df.copy()
    close = d["close"]

    d["ema_fast"] = close.ewm(
        span=9, adjust=False
    ).mean()

    d["ema_slow"] = close.ewm(
        span=21, adjust=False
    ).mean()

    # EMA 50 como filtro de tendencia.
    d["ema_trend"] = close.ewm(
        span=50, adjust=False
    ).mean()

    # RSI de 14 periodos.
    change = close.diff()

    gain = change.clip(lower=0).ewm(
        alpha=1 / 14, adjust=False
    ).mean()

    loss = (-change.clip(upper=0)).ewm(
        alpha=1 / 14, adjust=False
    ).mean()

    rs = gain / loss.replace(0, float("nan"))
    d["rsi"] = 100 - (100 / (1 + rs))

    # ATR de 14 periodos.
    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            d["high"] - d["low"],
            (d["high"] - previous_close).abs(),
            (d["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    d["atr"] = true_range.ewm(
        alpha=1 / 14, adjust=False
    ).mean()

    d["atr_pct"] = d["atr"] / close

    # Volumen relativo: compara con las últimas 20 velas.
    d["volume_avg"] = d["volume"].rolling(20).mean()
    d["volume_ratio"] = d["volume"] / d["volume_avg"]

    return d.replace(
        [float("inf"), float("-inf")], float("nan")
    ).dropna().reset_index(drop=True)


# =========================================================
# 7. MOTOR DE ANALISIS
# =========================================================

def analyze(df):
    d = indicators(df)

    if len(d) < 55:
        return Signal(
            "HOLD", float(df["close"].iloc[-1]),
            0.0, 0.0, "Datos insuficientes para indicadores"
        )

    previous = d.iloc[-2]
    current = d.iloc[-1]

    price = float(current["close"])
    atr = float(current["atr"])
    rsi = float(current["rsi"])
    atr_pct = float(current["atr_pct"])
    volume_ratio = float(current["volume_ratio"])

    if min(price, atr) <= 0:
        return Signal("HOLD", price, atr, rsi, "Precio o ATR inválido")

    # Evita mercados con volatilidad excesivamente baja o alta.
    if not MIN_ATR_PCT <= atr_pct <= MAX_ATR_PCT:
        return Signal(
            "HOLD", price, atr, rsi,
            f"Volatilidad fuera del rango: {atr_pct:.2%}"
        )

    # No comprar si el mercado está bajo su EMA 50.
    trend_up = price > current["ema_trend"]
    trend_down = price < current["ema_trend"]

    bullish_cross = (
        previous["ema_fast"] <= previous["ema_slow"]
        and current["ema_fast"] > current["ema_slow"]
    )

    bearish_cross = (
        previous["ema_fast"] >= previous["ema_slow"]
        and current["ema_fast"] < current["ema_slow"]
    )

    # Volumen mínimo configurable para filtrar señales débiles.
    volume_ok = volume_ratio >= 0.8

    if bullish_cross and trend_up and 45 <= rsi <= 68 and volume_ok:
        return Signal(
            "BUY", price, atr, rsi,
            f"Cruce alcista, tendencia favorable, "
            f"RSI={rsi:.1f}, volumen relativo={volume_ratio:.2f}"
        )

    if bearish_cross and trend_down and 32 <= rsi <= 55 and volume_ok:
        return Signal(
            "SELL", price, atr, rsi,
            f"Cruce bajista, tendencia débil, "
            f"RSI={rsi:.1f}, volumen relativo={volume_ratio:.2f}"
        )

    return Signal(
        "HOLD", price, atr, rsi,
        f"Sin señal confirmada; RSI={rsi:.1f}"
    )


# =========================================================
# 8. GESTOR DE RIESGO
# =========================================================

class RiskManager:
    def __init__(self):
        self.day = datetime.now(timezone.utc).date()
        self.day_start = START_BALANCE
        self.halted = False

    def check(self, equity, positions):
        today = datetime.now(timezone.utc).date()

        if today != self.day:
            self.day = today
            self.day_start = equity
            self.halted = False
            log.info("Nuevo día UTC: se reinicia el control diario.")

        if self.halted:
            return False

        loss = max(0.0, self.day_start - equity)

        if self.day_start > 0 and loss / self.day_start >= MAX_DAILY_LOSS:
            self.halted = True
            log.error(
                "Límite de pérdida diario alcanzado. "
                "Se bloquean nuevas entradas."
            )
            return False

        return len(positions) < MAX_POSITIONS

    def quantity(self, equity, price, stop_distance):
        if min(equity, price, stop_distance) <= 0:
            return 0.0

        # Riesgo teórico si se ejecuta el stop al precio esperado.
        risk_amount = equity * RISK_PER_TRADE
        by_risk = risk_amount / stop_distance

        # Límite de exposición por posición.
        by_value = equity * MAX_NOTIONAL / price

        return max(0.0, min(by_risk, by_value))


# =========================================================
# 9. SIMULADOR DE OPERACIONES
# =========================================================

class PaperBroker:
    def __init__(self):
        # Spot: balance disponible en efectivo.
        # Futuros simulados: balance de margen.
        self.balance = START_BALANCE
        self.positions = {}
        self.trades = []

    def equity(self, prices):
        value = self.balance

        for symbol, p in self.positions.items():
            price = prices.get(symbol, p["entry"])

            if MARKET == "spot":
                value += p["qty"] * price
            else:
                direction = 1 if p["side"] == "LONG" else -1
                value += direction * (price - p["entry"]) * p["qty"]

        return value

    def open_position(self, symbol, side, qty, price, stop, take):
        if symbol in self.positions or qty <= 0 or price <= 0:
            return False

        if MARKET == "spot" and side != "LONG":
            return False

        notional = qty * price
        fee = notional * FEE_RATE

        if notional < MIN_TRADE_VALUE:
            return False

        if MARKET == "spot":
            required = notional + fee
            if required > self.balance:
                # Ajustar a la cantidad que puede financiarse.
                qty = self.balance / (price * (1 + FEE_RATE))
                notional = qty * price
                fee = notional * FEE_RATE

            if qty * price < MIN_TRADE_VALUE:
                return False

            self.balance -= notional + fee

        else:
            # El simulador de futuros usa margen simplificado sin
            # apalancamiento: no representa liquidaciones reales.
            if notional + fee > self.balance:
                return False

            self.balance -= fee

        self.positions[symbol] = {
            "side": side,
            "qty": qty,
            "entry": price,
            "stop": stop,
            "take": take,
            "entry_fee": fee,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }

        log.info(
            "APERTURA SIMULADA %s %s | cantidad=%.8f | precio=%.8f "
            "| stop=%.8f | objetivo=%.8f",
            symbol, side, qty, price, stop, take
        )

        return True

    def close_position(self, symbol, price, reason):
        p = self.positions.get(symbol)

        if not p or price <= 0:
            return

        # Simula deslizamiento desfavorable al salir.
        if p["side"] == "LONG":
            exit_price = price * (1 - SLIPPAGE)
            direction = 1
        else:
            exit_price = price * (1 + SLIPPAGE)
            direction = -1

        notional = p["qty"] * exit_price
        exit_fee = notional * FEE_RATE
        gross_pnl = direction * (exit_price - p["entry"]) * p["qty"]

        if MARKET == "spot":
            self.balance += notional - exit_fee
        else:
            self.balance += gross_pnl - exit_fee

        net_pnl = gross_pnl - p["entry_fee"] - exit_fee

        trade = {
            "symbol": symbol,
            "side": p["side"],
            "entry": p["entry"],
            "exit": exit_price,
            "qty": p["qty"],
            "gross_pnl": gross_pnl,
            "fees": p["entry_fee"] + exit_fee,
            "net_pnl": net_pnl,
            "reason": reason,
            "opened_at": p["opened_at"],
            "closed_at": datetime.now(timezone.utc).isoformat(),
        }

        self.trades.append(trade)
        del self.positions[symbol]

        log.info(
            "CIERRE SIMULADO %s | motivo=%s | resultado neto=%.4f",
            symbol, reason, net_pnl
        )

    def manage(self, symbol, price):
        p = self.positions.get(symbol)

        if not p:
            return

        if p["side"] == "LONG":
            if price <= p["stop"]:
                self.close_position(symbol, p["stop"], "STOP")
            elif price >= p["take"]:
                self.close_position(symbol, p["take"], "TAKE")

        else:
            if price >= p["stop"]:
                self.close_position(symbol, p["stop"], "STOP")
            elif price <= p["take"]:
                self.close_position(symbol, p["take"], "TAKE")

    def save_trades(self):
        if not self.trades:
            return

        df = pd.DataFrame(self.trades)
        df.to_csv("trades.csv", index=False, encoding="utf-8")


# =========================================================
# 10. REVISION OPCIONAL CON IA
# =========================================================

def ai_review(symbol, sig):
    if not USE_AI:
        return True

    try:
        from openai import OpenAI

        client = OpenAI(api_key=AI_KEY, timeout=20.0, max_retries=1)

        response = client.responses.create(
            model=AI_MODEL,
            instructions=(
                "Eres un revisor prudente de señales de trading. "
                "No predigas el futuro ni inventes datos. "
                "Evalúa solo los datos proporcionados. "
                "Responde exactamente ALLOW o BLOCK. "
                "Si existe incertidumbre, responde BLOCK."
            ),
            input=(
                f"Símbolo: {symbol}\n"
                f"Acción: {sig.action}\n"
                f"Precio: {sig.price}\n"
                f"ATR: {sig.atr}\n"
                f"RSI: {sig.rsi}\n"
                f"Motivo: {sig.reason}"
            ),
        )

        decision = response.output_text.strip().upper()
        return decision == "ALLOW"

    except Exception as exc:
        # Si la IA falla, se bloquea la nueva entrada.
        log.warning("IA no disponible; entrada bloqueada: %s", exc)
        return False


# =========================================================
# 11. CICLO PRINCIPAL
# =========================================================

def main():
    validate_config()

    log.info(
        "Bot iniciado | modo=%s | mercado=%s | símbolos=%s",
        MODE, MARKET, SYMBOLS
    )

    market = Market()
    broker = PaperBroker() if MODE == "paper" else None
    risk = RiskManager()

    while True:
        cycle_start = time.monotonic()
        prices = {}
        signals = {}

        for symbol in SYMBOLS:
            try:
                df = market.candles(symbol)
                sig = analyze(df)

                prices[symbol] = sig.price
                signals[symbol] = sig

                log.info(
                    "%s | %s | precio=%.8f | RSI=%.1f | %s",
                    symbol, sig.action, sig.price, sig.rsi, sig.reason
                )

            except Exception:
                log.exception("No se pudo analizar %s", symbol)

        if MODE == "paper" and broker is not None:
            # Primero se actualizan las posiciones existentes.
            for symbol, price in prices.items():
                broker.manage(symbol, price)

            equity = broker.equity(prices)
            can_open = risk.check(equity, broker.positions)

            if can_open:
                for symbol, sig in signals.items():
                    if symbol in broker.positions:
                        # Una señal opuesta cierra la posición.
                        p = broker.positions[symbol]

                        if p["side"] == "LONG" and sig.action == "SELL":
                            broker.close_position(symbol, sig.price, "SIGNAL")
                        elif p["side"] == "SHORT" and sig.action == "BUY":
                            broker.close_position(symbol, sig.price, "SIGNAL")

                        continue

                    if sig.action not in ("BUY", "SELL"):
                        continue

                    # En Spot no se abren cortos.
                    if MARKET == "spot" and sig.action == "SELL":
                        continue

                    if len(broker.positions) >= MAX_POSITIONS:
                        break

                    if not ai_review(symbol, sig):
                        log.info("%s: señal bloqueada por IA.", symbol)
                        continue

                    stop_distance = sig.atr * STOP_ATR

                    qty = risk.quantity(
                        equity, sig.price, stop_distance
                    )

                    if qty * sig.price < MIN_TRADE_VALUE:
                        continue

                    if sig.action == "BUY":
                        side = "LONG"
                        stop = sig.price - stop_distance
                        take = sig.price + stop_distance * TAKE_R
                    else:
                        side = "SHORT"
                        stop = sig.price + stop_distance
                        take = sig.price - stop_distance * TAKE_R

                    if stop <= 0 or take <= 0:
                        log.warning("%s: stop u objetivo inválido.", symbol)
                        continue

                    broker.open_position(
                        symbol, side, qty, sig.price, stop, take
                    )

            log.info(
                "PAPER | efectivo/margen=%.2f | equity=%.2f "
                "| posiciones=%d | operaciones cerradas=%d",
                broker.balance,
                broker.equity(prices),
                len(broker.positions),
                len(broker.trades),
            )

            broker.save_trades()

        else:
            log.info(
                "ANÁLISIS SOLAMENTE: modo=%s. No se envían órdenes.",
                MODE
            )

        elapsed = time.monotonic() - cycle_start
        time.sleep(max(5, POLL_SECONDS - elapsed))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Bot detenido manualmente.")
    except Exception:
        log.exception("Error fatal; revisa la configuración.")
