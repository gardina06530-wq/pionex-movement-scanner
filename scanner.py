import os
import json
import time
import urllib.parse
import urllib.request
from statistics import mean


# ============================================================
# CONFIGURATION
# ============================================================

API = "https://api.pionex.com"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Nombre maximum de marchés analysés en profondeur
DEEP_SCAN_COUNT = 80

# Score minimum pour déclencher une vraie alerte
SIGNAL_SCORE = 7

# Volume 24h minimum en USDT
MIN_24H_VOLUME = 50000


# ============================================================
# PIONEX API
# ============================================================

def get_json(path, params=None):

    if params:
        path += "?" + urllib.parse.urlencode(params)

    url = API + path

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Pionex-Movement-Scanner/2.0"
        }
    )

    with urllib.request.urlopen(request, timeout=20) as response:

        data = json.loads(
            response.read().decode()
        )

    if not data.get("result"):
        raise RuntimeError(
            "Erreur API Pionex : " + str(data)
        )

    return data["data"]


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    print("================================")
    print("TEST ENVOI TELEGRAM")
    print("================================")

    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN est absent."
        )

    if not CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID est absent."
        )

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

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            result = response.read().decode()

        print("REPONSE TELEGRAM :")
        print(result)

        if '"ok":true' not in result:

            raise RuntimeError(
                "Telegram a refuse le message : "
                + result
            )

        print("TELEGRAM : MESSAGE ENVOYE AVEC SUCCES")

    except Exception as error:

        print(
            "TELEGRAM ERREUR :",
            str(error)
        )

        raise


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    result = mean(
        values[:period]
    )

    multiplier = 2 / (period + 1)

    for value in values[period:]:

        result = (
            (value - result)
            * multiplier
            + result
        )

    return result


# ============================================================
# RSI
# ============================================================

def calculate_rsi(values, period=14):

    if len(values) < period + 1:
        return 50

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = mean(
        gains[-period:]
    )

    avg_loss = mean(
        losses[-period:]
    )

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# ANALYSE D'UNE PAIRE
# ============================================================

