import os
import json
import re
import time
import random
import logging
import requests
from config import MIN_PRICE, MAX_PRICE, HARD_EXCLUDES, SCRAPFLY_KEY

logger = logging.getLogger(__name__)

MAX_PER_SOURCE = 20


# ──────────────────────────────────────────
# UTILITAIRES
# ──────────────────────────────────────────

def parse_price(raw) -> float | None:
    try:
        if isinstance(raw, dict):
            if raw.get("cents"):
                return float(raw["cents"]) / 100
            v = raw.get("amount") or raw.get("value", "")
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

def scrapfly_api(url: str, headers: dict = None) -> dict | None:
    """
    Appelle ScrapFly pour contourner les blocages.
    Utilisé pour les APIs JSON (pas le rendu JS).
    """
    if not SCRAPFLY_KEY:
        logger.error("[ScrapFly] Clé manquante")
        return None
    try:
        params = {
            "key": SCRAPFLY_KEY,
            "url": url,
            "asp": "true",
            "country": "fr",
        }
        if headers:
            params["headers"] = json.dumps(headers)

        r = requests.get(
            "https://api.scrapfly.io/scrape",
            params=params,
            timeout=30,
        )
        if r.status_code != 200:
            logger.warning(f"[ScrapFly] Status {r.status_code}")
            return None

        content = r.json().get("result", {}).get("content", "")
        if not content:
            return None

        return json.loads(content)

    except Exception as e:
        logger.error(f"[ScrapFly] {e}")
        return None


# ──────────────────────────────────────────
# VINTED — API directe via ScrapFly
# ──────────────────────────────────────────

def fetch_vinted_new(brand: str) -> list:
    logger.info(f"[Vinted] Recherche '{brand}'...")

    url = (
        f"https://www.vinted.fr/api/v2/catalog/items"
        f"?search_text={brand.replace(' ', '%20')}"
        f"&price_from={MIN_PRICE}&price_to={MAX_PRICE}"
        f"&currency=EUR&per_page=50&page=1&order=newest_first"
    )

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Origin": "https://www.vinted.fr",
        "Referer": "https://www.vinted.fr/",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    }

    data = scrapfly_api(url, headers)
    if not data:
        logger.warning(f"[Vinted] Pas de données pour '{brand}'")
        return []

    items = data.get("items", [])
    logger.info(f"[Vinted] {len(items)} items bruts pour '{brand}'")

    results = []
    for item in items:
        title = item.get("title", "")
        price_raw = item.get("price")

        if not title_ok(title, brand) or not price_ok(price_raw):
            continue

        price = parse_price(price_raw)
        photo = item.get("photo") or {}
        image = photo.get("url") or photo.get("full_size_url")
        item_id = str(item.get("id", ""))

        size = item.get("size_title", "") or ""
        if not size:
            sz = item.get("size", {})
            if isinstance(sz, dict):
                size = sz.get("title", "") or sz.get("name", "")

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

    logger.info(f"[Vinted] {len(results)} articles valides pour '{brand}'")
    return results


# ──────────────────────────────────────────
# VESTIAIRE COLLECTIVE — API directe via ScrapFly
# ──────────────────────────────────────────

def fetch_vestiaire_new(brand: str) -> list:
    logger.info(f"[VC] Recherche '{brand}'...")

    url = (
        f"https://www.vestiairecollective.com/api/product/search/v2/"
        f"?keywords={brand.replace(' ', '+')}"
        f"&priceMin={MIN_PRICE}&priceMax={MAX_PRICE}"
        f"&sortBy=new&page=1&pageSize=50"
    )

    headers = {
        "Accept": "application/json",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": "https://www.vestiairecollective.com/search/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "x-market": "FR",
    }

    data = scrapfly_api(url, headers)

    # Fallback sur l'API search alternative
    if not data:
        url2 = (
            f"https://search.vestiairecollective.com/api/v1/catalog/query"
            f"?query={brand.replace(' ', '+')}"
            f"&priceMin={MIN_PRICE}&priceMax={MAX_PRICE}"
            f"&sort=newest&page=1"
        )
        data = scrapfly_api(url2, headers)

    if not data:
        logger.warning(f"[VC] Pas de données pour '{brand}'")
        return []

    # Cherche les items dans la réponse
    items = (
        data.get("items", [])
        or data.get("products", [])
        or data.get("results", [])
        or data.get("data", {}).get("items", [])
        or data.get("data", {}).get("products", [])
    )

    logger.info(f"[VC] {len(items)} items bruts pour '{brand}'")

    results = []
    for item in items:
        title = item.get("name", "") or item.get("title", "") or item.get("description", "")
        price_obj = item.get("price", {}) or item.get("priceEur", {})

        if isinstance(price_obj, dict):
            cents = price_obj.get("cents")
            price_raw = cents / 100 if cents else (
                price_obj.get("amount")
                or price_obj.get("value")
                or price_obj.get("original")
            )
        else:
            price_raw = price_obj

        if not title_ok(title, brand) or not price_ok(price_raw):
            continue

        price = parse_price(price_raw)
        link = item.get("url", "") or item.get("link", "")
        if link and not link.startswith("http"):
            link = "https://www.vestiairecollective.com" + link

        image = None
        pics = item.get("pictures", []) or item.get("images", [])
        if pics and isinstance(pics, list):
            image = pics[0].get("url") if isinstance(pics[0], dict) else pics[0]
        elif item.get("picture"):
            pic = item["picture"]
            image = pic.get("url") if isinstance(pic, dict) else pic

        size_str = ""
        size = item.get("size", {})
        if isinstance(size, dict):
            size_str = size.get("name", "") or size.get("title", "")
        elif isinstance(size, str):
            size_str = size

        item_id = str(item.get("id", link))

        results.append({
            "id": item_id,
            "title": title,
            "price": price,
            "size": size_str,
            "url": link,
            "image": image,
            "source": "Vestiaire Collective",
            "brand": brand,
        })

    logger.info(f"[VC] {len(results)} articles valides pour '{brand}'")
    return results


# ──────────────────────────────────────────
# UNIFIÉ
# ──────────────────────────────────────────

def fetch_new(brand: str) -> list:
    results = []
    results.extend(fetch_vinted_new(brand))
    time.sleep(random.uniform(1, 2))
    results.extend(fetch_vestiaire_new(brand))
    return results
