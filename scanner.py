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

    if not data.get("result"):
        raise RuntimeError(
            "Erreur API Pionex : " + str(data)
        )

    return data["data"]


# =========================
# TELEGRAM
# =========================

def send_telegram(message):

    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN absent."
       
