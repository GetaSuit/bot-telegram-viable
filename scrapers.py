import requests
import time
import random
import logging
from config import (
    BRANDS, MIN_PRICE, MAX_PRICE,
    EBAY_APP_ID, EBAY_CERT_ID,
    TIER1_BRANDS, TIER2_BRANDS, TIER3_BRANDS,
    EXCLUDED_KEYWORDS, ALLOWED_KEYWORDS,
    RUNWAY_KEYWORDS, ALERT_PRICE_THRESHOLD,
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
# SCORE DE PERTINENCE (0–100)
# ──────────────────────────────────────────

def compute_score(item: dict, brand: str) -> int:
    """
    Calcule un score de pertinence de 0 à 100.
    Critères : présence marque, catégorie, prix, marge estimée.
    """
    score = 0
    title = (item.get("title") or "").lower()
    price = parse_price(item.get("price"))

    # Marque présente dans le titre (+30)
    if brand.lower() in title:
        score += 30

    # Catégorie ciblée présente (+20)
    for kw in ALLOWED_KEYWORDS:
        if kw.lower() in title:
            score += 20
            break

    # Prix dans la fourchette basse = meilleure marge (+25)
    if price is not None:
        if MIN_PRICE <= price <= 150:
            score += 25
        elif 150 < price <= 250:
            score += 15
        elif 250 < price <= MAX_PRICE:
            score += 5

    # Source fiable (+10 eBay, +5 Vinted)
    if item.get("source") == "eBay":
        score += 10
    elif item.get("source") == "Vinted":
        score += 5

    # Photo disponible (+10)
    if item.get("image"):
        score += 10

    # Pénalité si titre trop court (probablement vague)
    if len(title) < 20:
        score -= 10

    return max(0, min(100, score))


# ──────────────────────────────────────────
# DÉTECTEUR DE DÉFILÉ
# ──────────────────────────────────────────

def is_runway_suspect(item: dict) -> bool:
    """
    Retourne True si l'article ressemble à une pièce de défilé
    vendue à un prix anormalement bas (probablement erreur ou arnaque).
    """
    title = (item.get("title") or "").lower()
    price = parse_price(item.get("price"))

    has_runway_kw = any(kw.lower() in title for kw in RUNWAY_KEYWORDS)
    price_suspect = price is not None and price < MIN_PRICE * 0.8  # sous 80% du min

    return has_runway_kw and price_suspect


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
                }
                result["score"] = compute_score(result, brand)
                result["runway_suspect"] = is_runway_suspect(result)
                result["is_alert"] = parsed_price is not None and parsed_price <= ALERT_PRICE_THRESHOLD
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
        logger.info(f"[eBay] {len(unique)} résultats valides pour '{brand}'")
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
                }
                result["score"] = compute_score(result, brand)
                result["runway_suspect"] = is_runway_suspect(result)
                result["is_alert"] = parsed_price is not None and parsed_price <= ALERT_PRICE_THRESHOLD
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
        logger.info(f"[Vinted] {len(unique)} résultats valides pour '{brand}'")
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
