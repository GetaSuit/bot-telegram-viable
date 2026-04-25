import base64
import time
import logging
import requests
from config import MIN_PRICE, MAX_PRICE, HARD_EXCLUDES, EBAY_APP_ID, EBAY_CERT_ID
from ai_scorer import analyze

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
# EBAY TOKEN
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
        _ebay_token["value"] = data.get("access_token")
        _ebay_token["expires"] = time.time() + data.get("expires_in", 7200) - 60
        logger.info("[eBay] Token obtenu")
        return _ebay_token["value"]
    except Exception as e:
        logger.error(f"[eBay] Token: {e}")
        return None


# ──────────────────────────────────────────
# EBAY + ANALYSE IA
# ──────────────────────────────────────────

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
            item_id = str(item.get("itemId", url))

            # Analyse IA complète
            ai = analyze(title, brand, price or 0)

            # Filtre : revendeur pro → skip
            if ai.get("seller_type") == "pro":
                logger.info(f"[eBay] Pro ignoré: {title[:50]}")
                continue

            # Filtre : non authentique → skip
            if not ai.get("is_authentic", True):
                logger.info(f"[eBay] Suspect ignoré: {title[:50]}")
                continue

            # Filtre : IA dit non rentable → skip
            if not ai.get("keep", True):
                logger.info(f"[eBay] Non rentable: {title[:50]}")
                continue

            # Vérif revente ≥ 2× prix
            resale = ai.get("resale_value")
            if resale and price and float(resale) < float(price) * 2:
                logger.info(f"[eBay] Marge insuffisante ({price}€ → {resale}€): {title[:40]}")
                continue

            results.append({
                "id": item_id,
                "title": title,
                "price": price,
                "size": "",
                "url": url,
                "image": image,
                "source": "eBay",
                "brand": brand,
                # Données IA
                "resale_value": resale,
                "ai_reason": ai.get("reason", ""),
                "is_rare": ai.get("is_rare", False),
                "is_runway": ai.get("is_runway", False),
                "material_quality": ai.get("material_quality", "normale"),
            })

    except Exception as e:
        logger.error(f"[eBay] Erreur '{brand}': {e}")

    logger.info(f"[eBay] {len(results)} articles retenus pour '{brand}'")
    return results


def fetch_new(brand: str) -> list:
    return fetch_ebay_new(brand)
