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

# ── Tailles recherchées
TARGET_SIZES = ["46", "48", "50", "52", "M", "L"]

# ── Catégories ciblées (au moins un mot requis dans le titre)
ALLOWED_KEYWORDS = [
    # Vestes / Blazers / Costumes
    "veste", "jacket", "blazer", "costume", "suit", "tailleur",
    "smoking", "tuxedo", "veston",
    # Manteaux
    "manteau", "coat", "parka", "trench", "imperméable",
    "duffle", "caban", "pardessus", "overcoat",
    # Sacs
    "sac", "bag", "tote", "cabas", "pochette", "clutch",
    "backpack", "sac à dos", "besace", "bourse",
]

# ── Mots-clés interdits
EXCLUDED_KEYWORDS = [
    # Parfums / Beauté
    "parfum", "eau de", "cologne", "fragrance", "perfume",
    "miniature", "spray", "toilette", "deodorant",
    "cosmetic", "maquillage", "beauté", "crème", "lotion",
    # Accessoires non ciblés
    "montre", "watch", "bracelet", "collier", "bague", "bijou",
    "lunettes", "sunglasses", "portefeuille", "wallet",
    "ceinture", "belt", "chapeau", "hat",
    "écharpe", "scarf", "foulard", "twilly", "soie", "silk",
    "gant", "gloves", "chaussette", "sock",
    "cravate", "tie", "noeud papillon",
    # Chaussures (pas dans tes catégories)
    "chaussure", "shoe", "sneaker", "boot", "botte",
    "mocassin", "loafer", "derby", "oxford", "basket",
    # Vêtements non ciblés
    "pantalon", "trouser", "jean", "chino",
    "chemise", "shirt", "pull", "sweater", "cardigan",
    "polo", "t-shirt", "tee shirt",
    # High-tech / Divers
    "jouet", "toy", "livre", "book", "dvd", "cd",
    "talkie", "imprimante", "phone", "iphone", "samsung",
    "ordinateur", "laptop", "tablette", "console",
    "voiture", "moto", "vélo",
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
