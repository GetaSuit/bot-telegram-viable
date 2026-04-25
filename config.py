import os

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
EBAY_APP_ID = os.environ.get("EBAY_APP_ID", "")
EBAY_CERT_ID = os.environ.get("EBAY_CERT_ID", "")

MIN_PRICE = 70
MAX_PRICE = 400

HARD_EXCLUDES = [
    "parfum", "perfume", "cologne", "eau de toilette",
    "iphone", "samsung", "ordinateur", "laptop", "tablette",
    "voiture", "moto", "vélo", "jouet", "livre", "dvd",
    "montre", "watch", "bracelet", "bijou", "lunettes",
    "chaussure", "shoe", "sneaker", "boot",
]

BRANDS = [
    "Hermès", "Chanel", "Louis Vuitton", "Dior", "Brioni",
    "Kiton", "Loro Piana", "Berluti", "Cesare Attolini", "Stefano Ricci",
    "Zegna", "Canali", "Isaia", "Corneliani", "Caruso",
    "Tom Ford", "Gucci", "Prada", "Balenciaga", "Bottega Veneta",
    "Ralph Lauren Purple Label", "Saint Laurent", "Dries Van Noten",
    "Burberry", "Ralph Lauren", "Givenchy", "Lanvin",
    "Valentino", "Versace", "Dolce & Gabbana",
    "Brunello Cucinelli", "Ami Paris",
    "Celine", "Loewe", "Fendi", "Balmain", "Acne Studios",
    "Vivienne Westwood",
]
