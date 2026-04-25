import base64
import time
import random
import logging
import requests
from config import MIN_PRICE, MAX_PRICE, HARD_EXCLUDES, EBAY_APP_ID, EBAY_CERT_ID

logger = logging.getLogger(__name__)


def parse_price(raw) -> float | None:
    try:
        if isinstance(raw, dict):
            v = raw.get("value") or raw.get("amount", "")
        else:
            v = raw
        return float(str(v).replace(",", ".").replace("€", "").replace(" ", ""))
    except Exception:
        return None

def price_ok(raw) -> bool:
    p = parse_price(raw)
    return p is not None and MIN_PRICE <= p <= MAX_PRICE

def title_ok(title: str, brand: str) -> bool:
    if not title or not brand:
        return False
    tl = title.lower()
    if brand.lower() not in tl:
        return False
    for kw in HARD_EXCLUDES:
        if kw in tl:
            return False
    return True


# ──────────────────────────────────────────
# EBAY
# ──────────────────────────────────────────

_ebay_token = {"value": None, "expires": 0}

def get_ebay_token() -> str | None:
    if _ebay_token["value"] and time.time() < _ebay_token["expires"]:
        return _ebay_token["value"]
    try:
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
        r.raise_for_status()
        data = r.json()
        token = data.get("access_token")
        expires = data.get("expires_in", 7200)
        _ebay_token["value"] = token
        _ebay_token["expires"] = time.time() + expires - 60
        logger.info("[eBay] Token obtenu")
        return token
    except Exception as e:
        logger.error(f"[eBay] Token: {e}")
        return None

def fetch_ebay_new(brand: str) -> list:
    logger.info(f"[eBay] Recherche '{brand}'...")
    results = []

    token = get_ebay_token()
    if not token:
        return []

    try:
        params = {
            "q": brand,
            "filter": f"price:[{MIN_PRICE}..{MAX_PRICE}],currency:EUR",
            "sort": "newlyListed",
            "limit": 50,
        }
        r = requests.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=15,
        )
        r.raise_for_status()
        items = r.json().get("itemSummaries", [])
        logger.info(f"[eBay] {len(items)} items bruts pour '{brand}'")

        for item in items:
            title = item.get("title", "")
            price_raw = item.get("price", {})

            if not title_ok(title, brand) or not price_ok(price_raw):
                continue

            price = parse_price(price_raw)
            image = item.get("image", {}).get("imageUrl")
            url = item.get("itemWebUrl", "")
            item_id = item.get("itemId", url)

            results.append({
                "id": str(item_id),
                "title": title,
                "price": price,
                "size": "",
                "url": url,
                "image": image,
                "source": "eBay",
                "brand": brand,
            })

    except Exception as e:
        logger.error(f"[eBay] Erreur '{brand}': {e}")

    logger.info(f"[eBay] {len(results)} articles valides pour '{brand}'")
    return results


# ──────────────────────────────────────────
# VINTED
# ──────────────────────────────────────────

VINTED_SESSION = requests.Session()
VINTED_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Origin": "https://www.vinted.fr",
    "Referer": "https://www.vinted.fr/",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
})
_vinted_init_done = {"done": False}

def init_vinted():
    if _vinted_init_done["done"]:
        return
    try:
        VINTED_SESSION.get("https://www.vinted.fr", timeout=10)
        time.sleep(1)
        VINTED_SESSION.get("https://www.vinted.fr/api/v2/configurations", timeout=10)
        _vinted_init_done["done"] = True
        logger.info("[Vinted] Session initialisée")
    except Exception as e:
        logger.warning(f"[Vinted] Init: {e}")

def fetch_vinted_new(brand: str) -> list:
    logger.info(f"[Vinted] Recherche '{brand}'...")
    results = []

    try:
        init_vinted()
        params = {
            "search_text": brand,
            "price_from": MIN_PRICE,
            "price_to": MAX_PRICE,
            "currency": "EUR",
            "per_page": 50,
            "page": 1,
            "order": "newest_first",
        }
        r = VINTED_SESSION.get(
            "https://www.vinted.fr/api/v2/catalog/items",
            params=params,
            timeout=15,
        )
        logger.info(f"[Vinted] Status: {r.status_code}")

        if r.status_code != 200:
            logger.warning(f"[Vinted] Bloqué: {r.status_code}")
            return []

        items = r.json().get("items", [])
        logger.info(f"[Vinted] {len(items)} items bruts")

        for item in items:
            title = item.get("title", "")
            price_raw = item.get("price")
            if not title_ok(title, brand) or not price_ok(price_raw):
                continue

            price = parse_price(price_raw)
            photo = item.get("photo") or {}
            image = photo.get("url")
            item_id = str(item.get("id", ""))

            size = item.get("size_title", "")
            if not size:
                sz = item.get("size", {})
                if isinstance(sz, dict):
                    size = sz.get("title", "")

            results.append({
                "id": item_id,
                "title": title,
                "price": price,
                "size": size,
                "url": f"https://www.vinted.fr/items/{item_id}",
                "image": image,
                "source": "Vinted",
                "brand": brand,
            })

    except Exception as e:
        logger.error(f"[Vinted] Erreur '{brand}': {e}")

    logger.info(f"[Vinted] {len(results)} articles valides pour '{brand}'")
    return results


# ──────────────────────────────────────────
# UNIFIÉ
# ──────────────────────────────────────────

def fetch_new(brand: str) -> list:
    results = []
    results.extend(fetch_ebay_new(brand))
    time.sleep(random.uniform(0.5, 1))
    results.extend(fetch_vinted_new(brand))
    return results
