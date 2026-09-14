import os
import json
import time
import urllib.parse
import urllib.request
from statistics import mean

API = "https://api.pionex.com"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

DEEP_SCAN_COUNT = 200
SIGNAL_SCORE = 5
MIN_24H_VOLUME = 50000

PAPER_START_BALANCE = 1000.0
PAPER_RISK_PER_TRADE = 0.01
PAPER_STOP_LOSS = 0.015
PAPER_TAKE_PROFIT = 0.03
MAX_OPEN_POSITIONS = 3

STATE_FILE = "paper_state.json"


def get_json(path, params=None):
    if params:
        path += "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        API + path,
        headers={"User-Agent": "Pionex-Movement-Scanner/5.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode())

    if not data.get("result"):
        raise RuntimeError("Erreur API Pionex : " + str(data))

    return data["data"]


def send_telegram(message):
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN absent.")

    if not CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID absent.")

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

    if '"ok":true' not in result:
        raise RuntimeError("Telegram a refuse le message : " + result)


def default_state():
    return {
        "balance": PAPER_START_BALANCE,
        "realized_pnl": 0.0,
        "wins": 0,
        "losses": 0,
        "trades": [],
        "positions": {}
    }


def load_state():
    if not os.path.exists(STATE_FILE):
        return default_state()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        base = default_state()
        base.update(state)
        return base

    except Exception:
        return default_state()


def save_state(state):
    temp = STATE_FILE + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp, STATE_FILE)


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

    closes = [float(x["close"]) for x in candles]
    highs = [float(x["high"]) for x in candles]
    lows = [float(x["low"]) for x in candles]
    volumes = [float(x["volume"]) for x in candles]

    price = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    rsi = calculate_rsi(closes)

    previous_volumes = volumes[-21:-1]
    average_volume = mean(previous_volumes)

    if average_volume <= 0:
        return None

    volume_ratio = volumes[-1] / average_volume

    recent_avg = mean(volumes[-3:])
    older_avg = mean(volumes[-20:-3])

    volume_acceleration = (
        recent_avg / older_avg
        if older_avg > 0
        else 1
    )

    resistance = max(highs[-21:-1])
    support = min(lows[-21:-1])

    momentum_30m = (
        (price / closes[-7]) - 1
    ) * 100

    momentum_60m = (
        (price / closes[-13]) - 1
    ) * 100

    ranges = []

    for i in range(-20, 0):
        if closes[i] != 0:
            ranges.append(
                ((highs[i] - lows[i]) / closes[i]) * 100
            )

    volatility = mean(ranges) if ranges else 0

    short_ranges = ranges[-5:]
    long_ranges = ranges[:-5]

    compression = (
        bool(long_ranges)
        and mean(short_ranges) < mean(long_ranges) * 0.75
    )

    long_score = 0
    short_score = 0

    reasons_long = []
    reasons_short = []

    if volume_ratio >= 2:
        long_score += 2
        short_score += 2

        reasons_long.append(
            "volume x%.1f" % volume_ratio
        )

        reasons_short.append(
            "volume x%.1f" % volume_ratio
        )

    elif volume_ratio >= 1.4:
        long_score += 1
        short_score += 1

    if volume_acceleration >= 1.5:
        long_score += 1
        short_score += 1

        reasons_long.append("volume en acceleration")
        reasons_short.append("volume en acceleration")

    if ema20 and ema50:

        if ema20 > ema50:
            long_score += 2
            reasons_long.append("EMA haussiere")

        elif ema20 < ema50:
            short_score += 2
            reasons_short.append("EMA baissiere")

    if 52 <= rsi <= 70:
        long_score += 1
        reasons_long.append("RSI haussier")

    elif 30 <= rsi <= 48:
        short_score += 1
        reasons_short.append("RSI baissier")

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

    if momentum_30m >= 0.6:
        long_score += 1
        reasons_long.append(
            "momentum +%.2f%%" % momentum_30m
        )

    if momentum_60m >= 1.0:
        long_score += 1
        reasons_long.append("impulsion 1h")

    if momentum_30m <= -0.6:
        short_score += 1
        reasons_short.append(
            "momentum %.2f%%" % momentum_30m
        )

    if momentum_60m <= -1.0:
        short_score += 1
        reasons_short.append("impulsion 1h")

    if compression:

        if long_score >= short_score:
            long_score += 1
            reasons_long.append("compression")

        if short_score >= long_score:
            short_score += 1
            reasons_short.append("compression")

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
        "reasons": reasons
    }


