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
    "parfum", "eau de", "cologne", "fragrance", "cosmetic",
    "maquillage", "beauté", "crème", "lotion", "montre", "watch",
    "bracelet", "collier", "bague", "bijou", "lunettes", "sunglasses",
    "portefeuille", "wallet", "ceinture", "belt", "chapeau", "hat",
    "écharpe", "scarf", "gant", "gloves", "chaussette", "sock",
    "jouet", "toy", "livre", "book", "dvd", "talkie", "imprimante",
    "phone", "iphone", "samsung", "ordinateur", "laptop",
]

# ── Mots-clés autorisés (au moins un requis)
ALLOWED_KEYWORDS = [
    "veste", "jacket", "blazer", "costume", "suit",
    "manteau", "coat", "parka", "trench",
    "sac", "bag", "tote", "cabas", "pochette",
    "chaussure", "shoe", "sneaker", "boot", "botte", "mocassin",
    "pantalon", "trouser", "jean",
    "chemise", "shirt", "pull", "sweater", "cardigan",
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
