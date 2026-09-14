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
# PARAMETRES V4
# =========================

DEEP_SCAN_COUNT = 200
MIN_24H_VOLUME = 50000

MIN_SIGNAL_SCORE = 6
MIN_ENTRY_SCORE = 8

MIN_VOLUME_SIGNAL = 1.0
MIN_VOLUME_ENTRY = 1.5

MAX_OPEN_POSITIONS = 3

PAPER_START_BALANCE = 1000.0
PAPER_RISK_PER_TRADE = 0.01
PAPER_STOP_LOSS = 0.015
PAPER_TAKE_PROFIT = 0.03

STATE_FILE = "paper_state.json"


# =========================
# API
# =========================

def get_json(path, params=None):

    if params:
        path += "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        API + path,
        headers={
            "User-Agent": "Pionex-Movement-Scanner-V4"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:

        data = json.loads(
            response.read().decode()
        )

    if not isinstance(data, dict) or data.get("result") != True:
    raise RuntimeError(
        f"Erreur API Pionex: {data}"
    )

    return data["data"]


# =========================
# TELEGRAM
# =========================

def send_telegram(message):

    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN absent."
        )

    if not CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID absent."
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

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:

        result = response.read().decode()

    if '"ok":true' not in result:
        raise RuntimeError(
            "Telegram refuse le message : "
            + result
        )


# =========================
# ETAT
# =========================

def default_state():

    return {
        "balance": PAPER_START_BALANCE,
        "realized_pnl": 0.0,
        "wins": 0,
        "losses": 0,
        "trades": [],
        "positions": {},
        "last_alerted": {}
    }


def load_state():

    if not os.path.exists(STATE_FILE):
        return default_state()

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            state = json.load(f)

        base = default_state()
        base.update(state)

        return base

    except Exception:

        return default_state()


def save_state(state):

    temp = STATE_FILE + ".tmp"

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        temp,
        STATE_FILE
    )


# =========================
# INDICATEURS
# =========================

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


def calculate_rsi(values, period=14):

    if len(values) < period + 1:
        return 50

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i] -
            values[i - 1]
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