def open_position(state, signal):

    symbol = signal["symbol"]

    if symbol in state["positions"]:
        return None

    if len(state["positions"]) >= MAX_OPEN_POSITIONS:
        return None

    entry = signal["price"]

    risk_money = (
        state["balance"] *
        PAPER_RISK_PER_TRADE
    )

    position_size = (
        risk_money /
        (entry * PAPER_STOP_LOSS)
    )

    if signal["direction"] == "LONG":

        stop = entry * (1 - PAPER_STOP_LOSS)
        target = entry * (1 + PAPER_TAKE_PROFIT)

    else:

        stop = entry * (1 + PAPER_STOP_LOSS)
        target = entry * (1 - PAPER_TAKE_PROFIT)

    position = {
        "symbol": symbol,
        "direction": signal["direction"],
        "entry": entry,
        "stop": stop,
        "target": target,
        "size": position_size,
        "opened_at": int(time.time())
    }

    state["positions"][symbol] = position

    return position


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

            hit_stop = price <= position["stop"]
            hit_target = price >= position["target"]

        else:

            pnl_pct = (
                entry / price - 1
            ) * 100

            hit_stop = price >= position["stop"]
            hit_target = price <= position["target"]

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


def dashboard(state, signals, prices):

    total = state["wins"] + state["losses"]

    winrate = (
        state["wins"] / total * 100
        if total
        else 0
    )

    unrealized = 0.0

    message = (
        "🤖 PIONEX BOT — TABLEAU DE BORD\n\n"
        "💰 Capital paper : %.2f USDT\n"
        "📈 P&L réalisé : %+0.2f USDT\n"
        "🎯 Trades : %d | 🟢 %d | 🔴 %d\n"
        "🏆 Winrate : %.1f%%\n"
        "🔓 Positions : %d/%d\n\n"
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

    for signal in signals[:5]:

        emoji = (
            "🟢"
            if signal["direction"] == "LONG"
            else "🔴"
        )

        message += (
            "\n%s %s %s — SCORE %d\n"
            "Prix %.8g | RSI %.1f | Vol x%.1f\n"
            "Momentum 30m %+0.2f%%\n"
            % (
                emoji,
                signal["direction"],
                signal["symbol"],
                signal["score"],
                signal["price"],
                signal["rsi"],
                signal["volume_ratio"],
                signal["momentum"]
            )
        )

    if state["positions"]:

        message += "\n📌 POSITIONS PAPER\n"

        for position in state["positions"].values():

            price = prices.get(
                position["symbol"],
                position["entry"]
            )

            if position["direction"] == "LONG":

                pnl_pct = (
                    price / position["entry"] - 1
                ) * 100

                unrealized += (
                    position["size"] *
                    (price - position["entry"])
                )

            else:

                pnl_pct = (
                    position["entry"] / price - 1
                ) * 100

                unrealized += (
                    position["size"] *
                    (position["entry"] - price)
                )

            message += (
                "%s %s | actuel %.8g | P&L %+.2f%%\n"
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


def main():

    print("PIONEX MOVEMENT BOT V3")

    state = load_state()

    symbols_data = get_json(
        "/api/v1/common/symbols",
        {"type": "SPOT"}
    )

    usdt_symbols = {
        s["symbol"]
        for s in symbols_data["symbols"]
        if s.get("enable")
        and s.get("quoteCurrency") == "USDT"
    }

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
                ticker.get("amount", 0)
            )

            price = float(
                ticker.get("close", 0)
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

    closed = update_positions(
        state,
        prices
    )

    signals = []

    markets.sort(
        key=lambda x: x["volume"],
        reverse=True
    )

    for market in markets[:DEEP_SCAN_COUNT]:

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

    signals.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    if (
        signals
        and len(state["positions"]) < MAX_OPEN_POSITIONS
    ):

        for signal in signals:

            if signal["symbol"] not in state["positions"]:

                position = open_position(
                    state,
                    signal
                )

                if position:
                    print(
                        "PAPER ENTRY",
                        position
                    )
                    break

    save_state(state)

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
                "Résultat : %+0.2f USDT (%+.2f%%)\n"
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
