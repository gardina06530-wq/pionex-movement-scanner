import os
import time
import requests

# =========================
# CONFIGURATION
# =========================

PIONEX = "https://api.pionex.com/api/v1"
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SCAN_LIMIT = 15
MIN_VOLUME_24H = 50000

# =========================
# API
# =========================

def get_json(url, params=None):
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    if data.get("result") is not True:
        raise RuntimeError(f"Erreur Pionex: {data}")

    return data["data"]


def get_symbols():
    data = get_json(
        f"{PIONEX}/common/symbols",
        {"type": "SPOT"}
    )

    if isinstance(data, dict):
        symbols = data.get("symbols", [])
    else:
        symbols = data

    result = []

    for s in symbols:
        symbol = s.get("symbol", "")

        if symbol.endswith("_USDT"):
            result.append(symbol)

    return result


def get_tickers():
    data = get_json(
        f"{PIONEX}/market/tickers",
        {"type": "SPOT"}
    )

    if isinstance(data, dict):
        tickers = data.get("tickers", [])
    else:
        tickers = data

    return tickers


def get_klines(symbol):
    data = get_json(
        f"{PIONEX}/market/klines",
        {
            "symbol": symbol,
            "interval": "5M",
            "limit": 50
        }
    )

    if isinstance(data, dict):
        return data.get("klines", [])

    return data


# =========================
# INDICATEURS
# =========================

def close_price(k):
    if isinstance(k, dict):
        return float(k["close"])

    return float(k[4])


def volume(k):
    if isinstance(k, dict):
        return float(k.get("volume", 0))

    return float(k[5])


def pct(a, b):
    if b == 0:
        return 0

    return (a / b - 1) * 100


def analyse(symbol):
    candles = get_klines(symbol)

    if len(candles) < 20:
        return None

    closes = [close_price(x) for x in candles]
    volumes = [volume(x) for x in candles]

    price = closes[-1]

    # Mouvement 15 / 30 / 60 minutes
    move_15 = pct(price, closes[-4])
    move_30 = pct(price, closes[-7])
    move_60 = pct(price, closes[-13])

    # Volume actuel contre moyenne
    avg_volume = sum(volumes[-21:-1]) / max(len(volumes[-21:-1]), 1)
    current_volume = volumes[-1]

    if avg_volume > 0:
        volume_ratio = current_volume / avg_volume
    else:
        volume_ratio = 0

    # Moyennes mobiles simples
    sma10 = sum(closes[-10:]) / 10
    sma20 = sum(closes[-20:]) / 20

    bullish = sma10 > sma20
    bearish = sma10 < sma20

    # Score
    score = 0

    direction = None

    if move_30 >= 2:
        direction = "LONG"
        score += 3
    elif move_30 <= -2:
        direction = "SHORT"
        score += 3

    if abs(move_15) >= 1:
        score += 2

    if abs(move_60) >= 3:
        score += 1

    if volume_ratio >= 1.5:
        score += 2

    if direction == "LONG" and bullish:
        score += 2

    if direction == "SHORT" and bearish:
        score += 2

    if direction is None:
        return None

    if volume_ratio < 1.0:
        return None

    return {
        "symbol": symbol,
        "price": price,
        "move_15": move_15,
        "move_30": move_30,
        "move_60": move_60,
        "volume_ratio": volume_ratio,
        "direction": direction,
        "score": score,
    }


# =========================
# TELEGRAM
# =========================

def telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=15
    )

    response.raise_for_status()


# =========================
# SCANNER
# =========================

def main():

    print("Démarrage du scanner Pionex...")

    symbols = get_symbols()

    print(f"{len(symbols)} marchés USDT trouvés.")

    tickers = get_tickers()

    ticker_map = {}

    for t in tickers:
        symbol = t.get("symbol")

        if not symbol:
            continue

        try:
            volume_24h = float(
                t.get("amount", 0)
                or t.get("volume", 0)
            )
        except:
            volume_24h = 0

        ticker_map[symbol] = volume_24h

    candidates = []

    for symbol in symbols:

        # Filtre volume 24h
        volume_24h = ticker_map.get(symbol, 0)

        if volume_24h < MIN_VOLUME_24H:
            continue

        try:
            result = analyse(symbol)

            if result:
                candidates.append(result)

        except Exception as e:
            print(f"{symbol}: erreur {e}")

        # Petite pause pour éviter de bombarder l'API
        time.sleep(0.05)

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    candidates = candidates[:SCAN_LIMIT]

    print(f"{len(candidates)} signaux trouvés.")

    # =========================
    # MESSAGE TELEGRAM
    # =========================

    if not candidates:

        message = (
            "😴 SCANNER PIONEX\n\n"
            "Aucun mouvement suffisamment fort "
            "avec volume actuellement.\n\n"
            "Le scanner continue de surveiller."
        )

        telegram(message)
        return

    lines = [
        "🚨 SCANNER PIONEX",
        "",
        f"🔥 {len(candidates)} mouvements détectés",
        ""
    ]

    for i, x in enumerate(candidates, 1):

        if x["direction"] == "LONG":
            emoji = "🟢"
        else:
            emoji = "🔴"

        lines.append(
            f"{emoji} {i}. {x['symbol']}"
        )

        lines.append(
            f"   {x['direction']} possible"
        )

        lines.append(
            f"   💰 Prix : {x['price']:.8g}"
        )

        lines.append(
            f"   ⚡ 15m : {x['move_15']:+.2f}%"
        )

        lines.append(
            f"   📊 30m : {x['move_30']:+.2f}%"
        )

        lines.append(
            f"   📈 1h : {x['move_60']:+.2f}%"
        )

        lines.append(
            f"   🔊 Volume : x{x['volume_ratio']:.1f}"
        )

        lines.append(
            f"   ⭐ Force : {x['score']}/10"
        )

        # Zone indicative
        if x["direction"] == "LONG":
            entry_low = x["price"] * 0.995
            entry_high = x["price"] * 1.002
            stop = x["price"] * 0.985
            tp1 = x["price"] * 1.025
            tp2 = x["price"] * 1.04

        else:
            entry_low = x["price"] * 0.998
            entry_high = x["price"] * 1.005
            stop = x["price"] * 1.015
            tp1 = x["price"] * 0.975
            tp2 = x["price"] * 0.96

        lines.append(
            f"   📍 Zone : {entry_low:.8g} → {entry_high:.8g}"
        )

        lines.append(
            f"   🛑 Stop indicatif : {stop:.8g}"
        )

        lines.append(
            f"   🎯 TP1 : {tp1:.8g}"
        )

        lines.append(
            f"   🎯 TP2 : {tp2:.8g}"
        )

        lines.append("")

    lines.append(
        "⚠️ Signal technique uniquement — "
        "aucun ordre automatique."
    )

    message = "\n".join(lines)

    # Telegram limite les messages longs
    if len(message) > 4000:
        message = message[:3950] + "\n..."

    telegram(message)

    print("Message Telegram envoyé.")


if __name__ == "__main__":
    main()
