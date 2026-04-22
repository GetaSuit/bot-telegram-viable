import os
import requests
import time
import random
import logging
from config import (
    BRANDS, MIN_PRICE, MAX_PRICE,
    EBAY_APP_ID, EBAY_CERT_ID,
    HYPE_KEYWORDS,
)
from ai_scorer import analyze_article

logger = logging.getLogger(__name__)

MAX_ARTICLES_PER_SOURCE = 10
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")


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
    if isinstance(price_raw, dict):
        parsed = parse_price(price_raw)
        currency = price_raw.get("currency", "EUR")
        if parsed is None:
            return False
        price_eur = parsed * 0.92 if currency == "USD" else parsed
        return MIN_PRICE <= price_eur <= MAX_PRICE
    price = parse_price(price_raw)
    if price is None:
        return False
    return MIN_PRICE <= price <= MAX_PRICE


# ──────────────────────────────────────────
# HYPE
# ──────────────────────────────────────────

def is_hype(title: str, description: str = "") -> bool:
    text = (title + " " + description).lower()
    return any(kw.lower() in text for kw in HYPE_KEYWORDS)


# ──────────────────────────────────────────
# FILTRE MINIMAL
# ──────────────────────────────────────────

def is_relevant(title: str, brand: str) -> bool:
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

def search_ebay(brand: str, min_price=MIN_PRICE, max_price=MAX_PRICE,
                max_articles=MAX_ARTICLES_PER_SOURCE):
    results = []
    candidates = []
    try:
        token = get_ebay_token()
        if not token:
            logger.error("[eBay] Token introuvable")
            return []

        offset = 0
        limit = 50

        while offset < 200 and len(candidates) < max_articles * 3:
            params = {
                "q": brand,
                "sort": "newlyListed",
                "limit": limit,
                "offset": offset,
            }
            r = requests.get(
                "https://api.ebay.com/buy/browse/v1/item_summary/search",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": "EBAY_FR",
                },
                params=params,
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            items = data.get("itemSummaries", [])

            logger.info(f"[eBay] offset={offset} → {len(items)} items bruts pour '{brand}'")

            if not items:
                break

            for item in items:
                title = item.get("title", "")
                price_raw = item.get("price", {})
                if not price_ok(price_raw):
                    continue
                if not is_relevant(title, brand):
                    continue
                candidates.append(item)

            offset += limit
            if offset >= data.get("total", 0):
                break
            time.sleep(0.3)

        logger.info(f"[eBay] {len(candidates)} candidats → Claude analyse {min(len(candidates), max_articles)}")

        for item in candidates[:max_articles]:
            title = item.get("title", "")
            parsed_price = parse_price(item.get("price", {}))
            image_url = item.get("image", {}).get("imageUrl")
            use_vision = is_hype(title)

            ai = analyze_article(
                title=title,
                brand=brand,
                price=parsed_price or 0,
                source="eBay",
                image_url=image_url if use_vision else None,
            )

            if not ai.get("keep", True):
                logger.info(f"[eBay] Ignoré: {title[:50]}")
                continue

            results.append({
                "title": title,
                "price": parsed_price,
                "url": item.get("itemWebUrl"),
                "image": image_url,
                "source": "eBay",
                "is_trending": ai.get("is_trending", False),
                "is_hype": is_hype(title) or ai.get("is_trending", False),
                "is_runway": ai.get("is_runway", False),
                "collection": ai.get("collection"),
                "ai_verdict": ai.get("verdict", "correct"),
                "ai_reason": ai.get("reason", ""),
                "market_value": ai.get("market_value"),
            })

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
# VINTED VIA SCRAPERAPI
# ──────────────────────────────────────────

def _scraper_get(url: str, params: dict) -> requests.Response:
    """Passe par ScraperAPI pour contourner le blocage IP de Vinted."""
    target_url = url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    api_url = (
        f"http://api.scraperapi.com"
        f"?api_key={SCRAPER_API_KEY}"
        f"&url={requests.utils.quote(target_url)}"
        f"&country_code=fr"
    )
    return requests.get(api_url, timeout=30)

def search_vinted(brand: str, min_price=MIN_PRICE, max_price=MAX_PRICE,
                  max_articles=MAX_ARTICLES_PER_SOURCE):
    results = []
    candidates = []

    if not SCRAPER_API_KEY:
        logger.error("[Vinted] SCRAPER_API_KEY manquante")
        return []

    try:
        for page in range(1, 5):
            params = {
                "search_text": brand.replace(" ", "+"),
                "price_from": min_price,
                "price_to": max_price,
                "currency": "EUR",
                "per_page": 50,
                "page": page,
                "order": "relevance",
            }
            try:
                r = _scraper_get(
                    "https://www.vinted.fr/api/v2/catalog/items",
                    params,
                )
                logger.info(f"[Vinted] ScraperAPI status={r.status_code} page={page} pour '{brand}'")

                if r.status_code != 200:
                    logger.warning(f"[Vinted] Status {r.status_code} page {page}")
                    break
                if not r.text.strip():
                    logger.warning(f"[Vinted] Réponse vide page {page}")
                    break

                data = r.json()
                items = data.get("items", [])
                logger.info(f"[Vinted] page={page} → {len(items)} items bruts")

            except Exception as e:
                logger.error(f"[Vinted] Erreur page {page}: {e}")
                break

            if not items:
                break

            for item in items:
                title = item.get("title", "")
                price_raw = item.get("price")
                if not price_ok(price_raw):
                    continue
                if not is_relevant(title, brand):
                    continue
                candidates.append(item)

            if len(candidates) >= max_articles * 3:
                break

            time.sleep(random.uniform(1.0, 2.0))

        logger.info(f"[Vinted] {len(candidates)} candidats → Claude analyse {min(len(candidates), max_articles)}")

        for item in candidates[:max_articles]:
            title = item.get("title", "")
            price_raw = item.get("price")
            desc = item.get("description", "") or ""
            parsed_price = parse_price(price_raw)
            photo = item.get("photo") or {}
            image_url = photo.get("url")
            use_vision = is_hype(title, desc)

            ai = analyze_article(
                title=title,
                brand=brand,
                price=parsed_price or 0,
                source="Vinted",
                image_url=image_url if use_vision else None,
            )

            if not ai.get("keep", True):
                logger.info(f"[Vinted] Ignoré: {title[:50]}")
                continue

            results.append({
                "title": title,
                "price": parsed_price,
                "url": f"https://www.vinted.fr/items/{item.get('id')}",
                "image": image_url,
                "source": "Vinted",
                "is_trending": ai.get("is_trending", False),
                "is_hype": is_hype(title, desc) or ai.get("is_trending", False),
                "is_runway": ai.get("is_runway", False),
                "collection": ai.get("collection"),
                "ai_verdict": ai.get("verdict", "correct"),
                "ai_reason": ai.get("reason", ""),
                "market_value": ai.get("market_value"),
            })

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

def search_all_sources(brand: str, max_articles=MAX_ARTICLES_PER_SOURCE):
    all_results = []
    all_results.extend(search_ebay(brand, max_articles=max_articles))
    all_results.extend(search_vinted(brand, max_articles=max_articles))
    return all_results
