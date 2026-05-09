"""
SERVIDOR WEBHOOK — Scalping 5min
TradingView → Railway → Alpaca
"""

import os
from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
from datetime import datetime

# ─────────────────────────────────────────
# CONFIGURACIÓN (variables de entorno en Railway)
# ─────────────────────────────────────────
API_KEY    = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
BASE_URL   = os.environ.get("BASE_URL", "https://paper-api.alpaca.markets")
TOKEN      = os.environ.get("TOKEN", "MI_TOKEN_SECRETO")
SYMBOL     = os.environ.get("SYMBOL", "SPY")

# Scalping: % del capital por operación (ej: 10% = bajo riesgo por trade)
PCT_CAPITAL = float(os.environ.get("PCT_CAPITAL", "10"))

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')
app = Flask(__name__)

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

def calcular_qty_symbol(symbol):
    """Calcula cantidad de acciones según % del capital disponible."""
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
    cuenta = api.get_account()
    return jsonify({
        "status": "ok",
        "symbol": SYMBOL,
        "balance": float(cuenta.cash),
        "posicion_actual": tengo_posicion()
    }), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    if not data or data.get("token") != TOKEN:
        log("❌ Token inválido")
        return jsonify({"error": "No autorizado"}), 403

    accion  = data.get("accion", "").upper()
    symbol  = data.get("symbol", SYMBOL).upper()
    log(f"📩 Alerta recibida: {accion} {symbol}")

    try:
        posicion = tengo_posicion_symbol(symbol)

        if accion == "COMPRAR" and posicion == 0:
            qty = calcular_qty_symbol(symbol)
            api.submit_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                type="market",
                time_in_force="day"
            )
            log(f"✅ COMPRA ejecutada — {qty} x {symbol}")
            return jsonify({"status": "Compra ejecutada", "qty": qty, "symbol": symbol}), 200

        elif accion == "VENDER" and posicion > 0:
            api.submit_order(
                symbol=symbol,
                qty=posicion,
                side="sell",
                type="market",
                time_in_force="day"
            )
            log(f"✅ VENTA ejecutada — {posicion} x {symbol}")
            return jsonify({"status": "Venta ejecutada", "qty": posicion, "symbol": symbol}), 200

        else:
            log(f"⏸  Sin accion (accion={accion}, symbol={symbol}, posicion={posicion})")
            return jsonify({"status": "Sin accion necesaria"}), 200

    except Exception as e:
        log(f"❌ Error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log(f"Servidor iniciado — {SYMBOL} | Capital por trade: {PCT_CAPITAL}%")
    app.run(host="0.0.0.0", port=port)
