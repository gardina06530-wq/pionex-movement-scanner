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

       
