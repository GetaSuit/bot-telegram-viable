import requests
import time
import random
import logging
from datetime import datetime, timezone
from config import (
    BRANDS, MIN_PRICE, MAX_PRICE,
    EBAY_APP_ID, EBAY_CERT_ID,
    EXCLUDED_KEYWORDS, ALLOWED_KEYWORDS,
    HYPE_KEYWORDS,
)
from ai_scorer import analyze_article

logger = logging.getLogger(__name__)

MAX_AGE_DAYS = 30


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
# DATE
# ──────────────────────────────────────────

def is_recent(timestamp: int) -> bool:
    if not timestamp:
        return True
    try:
        item_date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        days_old = (datetime.now(tz=timezone.utc) - item_date).days
        return days_old <= MAX_AGE_DAYS
    except Exception:
        return True


# ──────────────────────────────────────────
# DÉTECTEUR COUP DU JOUR
# ──────────────────────────────────────────

def is_hype(title: str, description: str = "") -> bool:
    text = (title + " " + description).lower()
    return any(kw.lower() in text for kw in HYPE_KEYWORDS)


# ──────────────────────────────────────────
# FILTRE MINIMAL
# ──────────────────────────────────────────

def is_relevant(title: str, brand: str) -> bool:
    """Filtre minimal — Claude décide du reste."""
    if not title or not brand:
        return False
    title_lower = title.lower()
    if brand.lower() not in title_lower:
        return False
    hard_excludes = [
        "parfum", "perfume", "cologne", "eau de",
        "iphone", "samsung", "ordinateur", "laptop",
        "voiture", "moto", "vélo", "jouet", "toy",
        "livre", "book", "dvd",
    ]
    for kw in hard_excludes:
        if kw in title_lower:
            return False
    return True


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

        # Recherche directe par marque sans catégorie forcée
        params = {
            "q": brand,
            "filter": (
                f"price:[{min_price}..{max_price}],"
                f"currency:EUR,"
                f"itemLocationCountry:FR"
            ),
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

        for item in r.json().get("itemSummaries", []):
            title = item.get("title", "")
            price_raw = item.get("price", {})

            if not price_ok(price_raw):
                continue
            if not is_relevant(title, brand):
                continue

            # Filtre date
            item_date_str = item.get("itemCreationDate", "")
            if item_date_str:
                try:
                    item_date = datetime.fromisoformat(
                        item_date_str.replace("Z", "+00:00")
                    )
                    if (datetime.now(tz=timezone.utc) - item_date).days > MAX_AGE_DAYS:
                        continue
                except Exception:
                    pass

            parsed_price = parse_price(price_raw)

            # Claude analyse
            ai = analyze_article(
                title=title,
                brand=brand,
                price=parsed_price or 0,
                source="eBay",
            )

            if not ai.get("keep", True):
                logger.info(f"[eBay] Ignoré: {title[:50]} — {ai.get('reason', '')}")
                continue

            results.append({
                "title": title,
                "price": parsed_price,
                "url": item.get("itemWebUrl"),
                "image": item.get("image", {}).get("imageUrl"),
                "source": "eBay",
                "is_trending": ai.get("is_trending", False),
                "is_hype": is_hype(title) or ai.get("is_trending", False),
                "ai_verdict": ai.get("verdict", "correct"),
                "ai_reason": ai.get("reason", ""),
                "market_value": ai.get("market_value"),
            })

        # Dédoublonnage
        seen = set()
        unique = []
        for item in results:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)

        logger.info(f"[eBay] {len(unique)} articles validés pour '{brand}'")
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
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://www.vinted.fr",
    "Referer": "https://www.vinted.fr/",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
})

def _vinted_init_session():
    try:
        VINTED_SESSION.get("https://www.vinted.fr", timeout=10, allow_redirects=True)
        VINTED_SESSION.get("https://www.vinted.fr/api/v2/configurations", timeout=10)
        return True
    except Exception as e:
        logger.error(f"[Vinted] Init session: {e}")
        return False

def search_vinted(brand: str, min_price=MIN_PRICE, max_price=MAX_PRICE):
    results = []
    try:
        _vinted_init_session()

        # Recherche directe par marque sans catégorie forcée
        params = {
            "search_text": brand,
            "price_from": min_price,
            "price_to": max_price,
            "currency": "EUR",
            "per_page": 50,
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

            # Filtre date
            timestamp = item.get("updated_at_ts") or item.get("created_at_ts", 0)
            if timestamp and not is_recent(timestamp):
                continue

            parsed_price = parse_price(price_raw)

            # Claude analyse
            ai = analyze_article(
                title=title,
                brand=brand,
                price=parsed_price or 0,
                source="Vinted",
            )

            if not ai.get("keep", True):
                logger.info(f"[Vinted] Ignoré: {title[:50]} — {ai.get('reason', '')}")
                continue

            photo = item.get("photo") or {}
            results.append({
                "title": title,
                "price": parsed_price,
                "url": f"https://www.vinted.fr/items/{item.get('id')}",
                "image": photo.get("url"),
                "source": "Vinted",
                "is_trending": ai.get("is_trending", False),
                "is_hype": is_hype(title, desc) or ai.get("is_trending", False),
                "ai_verdict": ai.get("verdict", "correct"),
                "ai_reason": ai.get("reason", ""),
                "market_value": ai.get("market_value"),
            })

        time.sleep(random.uniform(1.0, 2.0))

        # Dédoublonnage
        seen = set()
        unique = []
        for item in results:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)

        logger.info(f"[Vinted] {len(unique)} articles validés pour '{brand}'")
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
