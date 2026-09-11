import os
import requests
import statistics
from datetime import datetime, timezone

PIONEX = "https://api.pionex.com"
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MIN_VOLUME_USDT = 100000
MIN_SCORE = 8


def pionex(path, params=None):
    r = requests.get(PIONEX + path, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    if not data.get("result"):
        raise RuntimeError(data)

    return data["data"]


def send_telegram(message):
    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    request = urllib.request.Request(
        url,
        data=payload,
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = response.read().decode()
            print("TELEGRAM REPONSE :", result)

            if '"ok":true' not in result:
                raise RuntimeError(
                    "Telegram a refusé le message : " + result
                )

            print("TELEGRAM : message envoyé avec succès")

    except Exception as error:
        print("TELEGRAM ERREUR :", error)
        raise 


def ema(values, period):
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    result = sum(values[:period]) / period

    for price in values[period:]:
        result = price * k + result * (1 - k)

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return 50

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def analyse(symbol):
    candles = pionex(
        "/api/v1/market/klines",
        {
            "symbol": symbol,
            "interval": "5M",
            "limit": 100,
        },
    )["klines"]

    closes = [float(x["close"]) for x in candles]
    highs = [float(x["high"]) for x in candles]
    lows = [float(x["low"]) for x in candles]
    volumes = [float(x["volume"]) for x in candles]

    if len(closes) < 60:
        return None

    price = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    current_rsi = rsi(closes)

    recent_high = max(highs[-21:-1])

    avg_volume = statistics.mean(volumes[-21:-1])
    current_volume = volumes[-1]

    volume_ratio = current_volume / avg_volume if avg_volume else 0

    score_long = 0
    score_short = 0

    # Volume anormal
    if volume_ratio >= 2:
        score_long += 2
        score_short += 2

    # EMA
    if ema20 and ema50:
        if ema20 > ema50:
            score_long += 1
        elif ema20 < ema50:
            score_short += 1

    # RSI
    if 55 <= current_rsi <= 70:
        score_long += 1

    if 30 <= current_rsi <= 45:
        score_short += 1

    # Breakout
    if price > recent_high:
        score_long += 2

    recent_low = min(lows[-21:-1])

    if price < recent_low:
        score_short += 2

    # Momentum 5 dernières bougies
    momentum = (price / closes[-6] - 1) * 100

    if momentum > 1:
        score_long += 1

    if momentum < -1:
        score_short += 1

    score = max(score_long, score_short)

    if score < MIN_SCORE:
        return None

    direction = "🟢 LONG" if score_long >= score_short else "🔴 SHORT"

    return {
        "symbol": symbol,
        "price": price,
        "score": score,
        "direction": direction,
        "volume_ratio": volume_ratio,
        "rsi": current_rsi,
        "momentum": momentum,
    }


def main():

    symbols_data = pionex(
        "/api/v1/common/symbols",
        {"type": "SPOT"},
    )

    symbols = [
        x["symbol"]
        for x in symbols_data["symbols"]
        if x.get("enable") and x["symbol"].endswith("_USDT")
    ]

    tickers = pionex(
        "/api/v1/market/tickers",
        {"type": "SPOT"},
    )["tickers"]

    volume_map = {
        x["symbol"]: float(x.get("amount", 0))
        for x in tickers
    }

    # On garde uniquement les marchés suffisamment liquides
    symbols = [
        s for s in symbols
        if volume_map.get(s, 0) >= MIN_VOLUME_USDT
    ]

    signals = []

    for symbol in symbols:

        try:
            result = analyse(symbol)

            if result:
                signals.append(result)

        except Exception as e:
            print(f"Erreur {symbol}: {e}")

    signals.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    if not signals:
        print("Aucun signal fort.")
        return
        if os.environ.get("TEST_MODE") == "1":
        send_telegram(
            "🤖 PIONEX SCANNER\n\n"
            "✅ Connexion réussie.\n"
            "Aucun signal fort actuellement."
        )
    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message = f"🚨 PIONEX SCANNER\n{now}\n\n"

    for s in signals[:5]:

        message += (
            f"{s['direction']} {s['symbol']}\n"
            f"Score : {s['score']}/12\n"
            f"Prix : {s['price']:.8g}\n"
            f"Volume : x{s['volume_ratio']:.2f}\n"
            f"RSI : {s['rsi']:.1f}\n"
            f"Momentum : {s['momentum']:.2f}%\n\n"
        )

    telegram(message)


if __name__ == "__main__":
    main()