def analyse(symbol):

    data = get_json(
        "/api/v1/market/klines",
        {
            "symbol": symbol,
            "interval": "5M",
            "limit": 100
        }
    )

    candles = data["klines"]

    if len(candles) < 60:
        return None

    closes = [
        float(x["close"])
        for x in candles
    ]

    highs = [
        float(x["high"])
        for x in candles
    ]

    lows = [
        float(x["low"])
        for x in candles
    ]

    volumes = [
        float(x["volume"])
        for x in candles
    ]

    price = closes[-1]
       
    if not signals:
        print("Aucun signal fort.")
        return
    # --------------------------------------------------------
    # INDICATEURS
    # --------------------------------------------------------

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    rsi = calculate_rsi(
        closes
    )

    average_volume = mean(
        volumes[-21:]
    )

    if average_volume <= 0:
        return None

    volume_ratio = (
        volumes[-1]
        / average_volume
    )

    # Résistance / support des 20 dernières bougies
    resistance = max(
        highs[-21:-1]
    )

    support = min(
        lows[-21:-1]
    )

    # Momentum sur environ 30 minutes
    momentum = (
        (price / closes[-7])
        - 1
    ) * 100

    # Volatilité moyenne
    ranges = []

    for i in range(-20, 0):

        if closes[i] != 0:

            ranges.append(
                (
                    (highs[i] - lows[i])
                    / closes[i]
                ) * 100
            )

    volatility = mean(
        ranges
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    long_score = 0
    short_score = 0

    reasons_long = []
    reasons_short = []

    # VOLUME
    if volume_ratio >= 2:

        long_score += 2
        short_score += 2

        reasons_long.append(
            "volume x%.1f"
            % volume_ratio
        )

        reasons_short.append(
            "volume x%.1f"
            % volume_ratio
        )

    elif volume_ratio >= 1.5:

        long_score += 1
        short_score += 1

    # TENDANCE EMA
    if ema20 and ema50:

        if ema20 > ema50:

            long_score += 2

            reasons_long.append(
                "EMA20 > EMA50"
            )

        elif ema20 < ema50:

            short_score += 2

            reasons_short.append(
                "EMA20 < EMA50"
            )

    # RSI
    if 55 <= rsi <= 70:

        long_score += 1

        reasons_long.append(
            "RSI favorable"
        )

    elif 30 <= rsi <= 45:

        short_score += 1

        reasons_short.append(
            "RSI favorable"
        )

    # BREAKOUT
    if price > resistance:

        long_score += 2

        reasons_long.append(
            "BREAKOUT resistance"
        )

    # BREAKDOWN
    if price < support:

        short_score += 2

        reasons_short.append(
            "BREAKDOWN support"
        )

    # MOMENTUM
    if momentum >= 1:

        long_score += 2

        reasons_long.append(
            "momentum +%.2f%%"
            % momentum
        )

    elif momentum <= -1:

        short_score += 2

        reasons_short.append(
            "momentum %.2f%%"
            % momentum
        )

    # VOLATILITE
    if volatility >= 1:

        if long_score > short_score:

            long_score += 1

            reasons_long.append(
                "volatilite elevee"
            )

        elif short_score > long_score:

            short_score += 1

            reasons_short.append(
                "volatilite elevee"
            )

    # --------------------------------------------------------
    # DIRECTION
    # --------------------------------------------------------

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

    # Score insuffisant
    if score < SIGNAL_SCORE:
        return None

    return {
        "symbol": symbol,
        "price": price,
        "score": score,
        "direction": direction,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "momentum": momentum,
        "volatility": volatility,
        "reasons": reasons
    }


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():

    print("================================")
    print("PIONEX MOVEMENT SCANNER")
    print("================================")

    # --------------------------------------------------------
    # TEST TELEGRAM
    # --------------------------------------------------------

    if os.environ.get("TEST_MODE") == "1":

        print(
            "TEST_MODE active : test Telegram..."
        )

        send_telegram(
            "🤖 PIONEX SCANNER\n\n"
            "✅ Connexion réussie.\n"
            "Le scanner fonctionne correctement."
        )

    # --------------------------------------------------------
    # RECUPERATION DES PAIRES
    # --------------------------------------------------------

    symbols_data = get_json(
        "/api/v1/common/symbols",
        {
            "type": "SPOT"
        }
    )

    symbols = symbols_data["symbols"]

    usdt_symbols = [

        s["symbol"]

        for s in symbols

        if (
            s.get("enable")
            and s.get("quoteCurrency")
            == "USDT"
        )
    ]

    print(
        "Paires USDT trouvées :",
        len(usdt_symbols)
    )

    # --------------------------------------------------------
    # TICKERS
    # --------------------------------------------------------

    ticker_data = get_json(
        "/api/v1/market/tickers",
        {
            "type": "SPOT"
        }
    )

    tickers = ticker_data["tickers"]

    markets = []

    for ticker in tickers:

        symbol = ticker["symbol"]

        if symbol not in usdt_symbols:
            continue

        try:

            amount = float(
                ticker.get(
                    "amount",
                    0
                )
            )

            price = float(
                ticker.get(
                    "close",
                    0
                )
            )

        except Exception:

            continue

        if amount < MIN_24H_VOLUME:
            continue

        markets.append({

            "symbol": symbol,

            "volume": amount,

            "price": price

        })

    # --------------------------------------------------------
    # TRI PAR LIQUIDITE
    # --------------------------------------------------------

    markets.sort(
        key=lambda x: x["volume"],
        reverse=True
    )

    print(
        "Marchés liquides :",
        len(markets)
    )

    candidates = markets[
        :DEEP_SCAN_COUNT
    ]

    print(
        "Analyse technique :",
        len(candidates)
    )

    # --------------------------------------------------------
    # ANALYSE
    # --------------------------------------------------------

    signals = []

    for market in candidates:

        symbol = market["symbol"]

        try:

            result = analyse(
                symbol
            )

            if result:

                result[
                    "volume24h"
                ] = market["volume"]

                signals.append(
                    result
                )

                print(
                    "SIGNAL :",
                    symbol,
                    result["direction"],
                    result["score"]
                )

        except Exception as error:

            print(
                "Erreur",
                symbol,
                str(error)
            )

        time.sleep(0.15)

    # --------------------------------------------------------
    # TRI DES SIGNAUX
    # --------------------------------------------------------

    signals.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    # --------------------------------------------------------
    # AUCUN SIGNAL
    # --------------------------------------------------------

    if not signals:

        print(
            "Aucun signal fort."
        )

        return

    # --------------------------------------------------------
    # MESSAGE TELEGRAM
    # --------------------------------------------------------

    message = (
        "🚨 PIONEX MOVEMENT SCANNER\n\n"
    )

    for signal in signals[:5]:

        emoji = (
            "🟢"
            if signal["direction"]
            == "LONG"
            else "🔴"
        )

        message += (

            "━━━━━━━━━━━━━━\n"

            f"{emoji} "
            f"{signal['direction']} "
            f"{signal['symbol']}\n"

            f"Score : "
            f"{signal['score']}/10\n"

            f"Prix : "
            f"{signal['price']:.8g}\n"

            f"Volume : "
            f"x{signal['volume_ratio']:.2f}\n"

            f"RSI : "
            f"{signal['rsi']:.1f}\n"

            f"Momentum : "
            f"{signal['momentum']:+.2f}%\n"

            f"Volatilité : "
            f"{signal['volatility']:.2f}%\n"

            "Signes : "
            + ", ".join(
                signal["reasons"]
            )

            + "\n"
        )

    message += (

        "\n⚠️ Signal algorithmique uniquement.\n"
        "Aucun ordre automatique."

    )

    send_telegram(
        message
    )


# ============================================================
# DEMARRAGE
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print(
            "ERREUR GENERALE :",
            str(error)
        )

        raise
