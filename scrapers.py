from ai_scorer import analyze_article
import requests
import time
import random
import logging
from config import (
    BRANDS, MIN_PRICE, MAX_PRICE,
    EBAY_APP_ID, EBAY_CERT_ID,
    TIER1_BRANDS, TIER2_BRANDS, TIER3_BRANDS,
    EXCLUDED_KEYWORDS, ALLOWED_KEYWORDS,
    HYPE_KEYWORDS,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# PRIX
# ──────────────────────────────────────────

def parse_price(price_raw) -> float | None:
    try:
        if isinstance(price_raw, dict):
            val = price_raw.get("amount") or price_raw.get("value", "")
        else:
            val = price_raw
        return float(str(val).replace(",", ".").replace("€", "").replace(" ", "").strip())
    except Exception:
        return None

def price_ok(price_raw) -> bool:
    price = parse_price(price_raw)
    if price is None:
        return False
    return MIN_PRICE <= price <= MAX_PRICE


# ──────────────────────────────────────────
# DÉTECTEUR COUP DU JOUR
# ──────────────────────────────────────────

def is_hype(title: str, description: str = "") -> bool:
    """
    Retourne True si l'article est au goût du jour :
    vu sur une star, en magazine, défilé, collab, édition limitée...
    """
    text = (title + " " + description).lower()
    return any(kw.lower() in text for kw in HYPE_KEYWORDS)


# ──────────────────────────────────────────
# SCORE DE PERTINENCE (0–100)
# ──────────────────────────────────────────

def compute_score(item: dict, brand: str) -> int:
    score = 0
    title = (item.get("title") or "").lower()
    desc = (item.get("description") or "").lower()
    price = parse_price(item.get("price"))

    # Marque dans le titre (+25)
    if brand.lower() in title:
        score += 25

    # Catégorie ciblée (+20)
    for kw in ALLOWED_KEYWORDS:
        if kw.lower() in title:
            score += 20
            break

    # Coup du jour détecté (+30 — bonus majeur)
    if is_hype(title, desc):
        score += 30

    # Prix dans la fourchette basse = meilleure marge (+15)
    if price is not None:
        if MIN_PRICE <= price <= 150:
            score += 15
        elif 150 < price <= 250:
            score += 10
        elif 250 < price <= MAX_PRICE:
            score += 5

    # Source (+10 eBay, +5 Vinted)
    if item.get("source") == "eBay":
        score += 10
    elif item.get("source") == "Vinted":
        score += 5

    # Photo disponible (+5)
    if item.get("image"):
        score += 5

    # Titre trop court (-10)
    if len(title) < 20:
        score -= 10

    return max(0, min(100, score))


# ──────────────────────────────────────────
# FILTRE PERTINENCE
# ──────────────────────────────────────────

def is_relevant(title: str, brand: str) -> bool:
    if not title or not brand:
        return False
    title_lower = title.lower()
    if brand.lower() not in title_lower:
        return False
    for kw in EXCLUDED_KEYWORDS:
        if kw.lower() in title_lower:
            return False
    for kw in ALLOWED_KEYWORDS:
        if kw.lower() in title_lower:
            return True
    return False


# ──────────────────────────────────────────
# EBAY
# ──────────────────────────────────────────

def get_ebay_token():
    import base64
    credentials = base64.b64encode(
        f"{EBAY_APP_ID}:{EBAY_CERT_ID}".encode()
    ).decode()
    r = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
        timeout=10,
    )
    return r.json().get("access_token")

def search_ebay(brand: str, min_price=MIN_PRICE, max_price=MAX_PRICE):
    results = []
    try:
        token = get_ebay_token()
        if not token:
            logger.error("[eBay] Token introuvable")
            return []

        for category in ["veste blazer", "manteau coat", "sac bag"]:
            params = {
                "q": f"{brand} {category}",
                "filter": (
                    f"price:[{min_price}..{max_price}],"
                    f"currency:EUR,"
                    f"itemLocationCountry:FR"
                ),
                "sort": "newlyListed",
                "limit": 20,
            }
            r = requests.get(
                "https://api.ebay.com/buy/browse/v1/item_summary/search",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=15,
            )
            r.raise_for_status()

            for item in r.json().get("itemSummaries", []):
                title = item.get("title", "")
                price_raw = item.get("price", {})

                if not price_ok(price_raw):
                    continue
                if not is_relevant(title, brand):
                    continue

                parsed_price = parse_price(price_raw)
                result = {
                    "title": title,
                    "price": parsed_price,
                    "url": item.get("itemWebUrl"),
                    "image": item.get("image", {}).get("imageUrl"),
                    "source": "eBay",
                    "description": "",
                }
                result["is_hype"] = is_hype(title)
                result["score"] = compute_score(result, brand)
                results.append(result)

            time.sleep(0.5)

        # Dédoublonnage + tri par score
        seen = set()
        unique = []
        for item in results:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)

        unique.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"[eBay] {len(unique)} résultats pour '{brand}'")
        return unique

    except Exception as e:
        logger.error(f"[eBay] Erreur '{brand}': {e}")
        return []


# ──────────────────────────────────────────
# VINTED
# ──────────────────────────────────────────

VINTED_SESSION = requests.Session()
VINTED_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Origin": "https://www.vinted.fr",
    "Referer": "https://www.vinted.fr/",
})

def _vinted_init_session():
    try:
        VINTED_SESSION.get("https://www.vinted.fr", timeout=10)
        return True
    except Exception as e:
        logger.error(f"[Vinted] Init session: {e}")
        return False

def search_vinted(brand: str, min_price=MIN_PRICE, max_price=MAX_PRICE):
    results = []
    try:
        _vinted_init_session()

        for category in ["veste blazer", "manteau", "sac"]:
            params = {
                "search_text": f"{brand} {category}",
                "price_from": min_price,
                "price_to": max_price,
                "currency": "EUR",
                "per_page": 20,
                "order": "newest_first",
            }
            r = VINTED_SESSION.get(
                "https://www.vinted.fr/api/v2/catalog/items",
                params=params,
                timeout=15,
            )
            r.raise_for_status()

            for item in r.json().get("items", []):
                title = item.get("title", "")
                price_raw = item.get("price")
                desc = item.get("description", "") or ""

                if not price_ok(price_raw):
                    continue
                if not is_relevant(title, brand):
                    continue

                parsed_price = parse_price(price_raw)
                photo = item.get("photo") or {}
                result = {
                    "title": title,
                    "price": parsed_price,
                    "url": f"https://www.vinted.fr/items/{item.get('id')}",
                    "image": photo.get("url"),
                    "source": "Vinted",
                    "description": desc,
                }
                result["is_hype"] = is_hype(title, desc)
                result["score"] = compute_score(result, brand)
                results.append(result)

            time.sleep(random.uniform(1.0, 2.0))

        # Dédoublonnage + tri par score
        seen = set()
        unique = []
        for item in results:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)

        unique.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"[Vinted] {len(unique)} résultats pour '{brand}'")
        return unique

    except Exception as e:
        logger.error(f"[Vinted] Erreur '{brand}': {e}")
        return []


# ──────────────────────────────────────────
# UNIFIÉ
# ──────────────────────────────────────────

def search_all_sources(brand: str):
    all_results = []
    all_results.extend(search_ebay(brand))
    all_results.extend(search_vinted(brand))
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_results
