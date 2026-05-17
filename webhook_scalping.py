"""
SERVIDOR WEBHOOK — Multi-activo con protecciones avanzadas
TradingView -> Render -> Alpaca
Mejoras: Stop Loss, Trailing Stop, Filtro de tendencia, Anti-duplicados via Alpaca
"""

import os
import threading
import time
from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
from datetime import datetime

# ─────────────────────────────────────────
# CONFIGURACION
# ─────────────────────────────────────────
API_KEY           = os.environ.get("API_KEY")
API_SECRET        = os.environ.get("API_SECRET")
BASE_URL          = os.environ.get("BASE_URL", "https://paper-api.alpaca.markets")
TOKEN             = os.environ.get("TOKEN", "MI_TOKEN_SECRETO")
SYMBOL            = os.environ.get("SYMBOL", "SPY")
PCT_CAPITAL       = float(os.environ.get("PCT_CAPITAL", "20"))
STOP_LOSS_PCT     = float(os.environ.get("STOP_LOSS_PCT", "1.0"))
TRAILING_STOP_PCT = float(os.environ.get("TRAILING_STOP_PCT", "0.5"))

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')
app = Flask(__name__)

max_prices = {}

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def tengo_posicion_symbol(symbol):
    try:
        pos = api.get_position(symbol)
        return int(float(pos.qty))
    except:
        return 0

def tengo_posicion():
    return tengo_posicion_symbol(SYMBOL)

def hay_orden_abierta(symbol):
    """Verifica en Alpaca si hay ordenes abiertas O posicion existente."""
    try:
        # Verificar ordenes abiertas
        ordenes = api.list_orders(status='open')
        for orden in ordenes:
            if orden.symbol == symbol:
                return True
        return False
    except:
        return False

def puede_comprar(symbol):
    """Doble verificacion: sin posicion Y sin ordenes abiertas."""
    posicion = tengo_posicion_symbol(symbol)
    orden_abierta = hay_orden_abierta(symbol)
    if posicion > 0:
        log(f"Ya tengo posicion en {symbol} ({posicion} acciones), no compro")
        return False
    if orden_abierta:
        log(f"Ya hay orden abierta para {symbol}, no compro")
        return False
    return True

def puede_vender(symbol):
    """Verificacion: tengo posicion Y sin ordenes de venta abiertas."""
    posicion = tengo_posicion_symbol(symbol)
    if posicion == 0:
        return False
    orden_abierta = hay_orden_abierta(symbol)
    if orden_abierta:
        log(f"Ya hay orden abierta para {symbol}, no vendo")
        return False
    return True

def calcular_qty_symbol(symbol):
    """Calcula UNA sola cantidad basada en el capital disponible."""
    cuenta = api.get_account()
    capital = float(cuenta.cash)
    precio  = float(api.get_latest_trade(symbol).price)
    qty = int((capital * PCT_CAPITAL / 100) / precio)
    return max(qty, 1)

def precio_actual(symbol):
    try:
        return float(api.get_latest_trade(symbol).price)
    except:
        return 0

def mercado_alcista(symbol):
    """Filtro de tendencia: EMA50 > EMA200."""
    try:
        barras = api.get_bars(symbol, tradeapi.TimeFrame.Day, limit=200).df
        if len(barras) < 200:
            return True
        ema50  = barras['close'].ewm(span=50).mean().iloc[-1]
        ema200 = barras['close'].ewm(span=200).mean().iloc[-1]
        return ema50 > ema200
    except:
        return True

def verificar_stops(symbol):
    """Verifica stop loss y trailing stop."""
    try:
        pos = api.get_position(symbol)
        qty = int(float(pos.qty))
        if qty == 0:
            return
        if hay_orden_abierta(symbol):
            return

        precio_entrada = float(pos.avg_entry_price)
        precio_now     = precio_actual(symbol)
        if precio_now == 0:
            return

        if symbol not in max_prices or precio_now > max_prices[symbol]:
            max_prices[symbol] = precio_now

        stop_loss_precio = precio_entrada * (1 - STOP_LOSS_PCT / 100)
        if precio_now <= stop_loss_precio:
            log(f"STOP LOSS activado {symbol} — precio {precio_now:.2f}")
            api.submit_order(symbol=symbol, qty=qty, side="sell", type="market", time_in_force="day")
            max_prices.pop(symbol, None)
            return

        trailing_precio = max_prices[symbol] * (1 - TRAILING_STOP_PCT / 100)
        if precio_now <= trailing_precio:
            ganancia = (precio_now - precio_entrada) * qty
            log(f"TRAILING STOP activado {symbol} — ganancia bloqueada: ${ganancia:.2f}")
            api.submit_order(symbol=symbol, qty=qty, side="sell", type="market", time_in_force="day")
            max_prices.pop(symbol, None)

    except Exception as e:
        log(f"Error stops {symbol}: {e}")

def monitor_stops():
    simbolos = ["SPY", "QQQ", "IWM"]
    while True:
        try:
            clock = api.get_clock()
            if clock.is_open:
                for sym in simbolos:
                    if tengo_posicion_symbol(sym) > 0:
                        verificar_stops(sym)
            time.sleep(60)
        except:
            time.sleep(60)

stop_thread = threading.Thread(target=monitor_stops, daemon=True)
stop_thread.start()

# ─────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    try:
        cuenta = api.get_account()
        posiciones = {}
        for sym in ["SPY", "QQQ", "IWM"]:
            qty = tengo_posicion_symbol(sym)
            if qty > 0:
                posiciones[sym] = qty
        return jsonify({
            "status": "ok",
            "balance": float(cuenta.cash),
            "posiciones": posiciones,
            "stop_loss_pct": STOP_LOSS_PCT,
            "trailing_stop_pct": TRAILING_STOP_PCT
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    if not data or data.get("token") != TOKEN:
        log("Token invalido")
        return jsonify({"error": "No autorizado"}), 403

    accion = data.get("accion", "").upper()
    symbol = data.get("symbol", SYMBOL).upper()
    log(f"Alerta recibida: {accion} {symbol}")

    try:
        if accion == "COMPRAR":
            if not puede_comprar(symbol):
                return jsonify({"status": "Compra bloqueada — ya hay posicion u orden"}), 200

            if not mercado_alcista(symbol):
                log(f"Mercado bajista para {symbol}, compra bloqueada")
                return jsonify({"status": "Mercado bajista, compra bloqueada"}), 200

            qty = calcular_qty_symbol(symbol)
            api.submit_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                type="market",
                time_in_force="day"
            )
            max_prices[symbol] = precio_actual(symbol)
            log(f"COMPRA ejecutada — {qty} x {symbol}")
            return jsonify({"status": "Compra ejecutada", "qty": qty, "symbol": symbol}), 200

        elif accion == "VENDER":
            if not puede_vender(symbol):
                return jsonify({"status": "Venta bloqueada — sin posicion o ya hay orden"}), 200

            posicion = tengo_posicion_symbol(symbol)
            api.submit_order(
                symbol=symbol,
                qty=posicion,
                side="sell",
                type="market",
                time_in_force="day"
            )
            max_prices.pop(symbol, None)
            log(f"VENTA ejecutada — {posicion} x {symbol}")
            return jsonify({"status": "Venta ejecutada", "qty": posicion, "symbol": symbol}), 200

        else:
            return jsonify({"status": "Accion no reconocida"}), 200

    except Exception as e:
        log(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log(f"Servidor iniciado — Stop Loss: {STOP_LOSS_PCT}% | Trailing Stop: {TRAILING_STOP_PCT}%")
    app.run(host="0.0.0.0", port=port)
