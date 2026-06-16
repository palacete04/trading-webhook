"""
SERVIDOR WEBHOOK — Multi-activo con protecciones avanzadas
TradingView -> Render -> Alpaca
v3: Fix cantidades fijas + max 1 simbolo a la vez + notificaciones Telegram + auto-adjust
"""

import os
import threading
import time
from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
from datetime import datetime
import requests

API_KEY           = os.environ.get("API_KEY")
API_SECRET        = os.environ.get("API_SECRET")
BASE_URL          = os.environ.get("BASE_URL", "https://paper-api.alpaca.markets")
TOKEN             = os.environ.get("TOKEN", "MI_TOKEN_SECRETO")
SYMBOL            = os.environ.get("SYMBOL", "SPY")
PCT_CAPITAL       = float(os.environ.get("PCT_CAPITAL", "20"))
STOP_LOSS_PCT     = float(os.environ.get("STOP_LOSS_PCT", "1.0"))
TAKE_PROFIT_PCT   = float(os.environ.get("TAKE_PROFIT_PCT", "2.0"))
TRAILING_STOP_PCT = float(os.environ.get("TRAILING_STOP_PCT", "0.5"))
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "8957492846:AAGophSxXOSZGT4Gd1cLTNOICzxpZIH5wEU")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "-5246245037")

SIMBOLOS = ["SPY", "QQQ", "IWM"]

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')
app = Flask(__name__)

max_prices = {}
qty_abierta = {}

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Error Telegram: {e}")

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def tengo_posicion_symbol(symbol):
    try:
        pos = api.get_position(symbol)
        return int(float(pos.qty))
    except:
        return 0

def hay_posicion_abierta_cualquier_simbolo():
    for sym in SIMBOLOS:
        if tengo_posicion_symbol(sym) > 0:
            return True, sym
    return False, None

def hay_orden_abierta(symbol):
    try:
        ordenes = api.list_orders(status='open')
        for orden in ordenes:
            if orden.symbol == symbol:
                return True
        return False
    except:
        return False

def puede_comprar(symbol):
    if tengo_posicion_symbol(symbol) > 0:
        return False
    hay_pos, sym_abierto = hay_posicion_abierta_cualquier_simbolo()
    if hay_pos:
        return False
    if hay_orden_abierta(symbol):
        return False
    return True

def puede_vender(symbol):
    posicion = tengo_posicion_symbol(symbol)
    if posicion == 0:
        return False
    if hay_orden_abierta(symbol):
        return False
    return True

def calcular_qty_symbol(symbol):
    cuenta = api.get_account()
    capital = float(cuenta.equity)
    precio  = float(api.get_latest_trade(symbol).price)
    qty = int((capital * PCT_CAPITAL / 100) / precio)
    return max(qty, 1)

def precio_actual(symbol):
    try:
        return float(api.get_latest_trade(symbol).price)
    except:
        return 0

def mercado_alcista(symbol):
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

        take_profit_precio = precio_entrada * (1 + TAKE_PROFIT_PCT / 100)
        if precio_now >= take_profit_precio:
            ganancia = (precio_now - precio_entrada) * qty
            api.submit_order(symbol=symbol, qty=qty, side="sell", type="market", time_in_force="day")
            send_telegram(f"✅ TAKE PROFIT {symbol}\nEntrada: ${precio_entrada:.2f} → Salida: ${precio_now:.2f}\nGanancia: ${ganancia:.2f}")
            max_prices.pop(symbol, None)
            qty_abierta.pop(symbol, None)
            return

        stop_loss_precio = precio_entrada * (1 - STOP_LOSS_PCT / 100)
        if precio_now <= stop_loss_precio:
            perdida = (precio_now - precio_entrada) * qty
            api.submit_order(symbol=symbol, qty=qty, side="sell", type="market", time_in_force="day")
            send_telegram(f"❌ STOP LOSS {symbol}\nEntrada: ${precio_entrada:.2f} → Salida: ${precio_now:.2f}\nPerdida: ${perdida:.2f}")
            max_prices.pop(symbol, None)
            qty_abierta.pop(symbol, None)
            return

        trailing_precio = max_prices[symbol] * (1 - TRAILING_STOP_PCT / 100)
        if precio_now <= trailing_precio:
            ganancia = (precio_now - precio_entrada) * qty
            api.submit_order(symbol=symbol, qty=qty, side="sell", type="market", time_in_force="day")
            send_telegram(f"🔒 TRAILING STOP {symbol}\nEntrada: ${precio_entrada:.2f} → Salida: ${precio_now:.2f}\nResultado: ${ganancia:.2f}")
            max_prices.pop(symbol, None)
            qty_abierta.pop(symbol, None)

    except Exception as e:
        log(f"Error stops {symbol}: {e}")

def monitor_stops():
    while True:
        try:
            clock = api.get_clock()
            if clock.is_open:
                for sym in SIMBOLOS:
                    if tengo_posicion_symbol(sym) > 0:
                        verificar_stops(sym)
            time.sleep(60)
        except:
            time.sleep(60)

stop_thread = threading.Thread(target=monitor_stops, daemon=True)
stop_thread.start()

