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

def hay_posicion_abierta_cualquier_simbolo()
