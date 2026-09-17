import os
import time
import requests

# ============================================================
# PIONEX PERPS MOVEMENT SCANNER
# ============================================================

API = "https://api.pionex.com/api/v1"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Nombre maximum de signaux envoyés
MAX_SIGNALS = 8

# Nombre de bougies 5 minutes
KLINE_LIMIT = 60

# Volume 24h minimum
MIN_24H_VOLUME = 50000

# Seuils
MIN_MOVE_30M = 1.5
MIN_VOLUME_RATIO =