@app.route("/", methods=["GET"])
def health():
    try:
        cuenta = api.get_account()
        posiciones = {}
        for sym in SIMBOLOS:
            qty = tengo_posicion_symbol(sym)
            if qty > 0:
                posiciones[sym] = qty
        return jsonify({
            "status": "ok",
            "balance": float(cuenta.cash),
            "equity": float(cuenta.equity),
            "posiciones": posiciones,
            "stop_loss_pct": STOP_LOSS_PCT,
            "take_profit_pct": TAKE_PROFIT_PCT,
            "trailing_stop_pct": TRAILING_STOP_PCT
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    global PCT_CAPITAL
    data = request.json

    if not data or data.get("token") != TOKEN:
        return jsonify({"error": "No autorizado"}), 403

    accion = data.get("accion", "").upper()
    symbol = data.get("symbol", SYMBOL).upper()
    log(f"Alerta recibida: {accion} {symbol}")

    try:
        if accion == "COMPRAR":
            if not puede_comprar(symbol):
                hay_pos, sym_abierto = hay_posicion_abierta_cualquier_simbolo()
                razon = f"Posicion abierta en {sym_abierto}" if hay_pos else "Bloqueado"
                return jsonify({"status": f"Compra bloqueada — {razon}"}), 200

            if not mercado_alcista(symbol):
                return jsonify({"status": "Mercado bajista, compra bloqueada"}), 200

            qty = calcular_qty_symbol(symbol)
            precio = precio_actual(symbol)
            api.submit_order(symbol=symbol, qty=qty, side="buy", type="market", time_in_force="day")
            max_prices[symbol] = precio
            qty_abierta[symbol] = qty

            msg = (f"📈 COMPRA {symbol}\n"
                   f"Qty: {qty} acciones\n"
                   f"Precio aprox: ${precio:.2f}\n"
                   f"Capital usado: ~${qty * precio:,.0f} ({PCT_CAPITAL}%)\n"
                   f"SL: ${precio * (1 - STOP_LOSS_PCT/100):.2f} | TP: ${precio * (1 + TAKE_PROFIT_PCT/100):.2f}")
            send_telegram(msg)
            return jsonify({"status": "Compra ejecutada", "qty": qty, "symbol": symbol}), 200

        elif accion == "VENDER":
            if not puede_vender(symbol):
                return jsonify({"status": "Venta bloqueada — sin posicion"}), 200

            posicion = tengo_posicion_symbol(symbol)
            precio = precio_actual(symbol)

            try:
                pos = api.get_position(symbol)
                precio_entrada = float(pos.avg_entry_price)
                resultado = (precio - precio_entrada) * posicion
                resultado_str = f"Resultado: ${resultado:+.2f}"
            except:
                resultado_str = ""

            api.submit_order(symbol=symbol, qty=posicion, side="sell", type="market", time_in_force="day")
            max_prices.pop(symbol, None)
            qty_abierta.pop(symbol, None)

            emoji = "✅" if "+" in resultado_str else "❌"
            msg = (f"{emoji} VENTA {symbol}\nQty: {posicion}\nPrecio: ${precio:.2f}\n{resultado_str}")
            send_telegram(msg)
            return jsonify({"status": "Venta ejecutada", "qty": posicion, "symbol": symbol}), 200

        else:
            return jsonify({"status": "Accion no reconocida"}), 200

    except Exception as e:
        send_telegram(f"⚠️ Error en webhook {symbol}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/adjust", methods=["POST"])
def adjust_params():
    global STOP_LOSS_PCT, TAKE_PROFIT_PCT, TRAILING_STOP_PCT, PCT_CAPITAL

    data = request.json
    if not data or data.get("token") != TOKEN:
        return jsonify({"error": "No autorizado"}), 403

    cambios = []

    if "stop_loss_pct" in data:
        STOP_LOSS_PCT = float(data["stop_loss_pct"])
        cambios.append(f"SL: {STOP_LOSS_PCT}%")

    if "take_profit_pct" in data:
        TAKE_PROFIT_PCT = float(data["take_profit_pct"])
        cambios.append(f"TP: {TAKE_PROFIT_PCT}%")

    if "trailing_stop_pct" in data:
        TRAILING_STOP_PCT = float(data["trailing_stop_pct"])
        cambios.append(f"Trailing: {TRAILING_STOP_PCT}%")

    if "pct_capital" in data:
        PCT_CAPITAL = float(data["pct_capital"])
        cambios.append(f"Capital: {PCT_CAPITAL}%")

    if cambios:
        msg = f"⚙️ Parámetros ajustados automáticamente:\n"
        msg += "\n".join(f"  - {c}" for c in cambios)
        send_telegram(msg)

    return jsonify({
        "status": "ok",
        "params": {
            "stop_loss_pct": STOP_LOSS_PCT,
            "take_profit_pct": TAKE_PROFIT_PCT,
            "trailing_stop_pct": TRAILING_STOP_PCT,
            "pct_capital": PCT_CAPITAL
        }
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log(f"Servidor iniciado — SL: {STOP_LOSS_PCT}% | TP: {TAKE_PROFIT_PCT}% | TS: {TRAILING_STOP_PCT}%")
    send_telegram(f"🚀 Webhook Alpaca iniciado\nSL: {STOP_LOSS_PCT}% | TP: {TAKE_PROFIT_PCT}% | TS: {TRAILING_STOP_PCT}%\nSimbolos: {', '.join(SIMBOLOS)}")
    app.run(host="0.0.0.0", port=port)
