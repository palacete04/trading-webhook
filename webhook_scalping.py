"""
SERVIDOR WEBHOOK — Multi-activo con proteccion de ordenes duplicadas
TradingView -> Render -> Alpaca
"""

import os
import threading
from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
from datetime import datetime

# ─────────────────────────────────────────
# CONFIGURACION
# ─────────────────────────────────────────
API_KEY     = os.environ.get("API_KEY")
API_SECRET  = os.environ.get("API_SECRET")
BASE_URL    = os.environ.get("BASE_URL", "https://paper-api.alpaca.markets")
TOKEN       = os.environ.get("TOKEN", "MI_TOKEN_SECRETO")
SYMBOL      = os.environ.get("SYMBOL", "SPY")
PCT_CAPITAL = float(os.environ.get("PCT_CAPITAL", "20"))

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')
app = Flask(__name__)

# Lock por simbolo para evitar ordenes duplicadas simultaneas
locks = {}
locks_mutex = threading.Lock()

def get_lock(symbol):
    with locks_mutex:
        if symbol not in locks:
            locks[symbol] = threading.Lock()
        return locks[symbol]

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

def hay_orden_pendiente(symbol):
    """Verifica si hay ordenes abiertas para este simbolo."""
    try:
        ordenes = api.list_orders(status='open', symbols=[symbol])
        return len(ordenes) > 0
    except:
        return False

def calcular_qty_symbol(symbol):
    """Calcula cantidad de acciones segun % del capital disponible."""
    cuenta = api.get_account()
    capital = float(cuenta.cash)
    precio  = float(api.get_latest_trade(symbol).price)
    qty = int((capital * PCT_CAPITAL / 100) / precio)
    return max(qty, 1)

def calcular_qty():
    return calcular_qty_symbol(SYMBOL)

# ─────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    try:
        cuenta = api.get_account()
        return jsonify({
            "status": "ok",
            "symbol": SYMBOL,
            "balance": float(cuenta.cash),
            "posicion_actual": tengo_posicion()
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

    # Usar lock por simbolo para evitar ejecuciones simultaneas
    lock = get_lock(symbol)
    if not lock.acquire(blocking=False):
        log(f"Orden en proceso para {symbol}, ignorando duplicado")
        return jsonify({"status": "Orden en proceso, ignorado"}), 200

    try:
        # Verificar posicion Y ordenes pendientes
        posicion = tengo_posicion_symbol(symbol)
        orden_pendiente = hay_orden_pendiente(symbol)

        if accion == "COMPRAR" and posicion == 0 and not orden_pendiente:
            qty = calcular_qty_symbol(symbol)
            api.submit_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                type="market",
                time_in_force="day"
            )
            log(f"COMPRA ejecutada — {qty} x {symbol}")
            return jsonify({"status": "Compra ejecutada", "qty": qty, "symbol": symbol}), 200

        elif accion == "VENDER" and posicion > 0 and not orden_pendiente:
            api.submit_order(
                symbol=symbol,
                qty=posicion,
                side="sell",
                type="market",
                time_in_force="day"
            )
            log(f"VENTA ejecutada — {posicion} x {symbol}")
            return jsonify({"status": "Venta ejecutada", "qty": posicion, "symbol": symbol}), 200

        else:
            log(f"Sin accion (accion={accion}, symbol={symbol}, posicion={posicion}, pendiente={orden_pendiente})")
            return jsonify({"status": "Sin accion necesaria"}), 200

    except Exception as e:
        log(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        lock.release()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log(f"Servidor iniciado — {SYMBOL} | Capital por trade: {PCT_CAPITAL}%")
    app.run(host="0.0.0.0", port=port)
