import os
import time
import requests

# ============================================================
# PIONEX PERPS MOVEMENT SCANNER
# ============================================================

API = "https://api.pionex.com/api/v1"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

MAX_SIGNALS = 8
KLINE_LIMIT = 60

# Volume 24h minimum
MIN_24H_VOLUME = 50000

# Seuils de détection
MIN_MOVE_30M = 1.5
MIN_VOLUME_RATIO = 1.2
MIN_SCORE = 6


def get_json(path, params=None):
    response = requests.get(
        API + path,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if data.get("result") is not True:
        raise RuntimeError(f"Erreur API Pionex : {data}")

    return data.get("data", {})


def get_symbols():
    data = get_json(
        "/common/symbols",
        {"type": "PERP"}
    )

    if isinstance(data, dict):
        symbols = data.get("symbols", [])
    else:
        symbols = data

    result = []

    for item in symbols:
        symbol = item.get("symbol", "")

        if symbol.endswith("_USDT"):
            result.append(symbol)

    return result


def get_tickers():
    data = get_json(
        "/market/tickers",
        {"type": "PERP"}
    )

    if isinstance(data, dict):
        return data.get("tickers", [])

    return data


def get_klines(symbol):
    data = get_json(
        "/market/klines",
        {
            "symbol": symbol,
            "interval": "5M",
            "limit": KLINE_LIMIT
        }
    )

    if isinstance(data, dict):
        return data.get("klines", [])

    return data


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def close_price(kline):
    if isinstance(kline, dict):
        return number(kline.get("close"))

    if len(kline) > 4:
        return number(kline[4])

    return 0.0


def candle_volume(kline):
    if isinstance(kline, dict):
        return number(
            kline.get(
                "volume",
                kline.get("amount", 0)
            )
        )

    if len(kline) > 5:
        return number(kline[5])

    return 0.0


def pct(current, previous):
    if previous == 0:
        return 0.0

    return (current / previous - 1) * 100


def analyse(symbol):

    candles = get_klines(symbol)

    if len(candles) < 25:
        return None

    closes = [
        close_price(x)
        for x in candles
    ]

    volumes = [
        candle_volume(x)
        for x in candles
    ]

    price = closes[-1]

    if price <= 0:
        return None

    # Mouvements
    move_5m = pct(
        price,
        closes[-2]
    )

    move_15m = pct(
        price,
        closes[-4]
    )

    move_30m = pct(
        price,
        closes[-7]
    )

    move_1h = pct(
        price,
        closes[-13]
    )

    # Volume
    avg_volume = (
        sum(volumes[-21:-1])
        / max(len(volumes[-21:-1]), 1)
    )

    if avg_volume > 0:
        volume_ratio = (
            volumes[-1] / avg_volume
        )
    else:
        volume_ratio = 0

    # Tendances
    sma10 = sum(closes[-10:]) / 10
    sma20 = sum(closes[-20:]) / 20

    bullish = sma10 > sma20
    bearish = sma10 < sma20

    # Accélération
    previous_15m = pct(
        closes[-4],
        closes[-7]
    )

    # Direction
    if move_30m >= MIN_MOVE_30M:
        direction = "LONG"

    elif move_30m <= -MIN_MOVE_30M:
        direction = "SHORT"

    else:
        return None

    # Volume obligatoire
    if volume_ratio < MIN_VOLUME_RATIO:
        return None

    # Score
    score = 0

    if abs(move_30m) >= 1.5:
        score += 2

    if abs(move_30m) >= 3:
        score += 1

    if abs(move_1h) >= 4:
        score += 1

    if direction == "LONG":

        if (
            move_15m > 0
            and move_15m > previous_15m
        ):
            score += 2

        if bullish:
            score += 2

    else:

        if (
            move_15m < 0
            and move_15m < previous_15m
        ):
            score += 2

        if bearish:
            score += 2

    # Force du volume
    if volume_ratio >= 1.2:
        score += 1

    if volume_ratio >= 2:
        score += 1

    if volume_ratio >= 3:
        score += 1

    if score < MIN_SCORE:
        return None

    # Niveaux indicatifs
    if direction == "LONG":

        entry_low = price * 0.997
        entry_high = price * 1.001

        stop = price * 0.985

        tp1 = price * 1.025
        tp2 = price * 1.040

    else:

        entry_low = price * 0.999
        entry_high = price * 1.003

        stop = price * 1.015

        tp1 = price * 0.975
        tp2 = price * 0.960

    return {
        "symbol": symbol,
        "price": price,
        "direction": direction,
        "move_5m": move_5m,
        "move_15m": move_15m,
        "move_30m": move_30m,
        "move_1h": move_1h,
        "volume_ratio": volume_ratio,
        "score": min(score, 10),
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2
    }


def send_telegram(message):

    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN manquant"
        )

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID manquant"
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if data.get("ok") is not True:
        raise RuntimeError(
            f"Erreur Telegram : {data}"
        )


