# ============================================================
#  CONFIG — Sourcing Luxe Bot
# ============================================================

import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID        = int(os.environ.get("CHAT_ID", "0"))

# Intervalle de scan en minutes
SCAN_INTERVAL_MIN = 60

# Prix d'achat maximum
MIN_BUY_PRICE = 70
MAX_BUY_PRICE = 400

# ── Tailles recherchées ────────────────────────────────────
SIZES_MEN   = ["M", "L", "48", "42", "XL", "50", "52"]
SIZES_WOMEN = ["S", "M", "36", "38", "8", "10"]

# ── Catégories autorisées ──────────────────────────────────
# Un article doit contenir AU MOINS UN de ces mots pour être accepté
ALLOWED_KEYWORDS = [
    "costume", "suit", "veste", "blazer", "jacket", "manteau", "coat",
    "pardessus", "trench", "imperméable", "overcoat", "gilet", "waistcoat",
    "pantalon", "trouser", "smoking", "tuxedo", "frac",
    "sac", "bag", "pochette", "handbag", "purse", "portefeuille", "wallet",
    "chaussure", "shoe", "derby", "oxford", "boot", "botte", "mocassin",
    "loafer", "sneaker", "ceinture", "belt",
]

# ── Catégories interdites ──────────────────────────────────
# Un article contenant UN de ces mots est rejeté
FORBIDDEN_KEYWORDS = [
    "t-shirt", "tshirt", "polo", "chemise", "shirt", "cravate", "tie",
    "boucle de ceinture", "belt buckle", "chaussette", "sock",
    "sous-vêtement", "underwear", "jean", "denim", "short",
    "pull", "sweater", "sweat", "hoodie", "parka", "doudoune",
    "écharpe", "scarf", "gant", "glove", "chapeau", "hat", "cap",
    "lunette", "glasses", "montre", "watch", "bijou", "jewelry",
    "parfum", "perfume", "accessoire",
]

# ── Matières interdites ────────────────────────────────────
FORBIDDEN_MATERIALS = [
    "polyester", "acrylique", "acrylic", "nylon", "viscose",
    "lycra", "elasthanne", "spandex", "polyamide", "modal",
    "synthétique", "synthetic",
]

# ── Matières nobles ────────────────────────────────────────
NOBLE_MATERIALS = [
    "laine", "wool", "cachemire", "cashmere", "soie", "silk",
    "lin", "linen", "cuir", "leather", "agneau", "lamb",
    "daim", "suède", "suede", "mohair", "alpaga", "alpaca",
    "angora", "tweed", "flanelle", "flannel", "gabardine",
    "velours", "velvet", "coton", "cotton", "100%",
]

# ── Marques Tier 1 ─────────────────────────────────────────
BRANDS_T1 = [
    "Brioni", "Kiton", "Cesare Attolini", "Caraceni",
    "Tommy Caraceni", "Domenico Caraceni", "Rubinacci",
    "Liverano Liverano", "Anderson & Sheppard", "Henry Poole",
    "Henry Maxwell", "Charvet", "Cifonelli", "Ambrosi Napoli",
    "Sartoria Renato Ciardi", "Camps de Lucas", "Sulka",
    "Di Nota", "Bouvard Bottier", "Daliet Grand", "Gravati",
    "John Lobb", "George Cleverley",
]

# ── Marques Tier 2 ─────────────────────────────────────────
BRANDS_T2 = [
    "Hermès", "Hermes", "Ermenegildo Zegna", "Zegna",
    "Brunello Cucinelli", "Loro Piana", "Berluti", "Scabal",
    "Canali", "Caruso", "Corneliani", "Montezemolo",
    "Bespoke", "Brano", "Arnys", "Francesco Smalto",
    "Ralph Lauren Purple Label", "Loewe", "Eric Bompard",
]

# ── Marques Tier 3 ─────────────────────────────────────────
BRANDS_T3 = [
    "Giorgio Armani", "Armani", "Yves Saint Laurent", "YSL",
    "Ralph Lauren", "Burberry", "Louis Vuitton", "Prada",
    "Bottega Veneta", "Celine", "Céline", "Dries Van Noten",
    "Marni", "Roberto Cavalli", "Aspesi", "Berluti",
    "Dior", "Christian Dior", "Tom Ford", "Kiton",
]

ALL_BRANDS = list(dict.fromkeys(BRANDS_T1 + BRANDS_T2 + BRANDS_T3))

# ── Multiplicateurs de revente ─────────────────────────────
MULTIPLIER = {
    "T1": 2.5,
    "T2": 2.0,
    "T3": 1.8,
}

def get_min_multiplier(buy_price: float) -> float:
    if buy_price < 400:
        return 3.0
    elif buy_price <= 2000:
        return 2.0
    else:
        return 1.8

def get_tier(brand: str) -> str:
    b = brand.lower()
    for br in BRANDS_T1:
        if br.lower() in b or b in br.lower():
            return "T1"
    for br in BRANDS_T2:
        if br.lower() in b or b in br.lower():
            return "T2"
    for br in BRANDS_T3:
        if br.lower() in b or b in br.lower():
            return "T3"
    return "T3"

def estimated_sell_price(buy_price: float, tier: str) -> float:
    return round(buy_price * MULTIPLIER[tier])

def margin_pct(buy_price: float, tier: str) -> int:
    sell = estimated_sell_price(buy_price, tier)
    return round(((sell - buy_price) / buy_price) * 100)

def is_pepite(buy_price: float, tier: str) -> bool:
    sell = estimated_sell_price(buy_price, tier)
    return (sell / buy_price) >= get_min_multiplier(buy_price)