# =========================
# ANALYSE
# =========================

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

    # -------------------------
    # VOLUME
    # -------------------------

    previous_volumes = volumes[-21:-1]

    average_volume = mean(
        previous_volumes
    )

    if average_volume <= 0:
        return None

    volume_ratio = (
        volumes[-1] /
        average_volume
    )

    recent_avg = mean(
        volumes[-3:]
    )

    older_avg = mean(
        volumes[-20:-3]
    )

    volume_acceleration = (
        recent_avg / older_avg
        if older_avg > 0
        else 1
    )

    # -------------------------
    # NIVEAUX
    # -------------------------

    resistance = max(
        highs[-21:-1]
    )

    support = min(
        lows[-21:-1]
    )

    # -------------------------
    # MOMENTUM
    # -------------------------

    momentum_5m = (
        (price / closes[-2]) - 1
    ) * 100

    momentum_30m = (
        (price / closes[-7]) - 1
    ) * 100

    momentum_60m = (
        (price / closes[-13]) - 1
    ) * 100

    # -------------------------
    # VOLATILITE
    # -------------------------

    ranges = []

    for i in range(-20, 0):

        if closes[i] != 0:

            ranges.append(
                (
                    (highs[i] - lows[i])
                    / closes[i]
                ) * 100
            )

    volatility = (
        mean(ranges)
        if ranges
        else 0
    )

    # =========================
    # SCORE LONG
    # =========================

    long_score = 0
    long_reasons = []

    # Volume
    if volume_ratio >= 2.5:

        long_score += 3
        long_reasons.append(
            "🔥 volume x%.1f"
            % volume_ratio
        )

    elif volume_ratio >= 1.5:

        long_score += 2
        long_reasons.append(
            "volume x%.1f"
            % volume_ratio
        )

    elif volume_ratio >= 1.0:

        long_score += 1

    # Acceleration
    if volume_acceleration >= 1.5:

        long_score += 2
        long_reasons.append(
            "volume en acceleration"
        )

    # EMA
    if ema20 and ema50:

        if ema20 > ema50:

            long_score += 2
            long_reasons.append(
                "EMA20 > EMA50"
            )

    # RSI
    if 52 <= rsi <= 68:

        long_score += 1
        long_reasons.append(
            "RSI haussier"
        )

    # Momentum
    if momentum_5m >= 0.25:

        long_score += 1
        long_reasons.append(
            "momentum 5m"
        )

    if momentum_30m >= 0.6:

        long_score += 1
        long_reasons.append(
            "momentum 30m"
        )

    if momentum_60m >= 1.0:

        long_score += 1
        long_reasons.append(
            "impulsion 1h"
        )

    # Breakout
    if price > resistance:

        long_score += 3
        long_reasons.append(
            "🚀 BREAKOUT"
        )

    elif price >= resistance * 0.995:

        long_score += 1
        long_reasons.append(
            "proche resistance"
        )

    # Volatilité
    if volatility >= 0.8:

        long_score += 1
        long_reasons.append(
            "volatilite"
        )

    # =========================
    # SCORE SHORT
    # =========================

    short_score = 0
    short_reasons = []

    # Volume
    if volume_ratio >= 2.5:

        short_score += 3
        short_reasons.append(
            "🔥 volume x%.1f"
            % volume_ratio
        )

    elif volume_ratio >= 1.5:

        short_score += 2
        short_reasons.append(
            "volume x%.1f"
            % volume_ratio
        )

    elif volume_ratio >= 1.0:

        short_score += 1

    # Acceleration
    if volume_acceleration >= 1.5:

        short_score += 2
        short_reasons.append(
            "volume en acceleration"
        )

    # EMA
    if ema20 and ema50:

        if ema20 < ema50:

            short_score += 2
            short_reasons.append(
                "EMA20 < EMA50"
            )

    # RSI
    if 32 <= rsi <= 48:

        short_score += 1
        short_reasons.append(
            "RSI baissier"
        )

    # Momentum
    if momentum_5m <= -0.25:

        short_score += 1
        short_reasons.append(
            "momentum 5m"
        )

    if momentum_30m <= -0.6:

        short_score += 1
        short_reasons.append(
            "momentum 30m"
        )

    if momentum_60m <= -1.0:

        short_score += 1
        short_reasons.append(
            "impulsion 1h"
        )

    # Breakdown
    if price < support:

        short_score += 3
        short_reasons.append(
            "💥 BREAKDOWN"
        )

    elif price <= support * 1.005:

        short_score += 1
        short_reasons.append(
            "proche support"
        )

    # Volatilité
    if volatility >= 0.8:

        short_score += 1
        short_reasons.append(
            "volatilite"
        )

    # =========================
    # DIRECTION
    # =========================

    if long_score > short_score:

        direction = "LONG"
        score = long_score
        reasons = long_reasons

    elif short_score > long_score:

        direction = "SHORT"
        score = short_score
        reasons = short_reasons

    else:

        return None

    # =========================
    # FILTRE VOLUME
    # =========================

    if volume_ratio < MIN_VOLUME_SIGNAL:
        return None

    # =========================
    # FILTRE SCORE
    # =========================

    if score < MIN_SIGNAL_SCORE:
        return None

    # =========================
    # QUALITE
    # =========================

    if (
        score >= 9
        and volume_ratio >= 2.5
    ):

        quality = "A+"

    elif (
        score >= 8
        and volume_ratio >= 1.5
    ):

        quality = "A"

    elif score >= 7:

        quality = "B"

    else:

        quality = "C"

    return {
        "symbol": symbol,
        "price": price,
        "score": score,
        "quality": quality,
        "direction": direction,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "volume_acceleration": volume_acceleration,
        "momentum_5m": momentum_5m,
        "momentum_30m": momentum_30m,
        "momentum_60m": momentum_60m,
        "volatility": volatility,
        "reasons": reasons
    }


