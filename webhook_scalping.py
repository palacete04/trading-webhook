import requests
import os
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8957492846:AAGophSxXOSZGT4Gd1cLTNOICzxpZIH5wEU")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-5246245037")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://trading-webhook-zhra.onrender.com")
TOKEN = os.environ.get("TOKEN", "MI_TOKEN_SECRETO")

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error Telegram: {e}")

def apply_params(nuevos_params):
    """Aplica los parámetros nuevos al webhook"""
    try:
        nuevos_params["token"] = TOKEN
        response = requests.post(
            f"{WEBHOOK_URL}/adjust",
            json=nuevos_params,
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Error aplicando params: {e}")
        return False

def run_optimization_alpaca(trades_data, params_actuales):
    if len(trades_data) < 5:
        return {"message": "Necesitas al menos 5 operaciones para optimizar"}

    total = len(trades_data)
    wins = sum(1 for t in trades_data if t['profit'] > 0)
    losses = total - wins
    win_rate = wins / total * 100
    total_profit = sum(t['profit'] for t in trades_data)

    avg_win  = sum(t['profit'] for t in trades_data if t['profit'] > 0) / wins if wins > 0 else 0
    avg_loss = sum(t['profit'] for t in trades_data if t['profit'] < 0) / losses if losses > 0 else 0

    params_nuevos = {}
    razones = []

    # ─────────────────────────────────────────
    # MODO AGRESIVO — sistema ganando
    # ─────────────────────────────────────────
    if win_rate > 60 and total_profit > 100:
        # Subir TP para capturar más ganancia
        nuevo_tp = min(params_actuales.get("take_profit_pct", 2.0) + 0.5, 4.0)
        params_nuevos["take_profit_pct"] = nuevo_tp
        razones.append(f"Win rate {win_rate:.0f}% → subir TP a {nuevo_tp}%")

        # Subir capital si resultados son muy buenos
        if total_profit > 300 and win_rate > 65:
            nuevo_capital = min(params_actuales.get("pct_capital", 20) + 5, 30)
            params_nuevos["pct_capital"] = nuevo_capital
            razones.append(f"P&L ${total_profit:.0f} → subir capital a {nuevo_capital}%")

        # Trailing más ajustado para proteger ganancias
        params_nuevos["trailing_stop_pct"] = 0.3
        razones.append("Modo agresivo → trailing más ajustado a 0.3%")

    # ─────────────────────────────────────────
    # MODO CONSERVADOR — sistema perdiendo
    # ─────────────────────────────────────────
    elif win_rate < 40 or total_profit < -100:
        # Bajar SL para cortar pérdidas antes
        nuevo_sl = max(params_actuales.get("stop_loss_pct", 1.0) - 0.2, 0.5)
        params_nuevos["stop_loss_pct"] = nuevo_sl
        razones.append(f"Win rate {win_rate:.0f}% → bajar SL a {nuevo_sl}%")

        # Bajar capital para reducir exposición
        nuevo_capital = max(params_actuales.get("pct_capital", 20) - 5, 10)
        params_nuevos["pct_capital"] = nuevo_capital
        razones.append(f"Modo conservador → bajar capital a {nuevo_capital}%")

        # Trailing más amplio para no salir antes de tiempo
        params_nuevos["trailing_stop_pct"] = 0.7
        razones.append("Modo conservador → trailing más amplio a 0.7%")

    # ─────────────────────────────────────────
    # MODO NORMAL — sin cambios grandes
    # ─────────────────────────────────────────
    else:
        razones.append("Sistema estable — sin cambios necesarios")

    # Reporte
    report = f"[OPTIMIZADOR ALPACA] {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
    report += f"Análisis de {total} operaciones:\n"
    report += f"  Win rate: {win_rate:.1f}%\n"
    report += f"  P&L total: ${total_profit:.2f}\n"
    report += f"  Ganancia promedio: ${avg_win:.2f}\n"
    report += f"  Pérdida promedio: ${avg_loss:.2f}\n\n"
    report += "Decisiones:\n"
    for r in razones:
        report += f"  - {r}\n"

    send_telegram(report)

    # Aplicar cambios si los hay
    if params_nuevos:
        exito = apply_params(params_nuevos)
        if exito:
            send_telegram(f"✅ Parámetros aplicados automáticamente")
        else:
            send_telegram(f"❌ Error al aplicar parámetros")

    return {
        "stats": {
            "total": total,
            "win_rate": round(win_rate, 1),
            "total_profit": round(total_profit, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2)
        },
        "razones": razones,
        "params_aplicados": params_nuevos
    }
