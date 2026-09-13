import os
import json
import time
import urllib.parse
import urllib.request
from statistics import mean

API = "https://api.pionex.com"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# =========================
# CONFIGURATION V2
# =========================

DEEP_SCAN_COUNT = 200
SIGNAL_SCORE = 5
MIN_24H_VOLUME = 50000

# Paper trading
PAPER_MODE = True
PAPER_START_BALANCE = 1000.0
PAPER_RISK_PER_TRADE = 0.01
PAPER_STOP_LOSS = 0.015
PAPER_TAKE_PROFIT = 0.03


# =========================
# API
# =========================

def get_json(path, params=None):
    if params:
        path += "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        API + path,
        headers={"User-Agent": "Pionex-Movement-Scanner/4.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode())

    if not data.get("result"):
        raise RuntimeError("Erreur API Pionex : " + str(data))

    return data["data"]


# =========================
# TELEGRAM
# =========================

def send_telegram(message):
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN est absent.")

    if not CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID est absent.")

    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"

    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    request = urllib.request.Request(
        url,
        data=payload,
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        result = response.read().decode()

    print("TELEGRAM :", result)

    if '"ok":true' not in result:
        raise RuntimeError("Telegram a refuse le message : " + result)


# =========================
# INDICATEURS
# =========================

def ema(values, period):
    if len(values) < period:
        return None

    result = mean(values[:period])
    multiplier = 2 / (period + 1)

    for value in values[period:]:
        result = (value - result) * multiplier + result

    return result


def calculate_rsi(values, period=14):
    if len(values) < period + 1:
        return 50

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = mean(gains[-period:])
    avg_loss = mean(losses[-period:])

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# =========================
# ANALYSE
# =========================

def analyse(symbol):
    data = get_json(
        "/api/v1/market/klines",
        {"symbol": symbol, "interval": "5M", "limit": 100}
    )

    candles = data["klines"]

    if len(candles) < 60:
        return None

    closes = [float(x["close"]) for x in candles]
    highs = [float(x["high"]) for x in candles]
    lows = [float(x["low"]) for x in candles]
    volumes = [float(x["volume"]) for x in candles]

    price = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    rsi = calculate_rsi(closes)

    # Volume récent vs moyenne précédente
    previous_volumes = volumes[-21:-1]
    average_volume = mean(previous_volumes)

    if average_volume <= 0:
        return None

    volume_ratio = volumes[-1] / average_volume

    # Accélération du volume
    recent_avg = mean(volumes[-3:])
    older_avg = mean(volumes[-20:-3])
    volume_acceleration = (
        recent_avg / older_avg if older_avg > 0 else 1
    )

    resistance = max(highs[-21:-1])
    support = min(lows[-21:-1])

    momentum_30m = ((price / closes[-7]) - 1) * 100
    momentum_60m = ((price / closes[-13]) - 1) * 100

    ranges = []
    for i in range(-20, 0):
        if closes[i] != 0:
            ranges.append(((highs[i] - lows[i]) / closes[i]) * 100)

    volatility = mean(ranges) if ranges else 0

    # Compression : volatilité actuelle faible par rapport à la période
    short_ranges = ranges[-5:]
    long_ranges = ranges[:-5]

    compression = False
    if long_ranges:
        compression = mean(short_ranges) < mean(long_ranges) * 0.75

    long_score = 0
    short_score = 0
    reasons_long = []
    reasons_short = []

    # VOLUME
    if volume_ratio >= 2:
        long_score += 2
        short_score += 2
        reasons_long.append("volume x%.1f" % volume_ratio)
        reasons_short.append("volume x%.1f" % volume_ratio)
    elif volume_ratio >= 1.4:
        long_score += 1
        short_score += 1

    # ACCELERATION VOLUME
    if volume_acceleration >= 1.5:
        long_score += 1
        short_score += 1
        reasons_long.append("acceleration volume")
        reasons_short.append("acceleration volume")

    # EMA
    if ema20 and ema50:
        if ema20 > ema50:
            long_score += 2
            reasons_long.append("tendance haussiere")
        elif ema20 < ema50:
            short_score += 2
            reasons_short.append("tendance baissiere")

    # RSI
    if 52 <= rsi <= 70:
        long_score += 1
        reasons_long.append("RSI haussier")
    elif 30 <= rsi <= 48:
        short_score += 1
        reasons_short.append("RSI baissier")

    # BREAKOUT / APPROCHE
    if price > resistance:
        long_score += 2
        reasons_long.append("BREAKOUT")
    elif price >= resistance * 0.995:
        long_score += 1
        reasons_long.append("proche resistance")

    if price < support:
        short_score += 2
        reasons_short.append("BREAKDOWN")
    elif price <= support * 1.005:
        short_score += 1
        reasons_short.append("proche support")

    # MOMENTUM
    if momentum_30m >= 0.6:
        long_score += 1
        reasons_long.append("momentum +%.2f%%" % momentum_30m)

    if momentum_60m >= 1.0:
        long_score += 1
        reasons_long.append("impulsion 1h")

    if momentum_30m <= -0.6:
        short_score += 1
        reasons_short.append("momentum %.2f%%" % momentum_30m)

    if momentum_60m <= -1.0:
        short_score += 1
        reasons_short.append("impulsion 1h")

    # COMPRESSION
    if compression:
        if long_score >= short_score:
            long_score += 1
            reasons_long.append("compression")
        if short_score >= long_score:
            short_score += 1
            reasons_short.append("compression")

    # VOLATILITE
    if volatility >= 0.8:
        if long_score > short_score:
            long_score += 1
            reasons_long.append("volatilite")
        elif short_score > long_score:
            short_score += 1
            reasons_short.append("volatilite")

    if long_score > short_score:
        direction = "LONG"
        score = long_score
        reasons = reasons_long
    elif short_score > long_score:
        direction = "SHORT"
        score = short_score
        reasons = reasons_short
    else:
        return None

    if score < SIGNAL_SCORE:
        return None

    return {
        "symbol": symbol,
        "price": price,
        "score": score,
        "direction": direction,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "volume_acceleration": volume_acceleration,
        "momentum": momentum_30m,
        "momentum_60m": momentum_60m,
        "volatility": volatility,
        "reasons": reasons,
    }


# =========================
# PAPER TRADING
# =========================

def paper_trade(signal):
    entry = signal["price"]

    if signal["direction"] == "LONG":
        stop = entry * (1 - PAPER_STOP_LOSS)
        target = entry * (1 + PAPER_TAKE_PROFIT)
    else:
        stop = entry * (1 + PAPER_STOP_LOSS)
        target = entry * (1 - PAPER_TAKE_PROFIT)

    risk_money = PAPER_START_BALANCE * PAPER_RISK_PER_TRADE
    position_size = risk_money / (entry * PAPER_STOP_LOSS)

    return {
        "symbol": signal["symbol"],
        "direction": signal["direction"],
        "entry": entry,
        "stop": stop,
        "target": target,
        "position_size": position_size,
    }


# =========================
# MAIN
# =========================

def main():
    print("================================")
    print("PIONEX MOVEMENT SCANNER V2")
    print("================================")

    if os.environ.get("TEST_MODE") == "1":
        send_telegram(
            "🤖 PIONEX SCANNER V2\n\n"
            "✅ Connexion Telegram OK.\n"
            "Scanner + paper trading prêts."
        )

    symbols_data = get_json(
        "/api/v1/common/symbols",
        {"type": "SPOT"}
    )

    usdt_symbols = {
        s["symbol"]
        for s in symbols_data["symbols"]
        if s.get("enable") and s.get("quoteCurrency") == "USDT"
    }

    print("Paires USDT :", len(usdt_symbols))

    ticker_data = get_json(
        "/api/v1/market/tickers",
        {"type": "SPOT"}
    )

    markets = []

    for ticker in ticker_data["tickers"]:
        symbol = ticker["symbol"]

        if symbol not in usdt_symbols:
            continue

        try:
            amount = float(ticker.get("amount", 0))
            price = float(ticker.get("close", 0))
        except Exception:
            continue

        if amount < MIN_24H_VOLUME or price <= 0:
            continue

        markets.append({
            "symbol": symbol,
            "volume": amount,
            "price": price,
        })

    markets.sort(key=lambda x: x["volume"], reverse=True)

    candidates = markets[:DEEP_SCAN_COUNT]

    print("Marchés analysés :", len(candidates))

    signals = []

    for market in candidates:
        try:
            result = analyse(market["symbol"])

            if result:
                result["volume24h"] = market["volume"]
                signals.append(result)
                print(
                    "SIGNAL",
                    result["symbol"],
                    result["direction"],
                    result["score"]
                )

        except Exception as error:
            print("Erreur", market["symbol"], str(error))

        time.sleep(0.12)

    signals.sort(key=lambda x: x["score"], reverse=True)

    if not signals:
        # Même sans signal fort, on prévient que le scan fonctionne.
        send_telegram(
            "🔎 PIONEX SCANNER V2\n\n"
            "Aucun signal au-dessus du seuil actuellement.\n"
            "Scan effectué sur %d marchés." % len(candidates)
        )
        print("Aucun signal.")
        return

    message = "🚨 PIONEX MOVEMENT SCANNER V2\n\n"

    for signal in signals[:5]:
        emoji = "🟢" if signal["direction"] == "LONG" else "🔴"

        message += (
            "━━━━━━━━━━━━━━\n"
            f"{emoji} {signal['direction']} {signal['symbol']}\n"
            f"Score : {signal['score']}/10+\n"
            f"Prix : {signal['price']:.8g}\n"
            f"Volume : x{signal['volume_ratio']:.2f}\n"
            f"Accélération volume : x{signal['volume_acceleration']:.2f}\n"
            f"RSI : {signal['rsi']:.1f}\n"
            f"Momentum 30m : {signal['momentum']:+.2f}%\n"
            f"Momentum 1h : {signal['momentum_60m']:+.2f}%\n"
            f"Volatilité : {signal['volatility']:.2f}%\n"
            "Signes : " + ", ".join(signal["reasons"]) + "\n"
        )

        if PAPER_MODE:
            trade = paper_trade(signal)
            message += (
                f"🧪 PAPER ENTRY : {trade['entry']:.8g}\n"
                f"🛑 Stop : {trade['stop']:.8g}\n"
                f"🎯 Target : {trade['target']:.8g}\n"
            )

    message += (
        "\n🧪 PAPER TRADING UNIQUEMENT\n"
        "⚠️ Aucun ordre réel n'est envoyé à Pionex."
    )

    send_telegram(message)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ERREUR GENERALE :", str(error))
        raise