# =========================
# ENTREE PAPER
# =========================

def open_position(state, signal):

    symbol = signal["symbol"]

    if symbol in state["positions"]:
        return None

    if len(state["positions"]) >= MAX_OPEN_POSITIONS:
        return None

    # Filtre d'entrée plus strict
    if signal["score"] < MIN_ENTRY_SCORE:
        return None

    if signal["volume_ratio"] < MIN_VOLUME_ENTRY:
        return None

    entry = signal["price"]

    risk_money = (
        state["balance"]
        * PAPER_RISK_PER_TRADE
    )

    position_size = (
        risk_money
        / (entry * PAPER_STOP_LOSS)
    )

    if signal["direction"] == "LONG":

        stop = (
            entry *
            (1 - PAPER_STOP_LOSS)
        )

        target = (
            entry *
            (1 + PAPER_TAKE_PROFIT)
        )

    else:

        stop = (
            entry *
            (1 + PAPER_STOP_LOSS)
        )

        target = (
            entry *
            (1 - PAPER_TAKE_PROFIT)
        )

    position = {
        "symbol": symbol,
        "direction": signal["direction"],
        "entry": entry,
        "stop": stop,
        "target": target,
        "size": position_size,
        "score": signal["score"],
        "quality": signal["quality"],
        "opened_at": int(time.time())
    }

    state["positions"][symbol] = position

    return position


# =========================
# POSITIONS
# =========================

def update_positions(state, prices):

    closed = []

    for symbol, position in list(
        state["positions"].items()
    ):

        price = prices.get(symbol)

        if price is None:
            continue

        direction = position["direction"]
        entry = position["entry"]

        if direction == "LONG":

            pnl_pct = (
                price / entry - 1
            ) * 100

            hit_stop = (
                price <= position["stop"]
            )

            hit_target = (
                price >= position["target"]
            )

        else:

            pnl_pct = (
                entry / price - 1
            ) * 100

            hit_stop = (
                price >= position["stop"]
            )

            hit_target = (
                price <= position["target"]
            )

        if not hit_stop and not hit_target:
            continue

        if hit_target:

            exit_price = position["target"]
            reason = "TAKE PROFIT"

        else:

            exit_price = position["stop"]
            reason = "STOP LOSS"

        if direction == "LONG":

            pnl = (
                exit_price - entry
            ) * position["size"]

        else:

            pnl = (
                entry - exit_price
            ) * position["size"]

        state["balance"] += pnl
        state["realized_pnl"] += pnl

        if pnl >= 0:

            state["wins"] += 1

        else:

            state["losses"] += 1

        state["trades"].append({
            "symbol": symbol,
            "direction": direction,
            "entry": entry,
            "exit": exit_price,
            "pnl": pnl,
            "reason": reason,
            "time": int(time.time())
        })

        closed.append({
            "symbol": symbol,
            "direction": direction,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "reason": reason
        })

        del state["positions"][symbol]

    return closed


# =========================
# ALERTES NOUVEAUX SIGNAUX
# =========================

