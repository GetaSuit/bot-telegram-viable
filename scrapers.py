import requests
import time
import random
import logging
from config import (
    BRANDS, MIN_PRICE, MAX_PRICE,
    EBAY_APP_ID, EBAY_CERT_ID,
    TIER1_BRANDS, TIER2_BRANDS, TIER3_BRANDS,
    EXCLUDED_KEYWORDS, ALLOWED_KEYWORDS,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# FILTRE PRIX STRICT
# ──────────────────────────────────────────

def parse_price(price_raw) -> float | None:
    """Convertit n'importe quel format de prix en float. Retourne None si impossible."""
    try:
        if isinstance(price_raw, dict):
            val = price_raw.get("amount") or price_raw.get("value", "")
        else:
            val = price_raw
        return float(str(val).replace(",", ".").replace("€", "").replace(" ", "").strip())
    except Exception:
        return None

def price_ok(price_raw) -> bool:
    """Retourne True uniquement si le prix est dans la fourchette MIN_PRICE–MAX_PRICE."""
    price = parse_price(price_raw)
    if price is None:
        return False
    return MIN_PRICE <= price <= MAX_PRICE


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

                # Double vérification prix côté Python
                if not price_ok(price_raw):
                    logger.debug(f"[eBay] Prix hors fourchette ignoré: {price_raw} — {title}")
                    continue

                if not is_relevant(title, brand):
                    continue

                results.append({
                    "title": title,
                    "price": parse_price(price_raw),
                    "url": item.get("itemWebUrl"),
                    "image": item.get("image", {}).get("imageUrl"),
                    "source": "eBay",
                })
            time.sleep(0.5)

        # Dédoublonnage
        seen = set()
        unique = []
        for item in results:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)

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

                # Double vérification prix côté Python
                if not price_ok(price_raw):
                    logger.debug(f"[Vinted] Prix hors fourchette ignoré: {price_raw} — {title}")
                    continue

                if not is_relevant(title, brand):
                    continue

                photo = item.get("photo") or {}
                results.append({
                    "title": title,
                    "price": parse_price(price_raw),
                    "url": f"https://www.vinted.fr/items/{item.get('id')}",
                    "image": photo.get("url"),
                    "source": "Vinted",
                })
            time.sleep(random.uniform(1.0, 2.0))

        # Dédoublonnage
        seen = set()
        unique = []
        for item in results:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)

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
    return all_results
