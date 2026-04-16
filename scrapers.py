import requests
import time
import random
import logging
from config import (
    BRANDS, MIN_PRICE, MAX_PRICE,
    EBAY_APP_ID, EBAY_CERT_ID,
    TIER1_BRANDS, TIER2_BRANDS, TIER3_BRANDS,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# FILTRE DE PERTINENCE
# ──────────────────────────────────────────

def is_relevant(title: str, brand: str) -> bool:
    """Vérifie que le titre contient vraiment le nom de la marque."""
    if not title or not brand:
        return False
    return brand.lower() in title.lower()


# ──────────────────────────────────────────
# EBAY
# ──────────────────────────────────────────

def get_ebay_token():
    import base64
    credentials = base64.b64encode(f"{EBAY_APP_ID}:{EBAY_CERT_ID}".encode()).decode()
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
        params = {
            "q": brand,
            "filter": f"price:[{min_price}..{max_price}],currency:EUR,itemLocationCountry:FR",
            "sort": "newlyListed",
            "limit": 10,
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
            if not is_relevant(title, brand):
                continue
            results.append({
                "title": title,
                "price": item.get("price", {}).get("value", "?"),
                "url": item.get("itemWebUrl"),
                "image": item.get("image", {}).get("imageUrl"),
                "source": "eBay",
            })
        logger.info(f"[eBay] {len(results)} résultats pertinents pour '{brand}'")
    except Exception as e:
        logger.error(f"[eBay] Erreur '{brand}': {e}")
    return results


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

def _parse_vinted_price(price_raw) -> str:
    if isinstance(price_raw, dict):
        return str(price_raw.get("amount", "?"))
    return str(price_raw) if price_raw else "?"

def search_vinted(brand: str, min_price=MIN_PRICE, max_price=MAX_PRICE):
    results = []
    try:
        _vinted_init_session()
        params = {
            "search_text": brand,
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
        data = r.json()
        for item in data.get("items", []):
            title = item.get("title", "")
            if not is_relevant(title, brand):
                continue
            photo = item.get("photo") or {}
            results.append({
                "title": title,
                "price": _parse_vinted_price(item.get("price")),
                "url": f"https://www.vinted.fr/items/{item.get('id')}",
                "image": photo.get("url"),
                "source": "Vinted",
            })
        logger.info(f"[Vinted] {len(results)} résultats pertinents pour '{brand}'")
        time.sleep(random.uniform(2.0, 4.0))
    except Exception as e:
        logger.error(f"[Vinted] Erreur '{brand}': {e}")
    return results


# ──────────────────────────────────────────
# LEBONCOIN
# ──────────────────────────────────────────

LBC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": "https://www.leboncoin.fr/",
    "Content-Type": "application/json",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
}

def search_leboncoin(brand: str, min_price=MIN_PRICE, max_price=MAX_PRICE):
    results = []
    try:
        payload = {
            "filters": {
                "category": {"id": "64"},
                "keywords": {"text": brand, "type": "all"},
                "price": {"min": str(min_price), "max": str(max_price)},
                "location": {},
            },
            "limit": 20,
            "offset": 0,
            "sort_by": "time",
            "sort_order": "desc",
        }
        r = requests.post(
            "https://api.leboncoin.fr/finder/search",
            json=payload,
            headers=LBC_HEADERS,
            timeout=15,
        )
        logger.info(f"[LBC] Status HTTP: {r.status_code}")
        r.raise_for_status()
        data = r.json()
        for ad in data.get("ads", []):
            title = ad.get("subject", "")
            if not is_relevant(title, brand):
                continue
            images = ad.get("images", {})
            thumb = images.get("thumb_url") or (images.get("urls", [None])[0])
            price_list = ad.get("price", [])
            price = str(price_list[0]) if price_list else "?"
            results.append({
                "title": title,
                "price": price,
                "url": ad.get("url"),
                "image": thumb,
                "source": "Leboncoin",
            })
        logger.info(f"[LBC] {len(results)} résultats pertinents pour '{brand}'")
    except Exception as e:
        logger.error(f"[LBC] Erreur '{brand}': {e}")
    return results


# ──────────────────────────────────────────
# UNIFIÉ
# ──────────────────────────────────────────

def search_all_sources(brand: str):
    all_results = []
    all_results.extend(search_ebay(brand))
    all_results.extend(search_vinted(brand))
    all_results.extend(search_leboncoin(brand))
    return all_results