def format_price(value):

    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:.4f}"

    if value >= 0.01:
        return f"{value:.6f}"

    return f"{value:.8g}"


def create_message(signals, scanned):

    lines = [
        "🚨 PIONEX PERPS",
        "",
        f"🔎 {scanned} marchés PERPS analysés",
        f"🔥 {len(signals)} signal(s) fort(s)",
        ""
    ]

    for index, signal in enumerate(
        signals,
        1
    ):

        emoji = (
            "🟢"
            if signal["direction"] == "LONG"
            else "🔴"
        )

        lines.append(
            f"{emoji} {index}. "
            f"{signal['symbol']} — "
            f"{signal['direction']} POSSIBLE"
        )

        lines.append(
            f"💰 Prix : "
            f"{format_price(signal['price'])}"
        )

        lines.append(
            f"⚡ 5m : "
            f"{signal['move_5m']:+.2f}%"
        )

        lines.append(
            f"⚡ 15m : "
            f"{signal['move_15m']:+.2f}%"
        )

        lines.append(
            f"📊 30m : "
            f"{signal['move_30m']:+.2f}%"
        )

        lines.append(
            f"📈 1h : "
            f"{signal['move_1h']:+.2f}%"
        )

        lines.append(
            f"🔊 Volume : "
            f"x{signal['volume_ratio']:.1f}"
        )

        lines.append(
            f"⭐ Force : "
            f"{signal['score']}/10"
        )

        lines.append(
            f"📍 Entrée indicative : "
            f"{format_price(signal['entry_low'])}"
            f" → "
            f"{format_price(signal['entry_high'])}"
        )

        lines.append(
            f"🛑 Stop indicatif : "
            f"{format_price(signal['stop'])}"
        )

        lines.append(
            f"🎯 TP1 : "
            f"{format_price(signal['tp1'])}"
        )

        lines.append(
            f"🎯 TP2 : "
            f"{format_price(signal['tp2'])}"
        )

        lines.append("")

    lines.append(
        "⚠️ Analyse technique uniquement."
    )

    lines.append(
        "❌ Aucun ordre automatique."
    )

    return "\n".join(lines)[:4000]


def main():

    print("================================")
    print("PIONEX PERPS MOVEMENT SCANNER")
    print("================================")

    symbols = get_symbols()

    print(
        f"PERPS trouvés : {len(symbols)}"
    )

    tickers = get_tickers()

    volume_map = {}

    for ticker in tickers:

        symbol = ticker.get("symbol")

        if not symbol:
            continue

        volume_24h = number(
            ticker.get(
                "amount",
                ticker.get("volume", 0)
            )
        )

        volume_map[symbol] = volume_24h

    liquid_symbols = [
        symbol
        for symbol in symbols
        if volume_map.get(
            symbol,
            0
        ) >= MIN_24H_VOLUME
    ]

    liquid_symbols.sort(
        key=lambda symbol:
        volume_map.get(
            symbol,
            0
        ),
        reverse=True
    )

    print(
        f"PERPS liquides : "
        f"{len(liquid_symbols)}"
    )

    signals = []

    for symbol in liquid_symbols:

        try:

            result = analyse(symbol)

            if result:

                signals.append(result)

                print(
                    f"Signal : "
                    f"{symbol} "
                    f"{result['direction']} "
                    f"{result['score']}/10"
                )

        except Exception as error:

            print(
                f"{symbol} : erreur {error}"
            )

        time.sleep(0.05)

    signals.sort(
        key=lambda signal: (
            signal["score"],
            abs(signal["move_30m"]),
            signal["volume_ratio"]
        ),
        reverse=True
    )

    signals = signals[:MAX_SIGNALS]

    print(
        f"Signaux trouvés : "
        f"{len(signals)}"
    )

    if signals:

        message = create_message(
            signals,
            len(liquid_symbols)
        )

    else:

        message = (
            "😴 PIONEX PERPS\n\n"
            f"🔎 {len(liquid_symbols)} "
            "marchés analysés.\n\n"
            "Aucun mouvement suffisamment "
            "fort avec volume actuellement.\n\n"
            "Le scanner continue de surveiller.\n\n"
            "❌ Aucun ordre automatique."
        )

    send_telegram(message)

    print(
        "✅ Message Telegram envoyé."
    )


if __name__ == "__main__":
    main()
