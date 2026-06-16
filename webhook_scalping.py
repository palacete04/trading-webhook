"""
SERVIDOR WEBHOOK — Multi-activo con protecciones avanzadas
TradingView -> Render -> Alpaca
v4: Migrado a alpaca-py + auto-adjust
"""

import os
import threading
import time
from flask import Flask, request, jsonify
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import requests

API_KEY           = os.environ.get("API_KEY")
API_SECRET        = os.environ.get("API_SECRET")
TOKEN             = os.environ.get("TOKEN", "MI_TOKEN_SECRETO")
SYMBOL            = os.environ.get("SYMBOL", "SPY")
PCT_CAPITAL       = float(os.environ.get("PCT_CAPITAL", "20"))
STOP_LOSS_PCT     = float(os.environ.get("STOP_LOSS_PCT", "1.0"))
TAKE_PROFIT_PCT   = float(os.environ.get("TAKE_PROFIT_PCT", "2.0"))
TRAILING_STOP_PCT = float(os.environ.get("TRAILING_STOP_PCT", "0.5"))
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "8957492846:AAGophSxXOSZGT4Gd1cLTNOICzxpZIH5wEU")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "-5246245037")

SIMBOLOS = ["SPY", "QQQ", "IWM"]

trading_client = TradingClient(API_KEY, API_SECRET, paper=True)
data_client    = StockHistoricalDataClient(API_KEY, API_SECRET)
app = Flask(__name__)

max_prices  = {}
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
        pos = trading_client.get_open_position(symbol)
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
        filtro = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        ordenes = trading_client.get_orders(filtro)
        return len(ordenes) > 0
    except:
        return False

def puede_comprar(symbol):
    if tengo_posicion_symbol(symbol) > 0:
        return False
    hay_pos, _ = hay_posicion_abierta_cualquier_simbolo()
    if hay_pos:
        return False
    if hay_orden_abierta(symbol):
        return False
    return True

def puede_vender(symbol):
    if tengo_posicion_symbol(symbol) == 0:
        return False
    if hay_orden_abierta(symbol):
        return False
    return True

def precio_actual(symbol):
    try:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=datetime.now() - timedelta(minutes=5)
        )
        bars = data_client.get_stock_bars(req)
        return float(bars[symbol][-1].close)
    except:
        return 0

def calcular_qty_symbol(symbol):
    cuenta = trading_client.get_account()
    capital = float(cuenta.equity)
    precio  = precio_actual(symbol)
    if precio == 0:
        return 1
    qty = int((capital * PCT_CAPITAL / 100) / precio)
    return max(qty, 1)

def mercado_alcista(symbol):
    try:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=210)
        )
        bars = data_client.get_stock_bars(req)
        closes = [b.close for b in bars[symbol]]
        if len(closes) < 200:
            return True
        ema50  = sum(closes[-50:])  / 50
        ema200 = sum(closes[-200:]) / 200
        return ema50 > ema200
    except:
        return True

def verificar_stops(symbol):
    try:
        pos = trading_client.get_open_position(symbol)
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

        # Take Profit
        if precio_now >= precio_entrada * (1 + TAKE_PROFIT_PCT / 100):
            ganancia = (precio_now - precio_entrada) * qty
            orden = MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
            trading_client.submit_order(orden)
            send_telegram(f"✅ TAKE PROFIT {symbol}\nEntrada: ${precio_entrada:.2f} → Salida: ${precio_now:.2f}\nGanancia: ${ganancia:.2f}")
            max_prices.pop(symbol, None)
            return

        # Stop Loss
        if precio_now <= precio_entrada * (1 - STOP_LOSS_PCT / 100):
            perdida = (precio_now - precio_entrada) * qty
            orden = MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
            trading_client.submit_order(orden)
            send_telegram(f"❌ STOP LOSS {symbol}\nEntrada: ${precio_entrada:.2f} → Salida: ${precio_now:.2f}\nPerdida: ${perdida:.2f}")
            max_prices.pop(symbol, None)
            return

        # Trailing Stop
        if precio_now <= max_prices[symbol] * (1 - TRAILING_STOP_PCT / 100):
            ganancia = (precio_now - precio_entrada) * qty
            orden = MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
            trading_client.submit_order(orden)
            send_telegram(f"🔒 TRAILING STOP {symbol}\nEntrada: ${precio_entrada:.2f} → Salida: ${precio_now:.2f}\nResultado: ${ganancia:.2f}")
            max_prices.pop(symbol, None)

    except Exception as e:
        log(f"Error stops {symbol}: {e}")

def monitor_stops():
    while True:
        try:
            clock = trading_client.get_clock()
            if clock.is_open:
                for sym in SIMBOLOS:
                    if tengo_posicion_symbol(sym) > 0:
                        verificar_stops(sym)
            time.sleep(60)
        except:
            time.sleep(60)

threading.Thread(target=monitor_stops, daemon=True).start()

@app.route("/", methods=["GET"])
def health():
    try:
        cuenta = trading_client.get_account()
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

            qty    = calcular_qty_symbol(symbol)
            precio = precio_actual(symbol)
            orden  = MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
            trading_client.submit_order(orden)
            max_prices[symbol]  = precio
            qty_abierta[symbol] = qty

            send_telegram(f"📈 COMPRA {symbol}\nQty: {qty}\nPrecio: ${precio:.2f}\nCapital: ~${qty*precio:,.0f} ({PCT_CAPITAL}%)\nSL: ${precio*(1-STOP_LOSS_PCT/100):.2f} | TP: ${precio*(1+TAKE_PROFIT_PCT/100):.2f}")
            return jsonify({"status": "Compra ejecutada", "qty": qty, "symbol": symbol}), 200

        elif accion == "VENDER":
            if not puede_vender(symbol):
                return jsonify({"status": "Venta bloqueada — sin posicion"}), 200

            posicion = tengo_posicion_symbol(symbol)
            precio   = precio_actual(symbol)

            try:
                pos = trading_client.get_open_position(symbol)
                precio_entrada = float(pos.avg_entry_price)
                resultado = (precio - precio_entrada) * posicion
                resultado_str = f"Resultado: ${resultado:+.2f}"
            except:
                resultado_str = ""

            orden = MarketOrderRequest(symbol=symbol, qty=posicion, side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
            trading_client.submit_order(orden)
            max_prices.pop(symbol, None)
            qty_abierta.pop(symbol, None)

            emoji = "✅" if "+" in resultado_str else "❌"
            send_telegram(f"{emoji} VENTA {symbol}\nQty: {posicion}\nPrecio: ${precio:.2f}\n{resultado_str}")
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
        send_telegram(f"⚙️ Parámetros ajustados:\n" + "\n".join(f"  - {c}" for c in cambios))

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
    send_telegram(f"🚀 Webhook Alpaca v4 iniciado\nSL: {STOP_LOSS_PCT}% | TP: {TAKE_PROFIT_PCT}% | TS: {TRAILING_STOP_PCT}%")
    app.run(host="0.0.0.0", port=port)