def new_signal_alerts(state, signals):

    alerts = []

    now = int(time.time())

    for signal in signals:

        if signal["score"] < MIN_ENTRY_SCORE:
            continue

        if signal["volume_ratio"] < MIN_VOLUME_ENTRY:
            continue

        symbol = signal["symbol"]

        key = (
            signal["direction"]
            + "_"
            + str(signal["score"])
        )

        last = state["last_alerted"].get(
            symbol
        )

        # Pas de répétition pendant 30 min
        if last:

            if (
                now - last["time"] < 1800
                and last["key"] == key
            ):
                continue

        emoji = (
            "🟢"
            if signal["direction"] == "LONG"
            else "🔴"
        )

        message = (
            "🚨 NOUVEAU MOUVEMENT\n\n"
            "%s %s — %s\n\n"
            "🔥 Score : %d\n"
            "🏆 Qualité : %s\n"
            "💰 Prix : %.8g\n"
            "📊 Volume : x%.1f\n"
            "📈 Momentum 5m : %+0.2f%%\n"
            "📈 Momentum 30m : %+0.2f%%\n"
            "📈 Momentum 1h : %+0.2f%%\n"
            "RSI : %.1f\n\n"
            "✅ %s\n\n"
            "🧪 PAPER — aucun ordre réel."
            % (
                emoji,
                signal["direction"],
                symbol,
                signal["score"],
                signal["quality"],
                signal["price"],
                signal["volume_ratio"],
                signal["momentum_5m"],
                signal["momentum_30m"],
                signal["momentum_60m"],
                signal["rsi"],
                "\n".join(
                    "• " + x
                    for x in signal["reasons"]
                )
            )
        )

        alerts.append(message)

        state["last_alerted"][symbol] = {
            "time": now,
            "key": key
        }

    return alerts


# =========================
# DASHBOARD
# =========================

def dashboard(state, signals, prices):

    total = (
        state["wins"]
        + state["losses"]
    )

    winrate = (
        state["wins"]
        / total
        * 100
        if total
        else 0
    )

    unrealized = 0.0

    message = (
        "🤖 PIONEX BOT V4\n\n"
        "💰 Capital paper : %.2f USDT\n"
        "📈 P&L réalisé : %+0.2f USDT\n"
        "🎯 Trades : %d | 🟢 %d | 🔴 %d\n"
        "🏆 Winrate : %.1f%%\n"
        "🔒 Positions : %d/%d\n\n"
        "🔥 TOP 5 OPPORTUNITÉS\n"
    ) % (
        state["balance"],
        state["realized_pnl"],
        total,
        state["wins"],
        state["losses"],
        winrate,
        len(state["positions"]),
        MAX_OPEN_POSITIONS
    )

    if not signals:

        message += (
            "\n⏳ Aucun signal suffisamment "
            "confirmé actuellement.\n"
        )

    for signal in signals[:5]:

        emoji = (
            "🟢"
            if signal["direction"] == "LONG"
            else "🔴"
        )

        message += (
            "\n%s %s %s — SCORE %d | %s\n"
            "Prix %.8g | RSI %.1f | Vol x%.1f\n"
            "Momentum 30m %+0.2f%%\n"
            % (
                emoji,
                signal["direction"],
                signal["symbol"],
                signal["score"],
                signal["quality"],
                signal["price"],
                signal["rsi"],
                signal["volume_ratio"],
                signal["momentum_30m"]
            )
        )

    if state["positions"]:

        message += (
            "\n📌 POSITIONS PAPER\n"
        )

        for position in state["positions"].values():

            price = prices.get(
                position["symbol"],
                position["entry"]
            )

            if position["direction"] == "LONG":

                pnl_pct = (
                    price
                    / position["entry"]
                    - 1
                ) * 100

                unrealized += (
                    position["size"]
                    * (
                        price
                        - position["entry"]
                    )
                )

            else:

                pnl_pct = (
                    position["entry"]
                    / price
                    - 1
                ) * 100

                unrealized += (
                    position["size"]
                    * (
                        position["entry"]
                        - price
                    )
                )

            message += (
                "%s %s | %.8g | P&L %+0.2f%%\n"
                "Entrée %.8g | SL %.8g | TP %.8g\n"
                % (
                    position["direction"],
                    position["symbol"],
                    price,
                    pnl_pct,
                    position["entry"],
                    position["stop"],
                    position["target"]
                )
            )

    message += (
        "\n📊 P&L latent : %+0.2f USDT\n"
        "\n🧪 MODE PAPER — aucun ordre réel.\n"
        "⏱️ Prochain scan : ~5 min."
    ) % unrealized

    return message


# =========================
# MAIN
# =========================

