import os

# ── Tokens (variables d'environnement Render)
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
EBAY_APP_ID = os.environ["EBAY_APP_ID"]
EBAY_CERT_ID = os.environ["EBAY_CERT_ID"]

# ── Paramètres sourcing
MIN_PRICE = 70
MAX_PRICE = 400
SCAN_INTERVAL_MINUTES = 60  # était 30, passe à 60
# ── Marques par tier de revente
TIER1_BRANDS = [
    "Hermès", "Chanel", "Louis Vuitton", "Dior", "Brioni",
    "Kiton", "Loro Piana", "Berluti",
]

TIER2_BRANDS = [
    "Zegna", "Canali", "Isaia", "Corneliani", "Boglioli",
    "Tom Ford", "Gucci", "Prada", "Balenciaga", "Bottega Veneta",
]

TIER3_BRANDS = [
    "Burberry", "Hugo Boss", "Ralph Lauren", "Lanvin", "Givenchy",
    "Valentino", "Versace", "Dolce & Gabbana", "Moncler", "Stone Island",
    "Brunello Cucinelli", "Paul Smith", "Sandro", "A.P.C.", "Ami Paris",
    "Celine", "Loewe", "Fendi", "Balmain", "Acne Studios",
]

# ── Liste complète (utilisée par les scrapers)
BRANDS = TIER1_BRANDS + TIER2_BRANDS + TIER3_BRANDS
