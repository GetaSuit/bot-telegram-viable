import os

# ── Tokens
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
EBAY_APP_ID = os.environ["EBAY_APP_ID"]
EBAY_CERT_ID = os.environ["EBAY_CERT_ID"]

# ── Paramètres sourcing
MIN_PRICE = 70
MAX_PRICE = 400
SCAN_INTERVAL_MINUTES = 60

# ── Mots-clés interdits
EXCLUDED_KEYWORDS = [
    # Parfums
    "parfum", "eau de", "cologne", "fragrance", "cosmetic", "perfume",
    "miniature", "spray", "toilette", "deodorant",
    # Accessoires non ciblés
    "maquillage", "beauté", "crème", "lotion",
    "montre", "watch", "bracelet", "collier", "bague", "bijou",
    "lunettes", "sunglasses", "portefeuille", "wallet",
    "ceinture", "belt", "chapeau", "hat",
    "écharpe", "scarf", "foulard", "twilly", "soie", "silk",
    "gant", "gloves", "chaussette", "sock",
    # High-tech / divers
    "jouet", "toy", "livre", "book", "dvd",
    "talkie", "imprimante", "phone", "iphone", "samsung",
    "ordinateur", "laptop", "tablette",
]

# ── Mots-clés autorisés (au moins un requis)
ALLOWED_KEYWORDS = [
    # Vêtements homme
    "veste", "jacket", "blazer", "costume", "suit",
    "manteau", "coat", "parka", "trench", "imperméable",
    "pantalon", "trouser", "jean", "chino",
    "chemise", "shirt", "pull", "sweater", "cardigan",
    "smoking", "tuxedo",
    # Chaussures
    "chaussure", "shoe", "sneaker", "boot", "botte",
    "mocassin", "loafer", "derby", "oxford",
    # Sacs
    "sac", "bag", "tote", "cabas", "pochette", "clutch",
    "backpack", "sac à dos",
]

# ── Marques par tier
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

BRANDS = TIER1_BRANDS + TIER2_BRANDS + TIER3_BRANDS