def main():

    print(
        "=============================="
    )

    print(
        "PIONEX MOVEMENT BOT V4"
    )

    print(
        "=============================="
    )

    state = load_state()

    # -------------------------
    # SYMBOLS
    # -------------------------

    symbols_data = get_json(
        "/api/v1/common/symbols",
        {"type": "SPOT"}
    )

    usdt_symbols = {
        s["symbol"]
        for s in symbols_data["symbols"]
        if s.get("enable")
        and s.get("quoteCurrency")
        == "USDT"
    }

    # -------------------------
    # TICKERS
    # -------------------------

    ticker_data = get_json(
        "/api/v1/market/tickers",
        {"type": "SPOT"}
    )

    markets = []
    prices = {}

    for ticker in ticker_data["tickers"]:

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

        if price <= 0:
            continue

        prices[symbol] = price

        if amount >= MIN_24H_VOLUME:

            markets.append({
                "symbol": symbol,
                "volume": amount,
                "price": price
            })

    # -------------------------
    # POSITIONS
    # -------------------------

    closed = update_positions(
        state,
        prices
    )

    # -------------------------
    # SCAN
    # -------------------------

    signals = []

    markets.sort(
        key=lambda x: x["volume"],
        reverse=True
    )

    for market in markets[
        :DEEP_SCAN_COUNT
    ]:

        try:

            result = analyse(
                market["symbol"]
            )

            if result:

                signals.append(result)

        except Exception as error:

            print(
                "Erreur",
                market["symbol"],
                str(error)
            )

        time.sleep(0.10)

    # -------------------------
    # TRI
    # -------------------------

    signals.sort(
        key=lambda x: (
            x["score"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    # -------------------------
    # ALERTES
    # -------------------------

    alerts = new_signal_alerts(
        state,
        signals
    )

    # -------------------------
    # ENTREE PAPER
    # -------------------------

    if (
        signals
        and len(state["positions"])
        < MAX_OPEN_POSITIONS
    ):

        for signal in signals:

            if (
                signal["symbol"]
                in state["positions"]
            ):
                continue

            position = open_position(
                state,
                signal
            )

            if position:

                print(
                    "PAPER ENTRY",
                    position
                )

                entry_message = (
                    "🎯 ENTRÉE PAPER\n\n"
                    "%s %s\n"
                    "Score : %d | Qualité : %s\n\n"
                    "💰 Entrée : %.8g\n"
                    "🛑 Stop : %.8g\n"
                    "🎯 TP : %.8g\n\n"
                    "📊 Volume x%.1f\n"
                    "RSI %.1f\n"
                    "Momentum 30m %+0.2f%%\n\n"
                    "🧪 Aucun ordre réel."
                    % (
                        position["direction"],
                        position["symbol"],
                        position["score"],
                        position["quality"],
                        position["entry"],
                        position["stop"],
                        position["target"],
                        signal["volume_ratio"],
                        signal["rsi"],
                        signal["momentum_30m"]
                    )
                )

                alerts.append(
                    entry_message
                )

                break

    # -------------------------
    # SAUVEGARDE
    # -------------------------

    save_state(state)

    # -------------------------
    # TELEGRAM
    # -------------------------

    if closed:

        close_message = (
            "📤 PAPER TRADE TERMINÉ\n\n"
        )

        for trade in closed:

            emoji = (
                "✅"
                if trade["pnl"] >= 0
                else "❌"
            )

            close_message += (
                "%s %s %s\n"
                "Résultat : %+0.2f USDT "
                "(%+.2f%%)\n"
                "%s\n\n"
                % (
                    emoji,
                    trade["direction"],
                    trade["symbol"],
                    trade["pnl"],
                    trade["pnl_pct"],
                    trade["reason"]
                )
            )

        send_telegram(
            close_message
        )

    for alert in alerts:

        send_telegram(
            alert
        )

    send_telegram(
        dashboard(
            state,
            signals,
            prices
        )
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print(
            "ERREUR GENERALE :",
            str(error)
        )

        raise
